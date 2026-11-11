"""Tidy data for the two Supporting Information figures of the twin (kb/figures/04_FIGURE_INVENTORY.md, SI table):
twin validation (E8, current twin) and twin calibration (B6). The lead renders them with drl_style.py; this script only
collects the plotted values from recorded files (no fitting, no re-estimation).

Point estimates are the ones the analyses use: queues as means, start-up time t1 and saturated headway h as medians.
Intervals:
  - queues: 95% t interval of the mean; observed over cycles (n = 11), simulated over run means (n = 15);
  - t1 and h: interquartile range (25th-75th percentile) of the pooled values (cycles, or headways).
Observed: Ryzhanskyi's files (26 Oct: discharge_headways.csv, observed_queue.csv; 28 Oct: 1.2_observed_queues.csv),
cycles 2-12. Simulated: E8 runs (sumo/demand.rou.xml seeds 1-5 + held-out x1.0 files 1001-1010, seed 1) for the
validation figure; B6 calibration runs (seeds 1-5 + train 3001-3010, seed 1) for the calibration figure.

    revision/.venv/Scripts/python.exe -I revision/tools/twin_figure_data.py --out revision/twin/figure_data
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics as st
from pathlib import Path

import numpy as np
from scipy import stats

ROOT = Path(__file__).resolve().parents[2]
APPR = ["SVB_N", "SVB_S", "PRB_E", "PRB_W"]
CYC = range(2, 13)
OBS26 = ROOT / "revision/incoming/2026-10-26/validation/validation_1_2"
OBS28 = ROOT / "revision/incoming/2026-10-28/answers/step_1.2_1.3/1.2_observed_queues.csv"
CAP = {"SVB_N": 9, "SVB_S": 5, "PRB_E": None, "PRB_W": None}
HEAD = ["figure", "panel", "quantity", "unit", "approach", "source", "estimate_type", "estimate", "interval_type",
        "lo", "hi", "n", "n_unit"]


def rd(p):
    return list(csv.DictReader(open(p, encoding="utf-8")))


def mean_t(x):
    x = np.asarray(x, float)
    m, h = x.mean(), stats.t.ppf(0.975, len(x) - 1) * x.std(ddof=1) / np.sqrt(len(x))
    return m, m - h, m + h


def med_iqr(x):
    x = np.asarray(x, float)
    return np.median(x), np.percentile(x, 25), np.percentile(x, 75)


def row(fig, panel, q, unit, ap, src, kind, vals, n_unit):
    est, lo, hi = mean_t(vals) if kind == "mean" else med_iqr(vals)
    return dict(figure=fig, panel=panel, quantity=q, unit=unit, approach=ap, source=src, estimate_type=kind,
                estimate=round(float(est), 3), interval_type="95% t interval of the mean" if kind == "mean" else
                "interquartile range", lo=round(float(lo), 3), hi=round(float(hi), 3), n=len(vals), n_unit=n_unit)


def observed():
    oh = [r for r in rd(OBS26 / "discharge_headways.csv") if int(r["cycle"]) in CYC]
    oq = [r for r in rd(OBS26 / "observed_queue.csv") if int(r["cycle"]) in CYC]
    o28 = [r for r in rd(OBS28) if int(r["cycle"]) in CYC]
    out = {}
    for a in APPR:
        out[a] = dict(t1=[float(r["t_after_green"]) for r in oh if r["approach"] == a and r["position"] == "1"],
                      h=[float(r["headway"]) for r in oh if r["approach"] == a and r["saturated"] == "True" and r["headway"]],
                      q=[int(r["discharged_queue"]) for r in oq if r["approach"] == a],
                      eor=[int(r["queue_veh"]) for r in o28 if r["approach"] == a])
    return out


def e8_sim():
    lc = rd(ROOT / "revision/twin/E8_lanecap/default/sim_queue_lanecap.csv")
    sh = [r for r in rd(ROOT / "revision/runs/e8_validation/sim_discharge_headways.csv") if int(r["cycle"]) in CYC]
    out = {}
    for a in APPR:
        runs = sorted({r["run"] for r in lc})
        out[a] = dict(eor=[st.mean(int(r["queue_capped"]) for r in lc if r["run"] == u and r["approach"] == a) for u in runs],
                      q=[st.mean(int(r["discharged_queue"]) for r in lc if r["run"] == u and r["approach"] == a) for u in runs],
                      t1=[float(r["t_after_green"]) for r in sh if r["approach"] == a and r["position"] == "1"],
                      h=[float(r["headway"]) for r in sh if r["approach"] == a and r["saturated"] == "True" and r["headway"]])
    return out


def b6_sim(pid):
    res = json.loads((ROOT / "revision/twin/B6/grid" / f"{pid}.json").read_text(encoding="utf-8"))
    out = {}
    for a in APPR:
        cs = [[c for c in r["cycles"][a] if c["cycle"] in CYC] for r in res["runs"]]
        out[a] = dict(t1=[c["t1"] for run in cs for c in run if c["t1"] is not None],
                      h=[x for run in cs for c in run for x in c["sat"]],
                      q=[st.mean(c["discharged"] for c in run) for run in cs])
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    obs = observed()

    # twin validation (E8, current twin)
    sim, rows = e8_sim(), []
    spec = [("a", "eor", "end-of-red queue (visible cap)", "veh", "mean"), ("b", "q", "discharged queue", "veh", "mean"),
            ("c", "h", "saturated headway", "s", "median"), ("d", "t1", "start-up time to first crossing", "s", "median")]
    for panel, k, q, unit, kind in spec:
        for ap_ in APPR:
            rows.append(row("SI_twin_validation", panel, q, unit, ap_, "observed", kind, obs[ap_][k],
                            "cycles" if k in ("eor", "q", "t1") else "headways"))
            rows.append(row("SI_twin_validation", panel, q, unit, ap_, "simulated_default", kind, sim[ap_][k],
                            "run means" if kind == "mean" else ("cycles" if k == "t1" else "headways")))
    write(a.out / "SI_twin_validation_data.csv", rows)

    # twin calibration (B6)
    fit = json.loads((ROOT / "revision/twin/B6/fit_summary.json").read_text(encoding="utf-8"))
    th = fit["folds"]["A"]["theta_star"]
    pid_t = f"sd{th['startupDelay']:.2f}_tau{th['tau']:.1f}_acc{th['accel']:.1f}"
    sims = {"simulated_default": b6_sim("sd0.00_tau1.0_acc2.6"), "simulated_theta_star_A": b6_sim(pid_t)}
    rows = []
    for panel, k, q, unit, kind in [("a", "t1", "start-up time to first crossing", "s", "median"),
                                    ("b", "h", "saturated headway", "s", "median"), ("c", "q", "discharged queue", "veh", "mean")]:
        for ap_ in APPR:
            rows.append(row("SI_twin_calibration", panel, q, unit, ap_, "observed", kind, obs[ap_][k],
                            "headways" if k == "h" else "cycles"))
            for src, s in sims.items():
                rows.append(row("SI_twin_calibration", panel, q, unit, ap_, src, kind, s[ap_][k],
                                "run means" if kind == "mean" else ("headways" if k == "h" else "cycles")))
    crit = []
    for fold, f in fit["folds"].items():
        e0, e1 = f["check_errors_default"], f["check_errors_theta_star"]
        for key, q, unit, thr in (("E_su", "start-up error", "s", 0.5 * e0["E_su"]),
                                  ("E_h_pp", "headway error", "percentage points", e0["E_h_pp"] - 2.0),
                                  ("E_q", "queue error", "veh", e0["E_q"] + 0.5)):
            for src, e in (("simulated_default", e0), ("simulated_theta_star", e1)):
                crit.append(dict(figure="SI_twin_calibration", panel="d", fold=fold, check_cycles=f["check_cycles"],
                                 quantity=q, unit=unit, source=src, estimate=round(e[key], 3),
                                 criterion_limit=round(thr, 3), passes=e[key] <= thr if src != "simulated_default" else ""))
    write(a.out / "SI_twin_calibration_data.csv", rows)
    with open(a.out / "SI_twin_calibration_criterion.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(crit[0]))
        w.writeheader()
        w.writerows(crit)
    print(f"wrote {a.out}; theta*A = {pid_t}")


def write(p, rows):
    with open(p, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=HEAD)
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    main()
