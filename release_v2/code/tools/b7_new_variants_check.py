"""Integrity and first summary of the B7 final-design episodes on the new variants (ce_bias, ce_rand, fov_meas)."""
import csv
import re
import statistics as st
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path

K = Path(r"D:\GitHub\video-to-sumo-rl-e12\e13")
D = Path(r"D:\GitHub\video-to-sumo-rl\revision\twin\B7\demand")
rows = list(csv.DictReader(open(K / "results" / "b7_final_episodes.csv", encoding="utf-8")))
print("rows", len(rows), "variants", dict(Counter((r["b7_load"], r["b7_variant"]) for r in rows)))
print("design", Counter((r["rung"], r["policy"]) for r in rows))

# expected vehicles per route file
nveh = {}
for p in D.glob("x1[02]/*/*.rou.xml"):
    nveh[p.name] = sum(1 for _ in re.finditer(rb"<vehicle ", p.read_bytes()))

problems = []
seen = Counter()
for r in rows:
    k, s = int(r["training_run"]), int(r["b7_seed"])
    e = s - 7000 if s < 7100 else s - 7100
    if int(r["sumo_seed"]) != 42 + 1000 + k + e:
        problems.append(("seed", r["b7_load"], r["b7_variant"], k, s, r["sumo_seed"]))
    if r["tripinfo_ok"] not in ("1", "True", "true"):
        problems.append(("tripinfo", r["b7_load"], r["b7_variant"], k, s))
    exp = nveh.get(r["route_file"])
    if exp is None or int(r["demand"]) != exp:
        problems.append(("demand", r["route_file"], r["demand"], exp))
    if f"_{r['b7_variant']}_{r['b7_load']}_s{s}." not in r["route_file"]:
        problems.append(("file", r["route_file"]))
    seen[(r["b7_load"], r["b7_variant"], k, s)] += 1
dups = [k for k, v in seen.items() if v > 1]
print("problems:", problems[:10], "| duplicates:", dups[:5])
for (load, var), n in sorted(Counter((r["b7_load"], r["b7_variant"]) for r in rows).items()):
    ks = {int(r["training_run"]) for r in rows if (r["b7_load"], r["b7_variant"]) == (load, var)}
    ss = sorted({int(r["b7_seed"]) for r in rows if (r["b7_load"], r["b7_variant"]) == (load, var)})
    print(f"  {load} {var}: {n} episodes, models {sorted(ks)}, seeds {ss[0]}..{ss[-1]} ({len(ss)})")

print("\n== final design, mean over models and seeds")
agg = defaultdict(list)
for r in rows:
    agg[(r["b7_load"], r["b7_variant"])].append(r)
print("load variant   demand  served%  mean_delay_s  total_delay_vh  not_inserted  unfinished  deadlocks")
for key in sorted(agg):
    g = agg[key]
    f = lambda c: st.mean(float(x[c]) for x in g)
    served = st.mean(float(x["arrived_1800"]) / float(x["demand"]) for x in g) * 100
    print(f"{key[0]} {key[1]:9} {f('demand'):7.1f} {served:7.2f} {f('mean_delay_s'):12.2f} {f('total_delay_vh'):14.3f}"
          f" {f('not_inserted'):12.2f} {f('unfinished'):10.2f} {sum(x['deadlock'] in ('1','True','true') for x in g):9d}")

print("\n== paired with base (same model k and seed index e = 1..5)")
by = {(r["b7_load"], r["b7_variant"], int(r["training_run"]), int(r["b7_seed"]) % 100): r for r in rows}
for load in ("x10", "x12"):
    for var in ("fov_meas", "ce_bias", "ce_rand"):
        d_delay, d_served = [], []
        for k in range(1, 6):
            for e in range(1, 6):
                b, v = by.get((load, "base", k, e)), by.get((load, var, k, e))
                if b and v:
                    d_delay.append(float(v["mean_delay_s"]) - float(b["mean_delay_s"]))
                    d_served.append(100 * (float(v["arrived_1800"]) / float(v["demand"])
                                           - float(b["arrived_1800"]) / float(b["demand"])))
        if d_delay:
            print(f"  {load} {var:9} n={len(d_delay):2d}  mean delay diff {st.mean(d_delay):+6.2f} s "
                  f"(min {min(d_delay):+.2f}, max {max(d_delay):+.2f})  served diff {st.mean(d_served):+5.2f} pp")
