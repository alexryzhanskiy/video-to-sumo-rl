"""B6 twin calibration: objective, selection and success criterion exactly as frozen in revision/twin/B6_protocol_draft.md
(sections 3-6), applied to the grid JSONs of twin_b6_grid.py.

    python revision/tools/twin_b6_fit.py --grid revision/twin/B6/grid \
        --observed revision/incoming/2026-10-26/validation/validation_1_2 --out revision/twin/B6

Writes <out>/grid_results.csv (every grid point x cycle set: medians/means per approach, errors, J),
<out>/fit_summary.json (theta* per fold, check-half errors against the default vehicle, criterion per fold, outcome)
and, only on success, revision/twin/calibrated_vtype.add.xml (fold A's theta*).
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics as st
from pathlib import Path

APPR = ["SVB_N", "SVB_S", "PRB_E", "PRB_W"]
SETS = {"even": set(range(2, 13, 2)), "odd": set(range(3, 13, 2)), "all": set(range(2, 13))}
FOLDS = {"A": ("even", "odd"), "B": ("odd", "even")}
DEFAULT = (0.0, 1.0, 2.6)
RANGE = (3.0, 1.0, 2.0)                    # grid ranges of startupDelay, tau, accel (tie rule distance)
SU_FACTOR, H_MARGIN_PP, Q_TOL = 0.5, 2.0, 0.5


def observed(folder: Path):
    oq = list(csv.DictReader(open(folder / "observed_queue.csv", encoding="utf-8")))
    oh = list(csv.DictReader(open(folder / "discharge_headways.csv", encoding="utf-8")))
    out = {}
    for name, cyc in SETS.items():
        for a in APPR:
            q = [int(r["discharged_queue"]) for r in oq if r["approach"] == a and int(r["cycle"]) in cyc]
            t1 = [float(r["t_after_green"]) for r in oh if r["approach"] == a and int(r["cycle"]) in cyc and r["position"] == "1"]
            h = [float(r["headway"]) for r in oh if r["approach"] == a and int(r["cycle"]) in cyc
                 and r["saturated"] == "True" and r["headway"]]
            t4 = {(r["cycle"]): float(r["t_after_green"]) for r in oh if r["approach"] == a and int(r["cycle"]) in cyc
                  and r["position"] == "4" and r["in_discharging_queue"] == "True"}
            out[(name, a)] = dict(t1=st.median(t1), h=st.median(h), q=st.mean(q), n_cycles=len(q), n_h=len(h),
                                  lost=st.median(t4.values()) - 4 * st.median(h) if t4 else None)
    return out


def simulated(res: dict):
    out = {}
    for name, cyc in SETS.items():
        for a in APPR:
            cs = [c for r in res["runs"] for c in r["cycles"][a] if c["cycle"] in cyc]
            t1 = [c["t1"] for c in cs if c["t1"] is not None]
            h = [x for c in cs for x in c["sat"]]
            t4 = [c["t4"] for c in cs if c["t4"] is not None]
            out[(name, a)] = dict(t1=st.median(t1), h=st.median(h) if h else float("nan"),
                                  q=st.mean(c["discharged"] for c in cs), n_cycles=len(cs), n_h=len(h),
                                  lost=st.median(t4) - 4 * st.median(h) if t4 and h else None)
    return out


def errors(sim, obs, name):
    e_su = st.mean(abs(sim[(name, a)]["t1"] - obs[(name, a)]["t1"]) for a in APPR)
    e_h = 100 * st.mean(abs(sim[(name, a)]["h"] - obs[(name, a)]["h"]) / obs[(name, a)]["h"] for a in APPR)
    e_q = st.mean(abs(sim[(name, a)]["q"] - obs[(name, a)]["q"]) for a in APPR)
    J = (st.mean(((sim[(name, a)]["t1"] - obs[(name, a)]["t1"]) / obs[(name, a)]["t1"]) ** 2 for a in APPR)
         + st.mean(((sim[(name, a)]["h"] - obs[(name, a)]["h"]) / obs[(name, a)]["h"]) ** 2 for a in APPR)
         + st.mean(((sim[(name, a)]["q"] - obs[(name, a)]["q"]) / obs[(name, a)]["q"]) ** 2 for a in APPR)) / 3
    return dict(E_su=e_su, E_h_pp=e_h, E_q=e_q, J=J)


def select(table, name):
    """argmin J; among J <= 1.01 J_min the point closest to the default (range-normalized), then smaller
    startupDelay, smaller tau, larger accel."""
    jmin = min(r[name]["J"] for r in table.values())
    near = [k for k, r in table.items() if r[name]["J"] <= 1.01 * jmin]
    dist = lambda k: sum(((k[i] - DEFAULT[i]) / RANGE[i]) ** 2 for i in range(3))   # noqa: E731
    return min(near, key=lambda k: (round(dist(k), 12), k[0], k[1], -k[2])), jmin, len(near)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--grid", type=Path, required=True)
    ap.add_argument("--observed", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--vtype-out", type=Path, default=Path("revision/twin/calibrated_vtype.add.xml"))
    ap.add_argument("--expect", type=int, default=858, help="number of grid points required")
    a = ap.parse_args()
    obs = observed(a.observed)
    files = sorted(a.grid.glob("sd*.json"))
    if len(files) != a.expect:
        raise SystemExit(f"{len(files)} grid points found, {a.expect} expected")
    table, sims, rows = {}, {}, []
    for f in files:
        res = json.loads(f.read_text(encoding="utf-8"))
        p = res["point"]
        k = (p["startupDelay"], p["tau"], p["accel"])
        sim = simulated(res)
        sims[k] = sim
        table[k] = {name: errors(sim, obs, name) for name in SETS}
        for name in SETS:
            row = dict(startupDelay=k[0], tau=k[1], accel=k[2], cycles=name, **{x: round(v, 6) for x, v in table[k][name].items()})
            for ap_ in APPR:
                for m in ("t1", "h", "q", "lost"):
                    v = sim[(name, ap_)][m]
                    row[f"{ap_}_{m}"] = None if v is None else round(v, 4)
            rows.append(row)
    if DEFAULT not in table:
        raise SystemExit("default point missing")
    a.out.mkdir(parents=True, exist_ok=True)
    with open(a.out / "grid_results.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    summ = dict(n_points=len(table), criterion=dict(start_up=f"E_su(theta*) <= {SU_FACTOR} x E_su(theta0)",
                                                    headway=f"E_h(theta*) <= E_h(theta0) - {H_MARGIN_PP} pp",
                                                    queue=f"E_q(theta*) <= E_q(theta0) + {Q_TOL} veh"),
                observed={f"{n}:{ap_}": obs[(n, ap_)] for n in SETS for ap_ in APPR}, folds={})
    ok_all = True
    for fold, (fit, chk) in FOLDS.items():
        th, jmin, n_near = select(table, fit)
        e0, e1 = table[DEFAULT][chk], table[th][chk]
        crit = dict(start_up=e1["E_su"] <= SU_FACTOR * e0["E_su"], headway=e1["E_h_pp"] <= e0["E_h_pp"] - H_MARGIN_PP,
                    queue=e1["E_q"] <= e0["E_q"] + Q_TOL)
        ok_all &= all(crit.values())
        summ["folds"][fold] = dict(fit_cycles=fit, check_cycles=chk, theta_star=dict(zip(("startupDelay", "tau", "accel"), th)),
                                   J_fit_min=jmin, points_within_1pct=n_near, fit_errors_theta_star=table[th][fit],
                                   check_errors_default=e0, check_errors_theta_star=e1, criterion=crit,
                                   passed=all(crit.values()),
                                   check_by_approach={ap_: dict(obs=obs[(chk, ap_)], default=sims[DEFAULT][(chk, ap_)],
                                                                theta_star=sims[th][(chk, ap_)]) for ap_ in APPR})
    th_all, _, _ = select(table, "all")
    summ["all_cycles_fit"] = dict(theta_star=dict(zip(("startupDelay", "tau", "accel"), th_all)),
                                  errors=table[th_all]["all"], default_errors=table[DEFAULT]["all"])
    summ["success"] = ok_all
    adopted = summ["folds"]["A"]["theta_star"]
    summ["adopted"] = adopted if ok_all else None
    if ok_all:
        a.vtype_out.parent.mkdir(parents=True, exist_ok=True)
        a.vtype_out.write_text(
            "<!-- B6 calibrated vehicle type (fold A theta*, protocol revision/twin/B6_protocol_draft.md).\n"
            "     Load as an additional file in every SUMO run (-a / --additional-files); route files define no vType. -->\n"
            f'<additional>\n    <vType id="DEFAULT_VEHTYPE" startupDelay="{adopted["startupDelay"]}" tau="{adopted["tau"]}" '
            f'accel="{adopted["accel"]}"/>\n</additional>\n', encoding="utf-8")
    (a.out / "fit_summary.json").write_text(json.dumps(summ, indent=1, default=str), encoding="utf-8")
    for fold, f in summ["folds"].items():
        print(f"fold {fold}: theta* {f['theta_star']}  check {f['check_cycles']}: E_su {f['check_errors_default']['E_su']:.2f}"
              f" -> {f['check_errors_theta_star']['E_su']:.2f} s, E_h {f['check_errors_default']['E_h_pp']:.1f} -> "
              f"{f['check_errors_theta_star']['E_h_pp']:.1f} pp, E_q {f['check_errors_default']['E_q']:.2f} -> "
              f"{f['check_errors_theta_star']['E_q']:.2f} veh; criterion {f['criterion']}")
    print("all-cycles fit:", summ["all_cycles_fit"]["theta_star"], "| SUCCESS" if ok_all else "| NOT MET")


if __name__ == "__main__":
    main()
