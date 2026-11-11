"""B7 (perception-error sensitivity): analysis as in revision/twin/B7/B7_run_spec.md, "What B7 reports".

Usage: python b7_analysis.py <e13/results> <S2c results folder(s), comma-separated> <output .md>
Controllers: fixed plan, actuated, tuned MaxPressure (S2c, k = 1) and the E13 final design (k = 1..5; per seed, the mean
over its five trained models). Per load and variant: mean over the variant's routeSampler seeds, and the paired
difference to `base` (variant minus base, same seed). Ranking stability: per seed, the ranks of the four controllers
(ties share the best rank) by arrivals (higher is better) and by total delay (lower is better), compared with the ranks
on `base`. Variants present in the episode files are reported (FOV variants since 30 Oct; fov_meas, ce_bias, ce_rand
since 4 Nov). ce_rand has its own seeds (7101-7110, one per draw) and no base file with the same seed: it is reported
as the mean over draws with the difference of means to base, the range over draws, and its ranks compared with the
ranks of the base means.
"""
import csv
import statistics as st
import sys
from pathlib import Path

from scipy.stats import rankdata

e13, out = Path(sys.argv[1]), Path(sys.argv[3])
rd = lambda p: list(csv.DictReader(open(p, encoding="utf-8")))
fin_rows = rd(e13 / "b7_final_episodes.csv")
base_rows = [r for d in sys.argv[2].split(",") for r in rd(Path(d) / "b7_episodes.csv")]
FINAL = f"{fin_rows[0]['rung']} {fin_rows[0]['policy']}"
CTRLS = ["Fixed plan", "Actuated", "MaxPressure", FINAL]
ORDER = ["base", "fovm20", "fovm10", "fovp10", "fovp20", "fov_meas", "ce_bias", "ce_rand"]
present = {r["b7_variant"] for r in fin_rows} | {r["b7_variant"] for r in base_rows}
VARIANTS = [v for v in ORDER if v in present] + sorted(present - set(ORDER))
FOV = [v for v in VARIANTS if v.startswith("fov")]
UNPAIRED = {"ce_rand"}
M = {"arrived_1800": float, "total_delay_vh": float, "mean_delay_s": float, "not_inserted": float}

val = {}    # (ctrl, load, variant, seed) -> metric dict
problems = []
for r in base_rows:
    if not r["tripinfo_ok"] in ("1", "True", "true"):
        problems.append(f"tripinfo not ok: {r['policy']} {r['b7_load']} {r['b7_variant']} {r['b7_seed']}")
    val[(r["policy"], r["b7_load"], r["b7_variant"], r["b7_seed"])] = {m: f(r[m]) for m, f in M.items()} | {
        "deadlock": r["deadlock"] in ("1", "True", "true")}
acc = {}
for r in fin_rows:
    if not r["tripinfo_ok"] in ("1", "True", "true"):
        problems.append(f"tripinfo not ok: final k{r['training_run']} {r['b7_load']} {r['b7_variant']} {r['b7_seed']}")
    acc.setdefault((FINAL, r["b7_load"], r["b7_variant"], r["b7_seed"]), []).append(r)
for k, rows in acc.items():
    if len(rows) != 5:
        problems.append(f"{k}: {len(rows)} models")
    val[k] = {m: st.mean(f(r[m]) for r in rows) for m, f in M.items()} | {
        "deadlock": any(r["deadlock"] in ("1", "True", "true") for r in rows)}
loads = sorted({k[1] for k in val})
SEEDS = {v: sorted({k[3] for k in val if k[2] == v}) for v in VARIANTS}
for c in CTRLS:
    for ld in loads:
        for v in VARIANTS:
            miss = [s for s in SEEDS[v] if (c, ld, v, s) not in val]
            if miss:
                problems.append(f"missing {c} {ld} {v} seeds {miss}")
for v in VARIANTS:
    if v not in UNPAIRED and SEEDS[v] != SEEDS["base"]:
        problems.append(f"{v}: seeds {SEEDS[v]} differ from base {SEEDS['base']}")
VARIANTS = [v for v in VARIANTS if all((c, ld, v, s) in val for c in CTRLS for ld in loads for s in SEEDS[v])]

md = ["# B7: perception-error sensitivity", "",
      f"Final design {FINAL} (mean of its 5 trained models per file) vs fixed plan, actuated and tuned MaxPressure (S2c, k = 1). "
      f"Loads {', '.join(loads)}; variants {', '.join(VARIANTS)}; routeSampler seeds {', '.join(SEEDS['base'])} "
      f"(ce_rand: {len(SEEDS.get('ce_rand', []))} draws), the same SUMO seed for a seed index across variants and "
      "controllers. Exploratory (pre-registration section 9).", ""]
for ld in loads:
    md += [f"## {ld}: mean over seeds; in brackets the paired change vs base (variant − base), mean [min, max] over seeds "
           "(ce_rand: difference of means [min, max over draws minus the base mean])", "",
           "| Variant | Controller | Arrived by 1800 s | Total delay, veh·h | Mean delay, s/veh | Deadlocks |", "|---|---|---|---|---|---|"]
    for v in VARIANTS:
        for c in CTRLS:
            xs = [val[(c, ld, v, s)] for s in SEEDS[v]]
            cell = []
            for m, nd in (("arrived_1800", 1), ("total_delay_vh", 2), ("mean_delay_s", 1)):
                mu = st.mean(x[m] for x in xs)
                if v == "base":
                    cell.append(f"{mu:.{nd}f}")
                elif v in UNPAIRED:
                    b = st.mean(val[(c, ld, "base", s)][m] for s in SEEDS["base"])
                    d = [x[m] - b for x in xs]
                    cell.append(f"{mu:.{nd}f} ({mu - b:+.{nd}f} [{min(d):+.{nd}f}, {max(d):+.{nd}f}])")
                else:
                    d = [val[(c, ld, v, s)][m] - val[(c, ld, "base", s)][m] for s in SEEDS[v]]
                    cell.append(f"{mu:.{nd}f} ({st.mean(d):+.{nd}f} [{min(d):+.{nd}f}, {max(d):+.{nd}f}])")
            md.append(f"| {v} | {c} | {' | '.join(cell)} | {sum(x['deadlock'] for x in xs)} |")
    md.append("")

md += ["## Ranking stability", "",
       "Per seed: ranks of the four controllers (ties share the best rank). 'Same order' = the rank vector equals that on base "
       "for the same seed (ce_rand: per draw, against the ranks of the base means). 'Final first' = the final design has "
       "rank 1 (alone or tied).", "",
       "| Load | Variant | Same order, arrivals | Same order, total delay | Final first, arrivals | Final first, total delay |",
       "|---|---|---|---|---|---|"]


def rank_of(xs, higher):
    return tuple(rankdata([-x if higher else x for x in xs], method="min").astype(int))


def ranks(ld, v, s, m, higher):
    return rank_of([val[(c, ld, v, s)][m] for c in CTRLS], higher)


def base_mean_ranks(ld, m, higher):
    return rank_of([st.mean(val[(c, ld, "base", s)][m] for s in SEEDS["base"]) for c in CTRLS], higher)


for ld in loads:
    for v in VARIANTS:
        n = len(SEEDS[v])
        cells = []
        for m, higher in (("arrived_1800", True), ("total_delay_vh", False)):
            ref = (lambda s: base_mean_ranks(ld, m, higher)) if v in UNPAIRED else (lambda s: ranks(ld, "base", s, m, higher))
            cells.append(sum(ranks(ld, v, s, m, higher) == ref(s) for s in SEEDS[v]))
        firsts = [sum(ranks(ld, v, s, m, h)[CTRLS.index(FINAL)] == 1 for s in SEEDS[v])
                  for m, h in (("arrived_1800", True), ("total_delay_vh", False))]
        md.append(f"| {ld} | {v} | {cells[0]}/{n} | {cells[1]}/{n} | {firsts[0]}/{n} | {firsts[1]}/{n} |")
md += ["", "## E10 (iii): fixed plan under a field-of-view error (change vs base, mean over seeds)", "",
       "| Load | Variant | Arrivals | Total delay, veh·h |", "|---|---|---|---|"]
for ld in loads:
    for v in [v for v in FOV if v in VARIANTS]:
        da = st.mean(val[("Fixed plan", ld, v, s)]["arrived_1800"] - val[("Fixed plan", ld, "base", s)]["arrived_1800"] for s in SEEDS[v])
        dd = st.mean(val[("Fixed plan", ld, v, s)]["total_delay_vh"] - val[("Fixed plan", ld, "base", s)]["total_delay_vh"] for s in SEEDS[v])
        md.append(f"| {ld} | {v} | {da:+.1f} | {dd:+.2f} |")
md += ["", "Problems: " + ("; ".join(problems) if problems else "none")]
out.write_text("\n".join(md) + "\n", encoding="utf-8")
print("\n".join(md))
