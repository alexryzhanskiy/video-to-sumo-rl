"""E13 locked test: CO2 per demanded vehicle at x1.0 and x1.2 (decision D-9, 30 Oct 2026; exploratory, NOT pre-specified).

Usage: python e13_co2_locked.py <e13/results> <S2c CO2 csv> <output prefix>
Inputs: <e13/results>/co2_final_locked.csv and co2_baselines_locked.csv (MyPC, e13/extract_co2.py) and the S2c CO2
file made with the same script on the laptop (revision/analysis/co2/co2_s2c_locked.csv: tuned MaxPressure and Webster).
CO2 = sum of CO2_abs over the episode's tripinfo (every vehicle written by SUMO; the emissions device was on in every
run). x1.5 is left out: vehicles that never enter emit nothing, which would favour controllers that keep demand out.
Unit = training run (n = 5): per run, the mean over its 10 locked files; 95% t CIs; final design minus each baseline,
paired on (route file, SUMO seed); two-sided one-sample t-tests on d_k, Holm over the 8 tests (2 loads x 4 baselines).
"""
import csv
import math
import statistics as st
import sys
from pathlib import Path

from scipy import stats

e13, s2c_co2, prefix = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
rd = lambda p: list(csv.DictReader(open(p, encoding="utf-8")))
LOADS = {"prybuzka_lt10": "x1.0", "prybuzka_lt12": "x1.2"}
NAME = {"Fixed plan": "Fixed plan", "Actuated": "Actuated", "MaxPressure": "Tuned MaxPressure", "Webster": "Webster plan"}
eps, problems = {}, []
for r in rd(e13 / "co2_final_locked.csv"):
    eps.setdefault(("Final design", r["map"]), []).append(r)
for r in rd(e13 / "co2_baselines_locked.csv") + rd(s2c_co2):
    eps.setdefault((NAME[r["policy"]], r["map"]), []).append(r)
for k, rows in eps.items():
    if len(rows) != 50:
        problems.append(f"{k}: {len(rows)} episodes")
    if any(r["entries"] != r["with_emissions"] or int(r["entries"]) != int(float(r["demand"])) for r in rows):
        problems.append(f"{k}: tripinfo entries differ from demand or lack emissions")
g_per_veh = lambda r: 1000 * float(r["co2_kg"]) / float(r["demand"])
key = lambda r: (r["route_file"], r["sumo_seed"])


def tci(xs):
    n, mu = len(xs), st.mean(xs)
    sd = st.stdev(xs)
    h = stats.t.ppf(0.975, n - 1) * sd / math.sqrt(n)
    return mu, sd, mu - h, mu + h


def per_run(rows, f):
    by = {}
    for r in rows:
        by.setdefault(r["training_run"], []).append(f(r))
    return [st.mean(v) for _, v in sorted(by.items(), key=lambda x: int(x[0]))]


CTRLS = ["Fixed plan", "Actuated", "Webster plan", "Tuned MaxPressure", "Final design"]
levels, diffs = [], []
for m, lab in LOADS.items():
    for c in CTRLS:
        vals = per_run(eps[(c, m)], g_per_veh)
        mu, sd, lo, hi = tci(vals)
        kg = st.mean(float(r["co2_kg"]) for r in eps[(c, m)])
        levels.append({"demand": lab, "controller": c, "episodes": len(eps[(c, m)]), "co2_g_per_veh": mu,
                       "lo": lo, "hi": hi, "co2_kg_per_episode": kg, "runs": ";".join(f"{v:.2f}" for v in vals)})
    fin = {key(r): r for r in eps[("Final design", m)]}
    for c in CTRLS[:-1]:
        paired = [(fin[key(r)], r) for r in eps[(c, m)] if key(r) in fin]
        if len(paired) != 50:
            problems.append(f"final vs {c} {lab}: {len(paired)} pairs")
        by = {}
        for a, b in paired:     # baselines run on the SUMO seeds of DRL run k
            by.setdefault(a["training_run"], []).append(g_per_veh(a) - g_per_veh(b))
        d = [st.mean(v) for _, v in sorted(by.items(), key=lambda x: int(x[0]))]
        mu, sd, lo, hi = tci(d)
        p = 2 * stats.t.sf(abs(mu) / (sd / math.sqrt(len(d))), len(d) - 1) if sd > 0 else (1.0 if mu == 0 else 0.0)
        diffs.append({"demand": lab, "baseline": c, "mean_g_per_veh": mu, "lo": lo, "hi": hi,
                      "pct_of_baseline": 100 * mu / st.mean(g_per_veh(b) for _, b in paired),
                      "runs_lower": sum(x < 0 for x in d), "runs_higher": sum(x > 0 for x in d), "p": p,
                      "d_k": ";".join(f"{x:.2f}" for x in d)})
run_max = 0.0
for i, x in enumerate(sorted(diffs, key=lambda x: x["p"])):
    run_max = max(run_max, min(1.0, (len(diffs) - i) * x["p"]))
    x["p_holm"] = run_max

for name, rows in (("levels", levels), ("diffs", diffs)):
    with open(f"{prefix}_{name}.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
md = ["# E13 locked test: CO2 per demanded vehicle (exploratory, not pre-specified; decision D-9)", "",
      "SUMO emissions device (default HBEFA-based passenger-car class, as every vehicle in the twin), summed over the "
      "episode's tripinfo; per run the mean over 10 locked files; 95% t CIs (df 4). x1.5 omitted (never-inserted "
      "vehicles emit nothing).", "", "| Demand | Controller | Episodes | CO2, g per demanded vehicle [95% CI] | CO2, kg per episode |",
      "|---|---|---|---|---|"]
for x in levels:
    md.append(f"| {x['demand']} | {x['controller']} | {x['episodes']} | {x['co2_g_per_veh']:.1f} [{x['lo']:.1f}, {x['hi']:.1f}] | "
              f"{x['co2_kg_per_episode']:.1f} |")
md += ["", "## Final design minus baseline (g per demanded vehicle); Holm over 8 tests", "",
       "| Demand | Baseline | Mean [95% CI] | % of baseline | Runs lower / higher | p | p (Holm) |", "|---|---|---|---|---|---|---|"]
for x in diffs:
    md.append(f"| {x['demand']} | {x['baseline']} | {x['mean_g_per_veh']:+.2f} [{x['lo']:+.2f}, {x['hi']:+.2f}] | "
              f"{x['pct_of_baseline']:+.1f}% | {x['runs_lower']} / {x['runs_higher']} | {x['p']:.4f} | {x['p_holm']:.4f} |")
md += ["", "Problems: " + ("; ".join(problems) if problems else "none")]
Path(f"{prefix}.md").write_text("\n".join(md) + "\n", encoding="utf-8")
print("\n".join(md))
