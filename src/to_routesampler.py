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
"""
from __future__ import annotations

import sys
from pathlib import Path
from xml.sax.saxutils import quoteattr

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
SUMO = ROOT / "sumo"
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

LABEL_LEG = {"SVB_N": "N", "SVB_S": "S", "PRB_E": "E", "PRB_W": "W"}


def approach_edge(label):  return f"n{LABEL_LEG[label]}_nC"
def exit_edge(label):      return f"nC_n{LABEL_LEG[label]}"


def main():
    import yaml
    cfg = yaml.safe_load(open(ROOT / "config.yaml", encoding="utf-8"))
    m = pd.read_csv(Path(cfg["paths"]["out_dir"]) / "movements_matrix.csv")
    interval = int(cfg["aggregation"]["interval_sec"])

    m = m[m["entry"] != m["exit"]].copy()           # выкинуть развороты (нет связи)
    m["from_e"] = m["entry"].map(approach_edge)
    m["to_e"] = m["exit"].map(exit_edge)

    # turn counts по интервалам (суммарно по типам ТС)
    turn = (m.groupby(["interval_start", "from_e", "to_e"])["count"].sum()
              .reset_index())
    tc = SUMO / "turn_counts_edges.xml"
    with open(tc, "w", encoding="utf-8") as f:
        f.write("<data>\n")
        for ivl, gi in turn.groupby("interval_start"):
            f.write(f'  <interval id="i{ivl}" begin="{ivl}" end="{ivl+interval}">\n')
            for _, r in gi.iterrows():
                f.write(f'    <edgeRelation from={quoteattr(r.from_e)} '
                        f'to={quoteattr(r.to_e)} count="{int(r["count"])}"/>\n')
            f.write("  </interval>\n")
        f.write("</data>\n")

    # кандидатные маршруты: по одному на присутствующую пару (from,to)
    pairs = turn[["from_e", "to_e"]].drop_duplicates().reset_index(drop=True)
    cand = SUMO / "candidate.rou.xml"
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
    print(f'  python "%SUMO_HOME%\\tools\\routeSampler.py" -r {cand} -t {tc} -o {SUMO/"demand.rou.xml"}')


if __name__ == "__main__":
    main()
