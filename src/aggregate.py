"""Этап 5 — агрегация движений в матрицу спроса для SUMO.

Сводит movements_<cam>.csv обеих камер в единую матрицу:
    подъезд (въезд) × движение × нога выезда × тип ТС × 5-мин интервал.

Камеры комплементарны (каждый подъезд считает ровно одна камера), поэтому конкатенация
без двойного счёта. Время приводится к общему нулю через sync_offset_sec из конфига
(рассинхрон OSD-часов ~19 с). Интервалы 5-мин.

На выходе:
    data/movements_matrix.csv   — tidy: interval_start, entry, movement, exit, cls, count
    data/turn_counts.xml        — формат routeSampler (<edgeRelation from to count>);
                                  from/to = метки подъезда/ноги (заменишь на edge id сети).

Для другой записи того же перекрёстка сдвиг часов и общее окно свои: sync_offset_sec из
конфига привязан к записи 08:24, поэтому задаются через --offsets и --window. Без --window
интервалы считаются от нуля, и первый интервал выходит короче на сдвиг второй камеры.

Запуск:
    python src/aggregate.py                # все камеры с готовыми movements_*.csv
    python src/aggregate.py --cameras center
    python src/aggregate.py --cameras center zarich \\
           --movements A.csv B.csv --offsets 87 0 --window 87:1445 \\
           --out M.csv --out-xml T.xml
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from xml.sax.saxutils import quoteattr

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")   # SystemExit печатается в stderr
except Exception:
    pass


def main() -> None:
    ap = argparse.ArgumentParser(description="Агрегация движений в матрицу спроса")
    ap.add_argument("--cameras", nargs="*", default=None, help="по умолч. — все из конфига")
    ap.add_argument("--movements", nargs="*", default=None,
                    help="CSV движений в том же порядке, что --cameras "
                         "(по умолч. movements_<cam>.csv)")
    ap.add_argument("--offsets", nargs="*", type=float, default=None,
                    help="сдвиг часов к общему нулю, в том же порядке, что --cameras "
                         "(по умолч. sync_offset_sec из конфига — он для записи 08:24)")
    ap.add_argument("--window", default=None, metavar="T0:T1",
                    help="общее окно двух камер в общем времени, с. Интервалы считаются "
                         "от T0, всё вне окна отбрасывается")
    ap.add_argument("--out", default=None, help="tidy-матрица (по умолч. movements_matrix.csv)")
    ap.add_argument("--out-xml", default=None, help="turn-counts (по умолч. turn_counts.xml)")
    args = ap.parse_args()

    cfg = yaml.safe_load(open(ROOT / "config.yaml", encoding="utf-8"))
    out_dir = Path(cfg["paths"]["out_dir"])
    tracks_dir = out_dir / "tracks"
    interval = int(cfg["aggregation"]["interval_sec"])
    cams = {c["id"]: c for c in cfg["cameras"]}
    want = args.cameras or list(cams)
    for name, given in (("--movements", args.movements), ("--offsets", args.offsets)):
        if given is not None and len(given) != len(want):
            raise SystemExit(f"[agg] {name}: {len(given)} значений на {len(want)} камер")

    t0 = t1 = None
    if args.window:
        try:
            t0, t1 = (float(v) for v in args.window.split(":"))
        except ValueError:
            raise SystemExit(f"[agg] --window: ожидается T0:T1, получено {args.window!r}")
        if t1 <= t0:
            raise SystemExit(f"[agg] --window: T1 должно быть больше T0 ({t0}:{t1})")

    parts = []
    for i, cid in enumerate(want):
        f = Path(args.movements[i]) if args.movements else tracks_dir / f"movements_{cid}.csv"
        if not f.exists():
            print(f"[agg] ПРОПУСК {cid}: нет {f.name} (нужен classify.py)")
            continue
        d = pd.read_csv(f)
        if d.empty:
            print(f"[agg] {cid}: пусто"); continue
        off = args.offsets[i] if args.offsets else float(cams[cid].get("sync_offset_sec", 0))
        d["camera"] = cid
        d["t_common"] = d["t_sec"] + off
        print(f"[agg] {cid}: {len(d)} ТС из {f.name}, сдвиг {off:+.0f} с, "
              f"общее время {d.t_common.min():.0f}..{d.t_common.max():.0f} с")
        parts.append(d)
    if not parts:
        raise SystemExit("[agg] нет данных движений — сначала classify.py")
    df = pd.concat(parts, ignore_index=True)

    if t0 is None:
        df = df[df["t_common"] >= 0].copy()
        df["interval_start"] = (df["t_common"] // interval * interval).astype(int)
    else:
        n = len(df)
        df = df[(df["t_common"] >= t0) & (df["t_common"] < t1)].copy()
        print(f"[agg] окно {t0:.0f}..{t1:.0f} с ({(t1-t0)/60:.1f} мин): "
              f"оставлено {len(df)} из {n} ТС")
        df["interval_start"] = (t0 + (df["t_common"] - t0) // interval * interval).astype(int)
        tail = (t1 - t0) % interval
        if tail:
            last = int(t0 + (t1 - t0) // interval * interval)
            print(f"[agg] ВНИМАНИЕ: последний интервал {last} неполный — {tail:.0f} с "
                  f"вместо {interval}; его счёт не сравнивать с остальными напрямую")

    grp = (df.groupby(["interval_start", "entry", "movement", "exit", "cls"])
             .size().reset_index(name="count")
             .sort_values(["interval_start", "entry", "movement"]))
    matrix_csv = Path(args.out) if args.out else out_dir / "movements_matrix.csv"
    matrix_csv.parent.mkdir(parents=True, exist_ok=True)
    grp.to_csv(matrix_csv, index=False)

    print(f"[agg] камеры={want}  интервал={interval}с  всего ТС={len(df)}")
    print("\n[agg] сводка подъезд × движение (все интервалы, все классы):")
    print(pd.crosstab(df["entry"], df["movement"]).to_string())
    print("\n[agg] по типам ТС:")
    print(df["cls"].value_counts().to_string())
    print("\n[agg] 5-мин интервалы × подъезд (ТС):")
    by_ivl = pd.crosstab(df["interval_start"], df["entry"], margins=True, margins_name="всего")
    print(by_ivl.to_string())
    print(f"\n[agg] tidy-матрица -> {matrix_csv}")

    # routeSampler turn-counts XML (from/to = метки, заменишь на edge id сети)
    turn = (df.groupby(["interval_start", "entry", "exit"]).size()
              .reset_index(name="count"))
    xml = Path(args.out_xml) if args.out_xml else out_dir / "turn_counts.xml"
    xml.parent.mkdir(parents=True, exist_ok=True)
    with open(xml, "w", encoding="utf-8") as fo:
        fo.write('<data>\n')
        for ivl, gi in turn.groupby("interval_start"):
            # хвост окна короче интервала: иначе routeSampler размажет его счёт на полные 300 с
            end = ivl + interval if t1 is None else min(ivl + interval, int(t1))
            fo.write(f'  <interval id="i{ivl}" begin="{ivl}" end="{end}">\n')
            for _, r in gi.iterrows():
                fo.write(f'    <edgeRelation from={quoteattr(r["entry"])} '
                         f'to={quoteattr(r["exit"])} count="{int(r["count"])}"/>\n')
            fo.write('  </interval>\n')
        fo.write('</data>\n')
    print(f"[agg] routeSampler turn-counts -> {xml}")
    print("[agg]   (from/to = метки подъезда/ноги; замени на edge id после сборки сети в netedit)")


if __name__ == "__main__":
    main()
