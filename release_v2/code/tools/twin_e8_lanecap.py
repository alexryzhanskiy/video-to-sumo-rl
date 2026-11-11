"""E8 rerun with a per-lane visible cap (Comment 1.2): the end-of-red queue that the camera can see.

Ryzhanskyi (answers of 28 Oct) sees the end of the queue on PRB_E and PRB_W, but only about 9 vehicles per lane on
SVB_N and about 5 per lane on SVB_S. The simulated queue is therefore counted per lane, keeping the halting vehicles
(speed < 0.1 m/s, 1 s before green) with rank <= cap from the stop line: SVB_N 9, SVB_S 5 per lane, PRB_E and PRB_W
uncapped. Everything else is e8_validation.py: field plan shifted to the observed phase (Svobody green at 16 s), the
same 15 runs (original demand with SUMO seeds 1-5, held-out x1.0 files 1001-1010 with seed 1), cycles 2-12, the same
discharge rules. --vtype adds a vehicle-type file (the B6 calibrated twin). Runs through libsumo if available.

    revision/.venv-resco/Scripts/python.exe revision/tools/twin_e8_lanecap.py --out revision/twin/E8_lanecap/default
    revision/.venv-resco/Scripts/python.exe revision/tools/twin_e8_lanecap.py --vtype revision/twin/calibrated_vtype.add.xml \
        --out revision/twin/E8_lanecap/calibrated

Gate: with the default vehicle, the uncapped halting counts and the discharged queues must equal
revision/runs/e8_validation/sim_queue_discharge.csv for every run and cycle (reported in summary.json).
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import statistics as st
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APPR = {"SVB_N": "nN_nC", "SVB_S": "nS_nC", "PRB_E": "nE_nC", "PRB_W": "nW_nC"}
GROUP = {"SVB_N": "SVB", "SVB_S": "SVB", "PRB_E": "PRB", "PRB_W": "PRB"}
WINDOW = {"SVB": 49.0, "PRB": 33.0}
FIRST = {"SVB": 16.0, "PRB": 84.0}
CAP = {"SVB_N": 9, "SVB_S": 5, "PRB_E": None, "PRB_W": None}
LEAD, HALT, END, CYC = 1.0, 0.1, 1500.0, (2, 12)
GAP_SPLIT, FIRST_MAX = 8.0, 8.0

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--out", type=Path, required=True)
ap.add_argument("--vtype", type=Path, help="additional vType file (calibrated twin)")
ap.add_argument("--e8", type=Path, default=ROOT / "revision" / "runs" / "e8_validation")
ap.add_argument("--observed", type=Path, default=ROOT / "revision" / "incoming" / "2026-10-28" / "answers" / "step_1.2_1.3")
ap.add_argument("--observed26", type=Path, default=ROOT / "revision" / "incoming" / "2026-10-26" / "validation" / "validation_1_2")
args = ap.parse_args()
if not os.environ.get("SUMO_HOME"):
    import sumo
    os.environ["SUMO_HOME"] = sumo.SUMO_HOME
sys.path.append(str(Path(os.environ["SUMO_HOME"]) / "tools"))
try:
    import libsumo as traci
except ImportError:
    import traci
args.out.mkdir(parents=True, exist_ok=True)
NET = ROOT / "sumo" / "intersection.net.xml"
RUNS = [("original", ROOT / "sumo" / "demand.rou.xml", s) for s in (1, 2, 3, 4, 5)] + \
       [("heldout", Path(f), 1) for f in sorted(glob.glob(str(ROOT / "revision/demand/heldout/x10/heldout_x10_s*.rou.xml")))]
tls = args.e8 / "tls_offset_16.add.xml"
adds = [tls] + ([args.vtype.resolve()] if args.vtype else [])
onsets = {g: [FIRST[g] + 120 * k for k in range(12)] for g in FIRST}
snap_t = {on - LEAD for g in onsets for on in onsets[g]}


def discharge(ts, onset, window):
    prev, pos, in_q, n_q, first = None, 0, True, 0, None
    for tc in sorted(x for x in ts if onset <= x < onset + window):
        if prev is None:
            pos, in_q, first = 1, (tc - onset) <= FIRST_MAX, tc - onset
        else:
            pos += 1
            if tc - prev > GAP_SPLIT:
                in_q = False
        n_q += int(in_q)
        prev = tc
    return n_q, first


rows = []
for lab, route, seed in RUNS:
    traci.start(["sumo", "-n", str(NET), "-r", str(route), "-a", ",".join(map(str, adds)), "--begin", "0", "--end",
                 str(END), "--seed", str(seed), "--time-to-teleport", "-1", "--no-step-log", "true", "--no-warnings",
                 "true", "--duration-log.disable", "true"])
    lanes = {a: [f"{e}_{i}" for i in range(3)] for a, e in APPR.items()}
    length = traci.lane.getLength(lanes["SVB_N"][0])
    last, cross, snaps, rises, prev_g = {}, {a: [] for a in APPR}, {}, {"SVB": [], "PRB": []}, {"SVB": None, "PRB": None}
    while traci.simulation.getTime() < END:
        traci.simulationStep()
        t = traci.simulation.getTime()
        s = traci.trafficlight.getRedYellowGreenState("nC")
        for g, i in (("SVB", 1), ("PRB", 5)):
            on = s[i] in "Gg"
            if on and prev_g[g] is False:
                rises[g].append(t - 1)
            prev_g[g] = on
        cur, snap = {}, {}
        for a, ls in lanes.items():
            per_lane = []
            for li, ln in enumerate(ls):
                d = []
                for vid in traci.lane.getLastStepVehicleIDs(ln):
                    pos = traci.vehicle.getLanePosition(vid)
                    cur[vid] = (t, traci.vehicle.getDistance(vid), pos, a)
                    if t in snap_t and traci.vehicle.getSpeed(vid) < HALT:
                        d.append(length - pos)
                per_lane.append(sorted(d))
            snap[a] = per_lane
        if t in snap_t:
            snaps[t] = snap
        alive = None
        for vid, (t0, odo0, pos0, a) in last.items():
            if vid in cur:
                continue
            if alive is None:
                alive = set(traci.vehicle.getIDList())
            if vid in alive:
                odo1 = traci.vehicle.getDistance(vid)
                frac = (length - pos0) / (odo1 - odo0) if odo1 > odo0 else 1.0
                cross[a].append(t0 + min(max(frac, 0.0), 1.0) * (t - t0))
        last = cur
    traci.close()
    assert all(rises[g][:12] == onsets[g] for g in rises), rises
    run_id = f"{lab}:{route.stem}:seed{seed}"
    for a, g in GROUP.items():
        for k, on in enumerate(onsets[g], 1):
            if not CYC[0] <= k <= CYC[1] or on + WINDOW[g] > END:
                continue
            pl = snaps[on - LEAD][a]
            cap = CAP[a]
            n_q, first = discharge(cross[a], on, WINDOW[g])
            rows.append(dict(run=run_id, set=lab, cycle=k, approach=a, green_onset=on, halting=sum(map(len, pl)),
                             halting_lane0=len(pl[0]), halting_lane1=len(pl[1]), halting_lane2=len(pl[2]),
                             cap_per_lane=cap if cap else "", queue_capped=sum(min(len(x), cap) if cap else len(x) for x in pl),
                             dist_last_capped_m=round(max((x[min(len(x), cap) - 1] if cap else x[-1]) for x in pl if x), 1)
                             if any(pl) else 0.0, discharged_queue=n_q, first_crossing=round(first, 3) if first is not None else ""))
    print(run_id, "done", flush=True)

with open(args.out / "sim_queue_lanecap.csv", "w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)

# gate against E8 (default vehicle only)
e8 = {(r["run"], r["approach"], int(r["cycle"])): r for r in csv.DictReader(open(args.e8 / "sim_queue_discharge.csv", encoding="utf-8"))}
mism = [(r["run"], r["approach"], r["cycle"]) for r in rows
        if (k := (r["run"], r["approach"], r["cycle"])) in e8 and
        (int(e8[k]["halting"]) != r["halting"] or int(e8[k]["discharged_queue"]) != r["discharged_queue"])]
gate = dict(compared=sum((r["run"], r["approach"], r["cycle"]) in e8 for r in rows), mismatches=len(mism), examples=mism[:5])

# comparison with the observed end-of-red queues (28 Oct file, identical counts to 26 Oct) and discharged queues
obs = [r for r in csv.DictReader(open(args.observed / "1.2_observed_queues.csv", encoding="utf-8")) if CYC[0] <= int(r["cycle"]) <= CYC[1]]
obs26 = [r for r in csv.DictReader(open(args.observed26 / "observed_queue.csv", encoding="utf-8")) if CYC[0] <= int(r["cycle"]) <= CYC[1]]
summ, lines = {}, ["| Approach | Cap per lane | Observed queue, mean ± SD (n) | Simulated, capped, mean ± SD (n) | Difference | "
                   "Simulated, uncapped | Observed discharged queue | Simulated discharged queue |", "|---|---|---|---|---|---|---|---|"]
for a in APPR:
    o = [int(r["queue_veh"]) for r in obs if r["approach"] == a]
    od = [int(r["discharged_queue"]) for r in obs26 if r["approach"] == a]
    sc = [r["queue_capped"] for r in rows if r["approach"] == a]
    su = [r["halting"] for r in rows if r["approach"] == a]
    sd = [r["discharged_queue"] for r in rows if r["approach"] == a]
    summ[a] = dict(cap=CAP[a], obs_mean=st.mean(o), obs_sd=st.stdev(o), obs_n=len(o), sim_capped_mean=st.mean(sc),
                   sim_capped_sd=st.stdev(sc), sim_n=len(sc), diff=st.mean(sc) - st.mean(o),
                   diff_pct=100 * (st.mean(sc) - st.mean(o)) / st.mean(o), sim_uncapped_mean=st.mean(su),
                   obs_discharged_mean=st.mean(od), sim_discharged_mean=st.mean(sd),
                   beyond_view=sorted({r["queue_beyond_view"] for r in obs if r["approach"] == a}))
    s = summ[a]
    lines.append(f"| {a} | {CAP[a] or 'none'} | {s['obs_mean']:.1f} ± {s['obs_sd']:.1f} ({s['obs_n']}) | "
                 f"{s['sim_capped_mean']:.1f} ± {s['sim_capped_sd']:.1f} ({s['sim_n']}) | {s['diff']:+.1f} ({s['diff_pct']:+.0f}%) | "
                 f"{s['sim_uncapped_mean']:.1f} | {s['obs_discharged_mean']:.1f} | {s['sim_discharged_mean']:.1f} |")
mae = st.mean(abs(summ[a]["diff"]) for a in APPR)
mae_d = st.mean(abs(summ[a]["sim_discharged_mean"] - summ[a]["obs_discharged_mean"]) for a in APPR)
lines += ["", f"MAE of the mean end-of-red queue over all four approaches (capped): {mae:.2f} vehicles; "
              f"MAE of the mean discharged queue: {mae_d:.2f} vehicles."]
meta = dict(vtype=str(args.vtype) if args.vtype else None, runs=[f"{l}:{Path(r).name}:seed{s}" for l, r, s in RUNS],
            caps=CAP, cycles=CYC, gate_vs_e8=gate, summary=summ, mae_queue_capped=mae, mae_discharged=mae_d,
            sumo=traci.getVersion()[1] if hasattr(traci, "getVersion") else "")
(args.out / "summary.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
(args.out / "E8_lanecap.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
print("\n".join(lines))
print("gate vs E8:", gate)
