"""E13 locked test, every learned candidate (decision D-10) and the transfer / general-model comparison (decision D-2).

Usage: python e13_locked_candidates.py <e13/results> <S2c out/results> <reports folder>
Writes <reports>/e13_candidates_locked_2026-10-30{.md,_levels.csv} and e13_transfer_locked_2026-10-30{.md,_diffs.csv}.

Exploratory (pre-registration 7.1), as revision/tools/e13_exploratory_locked.py: unit = training run k (n = 5); per k,
the mean over that k's locked files; 95% t CIs (df 4). Transfer family: the x1.0 model of the final design (L2 MPLight)
and the general model (L4 MPLight) at x1.2 and x1.5, each minus the fixed plan, tuned MaxPressure and the final design
trained at that load; paired on (route file, SUMO seed); two-sided one-sample t-tests on d_k with Holm within each
measure (arrivals; total delay), 12 tests each. SD = 0: p = 1 if all d_k are 0, else p = 0 (the limit, as D19).
"""
import csv
import json
import math
import statistics as st
import sys
from pathlib import Path

from scipy import stats

e13, s2c, rep = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
rd = lambda p: list(csv.DictReader(open(p, encoding="utf-8")))
true = lambda v: v in ("1", "True", "true")
final = json.load(open(e13 / "selection_final.json", encoding="utf-8"))["final"]
MAPS = {"prybuzka_lt10": "x1.0", "prybuzka_lt12": "x1.2", "prybuzka_lt15": "x1.5", "prybuzka_lts1": "S1",
        "prybuzka_lts2": "S2", "prybuzka_lts3": "S3", "prybuzka_lts4": "S4"}
REWARDS = ["IDQN-wait", "IDQN-queue", "MPLight", "IDQN-pressure"]


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


served = lambda r: 100 * float(r["arrived_1800"]) / float(r["demand"])
METRICS = {"served_pct": served, "total_delay_vh": lambda r: float(r["total_delay_vh"]),
           "mean_delay_s": lambda r: float(r["mean_delay_s"])}
ev = [r for r in rd(e13 / "eval_episodes.csv") if r["eval_set"] == "locked" and r["map"] in MAPS]
base = {}
for r in rd(e13 / "baseline_episodes.csv") + rd(s2c / "eval_episodes.csv"):
    if r["eval_set"] == "locked" and r["map"] in MAPS and r["policy"] in ("Fixed plan", "MaxPressure"):
        base.setdefault((r["policy"], r["map"]), []).append(r)
problems = []

# ---- all candidates: levels per (rung, reward, training load, demand) ------------------------------------------------
groups = {}
for r in ev:
    groups.setdefault((r["rung"], r["policy"], r["train_load"], r["map"]), []).append(r)
order = lambda k: (k[0], REWARDS.index(k[1]), k[2], list(MAPS).index(k[3]))
levels = []
for k in sorted(groups, key=order):
    rows = groups[k]
    if not all(true(r["tripinfo_ok"]) for r in rows):
        problems.append(f"{k}: tripinfo not ok")
    rec = {"rung": k[0], "reward": k[1], "train_load": k[2], "demand": MAPS[k[3]], "episodes": len(rows),
           "runs": len({r["training_run"] for r in rows}), "deadlocks": sum(true(r["deadlock"]) for r in rows),
           "full_pct": 100 * sum(true(r["full"]) for r in rows) / len(rows)}
    for name, f in METRICS.items():
        pr = per_run(rows, f)
        mu, sd, lo, hi = tci(list(pr.values()))
        rec |= {name: mu, f"{name}_lo": lo, f"{name}_hi": hi, f"{name}_runs": ";".join(f"{v:.3f}" for v in pr.values())}
    levels.append(rec)

# ---- transfer and general model ---------------------------------------------------------------------------------------
key = lambda r: (r["route_file"], r["sumo_seed"])
own = lambda m: [r for r in ev if r["rung"] == final["rung"] and r["policy"] == final["policy"] and r["map"] == m
                 and r["train_load"] == MAPS[m]]
MODELS = {f"{final['rung']} {final['policy']}, x1.0 model": (final["rung"], final["policy"], "x1.0"),
          f"L4 {final['policy']}, general model": ("L4", final["policy"], "mix")}
diffs = []
for m in ("prybuzka_lt12", "prybuzka_lt15"):
    comps = {"Fixed plan": base[("Fixed plan", m)], "Tuned MaxPressure": base[("MaxPressure", m)],
             f"Final design ({MAPS[m]} model)": own(m)}
    for lab, (rung, pol, tl) in MODELS.items():
        mod = {key(r): r for r in groups[(rung, pol, tl, m)]}
        for cname, crow in comps.items():
            paired = [(mod[key(r)], r) for r in crow if key(r) in mod]
            if len(paired) != len(crow) or len(paired) != len(mod):
                problems.append(f"{lab} vs {cname} {MAPS[m]}: {len(paired)} pairs of {len(mod)}/{len(crow)}")
            for metric, f in (("arrivals", lambda r: float(r["arrived_1800"])),
                              ("total_delay_vh", lambda r: float(r["total_delay_vh"]))):
                by = {}
                for a, b in paired:     # the model's training run k; baselines use the SUMO seeds of DRL run k
                    by.setdefault(a["training_run"], []).append(f(a) - f(b))
                d = [st.mean(v) for _, v in sorted(by.items(), key=lambda x: int(x[0]))]
                mu, sd, lo, hi = tci(d)
                if sd > 0:
                    p, note = 2 * stats.t.sf(abs(mu) / (sd / math.sqrt(len(d))), len(d) - 1), ""
                else:
                    p, note = (1.0, "all d_k = 0") if mu == 0 else (0.0, "all d_k equal")
                better = sum(x > 0 for x in d) if metric == "arrivals" else sum(x < 0 for x in d)
                worse = sum(x < 0 for x in d) if metric == "arrivals" else sum(x > 0 for x in d)
                diffs.append({"demand": MAPS[m], "model": lab, "comparator": cname, "metric": metric, "n": len(d),
                              "mean": mu, "lo": lo, "hi": hi, "runs_better": better, "runs_worse": worse, "p": p,
                              "note": note, "d_k": ";".join(f"{x:.2f}" for x in d)})
for metric in ("arrivals", "total_delay_vh"):
    fam = sorted([x for x in diffs if x["metric"] == metric], key=lambda x: x["p"])
    run_max = 0.0
    for i, x in enumerate(fam):
        run_max = max(run_max, min(1.0, (len(fam) - i) * x["p"]))
        x["p_holm"] = run_max

for name, rows in (("e13_candidates_locked_2026-10-30_levels", levels), ("e13_transfer_locked_2026-10-30_diffs", diffs)):
    with open(rep / f"{name}.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

f1 = lambda x: f"{x:.2f}"
md = ["# E13 locked test: every learned candidate (exploratory)", "",
      "Unit: training run (n = 5); per run, the mean over its locked files (10 per load, 5 per scenario); 95% t CIs "
      "(df 4). L1-L3 have one model per training load; L4 one model for all demands ('mix'). L0 = E12 models (not a "
      "candidate). Exploratory (pre-registration 7.1); the final design is "
      f"{final['rung']} {final['policy']}.", "",
      "| Rung | Reward | Trained at | Demand | Episodes | Deadlocks | Full | Served, % [95% CI] | Total delay, veh·h [95% CI] | Mean delay, s/veh |",
      "|---|---|---|---|---|---|---|---|---|---|"]
for x in levels:
    md.append(f"| {x['rung']} | {x['reward']} | {x['train_load']} | {x['demand']} | {x['episodes']} | {x['deadlocks']} | "
              f"{x['full_pct']:.0f}% | {f1(x['served_pct'])} [{f1(x['served_pct_lo'])}, {f1(x['served_pct_hi'])}] | "
              f"{f1(x['total_delay_vh'])} [{f1(x['total_delay_vh_lo'])}, {f1(x['total_delay_vh_hi'])}] | {x['mean_delay_s']:.1f} |")
md += ["", "Problems: " + ("; ".join(problems) if problems else "none")]
(rep / "e13_candidates_locked_2026-10-30.md").write_text("\n".join(md) + "\n", encoding="utf-8")

lv = {(x["rung"], x["reward"], x["train_load"], x["demand"]): x for x in levels}
md = ["# E13 locked test: transfer of the x1.0 model and the general model (exploratory; decision D-2)", "",
      "Levels: the x1.0 model and the general model (L4) of the final design's reward, the final design trained at "
      "the load, and two baselines. Differences: model minus comparator, paired on route file and SUMO seed; mean over "
      "5 runs with 95% t CI; runs better / worse; two-sided one-sample t-test on the 5 run differences, Holm within each "
      "measure (12 tests).", "", "## Levels", "",
      "| Demand | Controller | Served, % [95% CI] | Served, runs | Total delay, veh·h [95% CI] | Mean delay, s/veh | Deadlocks |",
      "|---|---|---|---|---|---|---|"]
lvb = {}
for x in rd(rep / "e13_exploratory_locked_2026-10-30_levels.csv"):
    lvb[(x["demand"], x["controller"])] = x
for dem in ("x1.2", "x1.5"):
    rows = [("Fixed plan", lvb[(dem, "Fixed plan")]), ("Tuned MaxPressure", lvb[(dem, "MaxPressure")]),
            (f"Final design ({dem} model)", lv[(final["rung"], final["policy"], dem, dem)]),
            (f"{final['rung']} {final['policy']}, x1.0 model", lv[(final["rung"], final["policy"], "x1.0", dem)]),
            (f"L4 {final['policy']}, general model", lv[("L4", final["policy"], "mix", dem)])]
    for name, x in rows:
        g = lambda c: float(x[c])
        md.append(f"| {dem} | {name} | {g('served_pct'):.2f} [{g('served_pct_lo'):.2f}, {g('served_pct_hi'):.2f}] | "
                  f"{x['served_pct_runs']} | {g('total_delay_vh'):.2f} [{g('total_delay_vh_lo'):.2f}, "
                  f"{g('total_delay_vh_hi'):.2f}] | {g('mean_delay_s'):.1f} | {x['deadlocks']} |")
fmt = lambda v: f"{v:+.2f}"
for metric, title in (("arrivals", "Arrivals by 1800 s (vehicles)"), ("total_delay_vh", "Total delay (veh·h)")):
    md += ["", f"## Model minus comparator: {title}", "",
           "| Demand | Model | Comparator | Mean [95% CI] | Runs better / worse | p | p (Holm) | d_k |", "|---|---|---|---|---|---|---|---|"]
    for x in [d for d in diffs if d["metric"] == metric]:
        md.append(f"| {x['demand']} | {x['model']} | {x['comparator']} | {fmt(x['mean'])} [{fmt(x['lo'])}, {fmt(x['hi'])}] | "
                  f"{x['runs_better']} / {x['runs_worse']} | {x['p']:.4f} | {x['p_holm']:.4f} | {x['d_k']} |")
md += ["", "Problems: " + ("; ".join(problems) if problems else "none")]
(rep / "e13_transfer_locked_2026-10-30.md").write_text("\n".join(md) + "\n", encoding="utf-8")
print("\n".join(md))
