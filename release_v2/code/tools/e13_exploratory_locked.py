"""E13 exploratory statistics on the locked test (pre-registration 7.1): run-level means, 95% CIs, sign counts, Holm.

Usage: python e13_exploratory_locked.py <e13/results> <S2c out/results> <output prefix>
Writes <prefix>.md (tables) and <prefix>_levels.csv, <prefix>_diffs.csv (for figures).

Unit = training run k (n = 5). For a learned controller, k is its training run; for a baseline, k is the seed group that
uses the SUMO seeds of DRL run k, so every comparison is paired on (map, route file, SUMO seed). Per k, a metric is the mean
over that k's locked files (10 per load, 5 per scenario). Families for Holm: arrivals differences (7 demands x 4 baselines)
and total-delay differences (the same 28), two-sided one-sample t-tests on d_k (df 4). If the five d_k are equal (SD = 0) the
t statistic is undefined: p = 1 if they are 0, else p = 0 (the limit; as D19), flagged in the table.
"""
import csv
import json
import math
import statistics as st
import sys
from pathlib import Path

from scipy import stats

e13, s2c, prefix = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
rd = lambda p: list(csv.DictReader(open(p, encoding="utf-8")))
true = lambda v: v in ("1", "True", "true")
final = json.load(open(e13 / "selection_final.json", encoding="utf-8"))["final"]
FINAL = f"{final['rung']} {final['policy']}"
DEMANDS = {"x1.0": ("prybuzka_lt10", "x1.0"), "x1.2": ("prybuzka_lt12", "x1.2"), "x1.5": ("prybuzka_lt15", "x1.5"),
           "S1": ("prybuzka_lts1", "x1.0"), "S2": ("prybuzka_lts2", "x1.0"), "S3": ("prybuzka_lts3", "x1.0"),
           "S4": ("prybuzka_lts4", "x1.0")}
BASELINES = ["Fixed plan", "Actuated", "MaxPressure", "Webster"]
CTRLS = BASELINES + [FINAL]

eps = {}    # (controller, map) -> rows
for r in rd(e13 / "baseline_episodes.csv") + rd(s2c / "eval_episodes.csv"):
    if r["eval_set"] == "locked" and r["policy"] in BASELINES:
        eps.setdefault((r["policy"], r["map"]), []).append(r)
for r in rd(e13 / "eval_episodes.csv"):
    if r["eval_set"] == "locked" and r["rung"] == final["rung"] and r["policy"] == final["policy"]:
        for lab, (m, tl) in DEMANDS.items():
            if r["map"] == m and r["train_load"] == tl:
                eps.setdefault((FINAL, m), []).append(r)
key = lambda r: (r["route_file"], r["sumo_seed"])


def tci(xs):
    n, mu = len(xs), st.mean(xs)
    sd = st.stdev(xs) if n > 1 else 0.0
    h = stats.t.ppf(0.975, n - 1) * sd / math.sqrt(n) if n > 1 else float("nan")
    return mu, sd, mu - h, mu + h


def per_run(rows, f):
    by = {}
    for r in rows:
        by.setdefault(r["training_run"], []).append(f(r))
    return {k: st.mean(v) for k, v in sorted(by.items(), key=lambda x: int(x[0]))}


arr_pct = lambda r: 100 * float(r["arrived_1800"]) / float(r["demand"])
METRICS = {"served_pct": arr_pct, "total_delay_vh": lambda r: float(r["total_delay_vh"]),
           "mean_delay_s": lambda r: float(r["mean_delay_s"])}
levels, problems = [], []
for lab, (m, _) in DEMANDS.items():
    for c in CTRLS:
        rows = eps.get((c, m), [])
        if not rows:
            problems.append(f"{c} {lab}: no locked episodes")
            continue
        if not all(true(r["tripinfo_ok"]) for r in rows):
            problems.append(f"{c} {lab}: tripinfo not ok")
        rec = {"demand": lab, "controller": c, "episodes": len(rows), "deadlocks": sum(true(r["deadlock"]) for r in rows),
               "full_pct": 100 * sum(true(r["full"]) for r in rows) / len(rows)}
        for name, f in METRICS.items():
            pr = per_run(rows, f)
            mu, sd, lo, hi = tci(list(pr.values()))
            rec |= {f"{name}": mu, f"{name}_sd": sd, f"{name}_lo": lo, f"{name}_hi": hi,
                    f"{name}_runs": ";".join(f"{v:.3f}" for v in pr.values())}
        levels.append(rec)

diffs = []
for lab, (m, _) in DEMANDS.items():
    fin = {key(r): r for r in eps.get((FINAL, m), [])}
    for b in BASELINES:
        base = eps.get((b, m), [])
        paired = [(fin[key(r)], r) for r in base if key(r) in fin]
        if len(paired) != len(base) or len(paired) != len(fin):
            problems.append(f"{FINAL} vs {b} {lab}: {len(paired)} pairs, {len(base)} baseline, {len(fin)} final episodes")
        for metric, f in (("arrivals", lambda r: float(r["arrived_1800"])), ("total_delay_vh", lambda r: float(r["total_delay_vh"]))):
            by = {}
            for a, r in paired:
                by.setdefault(r["training_run"], []).append(f(a) - f(r))
            d = [st.mean(v) for _, v in sorted(by.items(), key=lambda x: int(x[0]))]
            mu, sd, lo, hi = tci(d)
            if sd > 0:
                p, note = 2 * stats.t.sf(abs(mu) / (sd / math.sqrt(len(d))), len(d) - 1), ""
            else:
                p, note = (1.0, "all d_k = 0") if mu == 0 else (0.0, "all d_k equal")
            better = sum(x > 0 for x in d) if metric == "arrivals" else sum(x < 0 for x in d)
            diffs.append({"demand": lab, "baseline": b, "metric": metric, "n": len(d), "mean": mu, "sd": sd, "lo": lo, "hi": hi,
                          "runs_better": better, "runs_worse": sum(x < 0 for x in d) if metric == "arrivals" else sum(x > 0 for x in d),
                          "p": p, "note": note, "d_k": ";".join(f"{x:.2f}" for x in d)})
for metric in ("arrivals", "total_delay_vh"):    # Holm within each family
    fam = sorted([x for x in diffs if x["metric"] == metric], key=lambda x: x["p"])
    run_max = 0.0
    for i, x in enumerate(fam):
        run_max = max(run_max, min(1.0, (len(fam) - i) * x["p"]))
        x["p_holm"] = run_max

for name, rows in (("levels", levels), ("diffs", diffs)):
    with open(f"{prefix}_{name}.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

fmt = lambda x, nd=1: f"{x:+.{nd}f}" if isinstance(x, float) else str(x)
md = [f"# E13 locked test: exploratory statistics (pre-registration 7.1)", "",
      f"Final design: {FINAL}. Unit: training run (n = 5); per run, the mean over the locked files. 95% CIs: t, df 4. "
      "Baselines are paired with the DRL runs on route file and SUMO seed. Exploratory: no claim is judged on these tables "
      "except the confirmatory test (section 11 log).", "",
      "## Levels", "", "| Demand | Controller | Episodes | Deadlocks | Full | Served, % of demand [95% CI] | "
      "Total delay, veh·h [95% CI] | Mean delay, s/veh [95% CI] |", "|---|---|---|---|---|---|---|---|"]
for x in levels:
    md.append(f"| {x['demand']} | {x['controller']} | {x['episodes']} | {x['deadlocks']} | {x['full_pct']:.0f}% | "
              f"{x['served_pct']:.2f} [{x['served_pct_lo']:.2f}, {x['served_pct_hi']:.2f}] | "
              f"{x['total_delay_vh']:.2f} [{x['total_delay_vh_lo']:.2f}, {x['total_delay_vh_hi']:.2f}] | "
              f"{x['mean_delay_s']:.1f} [{x['mean_delay_s_lo']:.1f}, {x['mean_delay_s_hi']:.1f}] |")
for metric, unit, title in (("arrivals", "vehicles", "Arrivals by 1800 s"), ("total_delay_vh", "veh·h", "Total delay")):
    md += ["", f"## {FINAL} minus baseline: {title} ({unit}); family of 28 tests, Holm", "",
           "| Demand | Baseline | Mean [95% CI] | Runs better / worse | p | p (Holm) | Note |", "|---|---|---|---|---|---|---|"]
    for x in [d for d in diffs if d["metric"] == metric]:
        md.append(f"| {x['demand']} | {x['baseline']} | {fmt(x['mean'], 2)} [{fmt(x['lo'], 2)}, {fmt(x['hi'], 2)}] | "
                  f"{x['runs_better']} / {x['runs_worse']} | {x['p']:.4f} | {x['p_holm']:.4f} | {x['note']} |")
md += ["", "Problems: " + ("; ".join(problems) if problems else "none")]
Path(f"{prefix}.md").write_text("\n".join(md) + "\n", encoding="utf-8")
print("\n".join(md))
