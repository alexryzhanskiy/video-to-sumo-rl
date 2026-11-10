"""E12 diagnostics from the pack (files only): phase-switch rate and, in deadlocked episodes, where the vehicles stand.

Per E12 evaluation episode:
  switches        decision gaps of 9 s (3 s yellow + 4 s all-red + 2 s green); holds are 5-s gaps (RESCO metrics_N.csv)
  lost_time_s     7 s per switch
  unfinished_by_approach   unfinished vehicles by inbound approach (tripinfo departLane edge, nN/nS/nE/nW -> nC)
  top2_share      share of unfinished vehicles on the two most loaded approaches
For the fixed plan: 4 switches per 120-s cycle (60 per 1800 s), lost time 4 x 3 s yellow + 2 x 4 s all-red per cycle.

  revision/.venv/Scripts/python.exe revision/tools/e12_diagnostics.py --pack revision/runs/e12 \
      --episodes revision/analysis/e12/episodes_all.csv --out revision/analysis/e12
"""
from __future__ import annotations

import argparse
import csv
import re
import statistics as st
from collections import Counter, defaultdict
from pathlib import Path

E12_POL = ["IDQN-wait", "IDQN-queue", "MPLight", "IDQN-pressure"]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pack", type=Path, required=True)
    ap.add_argument("--episodes", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    with (args.pack / "results" / "eval_runs.csv").open(newline="", encoding="utf-8") as f:
        runs = list(csv.DictReader(f))
    with args.episodes.open(newline="", encoding="utf-8") as f:
        dead = {(r["policy"], r["set"], r["k"], r["map"], r["e"]): int(r["deadlock"])
                for r in csv.DictReader(f) if r["source"] == "E12"}
    name = {"heldout": "held-out", "scenario": "scenario", "transfer": "transfer"}
    rows = []
    for r in runs:
        trip = args.pack / r["tripinfo_path"]
        times = [float(line.split(",")[0]) for line in (trip.parent / f"metrics_{r['episode']}.csv").open() if line.strip()]
        gaps = Counter(round(b - a) for a, b in zip(times, times[1:]))
        unfinished = Counter()
        for attrs in re.findall(r"<tripinfo\s([^>]*)>", trip.read_text(encoding="utf-8")):
            a = dict(re.findall(r'(\w+)="([^"]*)"', attrs))
            if float(a["arrival"]) < 0:
                unfinished[a["departLane"].rsplit("_", 1)[0]] += 1
        n_unf = sum(unfinished.values())
        set_name = f"{name[r['eval_set']]} {r['load_or_scenario']}"
        rows.append({"policy": r["policy"], "set": set_name, "k": r["training_run"], "map": r["map"],
                     "e": r["episode"], "switches": gaps.get(9, 0), "holds": gaps.get(5, 0),
                     "other_gaps": sum(v for g, v in gaps.items() if g not in (5, 9)),
                     "lost_time_s": 7 * gaps.get(9, 0), "unfinished": n_unf,
                     "unfinished_by_approach": " ".join(f"{k}:{v}" for k, v in sorted(unfinished.items())),
                     "top2_share": round(sum(v for _, v in unfinished.most_common(2)) / n_unf, 3) if n_unf else "",
                     "deadlock": dead[(r["policy"], set_name, r["training_run"], r["map"], r["episode"])]})
    with (args.out / "diagnostics_episodes.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    md = ["# E12 diagnostics: phase switching and stranded vehicles", "",
          "From the pack's `metrics_N.csv` (decision times) and tripinfo files. Fixed plan for reference: 60 switches per "
          "1800 s and 300 s of yellow + all-red per 1800 s (4 × 3 s + 2 × 4 s per 120-s cycle). DRL: 7 s per switch.", "",
          f"Decision gaps other than 5 s and 9 s: {sum(r['other_gaps'] for r in rows)} in {len(rows)} episodes.", "",
          "| Set | Policy | Switches per 1800 s (mean) | Yellow + all-red, s (mean) | Deadlocked episodes | In deadlocks: "
          "unfinished vehicles (mean) | In deadlocks: share on the two most loaded approaches (mean) |",
          "|---|---|---|---|---|---|---|"]
    g = defaultdict(list)
    for r in rows:
        g[(r["set"], r["policy"])].append(r)
    for s in ["held-out x1.0", "held-out x1.2", "held-out x1.5", "scenario S1", "scenario S2", "scenario S3",
              "scenario S4", "transfer x1.2", "transfer x1.5"]:
        for p in E12_POL:
            rr = g.get((s, p), [])
            if not rr:
                continue
            dd = [r for r in rr if r["deadlock"]]
            md.append(f"| {s} | {p} | {st.mean(r['switches'] for r in rr):.0f} | {st.mean(r['lost_time_s'] for r in rr):.0f} | "
                      f"{len(dd)}/{len(rr)} | {st.mean(r['unfinished'] for r in dd):.0f} | "
                      f"{st.mean(r['top2_share'] for r in dd if r['top2_share'] != ''):.2f} |" if dd else
                      f"| {s} | {p} | {st.mean(r['switches'] for r in rr):.0f} | {st.mean(r['lost_time_s'] for r in rr):.0f} | "
                      f"0/{len(rr)} | – | – |")
    (args.out / "diagnostics.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md[:14]))


if __name__ == "__main__":
    main()
