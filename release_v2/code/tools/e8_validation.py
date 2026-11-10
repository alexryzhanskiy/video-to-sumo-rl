"""E8 (Comment 1.2): simulated counterparts of the observed end-of-red queues and stop-line discharge.

Runs the field fixed-time plan of the repository network with the program shifted so that the Svobody through green
starts at --svoboda-green s (field: 16.2 s of common time = simulation time), and measures per approach and cycle:
  - halting vehicles (speed < 0.1 m/s) on the approach lanes 1 s before the green onset of the approach (total and
    within given distances from the stop line), plus vehicles still waiting for insertion on that approach;
  - stop-line crossing times (interpolated between 1-s steps with the vehicle odometer) during green + yellow
    (Svobody 49 s, Prybuzka 33 s), with Ryzhanskyi's rules from extract_validation_1_2.py: the first vehicle must
    cross within 8 s of the green onset, the discharging queue ends at the first gap > 8 s, headways count as
    saturated from queue position 4; `discharged_queue` = vehicles in the discharging queue.
Then it compares the simulated distributions with the observed ones (validation_1_2/*.csv) over the same cycles.

    python revision/tools/e8_validation.py --net sumo/intersection.net.xml \
        --route original=sumo/demand.rou.xml --seeds-original 1 2 3 4 5 \
        --route-glob heldout="revision/demand/heldout/x10/heldout_x10_s*.rou.xml" --seed-glob 1 \
        --observed revision/incoming/2026-10-26/validation/validation_1_2 --out revision/runs/e8_validation

Car-following, step length (1 s) and teleport settings are those of the published runs (SUMO defaults, Krauss,
--time-to-teleport -1). Deterministic for given files and seeds.
"""
import argparse
import csv
import glob
import json
import os
import statistics as st
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import demandlib as dl  # noqa: E402

APPR = {"SVB_N": "nN_nC", "SVB_S": "nS_nC", "PRB_E": "nE_nC", "PRB_W": "nW_nC"}
GROUP = {"SVB_N": "SVB", "SVB_S": "SVB", "PRB_E": "PRB", "PRB_W": "PRB"}
WINDOW = {"SVB": 49.0, "PRB": 33.0}      # green + yellow (Table 2)
THROUGH_LINK = {"SVB": 1, "PRB": 5}      # tls link index of a through movement of each street
LEAD, SAT_FROM, GAP_SPLIT, FIRST_MAX, HALT = 1.0, 4, 8.0, 8.0, 0.1

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--net", type=Path, required=True)
ap.add_argument("--route", action="append", default=[], metavar="LABEL=FILE", help="route file run with --seeds-original")
ap.add_argument("--seeds-original", type=int, nargs="+", default=[1, 2, 3, 4, 5])
ap.add_argument("--route-glob", action="append", default=[], metavar="LABEL=GLOB", help="route files run once each")
ap.add_argument("--seed-glob", type=int, default=1, help="SUMO seed for the --route-glob files")
ap.add_argument("--observed", type=Path, required=True, help="validation_1_2 folder of the observed data")
ap.add_argument("--out", type=Path, required=True)
ap.add_argument("--svoboda-green", type=float, default=16.2, help="field Svobody green onset, common time (s)")
ap.add_argument("--cycles", type=int, nargs=2, default=[2, 12], metavar=("FIRST", "LAST"),
                help="cycles compared (cycle 1 excluded by default: the simulation starts empty)")
ap.add_argument("--dist", type=float, nargs="+", default=[20, 40, 60, 80], help="distances for truncated queues (m)")
ap.add_argument("--end", type=float, default=1500)
ap.add_argument("--sumo-home", default=None)
args = ap.parse_args()

home = dl.find_sumo_home(args.sumo_home)
os.environ["SUMO_HOME"] = str(home)
sys.path.append(str(home / "tools"))
import traci  # noqa: E402

SUMO = str(home / "bin" / ("sumo.exe" if os.name == "nt" else "sumo"))
args.out.mkdir(parents=True, exist_ok=True)


def tls_additional(offset: int) -> Path:
    tl = ET.parse(args.net).getroot().find("tlLogic")
    phases = "".join(f'    <phase duration="{p.get("duration")}" state="{p.get("state")}"/>\n' for p in tl.findall("phase"))
    p = args.out / f"tls_offset_{offset}.add.xml"
    p.write_text(f'<additional>\n  <tlLogic id="{tl.get("id")}" type="static" programID="e8_shift" offset="{offset}">\n'
                 f"{phases}  </tlLogic>\n</additional>\n", encoding="utf-8")
    return p


def sumo_cmd(route, add, seed, end):
    return [SUMO, "-n", str(args.net), "-r", str(route), "-a", str(add), "--begin", "0", "--end", str(end),
            "--seed", str(seed), "--time-to-teleport", "-1", "--no-step-log", "true", "--no-warnings", "true",
            "--duration-log.disable", "true"]


def green_rises(route, add, end):
    """Green onsets of each street's through movement. TraCI reports after a step (time t) the state that SUMO set at
    the start of that step (t - 1), so vehicles move under the new state from t - 1: the onset is t - 1."""
    traci.start(sumo_cmd(route, add, 1, end))
    rises, prev = {g: [] for g in THROUGH_LINK}, {g: None for g in THROUGH_LINK}
    while traci.simulation.getTime() < end:
        traci.simulationStep()
        t, s = traci.simulation.getTime(), traci.trafficlight.getRedYellowGreenState("nC")
        for g, i in THROUGH_LINK.items():
            on = s[i] in "Gg"
            if on and prev[g] is False:
                rises[g].append(t - 1)
            prev[g] = on
    traci.close()
    return rises


def first_edges(route_file):
    """vehicle id -> first edge (for the insertion backlog)."""
    root = ET.parse(route_file).getroot()
    named = {r.get("id"): r.get("edges").split()[0] for r in root.iter("route") if r.get("id")}
    out = {}
    for v in root.iter("vehicle"):
        r = v.find("route")
        out[v.get("id")] = r.get("edges").split()[0] if r is not None else named.get(v.get("route"))
    return out


def simulate(route, seed, add, end):
    traci.start(sumo_cmd(route, add, seed, end))
    lanes = {a: [f"{e}_{i}" for i in range(3)] for a, e in APPR.items()}
    length = traci.lane.getLength(lanes["SVB_N"][0])
    edge2appr = {e: a for a, e in APPR.items()}
    vfirst = first_edges(route)
    last, crossings, snaps, rises = {}, [], {}, {g: [] for g in THROUGH_LINK}
    prev_g = {g: None for g in THROUGH_LINK}
    while traci.simulation.getTime() < end:
        traci.simulationStep()
        t = traci.simulation.getTime()
        s = traci.trafficlight.getRedYellowGreenState("nC")
        for g, i in THROUGH_LINK.items():
            on = s[i] in "Gg"
            if on and prev_g[g] is False:
                rises[g].append(t - 1)  # see green_rises
            prev_g[g] = on
        cur, snap = {}, {}
        for a, ls in lanes.items():
            halt = []
            for li, ln in enumerate(ls):
                for vid in traci.lane.getLastStepVehicleIDs(ln):
                    pos, spd = traci.vehicle.getLanePosition(vid), traci.vehicle.getSpeed(vid)
                    cur[vid] = (t, traci.vehicle.getDistance(vid), pos, a, li)
                    if spd < HALT:
                        halt.append((li, length - pos))
            snap[a] = halt
        pending = traci.simulation.getPendingVehicles()
        for a in APPR:
            snap[a + "_backlog"] = sum(edge2appr.get(vfirst.get(v)) == a for v in pending)
        snaps[t] = snap
        alive = None
        for vid, (t0, odo0, pos0, a, li) in last.items():
            if vid in cur:
                continue
            if alive is None:
                alive = set(traci.vehicle.getIDList())
            if vid in alive:
                odo1 = traci.vehicle.getDistance(vid)
                frac = (length - pos0) / (odo1 - odo0) if odo1 > odo0 else 1.0
                crossings.append((a, li, t0 + min(max(frac, 0.0), 1.0) * (t - t0), vid))
        last = cur
    traci.close()
    return rises, crossings, snaps, length


def discharge(cross_times, onset, window):
    """Ryzhanskyi's rules (extract_validation_1_2.py)."""
    rows, prev, pos, in_q, n_q = [], None, 0, True, 0
    for tc in sorted(x for x in cross_times if onset <= x < onset + window):
        if prev is None:
            pos, hw, in_q = 1, None, (tc - onset) <= FIRST_MAX
        else:
            pos, hw = pos + 1, tc - prev
            if tc - prev > GAP_SPLIT:
                in_q = False
        rows.append(dict(position=pos, t_after_green=round(tc - onset, 3), headway=None if hw is None else round(hw, 3),
                         in_discharging_queue=in_q, saturated=in_q and pos >= SAT_FROM))
        n_q += int(in_q)
        prev = tc
    return rows, n_q


# --- 1. offset: find the program offset that puts the Svobody green rise at the wanted time
target = round(args.svoboda_green)
probe_route = Path(args.route[0].split("=", 1)[1]) if args.route else None
chosen = None
for off in (target, -target, 120 - target, target - 120):
    add = tls_additional(off)
    probe = green_rises(probe_route, add, 400)
    print(f"probe offset {off}: Svobody green rises {probe['SVB'][:3]}, Prybuzka {probe['PRB'][:3]}")
    if probe["SVB"] and probe["SVB"][0] == target:
        chosen = off
        break
if chosen is None:
    sys.exit(f"no offset puts the Svobody green at {target} s")
print(f"chosen tls offset {chosen} (field greens {args.svoboda_green} and {args.svoboda_green + 68} s)")

# --- 2. runs
runs = [(lab, Path(f), s) for lab, f in (x.split("=", 1) for x in args.route) for s in args.seeds_original]
for x in args.route_glob:
    lab, pat = x.split("=", 1)
    runs += [(lab, Path(f), args.seed_glob) for f in sorted(glob.glob(pat))]
q_rows, d_rows, meta = [], [], []
c0, c1 = args.cycles
for lab, route, seed in runs:
    rises, cross, snaps, length = simulate(route, seed, add, args.end)
    run_id = f"{lab}:{route.stem}:seed{seed}"
    by_appr = {a: [c[2] for c in cross if c[0] == a] for a in APPR}
    for a, g in GROUP.items():
        for k, on in enumerate(rises[g], 1):
            if not (c0 <= k <= c1) or on + WINDOW[g] > args.end:
                continue
            snap = snaps.get(on - LEAD, {})
            halt = snap.get(a, [])
            row = dict(run=run_id, set=lab, cycle=k, approach=a, green_onset=on, halting=len(halt),
                       halting_lane0=sum(h[0] == 0 for h in halt), halting_lane1=sum(h[0] == 1 for h in halt),
                       halting_lane2=sum(h[0] == 2 for h in halt), backlog=snap.get(a + "_backlog", 0))
            for dmax in args.dist:
                row[f"halting_within_{dmax:g}m"] = sum(h[1] <= dmax for h in halt)
            rows, n_q = discharge(by_appr[a], on, WINDOW[g])
            row["discharged_queue"] = n_q
            row["crossings"] = len(rows)
            q_rows.append(row)
            for d in rows:
                d_rows.append(dict(run=run_id, set=lab, cycle=k, approach=a, green_onset=on, **d))
    meta.append(dict(run=run_id, route=dl.posix(route), sha256=dl.sha256(route), seed=seed, crossings=len(cross)))
    print(f"{run_id}: {len(cross)} stop-line crossings")


def write(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


write(args.out / "sim_queue_discharge.csv", q_rows)
write(args.out / "sim_discharge_headways.csv", d_rows)


# --- 3. comparison with the observed data over the same cycles
def rd(p):
    with open(p, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, max(0, round(q * (len(xs) - 1))))]


def desc(xs):
    return dict(n=len(xs), mean=st.mean(xs), sd=st.stdev(xs) if len(xs) > 1 else 0.0, median=st.median(xs),
                p10=pct(xs, 0.1), p90=pct(xs, 0.9), min=min(xs), max=max(xs))


oq = [r for r in rd(args.observed / "observed_queue.csv") if c0 <= int(r["cycle"]) <= c1]
oh = [r for r in rd(args.observed / "discharge_headways.csv") if c0 <= int(r["cycle"]) <= c1]
comp = []
for a in APPR:
    oa = [r for r in oq if r["approach"] == a]
    sa = [r for r in q_rows if r["approach"] == a]
    for metric, ov, sv in (
            ("end_of_red_queue", [int(r["observed_queue"]) for r in oa], [r["halting"] for r in sa]),
            ("discharged_queue", [int(r["discharged_queue"]) for r in oa], [r["discharged_queue"] for r in sa]),
            ("sat_headway_s", [float(r["headway"]) for r in oh if r["approach"] == a and r["saturated"] == "True" and r["headway"]],
             [d["headway"] for d in d_rows if d["approach"] == a and d["saturated"] and d["headway"] is not None]),
            ("first_crossing_s", [float(r["t_after_green"]) for r in oh if r["approach"] == a and r["position"] == "1"],
             [d["t_after_green"] for d in d_rows if d["approach"] == a and d["position"] == 1])):
        o, s = desc(ov), desc(sv)
        comp.append(dict(approach=a, metric=metric, obs_n=o["n"], obs_mean=round(o["mean"], 2), obs_sd=round(o["sd"], 2),
                         obs_median=round(o["median"], 2), obs_min=o["min"], obs_max=o["max"],
                         sim_n=s["n"], sim_mean=round(s["mean"], 2), sim_sd=round(s["sd"], 2),
                         sim_median=round(s["median"], 2), sim_p10=round(s["p10"], 2), sim_p90=round(s["p90"], 2),
                         diff_mean=round(s["mean"] - o["mean"], 2),
                         diff_mean_pct=round(100 * (s["mean"] - o["mean"]) / o["mean"], 1) if o["mean"] else None,
                         diff_median_pct=round(100 * (s["median"] - o["median"]) / o["median"], 1) if o["median"] else None))
    for dmax in args.dist:
        sv = [r[f"halting_within_{dmax:g}m"] for r in sa]
        comp.append(dict(approach=a, metric=f"sim_queue_within_{dmax:g}m", sim_n=len(sv), sim_mean=round(st.mean(sv), 2),
                         sim_sd=round(st.stdev(sv), 2), sim_median=st.median(sv), sim_p10=pct(sv, 0.1), sim_p90=pct(sv, 0.9)))
    bl = [r["backlog"] for r in sa]
    comp.append(dict(approach=a, metric="sim_insertion_backlog", sim_n=len(bl), sim_mean=round(st.mean(bl), 2),
                     sim_sd=round(st.stdev(bl), 2), sim_median=st.median(bl), sim_p10=pct(bl, 0.1), sim_p90=pct(bl, 0.9)))
keys = []
for r in comp:
    keys += [k for k in r if k not in keys]
with open(args.out / "comparison.csv", "w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=keys)
    w.writeheader()
    w.writerows(comp)

# per-run means (spread between realizations)
per_run = []
for run in sorted({r["run"] for r in q_rows}):
    for a in APPR:
        rs = [r for r in q_rows if r["run"] == run and r["approach"] == a]
        hs = [d["headway"] for d in d_rows if d["run"] == run and d["approach"] == a and d["saturated"] and d["headway"] is not None]
        per_run.append(dict(run=run, approach=a, queue_mean=round(st.mean(r["halting"] for r in rs), 2),
                            discharged_mean=round(st.mean(r["discharged_queue"] for r in rs), 2),
                            sat_headway_median=round(st.median(hs), 3) if hs else None, n_sat=len(hs)))
write(args.out / "per_run_means.csv", per_run)
(args.out / "run_meta.json").write_text(json.dumps(dict(
    sumo_home=dl.posix(home), sumo_version=__import__("subprocess").run([SUMO, "--version"], capture_output=True, text=True).stdout.splitlines()[0],
    tls_offset=chosen, svoboda_green_sim=probe["SVB"][:2], prybuzka_green_sim=probe["PRB"][:2], cycles=args.cycles, window=WINDOW, rules=dict(
        lead=LEAD, sat_from=SAT_FROM, gap_split=GAP_SPLIT, first_max=FIRST_MAX, halting_speed=HALT),
    runs=meta), indent=1), encoding="utf-8")
print("wrote", dl.posix(args.out))
