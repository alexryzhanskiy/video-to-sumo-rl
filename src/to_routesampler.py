"""Мост Этап 5 -> routeSampler: метки подъездов/ног -> edge id сети.

Из movements_matrix.csv делает:
  sumo/turn_counts_edges.xml  — edgeRelation from/to = edge id (по интервалам)
  sumo/candidate.rou.xml      — кандидатные маршруты (по одному на присутствующее
                                движение approach_edge -> exit_edge)

Разворот (from-нога == to-нога) исключается: связи разворота в сети нет (--no-turnarounds),
и это в основном шум трекинга.

Соответствие меток -> нога -> edge:
  подъезд (from): label -> n{leg}_nC ;  выезд (to): label -> nC_n{leg}

Запуск:  python src/to_routesampler.py
         python src/to_routesampler.py --in M.csv --out-dir D --end 1445   # другая запись

Для другой записи время интервалов остаётся общим временем её камер, первый интервал
начинается не с нуля. --end — конец общего окна: без него хвост объявляется полным интервалом.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from xml.sax.saxutils import quoteattr

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
SUMO = ROOT / "sumo"
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")   # SystemExit печатается в stderr
except Exception:
    pass

LABEL_LEG = {"SVB_N": "N", "SVB_S": "S", "PRB_E": "E", "PRB_W": "W"}


def approach_edge(label):  return f"n{LABEL_LEG[label]}_nC"
def exit_edge(label):      return f"nC_n{LABEL_LEG[label]}"


def main():
    ap = argparse.ArgumentParser(description="Метки подъездов -> edge id для routeSampler")
    ap.add_argument("--in", dest="inp", default=None,
                    help="tidy-матрица (по умолч. movements_matrix.csv); требует --out-dir")
    ap.add_argument("--out-dir", default=None,
                    help="куда писать файлы (по умолч. sumo/). Нужен для другой записи, "
                         "чтобы не перезатереть опорные")
    ap.add_argument("--end", type=int, default=None, help="конец общего окна записи, с")
    args = ap.parse_args()
    if args.inp and not args.out_dir:
        raise SystemExit("[bridge] --in без --out-dir перезаписал бы опорные файлы в sumo/")

    import yaml
    cfg = yaml.safe_load(open(ROOT / "config.yaml", encoding="utf-8"))
    inp = Path(args.inp) if args.inp else Path(cfg["paths"]["out_dir"]) / "movements_matrix.csv"
    if not inp.exists():
        raise SystemExit(f"[bridge] нет матрицы: {inp}. Сначала aggregate.py")
    m = pd.read_csv(inp)
    interval = int(cfg["aggregation"]["interval_sec"])
    out_dir = Path(args.out_dir) if args.out_dir else SUMO
    out_dir.mkdir(parents=True, exist_ok=True)

    m = m[m["entry"] != m["exit"]].copy()           # выкинуть развороты (нет связи)
    m["from_e"] = m["entry"].map(approach_edge)
    m["to_e"] = m["exit"].map(exit_edge)

    # turn counts по интервалам (суммарно по типам ТС)
    turn = (m.groupby(["interval_start", "from_e", "to_e"])["count"].sum()
              .reset_index())
    tc = out_dir / "turn_counts_edges.xml"
    with open(tc, "w", encoding="utf-8") as f:
        f.write("<data>\n")
        for ivl, gi in turn.groupby("interval_start"):
            end = ivl + interval if args.end is None else min(ivl + interval, args.end)
            f.write(f'  <interval id="i{ivl}" begin="{ivl}" end="{end}">\n')
            for _, r in gi.iterrows():
                f.write(f'    <edgeRelation from={quoteattr(r.from_e)} '
                        f'to={quoteattr(r.to_e)} count="{int(r["count"])}"/>\n')
            f.write("  </interval>\n")
        f.write("</data>\n")

    # кандидатные маршруты: по одному на присутствующую пару (from,to)
    pairs = turn[["from_e", "to_e"]].drop_duplicates().reset_index(drop=True)
    cand = out_dir / "candidate.rou.xml"
    with open(cand, "w", encoding="utf-8") as f:
        f.write("<routes>\n")
        for i, r in pairs.iterrows():
            f.write(f'  <route id="m{i}" edges="{r.from_e} {r.to_e}"/>\n')
        f.write("</routes>\n")

    total = int(turn["count"].sum())
    print(f"[bridge] движений (без разворотов) = {total}, интервалов = {turn.interval_start.nunique()}, "
          f"маршрутов-кандидатов = {len(pairs)}")
    print(f"[bridge] -> {tc}")
    print(f"[bridge] -> {cand}")
    print("\n[bridge] запусти routeSampler:")
    print(f'  python "%SUMO_HOME%\\tools\\routeSampler.py" -r {cand} -t {tc} -o {out_dir/"demand.rou.xml"}')


if __name__ == "__main__":
    main()
