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

Запуск:
    python src/aggregate.py                # все камеры с готовыми movements_*.csv
    python src/aggregate.py --cameras center
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
except Exception:
    pass


def main() -> None:
    ap = argparse.ArgumentParser(description="Агрегация движений в матрицу спроса")
    ap.add_argument("--cameras", nargs="*", default=None, help="по умолч. — все из конфига")
    args = ap.parse_args()

    cfg = yaml.safe_load(open(ROOT / "config.yaml", encoding="utf-8"))
    out_dir = Path(cfg["paths"]["out_dir"])
    tracks_dir = out_dir / "tracks"
    interval = int(cfg["aggregation"]["interval_sec"])
    cams = {c["id"]: c for c in cfg["cameras"]}
    want = args.cameras or list(cams)

    parts = []
    for cid in want:
        f = tracks_dir / f"movements_{cid}.csv"
        if not f.exists():
            print(f"[agg] ПРОПУСК {cid}: нет {f.name} (нужен classify.py)")
            continue
        d = pd.read_csv(f)
        if d.empty:
            print(f"[agg] {cid}: пусто"); continue
        d["camera"] = cid
        d["t_common"] = d["t_sec"] + float(cams[cid].get("sync_offset_sec", 0))
        parts.append(d)
    if not parts:
        raise SystemExit("[agg] нет данных движений — сначала classify.py")
    df = pd.concat(parts, ignore_index=True)

    df = df[df["t_common"] >= 0].copy()
    df["interval_start"] = (df["t_common"] // interval * interval).astype(int)

    grp = (df.groupby(["interval_start", "entry", "movement", "exit", "cls"])
             .size().reset_index(name="count")
             .sort_values(["interval_start", "entry", "movement"]))
    matrix_csv = out_dir / "movements_matrix.csv"
    grp.to_csv(matrix_csv, index=False)

    print(f"[agg] камеры={want}  интервал={interval}с  всего ТС={len(df)}")
    print("\n[agg] сводка подъезд × движение (все интервалы, все классы):")
    print(pd.crosstab(df["entry"], df["movement"]).to_string())
    print("\n[agg] по типам ТС:")
    print(df["cls"].value_counts().to_string())
    print(f"\n[agg] tidy-матрица -> {matrix_csv}")

    # routeSampler turn-counts XML (from/to = метки, заменишь на edge id сети)
    turn = (df.groupby(["interval_start", "entry", "exit"]).size()
              .reset_index(name="count"))
    xml = out_dir / "turn_counts.xml"
    with open(xml, "w", encoding="utf-8") as fo:
        fo.write('<data>\n')
        for ivl, gi in turn.groupby("interval_start"):
            fo.write(f'  <interval id="i{ivl}" begin="{ivl}" end="{ivl+interval}">\n')
            for _, r in gi.iterrows():
                fo.write(f'    <edgeRelation from={quoteattr(r["entry"])} '
                         f'to={quoteattr(r["exit"])} count="{int(r["count"])}"/>\n')
            fo.write('  </interval>\n')
        fo.write('</data>\n')
    print(f"[agg] routeSampler turn-counts -> {xml}")
    print("[agg]   (from/to = метки подъезда/ноги; замени на edge id после сборки сети в netedit)")


if __name__ == "__main__":
    main()
