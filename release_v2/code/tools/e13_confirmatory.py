"""E13 confirmatory analysis (pre-registration 7.2-7.3): final design vs fixed plan, non-inferiority in arrivals by 1800 s.

Written on 30 Oct 2026 before any locked-test result existed. Usage:
    python e13_confirmatory.py <e13/results> [--set locked|validation]
--set validation is only a dry run of the code on data already used for selection; it is not a result.
"""
import argparse
import csv
import json
import math
import statistics as st
from pathlib import Path

from scipy import stats

ap = argparse.ArgumentParser()
ap.add_argument("results", type=Path)
ap.add_argument("--set", default="locked", choices=("locked", "validation"))
args = ap.parse_args()

MAPS = {"locked": {"x1.0": "prybuzka_lt10", "x1.2": "prybuzka_lt12"},
        "validation": {"x1.0": "prybuzka_va10", "x1.2": "prybuzka_va12"}}[args.set]
ALPHA = 0.025  # one-sided, per load; Holm over the two loads
N_RUNS, N_FILES = 5, 10

final = json.load(open(args.results / "selection_final.json", encoding="utf-8"))["final"]
ev = list(csv.DictReader(open(args.results / "eval_episodes.csv", encoding="utf-8")))
bl = list(csv.DictReader(open(args.results / "baseline_episodes.csv", encoding="utf-8")))
fixed = {(r["map"], r["route_file"], r["sumo_seed"]): r for r in bl
         if r["policy"] == "Fixed plan" and r["eval_set"] == args.set}
is_true = lambda v: v in ("1", "True", "true")

out, problems = {}, []
for load, m in MAPS.items():
    tl = "mix" if final["rung"] == "L4" else load
    eps = [r for r in ev if r["rung"] == final["rung"] and r["policy"] == final["policy"] and r["eval_set"] == args.set
           and r["train_load"] == tl and r["map"] == m]
    runs = sorted({r["training_run"] for r in eps}, key=int)
    d_arr, d_delay = [], []
    for k in runs:
        rk = [r for r in eps if r["training_run"] == k]
        pairs = [(r, fixed.get((m, r["route_file"], r["sumo_seed"]))) for r in rk]
        if len(rk) != N_FILES or any(f is None for _, f in pairs) or not all(
                is_true(x["tripinfo_ok"]) for r, f in pairs for x in (r, f)):
            problems.append(f"{load} run {k}: {len(rk)} files, unpaired or tripinfo not ok")
        pairs = [(r, f) for r, f in pairs if f]
        d_arr.append(st.mean(float(r["arrived_1800"]) - float(f["arrived_1800"]) for r, f in pairs))
        d_delay.append(st.mean(float(r["total_delay_vh"]) - float(f["total_delay_vh"]) for r, f in pairs))
    if len(runs) != N_RUNS:
        problems.append(f"{load}: {len(runs)} runs, expected {N_RUNS}")
    n = len(d_arr)
    demand = st.mean(float(r["demand"]) for r in eps)
    margin = 0.01 * demand
    mean, sd = st.mean(d_arr), st.stdev(d_arr)
    se = sd / math.sqrt(n)
    if sd > 0:
        t = (mean + margin) / se
        p = stats.t.sf(t, n - 1)  # H0: mean(d) <= -m, H1: mean(d) > -m
    else:  # D19: all d_k equal, t undefined; take the limit
        t = math.inf if mean > -margin else -math.inf
        p = 0.0 if mean > -margin else 1.0
    half = stats.t.ppf(0.975, n - 1) * se
    dmean, dse = st.mean(d_delay), st.stdev(d_delay) / math.sqrt(n)
    dhalf = stats.t.ppf(0.975, n - 1) * dse
    out[load] = {
        "map": m, "runs": n, "files_per_run": N_FILES, "d_k": [round(x, 3) for x in d_arr],
        "mean_d": mean, "sd_d": sd, "mean_demand": demand, "margin": margin,
        "t": t, "df": n - 1, "p_one_sided": p, "ci95_mean_d": [mean - half, mean + half],
        "sd_zero": sd == 0,
        "d_z": mean / sd if sd else None, "d_z_vs_margin": (mean + margin) / sd if sd else None,
        "sign_count_above_minus_m": sum(x > -margin for x in d_arr),
        "deadlocks_final_design": sum(is_true(r["deadlock"]) for r in eps), "episodes": len(eps),
        "delay_diff_vh": {"d_k": [round(x, 2) for x in d_delay], "mean": dmean, "ci95": [dmean - dhalf, dmean + dhalf],
                          "lower_delay_claim": bool(dmean + dhalf < 0)},
    }

# Holm over the two loads at family alpha 0.025
order = sorted(out, key=lambda l: out[l]["p_one_sided"])
stop = False
for i, load in enumerate(order):
    thr = ALPHA / (len(order) - i)
    out[load]["holm_threshold"] = thr
    out[load]["holm_reject"] = bool((not stop) and out[load]["p_one_sided"] <= thr)
    stop = stop or not out[load]["holm_reject"]
    out[load]["holm_adjusted_p"] = min(1.0, max(out[o]["p_one_sided"] * (len(order) - j) for j, o in enumerate(order[:i + 1])))

no_deadlock = all(v["deadlocks_final_design"] == 0 for v in out.values())
success = all(v["holm_reject"] for v in out.values()) and no_deadlock and not problems
report = {"set": args.set, "final_design": final, "alpha_one_sided": ALPHA, "loads": out,
          "criterion_1_holm_both": all(v["holm_reject"] for v in out.values()),
          "criterion_2_no_deadlock": no_deadlock, "problems": problems, "success": success}
print(json.dumps(report, indent=1, default=float))
