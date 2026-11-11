"""Switching inside the longest no-arrival window of deadlocked E12 episodes (files only)."""
import csv, re, sys, statistics as st
from collections import defaultdict
from pathlib import Path

pack, diag = Path(sys.argv[1]), Path(sys.argv[2])
dead = {(r["policy"], r["set"], r["k"], r["map"], r["e"]) for r in csv.DictReader(diag.open(encoding="utf-8")) if r["deadlock"] == "1"}
name = {"heldout": "held-out", "scenario": "scenario", "transfer": "transfer"}
out = defaultdict(list)
for r in csv.DictReader((pack / "results" / "eval_runs.csv").open(encoding="utf-8")):
    s = f"{name[r['eval_set']]} {r['load_or_scenario']}"
    if (r["policy"], s, r["training_run"], r["map"], r["episode"]) not in dead:
        continue
    trip = pack / r["tripinfo_path"]
    arr = sorted(float(a) for a in re.findall(r'arrival="([-\d.]+)"', trip.read_text(encoding="utf-8")) if float(a) >= 0)
    pts = [0.0] + arr + [1800.0]
    i = max(range(len(pts) - 1), key=lambda j: pts[j + 1] - pts[j])
    a, b = pts[i], pts[i + 1]
    times = [float(l.split(",")[0]) for l in (trip.parent / f"metrics_{r['episode']}.csv").open() if l.strip()]
    sw = sum(1 for x, y in zip(times, times[1:]) if round(y - x) == 9 and a <= x < b)
    out[r["policy"]].append((b - a, sw, sw / ((b - a) / 1800)))
for p, v in out.items():
    print(f"{p:14s} deadlocked episodes {len(v):3d} | window s (median) {st.median(x[0] for x in v):5.0f} | "
          f"switches in window: median {st.median(x[1] for x in v):4.0f}, zero in {sum(1 for x in v if x[1] == 0)} | "
          f"rate per 1800 s (median) {st.median(x[2] for x in v):5.1f}")
