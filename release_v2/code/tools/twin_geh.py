"""GEH recomputed with a stated definition (K15, Comments 1.1/1.2/2.5).

Observed C: the 5-min turning counts per movement in sumo/turn_counts_edges.xml (the pipeline counts that routeSampler
used to build the demand), as hourly equivalents 12 N. Simulated M: vehicles of movement i->j that cross the stop line
(leave the approach edge into the junction, E8 TraCI odometer extraction, interpolated crossing time) within the same
interval, as hourly equivalents. GEH = sqrt(2 (M - C)^2 / (M + C)); a cell with M = C = 0 has GEH 0.

Cells: 12 movements x 5 intervals over 0-1500 s = 60 cells; "48 cells" = the same without the first interval (0-300 s,
network filling). Primary statistic: GEH per cell of the run-mean M; also every run x cell value. Runs as in E8:
original demand with SUMO seeds 1-5 and the ten held-out x1.0 realizations (seed 1). Two signal programs: the
network's own fixed plan ("real", offset 0) and the field-phased plan of E8 (offset 16). Also written: the
departure-interval consistency of the route files (vehicles per relation by planned departure interval), which needs
no simulation and shows what routeSampler reproduces by construction.

    revision/.venv-resco/Scripts/python.exe revision/tools/twin_geh.py --out revision/twin/GEH
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import math
import os
import statistics as st
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NAMES = {"nN_nC": "SVB_N", "nS_nC": "SVB_S", "nE_nC": "PRB_E", "nW_nC": "PRB_W"}
END = 1500.0

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--out", type=Path, required=True)
ap.add_argument("--counts", type=Path, default=ROOT / "sumo" / "turn_counts_edges.xml")
ap.add_argument("--vtype", type=Path, help="additional vType file (calibrated twin)")
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
PLANS = {"real": [], "field16": [ROOT / "revision" / "runs" / "e8_validation" / "tls_offset_16.add.xml"]}

obs, ivals = {}, []
for iv in ET.parse(args.counts).getroot().iter("interval"):
    b, e = float(iv.get("begin")), float(iv.get("end"))
    ivals.append((b, e))
    for r in iv.iter("edgeRelation"):
        obs[(b, r.get("from"), r.get("to"))] = int(r.get("count"))
MOVS = sorted({(f, t) for _, f, t in obs})
assert len(MOVS) == 12 and len(ivals) == 5, (len(MOVS), ivals)


def geh(m, c):
    return 0.0 if m + c == 0 else math.sqrt(2 * (m - c) ** 2 / (m + c))


def ival_of(t):
    for b, e in ivals:
        if b <= t < e:
            return b
    return None


def depart_counts(route):
    n = {}
    for v in ET.parse(route).getroot().iter("vehicle"):
        b = ival_of(float(v.get("depart")))
        f, t = v.find("route").get("edges").split()
        if b is not None:
            n[(b, f, t)] = n.get((b, f, t), 0) + 1
    return n


def crossings(route, seed, adds):
    cmd = ["sumo", "-n", str(NET), "-r", str(route), "--begin", "0", "--end", str(END), "--seed", str(seed),
           "--time-to-teleport", "-1", "--no-step-log", "true", "--no-warnings", "true", "--duration-log.disable", "true"]
    if adds:
        cmd += ["-a", ",".join(map(str, adds))]
    traci.start(cmd)
    lanes = {e: [f"{e}_{i}" for i in range(3)] for e in NAMES}
    length = {e: traci.lane.getLength(lanes[e][0]) for e in NAMES}
    exit_of, last, n = {}, {}, {}
    while traci.simulation.getTime() < END:
        traci.simulationStep()
        t = traci.simulation.getTime()
        cur = {}
        for e, ls in lanes.items():
            for ln in ls:
                for vid in traci.lane.getLastStepVehicleIDs(ln):
                    if vid not in exit_of:
                        exit_of[vid] = traci.vehicle.getRoute(vid)[-1]
                    cur[vid] = (t, traci.vehicle.getDistance(vid), traci.vehicle.getLanePosition(vid), e)
        alive = None
        for vid, (t0, odo0, pos0, e) in last.items():
            if vid in cur:
                continue
            if alive is None:
                alive = set(traci.vehicle.getIDList())
            if vid in alive:
                odo1 = traci.vehicle.getDistance(vid)
                frac = (length[e] - pos0) / (odo1 - odo0) if odo1 > odo0 else 1.0
                b = ival_of(t0 + min(max(frac, 0.0), 1.0) * (t - t0))
                if b is not None:
                    n[(b, e, exit_of[vid])] = n.get((b, e, exit_of[vid]), 0) + 1
        last = cur
    traci.close()
    return n


cells, dep_rows = [], []
for lab, route, seed in RUNS:
    run_id = f"{lab}:{route.stem}:seed{seed}"
    if seed == 1:
        d = depart_counts(route)
        for b, _ in ivals:
            for f, t in MOVS:
                dep_rows.append(dict(route=route.name, interval_begin=b, movement=f"{NAMES[f]}->{t}", obs=obs[(b, f, t)],
                                     departed=d.get((b, f, t), 0), geh=round(geh(12 * d.get((b, f, t), 0), 12 * obs[(b, f, t)]), 4)))
    for plan, adds in PLANS.items():
        n = crossings(route, seed, adds + ([args.vtype.resolve()] if args.vtype else []))
        for b, _ in ivals:
            for f, t in MOVS:
                m, c = n.get((b, f, t), 0), obs[(b, f, t)]
                cells.append(dict(plan=plan, run=run_id, set=lab, interval_begin=b, movement=f"{NAMES[f]}->{t}", obs=c,
                                  sim=m, geh=round(geh(12 * m, 12 * c), 4)))
        print(run_id, plan, "done", flush=True)

for name, rows in (("geh_cells_by_run.csv", cells), ("geh_departure_consistency.csv", dep_rows)):
    with open(args.out / name, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def stats(vals):
    return dict(n=len(vals), mean=st.mean(vals), sd=st.stdev(vals), median=st.median(vals), max=max(vals),
                share_lt5=sum(v < 5 for v in vals) / len(vals))


summ, mean_rows = {}, []
for plan in PLANS:
    for sset in ("original", "heldout", "all"):
        rs = [r for r in cells if r["plan"] == plan and (sset == "all" or r["set"] == sset)]
        for cs_name, first in (("60_cells", 0.0), ("48_cells", 300.0)):
            rr = [r for r in rs if r["interval_begin"] >= first]
            keyed = {}
            for r in rr:
                keyed.setdefault((r["interval_begin"], r["movement"]), []).append(r)
            per_cell = []
            for (b, mv), lst in sorted(keyed.items()):
                m_bar, c = st.mean(r["sim"] for r in lst), lst[0]["obs"]
                per_cell.append(geh(12 * m_bar, 12 * c))
                if sset == "all" or (sset == "original" and plan == "real"):
                    mean_rows.append(dict(plan=plan, runs=sset, cells=cs_name, interval_begin=b, movement=mv, obs=c,
                                          sim_mean=round(m_bar, 3), geh_of_mean=round(per_cell[-1], 4)))
            summ[f"{plan}|{sset}|{cs_name}"] = dict(geh_of_run_mean=stats(per_cell), geh_every_run_cell=stats([r["geh"] for r in rr]),
                                                   runs=len({r["run"] for r in rr}))
dep = [r["geh"] for r in dep_rows]
summ["departure_consistency"] = dict(stats(dep), files=len({r["route"] for r in dep_rows}),
                                     exact_cells=sum(r["obs"] == r["departed"] for r in dep_rows))
with open(args.out / "geh_cells_run_mean.csv", "w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=list(mean_rows[0]))
    w.writeheader()
    w.writerows(mean_rows)
(args.out / "summary.json").write_text(json.dumps(dict(counts=str(args.counts), vtype=str(args.vtype) if args.vtype else None,
                                                       end=END, summary=summ), indent=1), encoding="utf-8")
lines = ["| Signal plan | Runs | Cells | GEH of run-mean flow: mean ± SD | max | share < 5 | every run × cell: mean ± SD | share < 5 |",
         "|---|---|---|---|---|---|---|---|"]
for k, v in summ.items():
    if k == "departure_consistency":
        continue
    plan, sset, cs = k.split("|")
    a, b = v["geh_of_run_mean"], v["geh_every_run_cell"]
    lines.append(f"| {plan} | {sset} ({v['runs']}) | {a['n']} | {a['mean']:.2f} ± {a['sd']:.2f} | {a['max']:.2f} | "
                 f"{100 * a['share_lt5']:.0f}% | {b['mean']:.2f} ± {b['sd']:.2f} | {100 * b['share_lt5']:.1f}% |")
dc = summ["departure_consistency"]
lines += ["", f"Departure-interval consistency of the route files ({dc['files']} files, {dc['n']} cells): "
              f"{dc['exact_cells']} cells exactly equal to the counts; GEH mean {dc['mean']:.2f}, max {dc['max']:.2f}."]
(args.out / "GEH.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
print("\n".join(lines))
