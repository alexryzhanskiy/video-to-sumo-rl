"""B6 twin calibration (protocol: revision/twin/B6_protocol_draft.md, frozen 29 Oct 2026): run the fixed-plan twin for
every grid point of (startupDelay, tau, accel) and store, per run, approach and cycle, the E8 discharge quantities.

Measurement = the E8 TraCI extraction (revision/tools/e8_validation.py), run through libsumo: every step, the vehicles
on the 3 lanes of each approach; a vehicle that has left the approach lanes crossed the stop line at
t0 + (lane length - pos0) / (odometer1 - odometer0) x (t - t0); green onsets = TraCI time of the first green state of
the street's through link minus 1 s. (The protocol's first choice, instantInductionLoop detectors, failed its gate on
29 Oct: their time base is one step earlier and their interpolation differs by about 0.02 s; see
revision/twin/B6/gate_detectors_laptop/gate_e8.json. The protocol prescribes this fallback.)

Self-contained (standard library + SUMO 1.26.0 with libsumo), so the same file runs on the laptop and on Colab.

    python twin_b6_grid.py gate --kit <folder> --e8 revision/runs/e8_validation --out <folder>
    python twin_b6_grid.py run  --kit <folder> --out <results folder> [--jobs N] [--only-default]

<kit> holds intersection.net.xml, demand.rou.xml and train_x10_s3001..s3010.rou.xml (copies of the repository's
sumo/ and revision/demand/train/x10/ files). One JSON per grid point is written atomically to <out>; a restart skips
the points already there.
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import platform
import shutil
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from multiprocessing import Pool
from pathlib import Path

APPR = {"SVB_N": "nN_nC", "SVB_S": "nS_nC", "PRB_E": "nE_nC", "PRB_W": "nW_nC"}
GROUP = {"SVB_N": "SVB", "SVB_S": "SVB", "PRB_E": "PRB", "PRB_W": "PRB"}
WINDOW = {"SVB": 49.0, "PRB": 33.0}
THROUGH_LINK = {"SVB": 1, "PRB": 5}
END, OFFSET = 1500.0, 16
SAT_FROM, GAP_SPLIT, FIRST_MAX = 4, 8.0, 8.0
GRID = dict(startupDelay=[round(0.25 * i, 2) for i in range(13)],          # 0, 0.25, ..., 3.0
            tau=[round(1.0 + 0.1 * i, 1) for i in range(11)],                 # 1.0, 1.1, ..., 2.0
            accel=[1.0, 1.4, 1.8, 2.2, 2.6, 3.0])
DEFAULT = dict(startupDelay=0.0, tau=1.0, accel=2.6)
RUNS = [("original", "demand.rou.xml", s) for s in (1, 2, 3, 4, 5)] + \
       [("train", f"train_x10_s{s}.rou.xml", 1) for s in range(3001, 3011)]


def sumo_home() -> Path:
    home = os.environ.get("SUMO_HOME")
    if not home:
        import sumo                                    # eclipse-sumo wheel
        home = sumo.SUMO_HOME
        os.environ["SUMO_HOME"] = home
    return Path(home)


def point_id(p: dict) -> str:
    return f"sd{p['startupDelay']:.2f}_tau{p['tau']:.1f}_acc{p['accel']:.1f}"


def tls_shift(kit: Path, work: Path) -> Path:
    """Identical to e8_validation.py's tls_offset_16.add.xml."""
    tl = ET.parse(kit / "intersection.net.xml").getroot().find("tlLogic")
    phases = "".join(f'    <phase duration="{p.get("duration")}" state="{p.get("state")}"/>\n' for p in tl.findall("phase"))
    p = work / f"tls_offset_{OFFSET}.add.xml"
    p.write_text(f'<additional>\n  <tlLogic id="{tl.get("id")}" type="static" programID="e8_shift" offset="{OFFSET}">\n'
                 f"{phases}  </tlLogic>\n</additional>\n", encoding="utf-8")
    return p


def simulate(traci, kit, route, seed, adds):
    """Stop-line crossings per approach and green onsets per street (e8_validation.simulate without the queue part)."""
    traci.start(["sumo", "-n", str(kit / "intersection.net.xml"), "-r", str(kit / route), "-a", ",".join(map(str, adds)),
                 "--begin", "0", "--end", str(END), "--seed", str(seed), "--time-to-teleport", "-1",
                 "--no-step-log", "true", "--no-warnings", "true", "--duration-log.disable", "true"])
    lanes = {a: [f"{e}_{i}" for i in range(3)] for a, e in APPR.items()}
    length = traci.lane.getLength(lanes["SVB_N"][0])
    last, cross, rises = {}, {a: [] for a in APPR}, {g: [] for g in THROUGH_LINK}
    prev_g = {g: None for g in THROUGH_LINK}
    while traci.simulation.getTime() < END:
        traci.simulationStep()
        t = traci.simulation.getTime()
        s = traci.trafficlight.getRedYellowGreenState("nC")
        for g, i in THROUGH_LINK.items():
            on = s[i] in "Gg"
            if on and prev_g[g] is False:
                rises[g].append(t - 1)
            prev_g[g] = on
        cur = {}
        for a, ls in lanes.items():
            for ln in ls:
                for vid in traci.lane.getLastStepVehicleIDs(ln):
                    cur[vid] = (t, traci.vehicle.getDistance(vid), traci.vehicle.getLanePosition(vid), a)
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
    return cross, rises


def discharge(cross_times, onset, window):
    rows, prev, pos, in_q, n_q = [], None, 0, True, 0
    for tc in sorted(x for x in cross_times if onset <= x < onset + window):
        if prev is None:
            pos, hw, in_q = 1, None, (tc - onset) <= FIRST_MAX
        else:
            pos, hw = pos + 1, tc - prev
            if tc - prev > GAP_SPLIT:
                in_q = False
        rows.append((pos, round(tc - onset, 3), None if hw is None else round(hw, 3), in_q, in_q and pos >= SAT_FROM))
        n_q += int(in_q)
        prev = tc
    return rows, n_q


def cycles(cross, rises):
    out = {}
    for a, g in GROUP.items():
        out[a] = []
        for k, on in enumerate(rises[g], 1):
            if on + WINDOW[g] > END:
                continue
            rows, n_q = discharge(cross[a], on, WINDOW[g])
            out[a].append(dict(cycle=k, onset=on, n_cross=len(rows), discharged=n_q,
                               t1=rows[0][1] if rows else None,
                               t4=rows[3][1] if len(rows) >= 4 and rows[3][3] else None,
                               sat=[r[2] for r in rows if r[4] and r[2] is not None]))
    return out


def run_point(job):
    p, kit, out = job
    pid = point_id(p)
    dest = out / f"{pid}.json"
    if dest.exists():
        return pid, "skip", 0.0
    home = sumo_home()
    sys.path.append(str(home / "tools"))
    try:
        import libsumo as traci
        backend = "libsumo"
    except ImportError:
        import traci
        backend = "traci"
    t0 = time.time()
    work = Path(tempfile.mkdtemp(prefix=f"b6_{pid}_"))
    try:
        vt = work / "vtype.add.xml"
        vt.write_text(f'<additional>\n  <vType id="DEFAULT_VEHTYPE" startupDelay="{p["startupDelay"]}" tau="{p["tau"]}" '
                      f'accel="{p["accel"]}"/>\n</additional>\n', encoding="utf-8")
        adds = [tls_shift(kit, work), vt]
        runs = []
        for label, route, seed in RUNS:
            cross, rises = simulate(traci, kit, route, seed, adds)
            runs.append(dict(set=label, route=route, seed=seed, onsets=dict(SVB=rises["SVB"][:2], PRB=rises["PRB"][:2]),
                             cycles=cycles(cross, rises)))
        res = dict(point=p, id=pid, runs=runs, seconds=round(time.time() - t0, 1), backend=backend,
                   sumo=traci.getVersion()[1] if hasattr(traci, "getVersion") else "",
                   host=platform.node(), python=platform.python_version(), platform=platform.platform())
        tmp = dest.with_suffix(".tmp")
        tmp.write_text(json.dumps(res), encoding="utf-8")
        os.replace(tmp, dest)
        return pid, "done", res["seconds"]
    finally:
        shutil.rmtree(work, ignore_errors=True)


def cmd_run(a):
    out = Path(a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    pts = [DEFAULT] if a.only_default else [dict(startupDelay=s, tau=t, accel=c) for s, t, c in
                                            itertools.product(GRID["startupDelay"], GRID["tau"], GRID["accel"])]
    if not a.only_default:
        assert len(pts) == 858 and DEFAULT in pts
    jobs = [(p, Path(a.kit).resolve(), out) for p in pts]
    done = sum((out / f"{point_id(p)}.json").exists() for p in pts)
    print(f"{len(pts)} grid points, {done} already done, {a.jobs} parallel jobs", flush=True)
    t0, n = time.time(), 0
    with Pool(a.jobs, maxtasksperchild=20) as pool:
        for pid, status, sec in pool.imap_unordered(run_point, jobs):
            if status == "done":
                n += 1
                if n % 10 == 0 or n < 4:
                    el = time.time() - t0
                    print(f"{done + n}/{len(pts)} done ({pid}, {sec:.0f} s; {el / 60:.1f} min elapsed, "
                          f"{el / n * (len(pts) - done - n) / 60:.0f} min left)", flush=True)
    print("finished", flush=True)


def cmd_gate(a):
    """Measurement check: default vehicle, 5 original-demand runs, this extraction vs the E8 files."""
    import csv
    out = Path(a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    run_point((DEFAULT, Path(a.kit).resolve(), out))
    res = json.loads((out / f"{point_id(DEFAULT)}.json").read_text(encoding="utf-8"))
    e8q = list(csv.DictReader(open(Path(a.e8) / "sim_queue_discharge.csv", encoding="utf-8")))
    e8h = list(csv.DictReader(open(Path(a.e8) / "sim_discharge_headways.csv", encoding="utf-8")))
    dq, dt, dh, nh = [], [], [], 0
    for r in res["runs"]:
        if r["set"] != "original":
            continue
        rid = f"original:demand.rou:seed{r['seed']}"
        for ap, cyc in r["cycles"].items():
            for c in cyc:
                q = [x for x in e8q if x["run"] == rid and x["approach"] == ap and int(x["cycle"]) == c["cycle"]]
                if not q:
                    continue
                dq.append(abs(int(q[0]["discharged_queue"]) - c["discharged"]))
                h = [x for x in e8h if x["run"] == rid and x["approach"] == ap and int(x["cycle"]) == c["cycle"]]
                t1 = [float(x["t_after_green"]) for x in h if x["position"] == "1"]
                if t1 and c["t1"] is not None:
                    dt.append(abs(t1[0] - c["t1"]))
                sat = [float(x["headway"]) for x in h if x["saturated"] == "True" and x["headway"]]
                if len(sat) == len(c["sat"]):
                    nh += len(sat)
                    dh += [abs(x - y) for x, y in zip(sat, c["sat"])]
                else:
                    dh.append(float("inf"))
    onsets = {r["seed"]: r["onsets"] for r in res["runs"] if r["set"] == "original"}
    rep = dict(method=res["backend"] + " (E8 extraction)", onsets=onsets, cycles_compared=len(dq),
               discharged_equal=sum(d == 0 for d in dq), t1_compared=len(dt), t1_max_abs_diff=max(dt) if dt else None,
               headways_compared=nh, headway_max_abs_diff=max(dh) if dh else None,
               passed=bool(dq and all(d == 0 for d in dq) and dt and max(dt) <= 0.01 and dh and max(dh) <= 0.01))
    (out / "gate_e8.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    print(json.dumps(rep, indent=1))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--kit", required=True)
    r.add_argument("--out", required=True)
    r.add_argument("--jobs", type=int, default=os.cpu_count())
    r.add_argument("--only-default", action="store_true")
    g = sub.add_parser("gate")
    g.add_argument("--kit", required=True)
    g.add_argument("--e8", required=True)
    g.add_argument("--out", required=True)
    a = ap.parse_args()
    {"run": cmd_run, "gate": cmd_gate}[a.cmd](a)


if __name__ == "__main__":
    main()
