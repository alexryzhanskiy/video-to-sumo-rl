"""Right-turn MaxPressure (post hoc, C-20, 8 Nov 2026): levels and paired differences on the locked test set and the
second real window, with the statistics of revision/tools/e13_exploratory_locked.py (locked) and
revision/tools/e14_analysis.py (second window); those tools and their outputs are not changed.

Usage: python mp_rt_analysis.py <output prefix>     (e.g. revision/reports/mp_rt_2026-11-08)

Unit = training run k (n = 5); a baseline's k is the seed group with the SUMO seeds of DRL run k, so every comparison
is paired on (map, route file, SUMO seed). Per k, a metric is the mean over that k's files (10 per load, 5 per
scenario, 10 in the second window). 95% t CIs (df 4); two-sided one-sample t-tests on d_k; if the five d_k are equal
(SD = 0): p = 1 when they are 0, else p = 0 (the limit, as D19), flagged. Holm within each family: per evaluation
(locked; second window) and per measure (arrivals by 1800 s; total delay), over all contrasts of that evaluation
(locked: 7 demands x 4 contrasts = 28; second window: 4).
Contrasts: final design - MaxPressure-RT (direction of the earlier reports: final design minus baseline), and
MaxPressure-RT - {pre-registered MaxPressure, fixed plan, actuated}.
"""
import csv
import hashlib
import json
import math
import statistics as st
import sys
from pathlib import Path

from scipy import stats

REV = Path(__file__).resolve().parent.parent
E13 = REV / "e12_kit" / "e13" / "results"
S2C = REV / "runs" / "s2c" / "out"
E14B = REV / "runs" / "e14" / "baselines"
RT = REV / "runs" / "s2c_rt" / "out"
E14_DEMAND = REV / "twin" / "E14" / "demand"
OLD_LOCKED = REV / "reports" / "e13_exploratory_locked_2026-10-30"
OLD_E14 = REV / "reports" / "e14_results_2026-11-02"
prefix = Path(sys.argv[1])
for suffix in (".md", "_levels.csv", "_diffs.csv"):
    if Path(f"{prefix}{suffix}").exists():
        sys.exit(f"{prefix}{suffix} exists: never overwrite a report")

rd = lambda p: list(csv.DictReader(open(p, encoding="utf-8")))
true = lambda v: v in ("1", "True", "true")
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
final = json.load(open(E13 / "selection_final.json", encoding="utf-8"))["final"]
FINAL = f"{final['rung']} {final['policy']}"
RTN = "MaxPressure-RT"
NAME = {"Fixed plan": "Fixed plan", "Actuated": "Actuated", "MaxPressure": "MaxPressure (pre-registered)",
        "Webster": "Webster plan", FINAL: f"Final design ({FINAL})", RTN: "MaxPressure-RT (post hoc)"}
CTRLS = ["Fixed plan", "Actuated", "MaxPressure", "Webster", FINAL, RTN]
CONTRASTS = [(FINAL, RTN), (RTN, "MaxPressure"), (RTN, "Fixed plan"), (RTN, "Actuated")]
DEMANDS = {"x1.0": ("prybuzka_lt10", "x1.0"), "x1.2": ("prybuzka_lt12", "x1.2"), "x1.5": ("prybuzka_lt15", "x1.5"),
           "S1": ("prybuzka_lts1", "x1.0"), "S2": ("prybuzka_lts2", "x1.0"), "S3": ("prybuzka_lts3", "x1.0"),
           "S4": ("prybuzka_lts4", "x1.0")}
METRICS = {"arrived_1800": lambda r: float(r["arrived_1800"]),
           "served_pct": lambda r: 100 * float(r["arrived_1800"]) / float(r["demand"]),
           "total_delay_vh": lambda r: float(r["total_delay_vh"]), "mean_delay_s": lambda r: float(r["mean_delay_s"]),
           "mean_wait_arrived_s": lambda r: float(r["mean_wait_arrived_s"])}
MEASURES = {"arrivals": ("arrived_1800", "Arrivals by 1800 s", "vehicles"),
            "total_delay_vh": ("total_delay_vh", "Total delay", "veh·h")}
problems = []
tuned = json.load(open(RT / "tune" / "tuned_rt.json", encoding="utf-8"))
tuned_pre = json.load(open(S2C / "tune" / "tuned.json", encoding="utf-8"))
movmap = json.load(open(RT / "movements.json", encoding="utf-8"))

# ------------------------------------------------------------------ episodes
locked, e14 = {}, {}
for r in rd(E13 / "baseline_episodes.csv") + rd(S2C / "results" / "eval_episodes.csv"):
    if r["eval_set"] == "locked" and r["policy"] in ("Fixed plan", "Actuated", "MaxPressure", "Webster"):
        locked.setdefault((r["policy"], r["map"]), []).append(r)
for r in rd(E13 / "eval_episodes.csv"):
    if r["eval_set"] == "locked" and r["rung"] == final["rung"] and r["policy"] == final["policy"]:
        for lab, (m, tl) in DEMANDS.items():
            if r["map"] == m and r["train_load"] == tl:
                locked.setdefault((FINAL, m), []).append(r)
for r in rd(RT / "results" / "eval_episodes.csv"):
    if r["eval_set"] == "locked" and r["policy"] == RTN:
        locked.setdefault((RTN, r["map"]), []).append(r)
for r in rd(E13 / "e14_final_episodes.csv"):
    e14.setdefault(FINAL, []).append(r)
for r in rd(E14B / "results" / "e14_episodes.csv"):
    e14.setdefault(r["policy"], []).append(r)
for r in rd(RT / "results" / "e14_episodes.csv"):
    if r["policy"] == RTN:
        e14.setdefault(RTN, []).append(r)

# checks of the new episodes
for lab, (m, cfg_load) in DEMANDS.items():
    rows = locked.get((RTN, m), [])
    want = f"{tuned['loads'][cfg_load]['variant']} h={tuned['loads'][cfg_load]['h']:g}"
    n_exp = 50 if lab.startswith("x") else 25
    if len(rows) != n_exp:
        problems.append(f"{RTN} {lab}: {len(rows)} locked episodes, expected {n_exp}")
    for r in rows:
        if r["controller_config"] != want or r["train_load"] != cfg_load or not r["movement_map"].startswith("rt-") \
                or not true(r["tripinfo_ok"]):
            problems.append(f"{RTN} {lab} {r['route_file']} {r['sumo_seed']}: config {r['controller_config']} "
                            f"({r['train_load']}), map {r['movement_map']}, tripinfo_ok {r['tripinfo_ok']}")
    pre = {(r["route_file"], r["sumo_seed"], r["training_run"]) for r in locked.get(("MaxPressure", m), [])}
    if {(r["route_file"], r["sumo_seed"], r["training_run"]) for r in rows} != pre:
        problems.append(f"{RTN} {lab}: (file, seed, k) set differs from the pre-registered MaxPressure")
want14 = f"{tuned['loads']['x1.0']['variant']} h={tuned['loads']['x1.0']['h']:g}"
e14_sha = {p.name: sha(p) for p in E14_DEMAND.rglob("*.rou.xml")}
for c in CTRLS:
    rs = e14.get(c, [])
    if len(rs) != 50:
        problems.append(f"second window {c}: {len(rs)} episodes, expected 50")
    for r in rs:
        k, e = int(r["training_run"]), int(r["b7_seed"]) % 100
        if int(r["sumo_seed"]) != 1042 + k + e or r["route_file"] not in e14_sha or not true(r["tripinfo_ok"]) \
                or int(r["demand"]) != 923:
            problems.append(f"second window {c} {r['route_file']} k{k}: seed {r['sumo_seed']}, demand {r['demand']}")
        if c == RTN and (r["controller_config"] != want14 or not r["movement_map"].startswith("rt-")):
            problems.append(f"second window {RTN} {r['route_file']}: config {r['controller_config']}")


# ------------------------------------------------------------------ statistics (as the two earlier tools)
def tci(xs):
    n, mu = len(xs), st.mean(xs)
    sd = st.stdev(xs) if n > 1 else 0.0
    h = stats.t.ppf(0.975, n - 1) * sd / math.sqrt(n) if n > 1 else float("nan")
    return mu, sd, mu - h, mu + h


def per_run(rows, f):
    by = {}
    for r in rows:
        by.setdefault(int(r["training_run"]), []).append(f(r))
    return [st.mean(by[k]) for k in sorted(by)]


def level(ev, demand, c, rows):
    rec = {"evaluation": ev, "demand": demand, "controller": NAME[c], "episodes": len(rows),
           "deadlocks": sum(true(r["deadlock"]) for r in rows), "full_pct": 100 * sum(true(r["full"]) for r in rows) / len(rows),
           "demand_veh": st.mean(float(r["demand"]) for r in rows)}
    for name, f in METRICS.items():
        mu, sd, lo, hi = tci(per_run(rows, f))
        rec |= {name: mu, f"{name}_sd": sd, f"{name}_lo": lo, f"{name}_hi": hi}
    return rec


key = lambda r: (r["route_file"], r["sumo_seed"])


def diff(ev, demand, a, b, ra, rb, measure):
    col = MEASURES[measure][0]
    ia = {key(r): r for r in ra}
    pairs = [(ia[key(r)], r) for r in rb if key(r) in ia]
    if len(pairs) != len(ra) or len(pairs) != len(rb):
        problems.append(f"{ev} {demand} {a} - {b}: {len(pairs)} pairs of {len(ra)} / {len(rb)}")
    by = {}
    for x, y in pairs:
        if x["training_run"] != y["training_run"]:
            problems.append(f"{ev} {demand} {a} - {b}: k differs for {key(x)}")
        by.setdefault(int(y["training_run"]), []).append(float(x[col]) - float(y[col]))
    d = [st.mean(by[k]) for k in sorted(by)]
    mu, sd, lo, hi = tci(d)
    if sd > 0:
        p, note = 2 * stats.t.sf(abs(mu) / (sd / math.sqrt(len(d))), len(d) - 1), ""
    else:
        p, note = (1.0, "all d_k = 0") if mu == 0 else (0.0, "all d_k equal")
    better = sum(x > 0 for x in d) if measure == "arrivals" else sum(x < 0 for x in d)
    worse = sum(x < 0 for x in d) if measure == "arrivals" else sum(x > 0 for x in d)
    base_mean = st.mean(float(y[col]) for _, y in pairs)
    return {"evaluation": ev, "demand": demand, "contrast": f"{NAME[a]} - {NAME[b]}", "a": a, "b": b,
            "measure": measure, "n": len(d), "mean": mu, "sd": sd, "lo": lo, "hi": hi,
            "pct_of_b": 100 * mu / base_mean if base_mean else float("nan"), "runs_a_better": better,
            "runs_a_worse": worse, "p": p, "note": note, "d_k": ";".join(f"{x:.3f}" for x in d)}


def holm(rows):
    for ev in {x["evaluation"] for x in rows}:
        for measure in MEASURES:
            fam = sorted([x for x in rows if x["evaluation"] == ev and x["measure"] == measure], key=lambda x: x["p"])
            run_max = 0.0
            for i, x in enumerate(fam):
                run_max = max(run_max, min(1.0, (len(fam) - i) * x["p"]))
                x["p_holm"], x["family_size"] = run_max, len(fam)


levels, diffs, extra = [], [], []
for lab, (m, _) in DEMANDS.items():
    for c in CTRLS:
        rows = locked.get((c, m), [])
        if rows:
            levels.append(level("locked", lab, c, rows))
        else:
            problems.append(f"locked {c} {lab}: no episodes")
    for a, b in CONTRASTS:
        for measure in MEASURES:
            diffs.append(diff("locked", lab, a, b, locked[(a, m)], locked[(b, m)], measure))
    for measure in MEASURES:    # the earlier report's contrast, recomputed for the side-by-side table (not in a family)
        extra.append(diff("locked", lab, FINAL, "MaxPressure", locked[(FINAL, m)], locked[("MaxPressure", m)], measure))
for c in CTRLS:
    levels.append(level("second window", "x1.0 (09:38)", c, e14[c]))
for a, b in CONTRASTS:
    for measure in MEASURES:
        diffs.append(diff("second window", "x1.0 (09:38)", a, b, e14[a], e14[b], measure))
for measure in MEASURES:
    extra.append(diff("second window", "x1.0 (09:38)", FINAL, "MaxPressure", e14[FINAL], e14["MaxPressure"], measure))
holm(diffs)

# ------------------------------------------------------------------ reproduction of the earlier reports
repro = []
old = {(r["demand"], r["controller"]): r for r in rd(f"{OLD_LOCKED}_levels.csv")}
n_ok = n = 0
for x in levels:
    if x["evaluation"] != "locked" or x["controller"] == NAME[RTN]:
        continue
    o = old.get((x["demand"], {v: k for k, v in NAME.items()}[x["controller"]]))
    n += 1
    n_ok += bool(o) and all(abs(float(o[f]) - x[f]) < 1e-9 for f in ("served_pct", "served_pct_lo", "total_delay_vh",
                                                                      "total_delay_vh_lo", "mean_delay_s"))
repro.append(f"locked levels of the five earlier controllers: {n_ok}/{n} rows equal to `{OLD_LOCKED.name}_levels.csv`")
oldd = {(r["demand"], r["baseline"], r["metric"]): r for r in rd(f"{OLD_LOCKED}_diffs.csv")}
n_ok = n = 0
for x in extra:
    if x["evaluation"] != "locked":
        continue
    o = oldd.get((x["demand"], "MaxPressure", x["measure"]))
    n += 1
    ok = bool(o) and all(abs(float(o[f]) - x[f]) < 1e-9 for f in ("mean", "lo", "hi", "p"))
    n_ok += ok
    if o:
        x["p_holm_earlier"] = float(o["p_holm"])
repro.append(f"locked final design - pre-registered MaxPressure: {n_ok}/{n} rows equal to `{OLD_LOCKED.name}_diffs.csv` "
             "(mean, CI, p)")
old14 = {r["controller"]: r for r in rd(f"{OLD_E14}_levels.csv")}
name14 = {"Fixed plan": "Fixed plan", "Actuated": "Actuated", "MaxPressure": "Tuned MaxPressure",
          "Webster": "Webster plan", FINAL: f"Final design ({FINAL})"}
n_ok = n = 0
for x in levels:
    if x["evaluation"] != "second window" or x["controller"] == NAME[RTN]:
        continue
    o = old14.get(name14[{v: k for k, v in NAME.items()}[x["controller"]]])
    n += 1
    n_ok += bool(o) and all(abs(float(o[f]) - x[f]) < 1e-9 for f in ("arrived_1800", "total_delay_vh",
                                                                      "total_delay_vh_lo", "mean_delay_s"))
repro.append(f"second-window levels of the five earlier controllers: {n_ok}/{n} rows equal to `{OLD_E14.name}_levels.csv`")
old14d = {(r["measure"], r["baseline"]): r for r in rd(f"{OLD_E14}_diffs.csv")}
n_ok = n = 0
for x in extra:
    if x["evaluation"] != "second window":
        continue
    o = old14d.get(({"arrivals": "Arrivals by 1800 s", "total_delay_vh": "Total delay (veh-h)"}[x["measure"]],
                    "Tuned MaxPressure"))
    n += 1
    n_ok += bool(o) and all(abs(float(o[f]) - x[f]) < 1e-9 for f in ("mean", "lo", "hi", "p"))
    if o:
        x["p_holm_earlier"] = float(o["p_holm"])
repro.append(f"second window final design - pre-registered MaxPressure: {n_ok}/{n} rows equal to `{OLD_E14.name}_diffs.csv`")
for s in repro:
    a, b = s.split(": ")[1].split(" ")[0].split("/")
    if a != b or a == "0":
        problems.append(f"reproduction: {s}")

# ------------------------------------------------------------------ files
for name, rows in (("levels", levels), ("diffs", diffs)):
    keys = list(dict.fromkeys(k for r in rows for k in r if k not in ("a", "b")))
    with open(f"{prefix}_{name}.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

# ------------------------------------------------------------------ report
f2 = lambda x: f"{x:+.2f}"
L = lambda ev, d, c: next(x for x in levels if x["evaluation"] == ev and x["demand"] == d and x["controller"] == NAME[c])
D = lambda ev, d, a, b, m: next(x for x in diffs if x["evaluation"] == ev and x["demand"] == d and x["a"] == a
                                 and x["b"] == b and x["measure"] == m)
X = lambda ev, d, m: next(x for x in extra if x["evaluation"] == ev and x["demand"] == d and x["measure"] == m)
reg = json.load(open(RT / "regression" / "regression_report.json", encoding="utf-8"))
smk = json.load(open(RT / "smoke" / "smoke_report.json", encoding="utf-8"))
fx = tuned["fixed_plan_episodes"]
lk = json.load(open(RT / "locked_eval.json", encoding="utf-8"))
md = ["# Right-turn MaxPressure: post hoc exploratory baseline (C-20, 8 Nov 2026)", "",
      "**Not pre-registered.** Added after peer review, by decision C-20 of 8 Nov 2026 (approved by Pavlo Radiuk). The "
      "pre-registered tuned MaxPressure (S2c, pre-registration 6.2, reading C1) leaves right turns out of the phase "
      "pressure. Here the phase pressure also counts the right turns; the controller is re-tuned with exactly the "
      "pre-registered grid and rule and evaluated on the locked test set (×1.0, ×1.2, ×1.5, S1–S4) and the second real "
      "window. It is reported **alongside** the pre-registered MaxPressure, never instead of it. The confirmatory test "
      "(final design vs fixed plan, section 11) does not involve MaxPressure and is unchanged.", "",
      f"Generated by `revision/s2c_rt/mp_rt_analysis.py` (statistics as `revision/tools/e13_exploratory_locked.py` and "
      f"`revision/tools/e14_analysis.py`). Driver: `revision/s2c_rt/s2c_rt.py` (imports `revision/s2c/s2c.py` and, "
      f"through it, `e13.py` read-only; overrides only the movement map). Outputs: `revision/runs/s2c_rt/out/` "
      f"(SHA-256 manifest `MANIFEST.sha256`). SUMO 1.26.0 with libsumo, laptop, default twin.", "",
      "## 1. Movement map", "",
      "Signal `nC` links with direction `r` (from the network of the fixed plan, `"
      + Path(movmap["net"]).name + f"`, sha256 `{movmap['net_sha256'][:12]}…`), and their state in the four green "
      "states (phase 0 Svobody through, 1 Svobody left, 2 Prybuzka through, 3 Prybuzka left) and in the all-red state:", "",
      "| Link | From lane → to lane | States, phases 0–3 | All-red | Green (G/g) in phase |", "|---|---|---|---|---|"]
for r in movmap["right_turn_links"]:
    md.append(f"| {r['linkIndex']} | `{r['from_lane']}` → `{r['to_lane']}` | `{r['states_phase0_3']}` | "
              f"`{r['allred_state']}` | {', '.join(map(str, r['green_in_phases']))} |")
md += ["", "Reading: each right turn is green (`G`) in exactly one phase, the through phase of its street; in the other "
       "three phases and in the all-red state it is `s` (SUMO: stop, then turn if clear), which is not green by the rule "
       "of C-20, so no right turn counts in two phases. (Had `s` counted, every right turn would be in all four phases, "
       "add the same term to every phase pressure and change no decision.) Movements per phase, incoming lanes → "
       "outgoing lanes, grouped per (approach, exit edge) as `s2c.movements()`; **bold** = added right turns:", "",
       "| Phase | Movements |", "|---|---|"]
pre_set = {str(p): [tuple(map(tuple, mv)) for mv in v] for p, v in movmap["pre_registered"].items()}
for p, mvs in movmap["right_turn"].items():
    cells = []
    for ins, outs in mvs:
        s = f"{'+'.join(ins)} → {'+'.join(outs)}"
        cells.append(s if (tuple(ins), tuple(outs)) in pre_set[p] else f"**{s}**")
    md.append(f"| {p} | {'; '.join(cells)} |")
md += ["", "The shared lane 0 of each approach is an incoming lane of both the through and the right-turn movement of "
       "its phase, so its vehicles count in both terms (the movement-sum definition of 6.2 applied literally). "
       f"Map digests (sha256 of the JSON): pre-registered `{movmap['pre_registered_sha256'][:12]}`, right-turn "
       f"`{movmap['right_turn_sha256'][:12]}`; every result row carries `movement_map` = `{tuned['movement_map']}`.", "",
       "## 2. Checks before the runs", "",
       f"**Regression** (`out/regression/regression_report.json`): the driver with the right turns removed again "
       f"(same override code path; map equal to `s2c.movements()`: {reg['equal_to_s2c_movements']}) re-ran "
       f"{len(reg['episodes'])} existing pre-registered MaxPressure episodes of `revision/runs/s2c/out` (run on Colab). "
       f"Records SHA-256 identical: {sum(e['records_identical'] for e in reg['episodes'])}/{len(reg['episodes'])}; "
       f"decision sequences identical: {sum(e['decisions_identical'] for e in reg['episodes'])}/{len(reg['episodes'])}; "
       f"metric rows identical: {sum(e['metrics_identical'] for e in reg['episodes'])}/{len(reg['episodes'])}; queue "
       f"series identical: {sum(bool(e['queue_identical']) for e in reg['episodes'])}/"
       f"{sum(e['queue_identical'] is not None for e in reg['episodes'])} (eval episodes). Passed: {reg['passed']}.", "",
       "| Episode | Configuration | SUMO seed | Records identical |", "|---|---|---|---|"]
for e in reg["episodes"]:
    md.append(f"| {e['episode']} | {e['config']} | {e['sumo_seed']} | {e['records_identical']} |")
md += ["", f"**Smoke** (`out/smoke/smoke_report.json`, training files, SUMO's own signal-state log checked with "
       f"`e13.check_tls`): passed {smk['passed']}.", "",
       "| Episode | Greens | Shortest / longest green, s | Rule violations | Arrived / demand | Deadlock | Pre-registered "
       "arrived, deadlock (same file, seed, config) |", "|---|---|---|---|---|---|---|"]
for e in smk["episodes"]:
    sr = e["signal_rules"]
    md.append(f"| {e['episode']} | {sr['greens']} | {sr['min_green']:g} / {sr['max_green']:g} | {sr['n_violations']} | "
              f"{e['arrived_1800']} / {e['demand']} | {e['deadlock']} | {e['prereg_arrived_1800']}, {e['prereg_deadlock']} |")
md += ["", "Deadlocks in free order at ×1.0 and ×1.2 are new compared with the pre-registered map. Mechanism (decision "
       "logs): the right-turn terms raise the pressure of the through phases 0 and 2, the left phases 1 and 3 stop being "
       "chosen (in free order a forced change also goes to the highest-pressure other phase, C2), the left-turn queues "
       "spill back and the junction gridlocks. This is the left-turn starvation that S2c saw for free order at high "
       "load, now at lower load; it follows from the rule, and rule 5.1 ranks candidates with deadlocks at ×1.0/×1.2 "
       "last. Field order serves every phase each cycle.", "",
       f"**Fixed-plan tuning episodes** were rerun on the laptop (not reused): {fx['records_identical_to_s2c']}/"
       f"{fx['fixed_episodes']} have records identical to the Colab S2c ones (`out/tune/fixed_vs_s2c.json`).", "",
       "## 3. Tuning (pre-registration 6.2 grid and rule 5.1 score, training files)", "",
       "Grid h ∈ {0, 2, 4, 6, 8, 12} × {free, field}, 20 training files × k = 1..5 per load, each paired with the fixed "
       "plan on the same file and SUMO seed; score = (mean arrivals − paired fixed arrivals) / mean demand, %; "
       "candidates with any deadlock at ×1.0/×1.2 last; ties within 0.1 pp to the lower mean delay (`e13.rank`, "
       "selection code `s2c.finalize_tuning`). Files: `out/tune/tuned_rt.json`, `out/tune/tuning_x10.csv` etc.", "",
       "| Load | Right-turn MaxPressure: selected | Score, % | Deadlocks (of 100) | Mean delay, s/veh | Pre-registered "
       "MaxPressure: selected | Score, % | Mean delay, s/veh |", "|---|---|---|---|---|---|---|---|"]
for load, c in tuned["loads"].items():
    p = tuned_pre["loads"][load]
    md.append(f"| {load} | {c['variant']} order, h = {c['h']:g} | {c['score']:+.4f} | {c['deadlocks']} | {c['delay']} | "
              f"{p['variant']} order, h = {p['h']:g} | {p['score']:+.4f} | {p['delay']} |")
if tuned.get("incomplete"):
    problems.append(f"tuning incomplete: {tuned['incomplete']}")
for load in tuned["loads"]:
    tag = {"x1.0": "x10", "x1.2": "x12", "x1.5": "x15"}[load]
    rows = rd(RT / "tune" / f"tuning_{tag}.csv")
    md += ["", f"Ranking at {load} (right-turn map):", "",
           "| Rank | Order | h | Score, % | Deadlocks | Arrivals | Fixed arrivals | Mean delay, s/veh | Median switches |",
           "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        md.append(f"| {r['rank']} | {r['variant']} | {r['h']} | {float(r['score']):+.4f} | {r['deadlocks']} | "
                  f"{r['arrived_1800']} | {r['fixed_arrived_1800']} | {r['delay']} | {r['switches_median']} |")
md += ["", f"## 4. Locked test set", "",
       f"Run once with `--locked-ok` (`out/locked_eval.json`: started {lk['started']}, finished {lk.get('finished')}, "
       f"complete {lk.get('complete')}, reruns {len(lk.get('reruns', []))}); the 50 locked route files were checked "
       "against `locked_test_hashes.txt` before the run. Same files, SUMO seeds and k as the pre-registered "
       "MaxPressure; scenarios S1–S4 use the ×1.0 configuration. Unit: k (n = 5), per k the mean over the files; 95% t "
       "CIs. Fixed plan and actuated: E13 baseline episodes; MaxPressure and Webster: S2c; final design: E13 locked "
       "evaluation (as the 30 Oct report).", "",
       "### Levels", "", "| Demand | Controller | Episodes | Deadlocks | Full | Arrivals by 1800 s [95% CI] | Served, % "
       "[95% CI] | Total delay, veh·h [95% CI] | Mean delay, s/veh [95% CI] |", "|---|---|---|---|---|---|---|---|---|"]
for x in [x for x in levels if x["evaluation"] == "locked"]:
    md.append(f"| {x['demand']} | {x['controller']} | {x['episodes']} | {x['deadlocks']} | {x['full_pct']:.0f}% | "
              f"{x['arrived_1800']:.1f} [{x['arrived_1800_lo']:.1f}, {x['arrived_1800_hi']:.1f}] | "
              f"{x['served_pct']:.2f} [{x['served_pct_lo']:.2f}, {x['served_pct_hi']:.2f}] | "
              f"{x['total_delay_vh']:.2f} [{x['total_delay_vh_lo']:.2f}, {x['total_delay_vh_hi']:.2f}] | "
              f"{x['mean_delay_s']:.1f} [{x['mean_delay_s_lo']:.1f}, {x['mean_delay_s_hi']:.1f}] |")
for ev in ("locked", "second window"):
    if ev == "second window":
        md += ["", "## 5. Second real window (09:38, 923 vehicles, 10 route files, x1.0 configurations)", "",
               "Final design: E13 x1.0 models (MyPC, `e14_final_episodes.csv`); fixed, actuated, pre-registered "
               "MaxPressure, Webster: `revision/runs/e14/baselines`; right-turn MaxPressure: this run, k = 1..5, SUMO "
               "seed 1042 + k + (routeSampler seed mod 100).", "",
               "| Controller | Episodes | Full demand | Deadlocks | Arrivals by 1800 s [95% CI] | Total delay, veh·h [95% CI] "
               "| Delay per demanded vehicle, s [95% CI] | Mean wait of arrived, s |", "|---|---|---|---|---|---|---|---|"]
        for x in [x for x in levels if x["evaluation"] == ev]:
            md.append(f"| {x['controller']} | {x['episodes']} | {x['full_pct'] * x['episodes'] / 100:.0f} | "
                      f"{x['deadlocks']} | {x['arrived_1800']:.1f} [{x['arrived_1800_lo']:.1f}, "
                      f"{x['arrived_1800_hi']:.1f}] | {x['total_delay_vh']:.2f} [{x['total_delay_vh_lo']:.2f}, "
                      f"{x['total_delay_vh_hi']:.2f}] | {x['mean_delay_s']:.1f} [{x['mean_delay_s_lo']:.1f}, "
                      f"{x['mean_delay_s_hi']:.1f}] | {x['mean_wait_arrived_s']:.1f} |")
    for measure, (col, title, unit) in MEASURES.items():
        fam = [x for x in diffs if x["evaluation"] == ev and x["measure"] == measure]
        md += ["", f"### {ev.capitalize()}: {title} ({unit}), paired differences A − B; Holm over {fam[0]['family_size']} "
               "contrasts", "", "| Demand | A − B | Mean [95% CI] | % of B | Runs A better / worse | p | p (Holm) | Note |",
               "|---|---|---|---|---|---|---|---|"]
        for x in fam:
            md.append(f"| {x['demand']} | {x['contrast']} | {f2(x['mean'])} [{f2(x['lo'])}, {f2(x['hi'])}] | "
                      f"{x['pct_of_b']:+.1f}% | {x['runs_a_better']} / {x['runs_a_worse']} | {x['p']:.4f} | "
                      f"{x['p_holm']:.4f} | {x['note']} |")

# ranking comparison
md += ["", "## 6. Does any ranking change? Final design vs pre-registered and vs right-turn MaxPressure", "",
       "Final design minus each MaxPressure, same pairing and CIs. The pre-registered column reproduces the earlier "
       "reports (Holm p from their families); the right-turn column is from the families above. Class by the 95% CI "
       "(unadjusted): final design better / MaxPressure better (CI excludes 0) or no clear difference.", "",
       "| Evaluation | Demand | Measure | Final − MaxPressure (pre-registered) [95% CI], runs better/worse, p (Holm) | "
       "Final − MaxPressure-RT [95% CI], runs better/worse, p (Holm) | Class: pre-registered → right-turn |",
       "|---|---|---|---|---|---|"]
changes = []
cells = [("locked", d) for d in DEMANDS] + [("second window", "x1.0 (09:38)")]
for ev, d in cells:
    for measure in MEASURES:
        a, b = X(ev, d, measure), D(ev, d, FINAL, RTN, measure)

        def cls(x):    # by the 95% CI of final - MaxPressure
            if (x["lo"] > 0) if measure == "arrivals" else (x["hi"] < 0):
                return "final design better"
            if (x["hi"] < 0) if measure == "arrivals" else (x["lo"] > 0):
                return "MaxPressure better"
            return "no clear difference"
        verdict = "same" if cls(a) == cls(b) else f"**{cls(a)} → {cls(b)}**"
        if cls(a) != cls(b):
            changes.append((ev, d, measure, f"{cls(a)} (pre-registered) → {cls(b)} (right-turn)"))
        md.append(f"| {ev} | {d} | {MEASURES[measure][1]} | {f2(a['mean'])} [{f2(a['lo'])}, {f2(a['hi'])}], "
                  f"{a['runs_a_better']}/{a['runs_a_worse']}, {a.get('p_holm_earlier', float('nan')):.4f} | "
                  f"{f2(b['mean'])} [{f2(b['lo'])}, {f2(b['hi'])}], {b['runs_a_better']}/{b['runs_a_worse']}, "
                  f"{b['p_holm']:.4f} | {verdict} |")
md += ["", "Order of the six controllers by mean total delay (lowest first):", "", "| Evaluation | Demand | Order |",
       "|---|---|---|"]
for ev, d in cells:
    xs = sorted([x for x in levels if x["evaluation"] == ev and x["demand"] == d], key=lambda x: x["total_delay_vh"])
    md.append(f"| {ev} | {d} | " + " < ".join(f"{x['controller']} {x['total_delay_vh']:.2f}" for x in xs) + " |")

dl = [(x["evaluation"], x["demand"], x["deadlocks"], x["episodes"]) for x in levels if x["controller"] == NAME[RTN]]
md += ["", "Deadlocked episodes of MaxPressure-RT: " + ", ".join(f"{ev} {d} {n}/{e}" for ev, d, n, e in dl if n)
       + f" (none elsewhere); configuration on the scenarios and the second window: the x1.0 one "
       f"({tuned['loads']['x1.0']['variant']} order, h = {tuned['loads']['x1.0']['h']:g})."]
md += ["", "## 7. Reproduction of the earlier reports by this script", ""] + [f"- {s}" for s in repro]
src = [E13 / "selection_final.json", E13 / "eval_episodes.csv", E13 / "baseline_episodes.csv",
       E13 / "e14_final_episodes.csv", S2C / "results" / "eval_episodes.csv", S2C / "tune" / "tuned.json",
       E14B / "results" / "e14_episodes.csv", RT / "results" / "eval_episodes.csv", RT / "results" / "e14_episodes.csv",
       RT / "results" / "tune_episodes.csv", RT / "tune" / "tuned_rt.json", RT / "movements.json",
       RT / "regression" / "regression_report.json", RT / "smoke" / "smoke_report.json", RT / "MANIFEST.sha256"]
md += ["", "## 8. Sources (SHA-256)", ""] + [f"- `{p.relative_to(REV.parent).as_posix()}` `{sha(p)}`" for p in src]
md += ["", "## 9. Draft deviation-log entry (section 11; number to be assigned)", "",
       "> D[XX] | Post hoc baseline (8 Nov 2026, after peer review; decision C-20) | A right-turn-aware MaxPressure was "
       "added as an exploratory baseline after the locked test and after peer review. It is not pre-registered. Its "
       "phase pressure also counts the right-turn connections that are green in the phase (links 0 and 8 in phase 0, "
       "4 and 12 in phase 2); everything else follows 6.2 and the S2c implementation (D18). It was re-tuned with the "
       "pre-registered grid and the score and ranking of rule 5.1 on the training files (selected: "
       + "; ".join(f"{l} {c['variant']} order, h = {c['h']:g}" for l, c in tuned["loads"].items())
       + ") and evaluated once on the locked test set (×1.0, ×1.2, ×1.5, S1–S4) and on the second real window. It is "
       "reported alongside the pre-registered MaxPressure, which is unchanged, and it does not change the confirmatory "
       "test (7.2–7.3) or any selection. Code `revision/s2c_rt/`, outputs `revision/runs/s2c_rt/out/`, report "
       f"`revision/reports/{prefix.name}.md`.", "",
       "Changes in the comparison with the final design: " + ("; ".join(f"{ev} {d} {MEASURES[m][1]}: {v}" for ev, d, m, v
                                                                      in changes) if changes else "none"), "",
       "Problems: " + ("; ".join(problems) if problems else "none")]
Path(f"{prefix}.md").write_text("\n".join(md) + "\n", encoding="utf-8")
print("\n".join(md))
