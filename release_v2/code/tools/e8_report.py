"""E8 (Comment 1.2): figure and Markdown tables from the outputs of e8_validation.py.

    python revision/tools/e8_report.py --runs revision/runs/e8_validation \
        --observed revision/incoming/2026-10-26/validation/validation_1_2 --cycles 2 12
"""
import argparse
import csv
import statistics as st
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--runs", type=Path, required=True)
ap.add_argument("--observed", type=Path, required=True)
ap.add_argument("--cycles", type=int, nargs=2, default=[2, 12])
args = ap.parse_args()
c0, c1 = args.cycles
APPR = ["SVB_N", "SVB_S", "PRB_E", "PRB_W"]


def rd(p):
    with open(p, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


oq = [r for r in rd(args.observed / "observed_queue.csv") if c0 <= int(r["cycle"]) <= c1]
oh = [r for r in rd(args.observed / "discharge_headways.csv") if c0 <= int(r["cycle"]) <= c1]
sq = rd(args.runs / "sim_queue_discharge.csv")
sh = rd(args.runs / "sim_discharge_headways.csv")
pr = rd(args.runs / "per_run_means.csv")

obs = {a: dict(queue=[int(r["observed_queue"]) for r in oq if r["approach"] == a],
               disc=[int(r["discharged_queue"]) for r in oq if r["approach"] == a],
               hw=[float(r["headway"]) for r in oh if r["approach"] == a and r["saturated"] == "True" and r["headway"]],
               first=[float(r["t_after_green"]) for r in oh if r["approach"] == a and r["position"] == "1"])
       for a in APPR}
sim = {a: dict(queue=[int(r["halting"]) for r in sq if r["approach"] == a],
               disc=[int(r["discharged_queue"]) for r in sq if r["approach"] == a],
               hw=[float(r["headway"]) for r in sh if r["approach"] == a and r["saturated"] == "True" and r["headway"]],
               first=[float(r["t_after_green"]) for r in sh if r["approach"] == a and r["position"] == "1"],
               backlog=[int(r["backlog"]) for r in sq if r["approach"] == a],
               within={d: [int(r[f"halting_within_{d}m"]) for r in sq if r["approach"] == a] for d in (20, 40, 60, 80)})
       for a in APPR}
runs = sorted({r["run"] for r in sq})


def m(xs):
    return st.mean(xs) if xs else float("nan")


def sd(xs):
    return st.stdev(xs) if len(xs) > 1 else 0.0


def runrange(a, key):
    v = [float(r[key]) for r in pr if r["approach"] == a and r[key] not in ("", "None")]
    return f"{min(v):.1f}–{max(v):.1f}"


out = [f"# E8 results: fixed-plan SUMO vs observed video (cycles {c0}–{c1})", "",
       f"Simulation: {len(runs)} runs ({sum(r.startswith('original') for r in runs)} × original demand with SUMO seeds, "
       f"{sum(r.startswith('heldout') for r in runs)} × held-out ×1.0 realizations), field plan shifted to the observed "
       "phase. Observed: Ryzhanskyi's files of 26 Oct 2026. Simulated values pool all runs and cycles; the range of "
       "the run means is given in brackets.", "",
       "## End-of-red queue (vehicles, 1 s before green)", "",
       "| Approach | Observed mean ± SD (min–max) | Simulated mean ± SD [run means] | Difference | Note |",
       "|---|---|---|---|---|"]
note = {"SVB_N": "obs: tail beyond ~25th vehicle not separable", "SVB_S": "obs = lower bound (tail out of view)",
        "PRB_E": "obs: medium confidence", "PRB_W": "obs: low-medium confidence"}
for a in APPR:
    o, s = obs[a]["queue"], sim[a]["queue"]
    out.append(f"| {a} | {m(o):.1f} ± {sd(o):.1f} ({min(o)}–{max(o)}) | {m(s):.1f} ± {sd(s):.1f} [{runrange(a, 'queue_mean')}] "
               f"| {m(s) - m(o):+.1f} ({100 * (m(s) - m(o)) / m(o):+.0f}%) | {note[a]} |")
out += ["", "Simulated queue within a distance of the stop line (mean):", "",
        "| Approach | ≤ 20 m | ≤ 40 m | ≤ 60 m | ≤ 80 m | whole approach (106 m) | waiting for insertion |", "|---|---|---|---|---|---|---|"]
for a in APPR:
    w = sim[a]["within"]
    out.append(f"| {a} | {m(w[20]):.1f} | {m(w[40]):.1f} | {m(w[60]):.1f} | {m(w[80]):.1f} | {m(sim[a]['queue']):.1f} | "
               f"{m(sim[a]['backlog']):.1f} |")
out += ["", "## Discharged queue (vehicles crossing continuously from the green onset)", "",
        "| Approach | Observed mean ± SD | Simulated mean ± SD [run means] | Difference |", "|---|---|---|---|"]
for a in APPR:
    o, s = obs[a]["disc"], sim[a]["disc"]
    out.append(f"| {a} | {m(o):.1f} ± {sd(o):.1f} | {m(s):.1f} ± {sd(s):.1f} [{runrange(a, 'discharged_mean')}] | "
               f"{m(s) - m(o):+.1f} ({100 * (m(s) - m(o)) / m(o):+.0f}%) |")
out += ["", "## Saturation headway per approach (s; from the 4th queued vehicle) and start-up", "",
        "| Approach | Observed median (mean ± SD, n) | Simulated median (mean ± SD, n) [run medians] | Median difference | "
        "Saturation flow obs / sim (veh/h per approach) | First crossing after green, obs / sim (median, s) |",
        "|---|---|---|---|---|---|"]
for a in APPR:
    o, s = obs[a]["hw"], sim[a]["hw"]
    mo, ms = st.median(o), st.median(s)
    out.append(f"| {a} | {mo:.2f} ({m(o):.2f} ± {sd(o):.2f}, {len(o)}) | {ms:.2f} ({m(s):.2f} ± {sd(s):.2f}, {len(s)}) "
               f"[{runrange(a, 'sat_headway_median')}] | {ms - mo:+.2f} ({100 * (ms - mo) / mo:+.0f}%) | "
               f"{3600 / mo:.0f} / {3600 / ms:.0f} | {st.median(obs[a]['first']):.1f} / {st.median(sim[a]['first']):.1f} |")
mae_q = st.mean(abs(m(sim[a]["queue"]) - m(obs[a]["queue"])) for a in APPR if a != "SVB_S")
mae_d = st.mean(abs(m(sim[a]["disc"]) - m(obs[a]["disc"])) for a in APPR)
mape_h = st.mean(abs(st.median(sim[a]["hw"]) - st.median(obs[a]["hw"])) / st.median(obs[a]["hw"]) for a in APPR)
out += ["", "## Summary", "",
        f"- Mean absolute error of the mean end-of-red queue over SVB_N, PRB_E, PRB_W (SVB_S excluded, lower bound): "
        f"{mae_q:.1f} vehicles.",
        f"- Mean absolute error of the mean discharged queue over all four approaches: {mae_d:.1f} vehicles.",
        f"- Mean absolute percentage difference of the median saturation headway: {100 * mape_h:.0f}%."]
(args.runs / "E8_results.md").write_text("\n".join(out) + "\n", encoding="utf-8")
print("\n".join(out))

# figure: three panels, observed vs simulated per approach
fig, axs = plt.subplots(1, 3, figsize=(12, 3.8))
titles = ["(a) End-of-red queue (veh)", "(b) Discharged queue (veh)", "(c) Saturation headway (s)"]
for ax, key, title in zip(axs, ["queue", "disc", "hw"], titles):
    pos_o = [i * 3 + 1 for i in range(4)]
    pos_s = [i * 3 + 2 for i in range(4)]
    bo = ax.boxplot([obs[a][key] for a in APPR], positions=pos_o, widths=0.8, patch_artist=True, showfliers=False)
    bs = ax.boxplot([sim[a][key] for a in APPR], positions=pos_s, widths=0.8, patch_artist=True, showfliers=False)
    for b in bo["boxes"]:
        b.set_facecolor("#9ecae1")
    for b in bs["boxes"]:
        b.set_facecolor("#fdae6b")
    ax.set_xticks([i * 3 + 1.5 for i in range(4)])
    ax.set_xticklabels(["SVB_N", "SVB_S\n(obs. lower bound)" if key == "queue" else "SVB_S", "PRB_E", "PRB_W"], fontsize=8)
    ax.set_title(title, fontsize=10, loc="left")
    ax.grid(axis="y", alpha=0.3)
    if key == "hw":
        ax.set_ylim(0, 5)
fig.legend([bo["boxes"][0], bs["boxes"][0]], ["Observed (video)", "Simulated (SUMO, field plan)"], fontsize=9,
           loc="lower center", ncol=2, frameon=False)
fig.tight_layout(rect=(0, 0.07, 1, 1))
fig.savefig(args.runs / "E8_observed_vs_simulated.png", dpi=300)
print("figure:", args.runs / "E8_observed_vs_simulated.png")
