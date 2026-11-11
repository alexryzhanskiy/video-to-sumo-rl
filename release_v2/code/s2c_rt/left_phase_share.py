"""Left-turn phases under the two MaxPressure variants on the locked test set (post hoc, deviation D20).

Reads the decision logs of the locked-test episodes (each episode JSON holds `decisions`, a list of [time s, phase]
with phases 0 Svobody through, 1 Svobody left, 2 Prybuzka through, 3 Prybuzka left) of the pre-registered tuned
MaxPressure (revision/runs/s2c/out/eval/locked/mp/) and of the right-turn MaxPressure
(revision/runs/s2c_rt/out/eval/locked/mp/), and writes per controller and demand:
  - share of decisions with a left-turn phase (1 or 3) chosen;
  - share of decision time with a left-turn phase, each decision counted until the next one;
  - left-turn greens per episode (changes into phase 1 or 3), mean and minimum.
Output: revision/runs/s2c_rt/out/results/left_phase_share.csv. Run from the repository root:

    python revision/s2c_rt/left_phase_share.py
"""
from __future__ import annotations

import csv
import json
import statistics as st
from pathlib import Path

REV = Path(__file__).resolve().parents[1]
SOURCES = {"MaxPressure (pre-registered)": REV / "runs/s2c/out/eval/locked/mp",
           "MaxPressure-RT (post hoc)": REV / "runs/s2c_rt/out/eval/locked/mp"}
DEMANDS = {"prybuzka_lt10": "x1.0", "prybuzka_lt12": "x1.2", "prybuzka_lt15": "x1.5", "prybuzka_lts1": "S1",
           "prybuzka_lts2": "S2", "prybuzka_lts3": "S3", "prybuzka_lts4": "S4"}
LEFT = (1, 3)
OUT = REV / "runs/s2c_rt/out/results/left_phase_share.csv"


def episode(path: Path) -> tuple[float, float, int]:
    dec = json.loads(path.read_text(encoding="utf-8"))["decisions"]
    phases = [p for _, p in dec]
    share_n = sum(p in LEFT for p in phases) / len(phases)
    durations = [t1 - t0 for (t0, _), (t1, _) in zip(dec, dec[1:])]
    share_t = sum(d for d, (_, p) in zip(durations, dec) if p in LEFT) / sum(durations)
    greens = sum(1 for a, b in zip([None] + phases, phases) if b in LEFT and a != b)
    return share_n, share_t, greens


def main() -> None:
    rows = []
    for ctrl, root in SOURCES.items():
        for m, lab in DEMANDS.items():
            files = sorted((root / m).glob("*.json"))
            if not files:
                raise SystemExit(f"{ctrl} {lab}: no episodes in {root / m}")
            vals = [episode(f) for f in files]
            rows.append({"controller": ctrl, "demand": lab, "episodes": len(vals),
                         "left_share_decisions": round(st.mean(v[0] for v in vals), 4),
                         "left_share_time": round(st.mean(v[1] for v in vals), 4),
                         "left_greens_mean": round(st.mean(v[2] for v in vals), 2),
                         "left_greens_min": min(v[2] for v in vals)})
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    for r in rows:
        print(r)


if __name__ == "__main__":
    main()
