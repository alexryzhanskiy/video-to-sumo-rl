"""E12 analysis: integrity checks, harmonized tables, paired comparisons with the fixed plan, E12 vs E3, training.

Reads files only (no simulation):
  --kit-results  revision/e12_kit/results              eval_episodes.csv, eval_runs.csv, train_episodes.csv, train_runs.csv
  --pack         revision/runs/e12                      extracted pack (runs/eval tripinfo, runs/train checkpoints)
  --envs         revision/e12_kit/resco/resco_benchmark/environments   route files (demand)
  --e6           revision/runs/e6/e6_episodes.csv       fixed plan and actuated, same files and SUMO seeds as E12
  --e3           revision/analysis/e3/e3_episodes.csv   original policies (Ryzhanskyi's E3/E4), rows with yellow3+allred4
Writes to --out (revision/analysis/e12): checks.txt, episodes_all.csv, run_level.csv, summary.csv, paired_vs_fixed.csv,
e12_vs_e3.csv, training.csv, E12_analysis.md.

Design: the unit of replication is the training run k (5 per policy and load). Every evaluation episode is paired across
controllers by (set, k, map, route file): E12 and E3 use trial 1000 + k and SUMO seed 42 + trial + episode; E6 runs the
same seeds. Confirmatory test (fixed before the analysis, plan of 28 Oct): each E12 policy against the fixed plan on
vehicles arrived by 1800 s on the held-out files of each load; one-sample t-test on the 5 run-level mean paired
differences, two-sided, Holm over the 12 tests. Everything else is exploratory.

  revision/.venv/Scripts/python.exe revision/tools/e12_analysis.py --kit-results revision/e12_kit/results \
      --pack revision/runs/e12 --envs revision/e12_kit/resco/resco_benchmark/environments \
      --e6 revision/runs/e6/e6_episodes.csv --e3 revision/analysis/e3/e3_episodes.csv --out revision/analysis/e12
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import math
import re
import statistics as st
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy import stats

E12_POL = ["IDQN-wait", "IDQN-queue", "MPLight", "IDQN-pressure"]
E3_POL = ["IDQN-wait", "IDQN-queue", "MPLight"]
SETS = ["held-out x1.0", "held-out x1.2", "held-out x1.5", "scenario S1", "scenario S2", "scenario S3", "scenario S4",
        "transfer x1.2", "transfer x1.5"]
HELDOUT = SETS[:3]
END = 1800.0


def read(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def set_name(eval_set: str, label: str) -> str:
    return {"heldout": f"held-out {label}", "transfer": f"transfer {label}"}.get(eval_set, f"scenario {label}")


def num(x) -> float:
    return float(x) if x not in ("", None, "nan") else math.nan


# ------------------------------------------------------------------ independent recomputation from tripinfo
def recompute(path: Path) -> dict:
    """Same definitions as the kit, coded separately: attribute parsing with regular expressions."""
    dep, arr, wt = [], [], []
    for attrs in re.findall(r"<tripinfo\s([^>]*)>", path.read_text(encoding="utf-8")):
        a = dict(re.findall(r'(\w+)="([^"]*)"', attrs))
        dep.append(float(a["depart"]))
        arr.append(float(a["arrival"]))
        wt.append(float(a["waitingTime"]))
    dep_sorted = np.sort(np.array(dep))
    done = sorted(a for a in arr if a >= 0)
    starts = [dep_sorted[0] if len(dep_sorted) else 0.0] + done
    ends = done + [END]
    longest = 0.0
    for i, (s, t) in enumerate(zip(starts, ends)):
        if np.searchsorted(dep_sorted, s, side="right") - i > 0:
            longest = max(longest, t - s)
    aw = [w for w, a in zip(wt, arr) if a >= 0]
    return {"entries": len(arr), "arrived_1500": sum(0 <= a <= 1500 for a in arr),
            "arrived_1800": sum(0 <= a <= 1800 for a in arr), "unfinished": sum(a < 0 for a in arr),
            "wait": st.mean(aw) if aw else math.nan, "longest": longest}


def route_demand(path: Path, cache: dict = {}) -> int:
    if path not in cache:
        cache[path] = len(re.findall(r"<(?:vehicle|trip)\s", path.read_text(encoding="utf-8")))
    return cache[path]


# ------------------------------------------------------------------ statistics helpers
def mean_ci(values: list[float]) -> tuple[float, float, float]:
    v = np.array([x for x in values if not math.isnan(x)], dtype=float)
    if len(v) == 0:
        return math.nan, math.nan, math.nan
    sd = float(v.std(ddof=1)) if len(v) > 1 else math.nan
    half = float(stats.t.ppf(0.975, len(v) - 1) * sd / math.sqrt(len(v))) if len(v) > 1 else math.nan
    return float(v.mean()), sd, half


def one_sample_t(d: list[float]) -> tuple[float, float, float]:
    """t, two-sided p, d_z for run-level paired differences."""
    v = np.array(d, dtype=float)
    sd = v.std(ddof=1)
    if sd == 0:
        return (math.inf if v.mean() else 0.0), (0.0 if v.mean() else 1.0), (math.inf if v.mean() else 0.0)
    t = v.mean() / (sd / math.sqrt(len(v)))
    return float(t), float(2 * stats.t.sf(abs(t), len(v) - 1)), float(v.mean() / sd)


def holm(ps: list[float]) -> list[float]:
    order = sorted(range(len(ps)), key=lambda i: ps[i])
    adj, running = [0.0] * len(ps), 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (len(ps) - rank) * ps[i]))
        adj[i] = running
    return adj


def fmt(x: float, nd: int = 0) -> str:
    return "–" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.{nd}f}"


def fp(p: float) -> str:
    return "< .001" if p < 0.001 else f"{p:.3f}".replace("0.", ".", 1)


# ------------------------------------------------------------------ main
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for a in ("--kit-results", "--pack", "--envs", "--e6", "--e3", "--out"):
        ap.add_argument(a, type=Path, required=True)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    checks: list[str] = []

    # ---------------- integrity checks
    ev = read(args.kit_results / "eval_episodes.csv")
    runs_tab = {(r["policy"], r["train_load"], r["training_run"], r["map"], r["episode"]): r
                for r in read(args.kit_results / "eval_runs.csv")}
    mism = defaultdict(int)
    for r in ev:
        key = (r["policy"], r["train_load"], r["training_run"], r["map"], r["episode"])
        kr = runs_tab[key]
        rc = recompute(args.pack / kr["tripinfo_path"])
        dem = route_demand(args.envs / r["map"] / "routes" / r["route_file"])
        for name, mine, theirs in (("entries", rc["entries"], int(r["entries"])),
                                   ("arrived_1500", rc["arrived_1500"], int(r["arrived_1500"])),
                                   ("arrived_1800", rc["arrived_1800"], int(r["arrived_1800"])),
                                   ("unfinished", rc["unfinished"], int(r["unfinished"])),
                                   ("demand", dem, int(r["demand"])),
                                   ("eval_runs n_entries", rc["entries"], int(kr["n_entries"])),
                                   ("eval_runs n_arrived_1800", rc["arrived_1800"], int(kr["n_arrived_1800"]))):
            mism[name] += mine != theirs
        mism["mean wait"] += not (math.isnan(rc["wait"]) and r["mean_wait_arrived_s"] == "") and \
            abs(rc["wait"] - num(r["mean_wait_arrived_s"])) > 0.01
        mism["longest no arrival"] += abs(rc["longest"] - num(r["longest_no_arrival_s"])) > 0.11
        mism["route file / seed vs eval_runs"] += (kr["route_file"], kr["sumo_seed"]) != (r["route_file"], r["sumo_seed"])
    checks.append(f"E12 evaluation: {len(ev)} episodes recomputed from the pack's tripinfo files with a separate parser; "
                  "differences per field: " + ", ".join(f"{k} {v}" for k, v in mism.items()))

    seeds = defaultdict(set)
    for r in ev:
        seeds[(set_name(r["eval_set"], r["load_or_scenario"]), r["training_run"], r["map"], r["episode"])].add(
            (r["route_file"], r["sumo_seed"]))
    checks.append(f"Pairing: {sum(len(v) == 1 for v in seeds.values())}/{len(seeds)} (set, run, map, episode) cells have "
                  "one route file and one SUMO seed across the 4 E12 policies")

    tr = read(args.kit_results / "train_runs.csv")
    bad_ck = sum(hashlib.sha256((args.pack / r["checkpoint"]).read_bytes()).hexdigest() != r["checkpoint_sha256"]
                 for r in tr)
    te = read(args.kit_results / "train_episodes.csv")
    per_run = defaultdict(list)
    for r in te:
        per_run[(r["policy"], r["load"], r["run"])].append(r)
    cyc = sum(r["route_file"] != sorted({x["route_file"] for x in per_run[(r["policy"], r["load"], r["run"])]})[(int(r["episode"]) - 1) % 20]
              for r in te)
    checks.append(f"Training: {len(tr)} runs, {sum(r['returncode'] == '0' for r in tr)} with exit 0; checkpoint SHA-256 "
                  f"mismatches {bad_ck}; {len(te)} episodes, {sum(len(v) == 100 for v in per_run.values())} runs with 100; "
                  f"tripinfo_ok {sum(r['tripinfo_ok'] == '1' for r in te)}; route-file cycle deviations {cyc}")

    # ---------------- unified episode table
    rec: list[dict] = []
    for r in ev:
        rec.append({"source": "E12", "policy": r["policy"], "set": set_name(r["eval_set"], r["load_or_scenario"]),
                    "k": int(r["training_run"]), "map": r["map"], "e": int(r["episode"]), "route_file": r["route_file"],
                    "seed": int(r["sumo_seed"]), "demand": int(r["demand"]), "entries": int(r["entries"]),
                    "arrived_1500": int(r["arrived_1500"]), "arrived_1800": int(r["arrived_1800"]),
                    "unfinished": int(r["unfinished"]), "not_inserted": int(r["not_inserted"]),
                    "wait": num(r["mean_wait_arrived_s"]), "full": int(r["full"]), "deadlock": int(r["deadlock"])})
    for r in read(args.e6):
        base = {"source": "E6", "policy": r["policy"], "k": int(r["training_run"]), "map": r["map"],
                "e": int(r["episode"]), "route_file": r["route_file"], "seed": int(r["sumo_seed"]),
                "demand": int(r["demand"]), "entries": int(r["entries"]), "arrived_1500": int(r["arrived_1500"]),
                "arrived_1800": int(r["arrived_1800"]), "unfinished": int(r["unfinished"]),
                "not_inserted": int(r["not_inserted"]), "wait": num(r["mean_wait_arrived_s"]), "full": int(r["full"]),
                "deadlock": int(r["deadlock"])}
        name = set_name(r["eval_set"], r["load_or_scenario"])
        rec.append(base | {"set": name})
        if name in ("held-out x1.2", "held-out x1.5"):    # the transfer files are the held-out files
            rec.append(base | {"set": name.replace("held-out", "transfer")})
    for r in read(args.e3):
        if r["clearance"] != "yellow3+allred4":
            continue
        rec.append({"source": "E3", "policy": r["policy"], "set": set_name(r["eval_set"], r["load_or_scenario"]),
                    "k": int(r["training_run"]), "map": r["map"], "e": int(r["episode"]), "route_file": r["route_file"],
                    "seed": int(r["sumo_seed"]), "demand": int(r["demand"]), "entries": int(r["entries"]),
                    "arrived_1500": int(r["arrived_1500"]), "arrived_1800": int(r["arrived_1800"]),
                    "unfinished": int(r["unfinished"]), "not_inserted": int(r["not_inserted"]),
                    "wait": num(r["mean_wait_arrived"]), "full": int(r["full_mine"] == "True"),
                    "deadlock": int(r["deadlock_mine"] == "True")})
    write(args.out / "episodes_all.csv", rec)

    idx = {(r["source"], r["policy"], r["set"], r["k"], r["map"], r["e"]): r for r in rec}
    seed_ok = seed_n = 0
    for r in rec:
        if r["source"] != "E12":
            for pol in E12_POL:
                o = idx.get(("E12", pol, r["set"], r["k"], r["map"], r["e"]))
                if o:
                    seed_n += 1
                    seed_ok += (o["seed"], o["route_file"]) == (r["seed"], r["route_file"])
                    break
    checks.append(f"Pairing with E6 and E3: {seed_ok}/{seed_n} baseline/E3 episodes have the same route file and SUMO "
                  "seed as the matching E12 episodes")
    counts = defaultdict(int)
    for r in rec:
        counts[(r["source"], r["policy"])] += 1
    checks.append("Episodes per controller: " + "; ".join(f"{s} {p} {n}" for (s, p), n in sorted(counts.items())))

    # ---------------- run level and summary
    groups = defaultdict(list)
    for r in rec:
        groups[(r["source"], r["policy"], r["set"], r["k"])].append(r)
    run_rows = []
    for (s, p, name, k), rr in sorted(groups.items()):
        waits = [x["wait"] for x in rr if not math.isnan(x["wait"])]
        run_rows.append({"source": s, "policy": p, "set": name, "k": k, "episodes": len(rr),
                         "arrived_1800": st.mean(x["arrived_1800"] for x in rr),
                         "arrived_1500": st.mean(x["arrived_1500"] for x in rr),
                         "full_share": st.mean(x["full"] for x in rr), "deadlocks": sum(x["deadlock"] for x in rr),
                         "not_inserted": st.mean(x["not_inserted"] for x in rr),
                         "unfinished": st.mean(x["unfinished"] for x in rr),
                         "wait_arrived": st.mean(waits) if waits else math.nan,
                         "demand": st.mean(x["demand"] for x in rr)})
    write(args.out / "run_level.csv", run_rows)

    by = defaultdict(list)
    for r in run_rows:
        by[(r["source"], r["policy"], r["set"])].append(r)
    controllers = [("E6", "Fixed plan"), ("E6", "Actuated")] + [("E12", p) for p in E12_POL] + [("E3", p) for p in E3_POL]
    summary = []
    for name in SETS:
        for s, p in controllers:
            rr = by.get((s, p, name))
            if not rr:
                continue
            eps = [x for x in rec if x["source"] == s and x["policy"] == p and x["set"] == name]
            m, sd, half = mean_ci([x["arrived_1800"] for x in rr])
            waits = [x["wait"] for x in eps if not math.isnan(x["wait"])]
            summary.append({"set": name, "source": s, "policy": p, "runs": len(rr), "episodes": len(eps),
                            "arrived_1800_mean": m, "arrived_1800_sd": sd, "arrived_1800_ci95": half,
                            "arrived_1500_mean": mean_ci([x["arrived_1500"] for x in rr])[0],
                            "full_pct": 100 * st.mean(x["full"] for x in eps), "deadlocks": sum(x["deadlock"] for x in eps),
                            "not_inserted_mean": st.mean(x["not_inserted"] for x in eps),
                            "unfinished_mean": st.mean(x["unfinished"] for x in eps),
                            "wait_arrived_median": st.median(waits) if waits else math.nan,
                            "demand_mean": st.mean(x["demand"] for x in eps)})
    write(args.out / "summary.csv", summary)

    # ---------------- paired comparisons with the fixed plan
    def paired(s: str, p: str, name: str, ref=("E6", "Fixed plan")) -> dict | None:
        d_k, better, worse, equal, wd = [], 0, 0, 0, []
        dfull, ddead = [], []
        for k in range(1, 6):
            diffs = []
            for x in rec:
                if (x["source"], x["policy"], x["set"], x["k"]) != (s, p, name, k):
                    continue
                y = idx.get((ref[0], ref[1], name, k, x["map"], x["e"]))
                if y is None:
                    continue
                diffs.append(x["arrived_1800"] - y["arrived_1800"])
                better += x["arrived_1800"] > y["arrived_1800"]
                worse += x["arrived_1800"] < y["arrived_1800"]
                equal += x["arrived_1800"] == y["arrived_1800"]
                dfull.append(x["full"] - y["full"])
                ddead.append(x["deadlock"] - y["deadlock"])
                if x["full"] and y["full"]:
                    wd.append(x["wait"] - y["wait"])
            if diffs:
                d_k.append(st.mean(diffs))
        if len(d_k) < 2:
            return None
        m, sd, half = mean_ci(d_k)
        t, p_val, dz = one_sample_t(d_k)
        return {"set": name, "source": s, "policy": p, "reference": ref[1], "runs": len(d_k),
                "pairs": better + worse + equal, "diff_arrived_1800": m, "ci95_low": m - half, "ci95_high": m + half,
                "sd_run_diffs": sd, "t_df4": t, "p": p_val, "d_z": dz, "runs_positive": sum(d > 0 for d in d_k),
                "episodes_better": better, "episodes_worse": worse, "episodes_equal": equal,
                "diff_full_pct": 100 * st.mean(dfull), "diff_deadlocks": sum(ddead),
                "both_full_pairs": len(wd), "wait_diff_both_full": st.mean(wd) if wd else math.nan}

    comp = [c for name in SETS for s, p in controllers[1:] if (c := paired(s, p, name))]
    conf = [c for c in comp if c["source"] == "E12" and c["set"] in HELDOUT]
    expl = [c for c in comp if c not in conf]
    for fam, label in ((conf, "confirmatory"), (expl, "exploratory")):
        for c, a in zip(fam, holm([c["p"] for c in fam])):
            c["family"] = label
            c["p_holm"] = a
    write(args.out / "paired_vs_fixed.csv", conf + expl)

    # ---------------- E12 against E3 (same policy, same files and seeds)
    e3cmp = []
    for name in SETS[:7]:
        for p in E3_POL:
            c = paired("E12", p, name, ref=("E3", p))
            if c:
                e3cmp.append(c)
    for c, a in zip(e3cmp, holm([c["p"] for c in e3cmp])):
        c["p_holm"] = a
    write(args.out / "e12_vs_e3.csv", e3cmp)

    # ---------------- training
    trows = []
    for p in E12_POL:
        for load in ("x1.0", "x1.2", "x1.5"):
            key = "n_arrived_1500" if load == "x1.0" else "n_arrived_1800"
            dem = {"x1.0": 1355, "x1.2": 1626, "x1.5": 2036}[load]
            first, last, lfull, ev_same = [], [], [], []
            for k in range(1, 6):
                eps = sorted(per_run[(p, load, str(k))], key=lambda r: int(r["episode"]))
                first.append(st.mean(int(r[key]) for r in eps[:10]))
                last.append(st.mean(int(r[key]) for r in eps[-10:]))
                lfull.append(st.mean(int(r["n_entries"]) >= 0.99 * dem for r in eps[-10:]))
                ho = [x for x in rec if x["source"] == "E12" and x["policy"] == p and x["set"] == f"held-out {load}" and x["k"] == k]
                ev_same.append(st.mean(x["arrived_1500" if load == "x1.0" else "arrived_1800"] for x in ho))
            trows.append({"policy": p, "load": load, "window_s": 1500 if load == "x1.0" else 1800, "demand": dem,
                          "train_first10_mean": st.mean(first), "train_last10_mean": st.mean(last),
                          "train_last10_sd": st.stdev(last), "train_last10_full_pct": 100 * st.mean(lfull),
                          "heldout_eval_mean": st.mean(ev_same), "heldout_eval_sd": st.stdev(ev_same)})
    write(args.out / "training.csv", trows)

    # ---------------- report
    (args.out / "checks.txt").write_text("\n".join(checks) + "\n", encoding="utf-8")
    md = ["# E12 analysis tables", "",
          "Generated by `revision/tools/e12_analysis.py` from files only. Means ± SD and 95% CI are across the 5 training "
          "runs (unit of replication); for the baselines, across the 5 SUMO seeds of the same files. All evaluation "
          "episodes: 1800 s, 3 s yellow + 4 s all-red for the DRL policies, field program for the baselines, "
          "`--time-to-teleport -1`. Full = at least 99% of the demand entered by 1800 s; deadlock = no arrival for at "
          "least 300 s while vehicles are in the network. E3 = the original policies (trained yellow-only on one demand "
          "file), evaluated with the same clearance on the same files and seeds.", "",
          "## Integrity checks", ""] + [f"- {c}" for c in checks]
    md += ["", "## 1. Held-out and scenario/transfer results", "",
           "| Set | Controller | Arrived by 1800 s, mean ± SD [95% CI] | Arrived by 1500 s | Full | Deadlocks | "
           "Not inserted | Unfinished | Wait of arrived, s (median) | Demand |", "|---|---|---|---|---|---|---|---|---|---|"]
    for r in summary:
        lab = r["policy"] if r["source"] == "E6" else f"{r['policy']} ({r['source']})"
        md.append(f"| {r['set']} | {lab} | {fmt(r['arrived_1800_mean'])} ± {fmt(r['arrived_1800_sd'])} "
                  f"[±{fmt(r['arrived_1800_ci95'])}] | {fmt(r['arrived_1500_mean'])} | {fmt(r['full_pct'])}% | "
                  f"{r['deadlocks']}/{r['episodes']} | {fmt(r['not_inserted_mean'])} | {fmt(r['unfinished_mean'])} | "
                  f"{fmt(r['wait_arrived_median'], 1)} | {fmt(r['demand_mean'])} |")
    md += ["", "## 2. Paired differences with the fixed plan (vehicles arrived by 1800 s)", "",
           "Difference = controller − fixed plan on the same file and SUMO seed, averaged per run; t-test on the 5 "
           "run-level differences (df = 4), two-sided; d_z = mean / SD of the run-level differences. Holm within the "
           "confirmatory family (E12 × held-out, 12 tests) and within the exploratory family. Wait difference: only "
           "episode pairs where both controllers served the full demand.", "",
           "| Family | Set | Controller | Diff. [95% CI] | t(4) | p | p (Holm) | d_z | Runs > 0 | Episodes better / worse | "
           "Δ full (pp) | Δ deadlocks | Both-full pairs | Δ wait, s |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for c in conf + expl:
        lab = c["policy"] if c["source"] == "E6" else f"{c['policy']} ({c['source']})"
        md.append(f"| {c['family']} | {c['set']} | {lab} | {fmt(c['diff_arrived_1800'], 1)} [{fmt(c['ci95_low'], 1)}, "
                  f"{fmt(c['ci95_high'], 1)}] | {fmt(c['t_df4'], 2)} | {fp(c['p'])} | {fp(c['p_holm'])} | "
                  f"{fmt(c['d_z'], 2)} | {c['runs_positive']}/5 | {c['episodes_better']} / {c['episodes_worse']} | "
                  f"{fmt(c['diff_full_pct'])} | {c['diff_deadlocks']:+d} | {c['both_full_pairs']} | "
                  f"{fmt(c['wait_diff_both_full'], 1)} |")
    md += ["", "## 3. Retrained (E12) against original (E3) policies, same clearance, files and seeds", "",
           "| Set | Policy | Diff. arrived by 1800 s [95% CI] | p (Holm, 21 tests) | Δ full (pp) | Δ deadlocks |",
           "|---|---|---|---|---|---|"]
    for c in e3cmp:
        md.append(f"| {c['set']} | {c['policy']} | {fmt(c['diff_arrived_1800'], 1)} [{fmt(c['ci95_low'], 1)}, "
                  f"{fmt(c['ci95_high'], 1)}] | {fp(c['p_holm'])} | {fmt(c['diff_full_pct'])} | {c['diff_deadlocks']:+d} |")
    md += ["", "## 4. Training (online learning) against held-out evaluation, same time window", "",
           "| Policy | Load | Window | Demand | Training, first 10 episodes | Training, last 10 (mean ± SD over runs) | "
           "Last 10 full | Held-out evaluation (mean ± SD over runs) |", "|---|---|---|---|---|---|---|---|"]
    for r in trows:
        md.append(f"| {r['policy']} | {r['load']} | {r['window_s']} s | {r['demand']} | {fmt(r['train_first10_mean'])} | "
                  f"{fmt(r['train_last10_mean'])} ± {fmt(r['train_last10_sd'])} | {fmt(r['train_last10_full_pct'])}% | "
                  f"{fmt(r['heldout_eval_mean'])} ± {fmt(r['heldout_eval_sd'])} |")
    (args.out / "E12_analysis.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(checks))
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
