"""E14 (exploratory, approved 2 Nov 2026; kb/07 E14): the frozen E13 final design and the four non-learning baselines on
the second real demand window (09:38, 923 vehicles over 0-1200 s, 10 route files, revision/twin/E14).

Usage: python e14_analysis.py <e13/results> <E14 baselines results folder> <E14 demand folder> <output prefix>
Inputs: <e13/results>/e14_final_episodes.csv (MyPC, b7.py) and selection_final.json; <baselines>/e14_episodes.csv
(laptop, s2c.py e14); the route files, to check the SHA-256 of what was run against what was generated.

Statistics as the exploratory locked-test analysis (e13_exploratory_locked.py, pre-registration 7.1): unit = training
run k (n = 5); for a baseline, k is the seed group with the SUMO seeds of DRL run k, so every comparison is paired on
(route file, SUMO seed). Per k, a metric is the mean over the 10 files; 95% t CIs (df 4); final design minus each
baseline, two-sided one-sample t-tests on d_k, Holm over the 4 baselines within each measure (arrivals by 1800 s; total
delay). If the five d_k are equal (SD = 0), p = 1 when they are 0, else 0 (the limit), flagged.
"""
import csv
import hashlib
import json
import math
import statistics as st
import sys
from pathlib import Path

from scipy import stats

e13, base_dir, demand, prefix = (Path(a) for a in sys.argv[1:5])
rd = lambda p: list(csv.DictReader(open(p, encoding="utf-8")))
final = json.load(open(e13 / "selection_final.json", encoding="utf-8"))["final"]
FINAL = f"{final['rung']} {final['policy']}"
BASELINES = ["Fixed plan", "Actuated", "MaxPressure", "Webster"]
NAME = {"Fixed plan": "Fixed plan", "Actuated": "Actuated", "MaxPressure": "Tuned MaxPressure",
        "Webster": "Webster plan", FINAL: f"Final design ({FINAL})"}
MEASURES = {"arrived_1800": "Arrivals by 1800 s", "total_delay_vh": "Total delay (veh-h)"}
EXTRA = {"mean_delay_s": "Delay per demanded vehicle (s)", "mean_wait_arrived_s": "Mean wait of arrived vehicles (s)"}
problems = []

sha = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in demand.rglob("*.rou.xml")}
rows = {FINAL: [r for r in rd(e13 / "e14_final_episodes.csv")]}
for r in rd(base_dir / "e14_episodes.csv"):
    rows.setdefault(r["policy"], []).append(r)
for r in rows[FINAL]:
    if f"{r['rung']} {r['policy']}" != FINAL or r["train_load"] != "x1.0":
        problems.append(f"final row of another model: {r['rung']} {r['policy']} {r['train_load']}")
for c, rs in rows.items():
    if len(rs) != 50:
        problems.append(f"{c}: {len(rs)} episodes, expected 50")
    for r in rs:
        k, e = int(r["training_run"]), int(r["b7_seed"]) % 100
        if int(r["sumo_seed"]) != 1042 + k + e:
            problems.append(f"{c} {r['route_file']} k{k}: SUMO seed {r['sumo_seed']} != {1042 + k + e}")
        if r["route_file"] not in sha:
            problems.append(f"{c}: unknown route file {r['route_file']}")
        if r["tripinfo_ok"] not in ("1", "True") or int(r["demand"]) != 923:
            problems.append(f"{c} {r['route_file']} k{k}: tripinfo_ok {r['tripinfo_ok']}, demand {r['demand']}")
if sorted(BASELINES + [FINAL]) != sorted(rows):
    problems.append(f"controllers {sorted(rows)}")


def tci(xs):
    n, mu = len(xs), st.mean(xs)
    sd = st.stdev(xs)
    h = stats.t.ppf(0.975, n - 1) * sd / math.sqrt(n)
    return mu, sd, mu - h, mu + h


def per_run(rs, m):
    by = {}
    for r in rs:
        by.setdefault(int(r["training_run"]), []).append(float(r[m]))
    return [st.mean(by[k]) for k in sorted(by)]


levels, diffs = [], []
for c in BASELINES + [FINAL]:
    rs = rows[c]
    x = {"controller": NAME[c], "episodes": len(rs), "full": sum(r["full"] in ("1", "True") for r in rs),
         "deadlock": sum(r["deadlock"] in ("1", "True") for r in rs)}
    for m in list(MEASURES) + list(EXTRA):
        mu, sd, lo, hi = tci(per_run(rs, m))
        x |= {m: mu, f"{m}_lo": lo, f"{m}_hi": hi}
    levels.append(x)
key = lambda r: (r["route_file"], r["sumo_seed"])
fin = {key(r): r for r in rows[FINAL]}
for m, lab in MEASURES.items():
    fam = []
    for c in BASELINES:
        pairs = [(fin[key(b)], b) for b in rows[c] if key(b) in fin]
        if len(pairs) != 50:
            problems.append(f"final vs {c}: {len(pairs)} pairs")
        by = {}
        for a, b in pairs:
            by.setdefault(int(a["training_run"]), []).append(float(a[m]) - float(b[m]))
        d = [st.mean(by[k]) for k in sorted(by)]
        mu, sd, lo, hi = tci(d)
        flag = ""
        if sd > 0:
            p = 2 * stats.t.sf(abs(mu) / (sd / math.sqrt(len(d))), len(d) - 1)
        else:
            p, flag = (1.0 if mu == 0 else 0.0), "SD = 0"
        fam.append({"measure": lab, "baseline": NAME[c], "mean": mu, "lo": lo, "hi": hi,
                    "pct_of_baseline": 100 * mu / st.mean(float(b[m]) for _, b in pairs) if mu else 0.0,
                    "runs_lower": sum(v < 0 for v in d), "runs_higher": sum(v > 0 for v in d), "p": p, "flag": flag,
                    "d_k": ";".join(f"{v:.3f}" for v in d)})
    run_max = 0.0
    for i, x in enumerate(sorted(fam, key=lambda x: x["p"])):
        run_max = max(run_max, min(1.0, (len(fam) - i) * x["p"]))
        x["p_holm"] = run_max
    diffs += fam

for name, rs in (("levels", levels), ("diffs", diffs)):
    with open(f"{prefix}_{name}.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rs[0]))
        w.writeheader()
        w.writerows(rs)
md = ["# E14: second real demand window (09:38), exploratory (not pre-specified)", "",
      f"Final design {FINAL} (x1.0 models, runs 1-5, frozen) and the baselines with their x1.0 configurations, on 10 route "
      "files of the 09:38 window (923 vehicles over 0-1200 s), 1800-s episodes, field clearance, default vehicle. Per run "
      "k the mean over the 10 files; 95% t CIs (df 4).", "",
      "| Controller | Episodes | Full demand | Deadlocks | Arrivals by 1800 s [95% CI] | Total delay, veh-h [95% CI] | "
      "Delay per demanded vehicle, s [95% CI] | Mean wait of arrived, s |", "|---|---|---|---|---|---|---|---|"]
for x in levels:
    md.append(f"| {x['controller']} | {x['episodes']} | {x['full']} | {x['deadlock']} | {x['arrived_1800']:.1f} "
              f"[{x['arrived_1800_lo']:.1f}, {x['arrived_1800_hi']:.1f}] | {x['total_delay_vh']:.2f} "
              f"[{x['total_delay_vh_lo']:.2f}, {x['total_delay_vh_hi']:.2f}] | {x['mean_delay_s']:.1f} "
              f"[{x['mean_delay_s_lo']:.1f}, {x['mean_delay_s_hi']:.1f}] | {x['mean_wait_arrived_s']:.1f} |")
md += ["", "## Final design minus baseline (paired on route file and SUMO seed); Holm over 4 baselines per measure", "",
       "| Measure | Baseline | Mean [95% CI] | % of baseline | Runs lower / higher | p | p (Holm) |", "|---|---|---|---|---|---|---|"]
for x in diffs:
    md.append(f"| {x['measure']} | {x['baseline']} | {x['mean']:+.3f} [{x['lo']:+.3f}, {x['hi']:+.3f}] | "
              f"{x['pct_of_baseline']:+.1f}% | {x['runs_lower']} / {x['runs_higher']} | {x['p']:.4f}{' (' + x['flag'] + ')' if x['flag'] else ''} | "
              f"{x['p_holm']:.4f} |")
md += ["", "Route files (SHA-256 of the files in the demand folder): " + ", ".join(f"{n} {h[:12]}" for n, h in sorted(sha.items())),
       "", "Problems: " + ("; ".join(problems) if problems else "none")]
Path(f"{prefix}.md").write_text("\n".join(md) + "\n", encoding="utf-8")
print("\n".join(md))
