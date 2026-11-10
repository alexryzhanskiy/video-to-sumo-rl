"""Locked test, exploratory comparison: E13 final design vs fixed plan, actuated (E13) and tuned MaxPressure, Webster (S2c).

Usage: python e13_locked_baselines.py <e13/results> <S2c out/results>
Episodes are paired on (map, route_file, sumo_seed); the baselines of training run k use the seeds of DRL run k.
Per-load DRL models (L1-L3) are evaluated on their own load; scenarios S1-S4 use the x1.0 model.
"""
import csv
import json
import statistics as st
import sys
from pathlib import Path

e13, s2c = Path(sys.argv[1]), Path(sys.argv[2])
rd = lambda p: list(csv.DictReader(open(p, encoding="utf-8")))
true = lambda v: v in ("1", "True", "true")
final = json.load(open(e13 / "selection_final.json", encoding="utf-8"))["final"]
MAPS = {"x1.0": "prybuzka_lt10", "x1.2": "prybuzka_lt12", "x1.5": "prybuzka_lt15",
        "S1": "prybuzka_lts1", "S2": "prybuzka_lts2", "S3": "prybuzka_lts3", "S4": "prybuzka_lts4"}
MODEL_LOAD = {"x1.0": "x1.0", "x1.2": "x1.2", "x1.5": "x1.5", "S1": "x1.0", "S2": "x1.0", "S3": "x1.0", "S4": "x1.0"}

rows = {}
for r in rd(e13 / "baseline_episodes.csv"):
    if r["eval_set"] == "locked":
        rows.setdefault((r["policy"], r["map"]), []).append(r)
for r in rd(e13 / "eval_episodes.csv"):
    if r["eval_set"] == "locked" and r["rung"] == final["rung"] and r["policy"] == final["policy"]:
        rows.setdefault(("final", r["map"], r["train_load"]), []).append(r)
for r in rd(s2c / "eval_episodes.csv"):
    if r["eval_set"] == "locked":
        rows.setdefault((r["policy"], r["map"]), []).append(r)
s2c_fixed = {(r["map"], r["route_file"], r["sumo_seed"]): r for r in rd(s2c / "queue_episodes.csv")
             if r["eval_set"] == "locked" and r["policy"] == "Fixed plan"}

key = lambda r: (r["map"], r["route_file"], r["sumo_seed"])
CTRLS = ["Fixed plan", "Actuated", "MaxPressure", "Webster", "final"]
print("| Demand | Controller | Episodes | Deadlocks | Full | Arrived by 1800 s | Δ fixed, % | Delay, s/veh | Total delay, veh·h |")
print("|---|---|---|---|---|---|---|---|---|")
pairs_out = {}
for lab, m in MAPS.items():
    fx = {key(r): r for r in rows.get(("Fixed plan", m), [])}
    for c in CTRLS:
        rr = rows.get(("final", m, MODEL_LOAD[lab]) if c == "final" else (c, m), [])
        if not rr:
            continue
        ok = all(true(r["tripinfo_ok"]) for r in rr)
        d = [float(r["arrived_1800"]) - float(fx[key(r)]["arrived_1800"]) for r in rr if key(r) in fx]
        dem = st.mean(float(r["demand"]) for r in rr)
        name = f"{final['rung']} {final['policy']}" + (" (x1.0 model)" if lab.startswith("S") else "") if c == "final" else c
        print(f"| {lab} | {name} | {len(rr)}{'' if ok else ' (tripinfo!)'} | {sum(true(r['deadlock']) for r in rr)} | "
              f"{100 * sum(true(r['full']) for r in rr) / len(rr):.0f}% | {st.mean(float(r['arrived_1800']) for r in rr):.1f} | "
              f"{'' if c == 'Fixed plan' else f'{100 * st.mean(d) / dem:+.2f}' if len(d) == len(rr) else 'unpaired'} | "
              f"{st.mean(float(r['mean_delay_s']) for r in rr):.1f} | {st.mean(float(r['total_delay_vh']) for r in rr):.2f} |")
    # final design vs tuned MaxPressure per training run (mean over files of the paired difference)
    fin = {key(r): r for r in rows.get(("final", m, MODEL_LOAD[lab]), [])}
    mp = rows.get(("MaxPressure", m), [])
    per = {}
    for r in mp:
        if key(r) in fin:
            per.setdefault(r["training_run"], []).append((float(fin[key(r)]["arrived_1800"]) - float(r["arrived_1800"]),
                                                          float(fin[key(r)]["total_delay_vh"]) - float(r["total_delay_vh"])))
    pairs_out[lab] = {k: (round(st.mean(a for a, _ in v), 2), round(st.mean(b for _, b in v), 2), len(v)) for k, v in sorted(per.items())}
print()
print("Final design minus tuned MaxPressure, per training run k: (arrivals, total delay veh·h, files)")
for lab, v in pairs_out.items():
    print(f"  {lab}: {v}")
# integrity: S2c fixed plan (queue stage) vs E13 fixed plan on the same locked episodes
e13_fixed = {key(r): r for k, rr in rows.items() if k[0] == "Fixed plan" for r in rr}
same = sum(1 for k, r in s2c_fixed.items() if k in e13_fixed and r["arrived_1800"] == e13_fixed[k]["arrived_1800"]
           and r["total_delay_vh"] == e13_fixed[k]["total_delay_vh"])
print(f"\nS2c fixed plan vs E13 fixed plan on the locked files: {same} of {len(s2c_fixed)} episodes identical "
      f"(E13 has {len(e13_fixed)})")
