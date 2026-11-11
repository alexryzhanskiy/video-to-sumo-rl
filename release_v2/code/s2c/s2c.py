#!/usr/bin/env python3
"""S2c: the non-learning baselines of E13 (pre-registration v1, section 6) and their B7 runs.

Tuned MaxPressure (6.2), the Webster plan per load (6.3), the queue log of every baseline episode, and the
fixed / actuated / tuned-MaxPressure episodes of B7 (section 9, revision/twin/B7/B7_run_spec.md). Every metric comes
from E13's own code: e13.py is imported read-only (safe_metrics, records_hash, check_tls, rank, route_files, SETS,
SET_OF, GLOBAL_SEED, TRIAL_OFFSET, END, RUNS_K), so every definition is identical to the E13 runs.

Episodes are run like e13.py baseline_job (same net files, SUMO flags, seeds 42 + 1000 + k + e for k = 1..5 and file
index e, end 1800 s, the twin of e13/twin.json), through libsumo (TraCI if libsumo is missing) so that the
controller and the queue log can read the simulation. One result file per episode, written atomically (temp file,
then os.replace); a restart skips finished episodes. Each run command ends with `collect` (CSV tables and a SHA-256
manifest of --out).

    python s2c.py tune   [--loads x1.0 x1.2 x1.5] [--h 0 2 4 6 8 12] [--variants free field]   grid on the training files
    python s2c.py plan                                Webster plans per load (needs plan/satflow.json)
    python s2c.py eval   --set validation|testA|locked [--locked-ok]   tuned MaxPressure and Webster
    python s2c.py queue  --set validation|testA|locked [--locked-ok]   fixed plan and actuated with the queue log
    python s2c.py b7                                  fixed, actuated, tuned MaxPressure on the B7 demand
    python s2c.py e14                                 fixed, actuated, tuned MaxPressure and Webster (x1.0 configurations)
                                                      on the E14 demand (second real window), k = 1..5 (kb/07 E14)
    python s2c.py status | collect | smoke | verify-kit
    python s2c.py satflow                             (laptop) discharge headways per lane group in the default twin
    python s2c.py kit                                 (laptop) build s2c_kit.zip for Colab

Common options: --out DIR (default ./out; on Colab /content/drive/MyDrive/S2c), --jobs N (parallel SUMO processes).
Subset options (smoke tests only): --maps, --limit-files N, --k 1 2, --mp-config VARIANT:H, --b7-only x10/base.
The locked set needs --locked-ok and refuses without it.
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True    # never write __pycache__ next to the read-only e13.py

import argparse  # noqa: E402
import csv  # noqa: E402
import gzip  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import os  # noqa: E402
import platform  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
import statistics as st  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402
import xml.etree.ElementTree as ET  # noqa: E402
import zipfile  # noqa: E402
from datetime import datetime  # noqa: E402
from multiprocessing import Pool  # noqa: E402
from pathlib import Path  # noqa: E402

HERE = Path(__file__).resolve().parent
KIT = (HERE / "e13" / "e13.py").is_file()    # Colab kit layout; else the repository (revision/s2c/)
if KIT:
    REPO_ROOT = None
    E13_DIR, B7_DEMAND, COUNTS = HERE / "e13", HERE / "b7" / "demand", HERE / "sumo" / "turn_counts_edges.xml"
else:
    REPO_ROOT = HERE.parent.parent
    E13_DIR = HERE.parent / "e12_kit" / "e13"
    B7_DEMAND = HERE.parent / "twin" / "B7" / "demand"
    COUNTS = REPO_ROOT / "sumo" / "turn_counts_edges.xml"
E14_DEMAND = (HERE / "e14" / "demand") if KIT else (HERE.parent / "twin" / "E14" / "demand")
PLAN_DIR, REF_DIR = HERE / "plan", HERE / "ref"
os.environ.pop("E13_SMOKE", None)    # all files and the five seeds k = 1..5, as the real E13 baselines
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
sys.path.insert(0, str(E13_DIR))
import e13  # noqa: E402  (read-only)

TLS = "nC"
END = e13.END                                     # 1800 s
SEED0 = e13.GLOBAL_SEED + e13.TRIAL_OFFSET        # SUMO seed = 1042 + k + e
KS = list(e13.RUNS_K)                             # k = 1..5
MIN_GREEN, MAX_GREEN, ALLRED_S, YELLOW_S, STEP_S = e13.MIN_GREEN, e13.MAX_GREEN, e13.ALLRED, 3, 5
STREET = e13.STREET
GREEN_STATES = [s for s, _ in sorted(e13.GREENS.items(), key=lambda x: x[1])]    # phases 0-3 of section 1
ALLRED_STATE = "srrrsrrrsrrrsrrr"                 # all-red state of the field program
H_GRID, VARIANTS = (0, 2, 4, 6, 8, 12), ("free", "field")
LOADS = ("x1.0", "x1.2", "x1.5")
LOAD_TAG = {"x1.0": "x10", "x1.2": "x12", "x1.5": "x15"}
B7_LOAD = {"x10": "x1.0", "x12": "x1.2"}
FIXED_NET = e13.CONTROLLERS["Fixed plan"][1]
ACT_NET = e13.CONTROLLERS["Actuated"][1]
CTRL_NAME = {"fixed": "Fixed plan", "actuated": "Actuated", "mp": "MaxPressure", "webster": "Webster"}
# RESCO's queue metric (metrics_*.csv, 'queue_lengths' {'nC': n}): Signal.lanes in the order of signal_config
# 'prybuzka' lane_sets, max_distance 200 m (agent_config of IDQN, IDQN_pressure, IDQN_pressure_inout, MPLight)
QUEUE_LANES = ["nS_nC_2", "nS_nC_0", "nS_nC_1", "nW_nC_2", "nW_nC_0", "nW_nC_1",
               "nN_nC_2", "nN_nC_0", "nN_nC_1", "nE_nC_2", "nE_nC_0", "nE_nC_1"]
QUEUE_MAX_DISTANCE, QUEUE_DT = 200.0, 5
QUEUE_TIMES = list(range(QUEUE_DT, int(END) + 1, QUEUE_DT))    # 5, 10, ..., 1800
FIELDS = ["rung", "policy", "train_load", "training_run", "eval_set", "map", "label", "episode", "route_file",
          "sumo_seed", "tripinfo_ok", "demand", "entries", "arrived_1500", "arrived_1800", "unfinished",
          "not_inserted", "undeparted_written", "full", "longest_no_arrival_s", "deadlock", "mean_wait_arrived_s",
          "total_delay_vh", "mean_delay_s", "switches", "clearance_s", "tripinfo"]


# ------------------------------------------------------------------ small helpers
def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_atomic(path: Path, data: bytes | str) -> None:
    """Write to a temporary name in the same folder, flush to disk, then rename: never a truncated file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp{os.getpid()}")
    with open(tmp, "wb") as f:
        f.write(data.encode("utf-8") if isinstance(data, str) else data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def write_json(path: Path, obj) -> None:
    write_atomic(path, json.dumps(obj, indent=1))


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def is_done(dest: Path) -> bool:
    r = read_json(dest) if dest.is_file() else None
    return bool(r) and r.get("status") == "done"


def write_csv(path: Path, rows: list[dict], first: list[str] | None = None) -> None:
    if not rows:
        return
    import io
    keys = list(dict.fromkeys((first or []) + [k for r in rows for k in r]))
    keys = [k for k in keys if any(k in r for r in rows)]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=keys, extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    write_atomic(path, buf.getvalue())


def rel_out(path: Path, out: Path) -> str:
    try:
        return path.resolve().relative_to(out.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def yellow_state(cur: str, nxt: str) -> str:
    """RESCO create_yellows(): links green now and red/stop next turn yellow, the others keep their state."""
    return "".join("y" if a in "Gg" and b in "rs" else a for a, b in zip(cur, nxt))


_MOV: dict | None = None


def movements() -> dict[int, list[tuple[list[str], list[str]]]]:
    """Movements of each phase (section 1: 0 = Svobody through [1,7], 1 = Svobody left [0,6], 2 = Prybuzka through
    [4,10], 3 = Prybuzka left [3,9]): the through (dir s) and left (dir l) connections green in the phase, grouped per
    (approach, exit edge); incoming lanes = their from-lanes, outgoing lanes = their to-lanes. Right turns are not
    movements of any phase in section 1."""
    global _MOV
    if _MOV is None:
        mv: dict = {}
        for c in ET.parse(FIXED_NET).getroot().findall("connection"):
            if c.get("tl") != TLS or c.get("dir") not in ("s", "l"):
                continue
            li = int(c.get("linkIndex"))
            for p, state in enumerate(GREEN_STATES):
                if state[li] == "G":
                    ins, outs = mv.setdefault((p, c.get("from"), c.get("to")), (set(), set()))
                    ins.add(f"{c.get('from')}_{c.get('fromLane')}")
                    outs.add(f"{c.get('to')}_{c.get('toLane')}")
        _MOV = {p: [] for p in range(4)}
        for (p, _, _), (ins, outs) in sorted(mv.items()):
            _MOV[p].append((sorted(ins), sorted(outs)))
    return _MOV


# ------------------------------------------------------------------ simulation backend
_TC = None


def backend():
    global _TC
    if _TC is None:
        try:
            import libsumo as tc
            _TC = (tc, "libsumo")
        except ImportError:
            sys.path.append(str(Path(e13.sumo_home()) / "tools"))
            import traci as tc
            _TC = (tc, "traci")
    return _TC


def sumo_cmd(net: Path, route: Path, seed: int, trip: Path, adds: list[str], end: float | None = END,
             resco: bool = False) -> list[str]:
    tc, name = backend()
    binary = "sumo" if name == "libsumo" else e13.sumo_exe()
    if resco:    # RESCO MultiSignal.reset() with E13's --undeparted (replay check only)
        cmd = [binary, "-n", str(net), "-r", str(route), "--seed", str(seed), "--time-to-teleport", "-1",
               "--tripinfo-output", str(trip), "--tripinfo-output.write-unfinished", "--device.emissions.probability",
               "1.0", "--no-step-log", "True", "--no-warnings", "True", "--tripinfo-output.write-undeparted"]
    else:        # e13.py baseline_job()
        cmd = [binary, "-n", str(net), "-r", str(route), "--begin", "0", "--end", str(int(end)), "--seed", str(seed),
               "--time-to-teleport", "-1", "--tripinfo-output", str(trip), "--tripinfo-output.write-unfinished",
               "--tripinfo-output.write-undeparted", "--device.emissions.probability", "1.0", "--no-step-log", "true",
               "--no-warnings", "true"]
    return cmd + (["-a", ",".join(adds)] if adds else [])


class QueueLog:
    """RESCO Signal.observe() 'queue' summed over Signal.lanes (= MultiSignal.calc_metrics 'queue_lengths'): vehicles
    on the 12 incoming lanes within 200 m of the signal whose RESCO waiting time is > 0, i.e. that were halting
    (SUMO waiting time > 0) at some observation since they entered these lanes; reset when they leave them."""

    def __init__(self, tc):
        self.tc, self.wait, self.last = tc, {}, None

    def observe(self) -> int:
        tc, q, seen = self.tc, 0, set()
        for lane in QUEUE_LANES:
            for v in tc.lane.getLastStepVehicleIDs(lane):
                nxt = tc.vehicle.getNextTLS(v)
                if not nxt or nxt[0][2] > QUEUE_MAX_DISTANCE:
                    continue
                seen.add(v)
                if v in self.wait:
                    self.wait[v] += QUEUE_DT
                elif tc.vehicle.getWaitingTime(v) > 0:
                    self.wait[v] = tc.vehicle.getWaitingTime(v)
                if self.wait.get(v, 0) > 0:
                    q += 1
        if self.last is not None:
            for v in self.last - seen:
                self.wait.pop(v, None)
        self.last = seen
        return q


class Episode:
    """Steps SUMO one second at a time up to `end`; samples the queue at 5, 10, ..., 1800 s if asked."""

    def __init__(self, tc, queue: bool, end: float = END):
        self.tc, self.end, self.t = tc, end, tc.simulation.getTime()
        self.qlog = QueueLog(tc) if queue else None
        self.queue: list[int] = []
        if self.qlog:
            self.qlog.observe()    # t = 0, as RESCO's observe() in reset()

    def advance(self, n: int) -> None:
        for _ in range(n):
            if self.t >= self.end:
                return
            self.tc.simulationStep()
            self.t = self.tc.simulation.getTime()
            if self.qlog and self.t % QUEUE_DT == 0:
                self.queue.append(self.qlog.observe())

    def to_end(self) -> None:
        while self.t < self.end:
            self.advance(1)


def pressures(tc) -> list[int]:
    """Pressure of each phase: sum over its movements of (vehicles on incoming lanes - vehicles on outgoing lanes)."""
    n = {}

    def cnt(lane):
        if lane not in n:
            n[lane] = tc.lane.getLastStepVehicleNumber(lane)
        return n[lane]
    return [sum(sum(cnt(a) for a in ins) - sum(cnt(b) for b in outs) for ins, outs in movements()[p]) for p in range(4)]


def mp_decide(p: list[int], green: int, elapsed: float, variant: str, h: float) -> int:
    if elapsed < MIN_GREEN:                       # minimum green not reached: keep
        return green
    forced = elapsed + STEP_S > MAX_GREEN         # holding would pass the maximum green by the next decision
    if variant == "field":
        nxt = (green + 1) % 4
        return nxt if forced or p[nxt] - p[green] >= h else green
    others = [(green + i) % 4 for i in (1, 2, 3)]    # ties: the first in field order after the current phase
    best = max(others, key=lambda x: p[x])
    return best if forced or p[best] - p[green] >= h else green


def run_mp(tc, ep: Episode, variant: str, h: float) -> list[tuple[float, int]]:
    """Decisions as RESCO MultiSignal.step() in E13 (decision every 5 s; a change = 3-s yellow, 4-s all-red only at a
    street change, new green, 2 s to the next decision). Returns (time, green) after every decision."""
    green, start, rows = 0, ep.t, []
    tc.trafficlight.setRedYellowGreenState(TLS, GREEN_STATES[0])
    while ep.t < ep.end:
        a = mp_decide(pressures(tc), green, ep.t - start, variant, h)
        if a != green:
            tc.trafficlight.setRedYellowGreenState(TLS, yellow_state(GREEN_STATES[green], GREEN_STATES[a]))
            ep.advance(YELLOW_S)
            if STREET[green] != STREET[a]:
                tc.trafficlight.setRedYellowGreenState(TLS, ALLRED_STATE)
                ep.advance(ALLRED_S)
            if ep.t >= ep.end:    # episode ended during the clearance: the new green never started
                rows.append((ep.t, green))
                break
            tc.trafficlight.setRedYellowGreenState(TLS, GREEN_STATES[a])
            green, start = a, ep.t
            ep.advance(STEP_S - YELLOW_S)
        else:
            ep.advance(STEP_S)
        rows.append((ep.t, green))
    return rows


def resco_metrics_csv(path: Path, rows: list[tuple[float, int]]) -> None:
    """The decisions in RESCO's metrics_*.csv layout, so that e13.switches() counts switches and clearance."""
    path.write_text("".join(f"{t}, {{}}, {{}}, {{}}, {{'{TLS}': {g}}}, \n" for t, g in rows), encoding="utf-8")


# ------------------------------------------------------------------ one episode (worker)
def run_job(job: dict) -> tuple[str, str, float, str | None]:
    dest = Path(job["dest"])
    if is_done(dest):
        return job["id"], "skip", 0.0, None
    tc, bname = backend()
    work = Path(tempfile.mkdtemp(prefix="s2c_"))
    t0 = time.time()
    try:
        trip = work / "tripinfo.xml"
        adds = []
        if job["ctrl"] == "webster":
            adds.append(job["plan"])
        if job.get("tls_log"):
            tls_add = work / "tls.add.xml"
            tls_add.write_text(f'<additional><timedEvent type="SaveTLSStates" source="{TLS}" '
                               f'dest="{(work / "tls_states.xml").as_posix()}"/></additional>\n', encoding="utf-8")
            adds.append(str(tls_add))
        if job.get("vtype"):
            adds.append(job["vtype"])
        net = ACT_NET if job["ctrl"] == "actuated" else FIXED_NET
        tc.start(sumo_cmd(net, Path(job["route"]), job["seed"], trip, adds))
        rows, program = None, None
        try:
            program = tc.trafficlight.getProgram(TLS)
            if job["ctrl"] == "webster" and program != job["plan_id"]:
                raise RuntimeError(f"active program {program!r}, expected {job['plan_id']!r}")
            ep = Episode(tc, job["queue"])
            if job["ctrl"] == "mp":
                rows = run_mp(tc, ep, job["variant"], job["h"])
            ep.to_end()
            version = tc.getVersion()[1]
        finally:
            tc.close()
        mcsv = None
        if rows is not None:
            mcsv = work / "metrics.csv"
            resco_metrics_csv(mcsv, rows)
        m = e13.safe_metrics(trip, Path(job["route"]), END, mcsv, False)
        row = {**job["row"], **m}
        res = {"status": "done" if m.get("tripinfo_ok") else "FAILED (tripinfo unreadable)", "job": job["id"],
               "row": row, "seconds": round(time.time() - t0, 2), "backend": bname, "sumo": version,
               "program": program, "host": platform.node(), "python": platform.python_version(),
               "finished": now(), "records_sha256": e13.records_hash(trip)}
        if job["queue"]:
            res["queue_times"] = [QUEUE_TIMES[0], QUEUE_DT, len(ep.queue)]
            res["queue"] = ep.queue
        if rows is not None:
            res["decisions"] = [[t, g] for t, g in rows]
        if job["ctrl"] == "webster":
            res["plan_sha256"] = sha256(Path(job["plan"]))
        if job.get("tls_log"):
            res["signal_rules"] = e13.check_tls(work / "tls_states.xml", END,
                                                job.get("variant", "field") if job["ctrl"] == "mp" else "field")
        if job.get("keep_trip"):
            gz = dest.with_name(dest.name.replace(".json", ".tripinfo.xml.gz"))
            write_atomic(gz, gzip.compress(trip.read_bytes(), compresslevel=6, mtime=0))
            row["tripinfo"] = gz.name
        write_json(dest, res)
        return job["id"], res["status"], res["seconds"], None
    except Exception as e:    # keep the other jobs running; the episode is retried on the next run
        try:
            write_json(dest.with_name(dest.name.replace(".json", ".failed.json")),
                       {"status": f"FAILED ({e!r})", "job": job["id"], "finished": now()})
        except OSError:
            pass
        return job["id"], "FAILED", round(time.time() - t0, 2), repr(e)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def run_pool(jobs: list[dict], n: int, what: str) -> int:
    todo = [j for j in jobs if not is_done(Path(j["dest"]))]
    print(f"{now()}  {what}: {len(jobs)} episodes, {len(jobs) - len(todo)} already done, {len(todo)} to run "
          f"with {n} processes", flush=True)
    failed, t0, k = 0, time.time(), 0
    if todo:
        todo.sort(key=lambda j: j.get("cost", 1.0), reverse=True)
        with Pool(max(1, n), maxtasksperchild=25) as pool:
            for jid, status, sec, err in pool.imap_unordered(run_job, todo):
                k += 1
                failed += status not in ("done", "skip")
                if status not in ("done", "skip") or k <= 3 or k % 25 == 0 or k == len(todo):
                    el = time.time() - t0
                    print(f"{now()}  {what} [{k}/{len(todo)}] {jid}: {status} ({sec:.1f} s)"
                          + (f" {err}" if err else "") + f"; {el / 60:.1f} min elapsed, "
                          f"about {el / k * (len(todo) - k) / 60:.0f} min left", flush=True)
    print(f"{now()}  {what}: finished, {failed} failed" + (" (run again to retry them)" if failed else ""), flush=True)
    return 1 if failed else 0


# ------------------------------------------------------------------ job lists
def twin_info() -> tuple[str, str | None]:
    t = e13.twin_for_runs()
    return e13.twin_tag(t), (str(E13_DIR / t["vtype"]) if t["twin"] == "calibrated" else None)


def ks(args) -> list[int]:
    return list(args.k) if getattr(args, "k", None) else KS


def files_of(map_name: str, args) -> list[tuple[int, Path]]:
    routes = list(enumerate(e13.route_files(map_name), 1))
    lim = getattr(args, "limit_files", None)
    return routes[:lim] if lim else routes


COST = {"x1.0": 1.0, "x1.2": 1.4, "x1.5": 2.0}


def base_job(stage: str, ctrl: str, dest: Path, route: Path, e: int, k: int, eval_set: str, map_name: str,
             label: str, twin: tuple, queue: bool, keep_trip: bool, cfg_load: str = "", **extra) -> dict:
    seed = SEED0 + k + e
    row = {"rung": "baseline", "policy": CTRL_NAME[ctrl], "train_load": cfg_load, "training_run": k,
           "eval_set": eval_set, "map": map_name, "label": label, "episode": e, "route_file": route.name,
           "sumo_seed": seed}
    row.update({k2: v for k2, v in extra.items() if k2 in ("controller_config", "b7_load", "b7_variant", "b7_seed")})
    job = {"id": f"{stage}/{dest.parent.parent.name}/{dest.parent.name}/{dest.stem}", "stage": stage, "ctrl": ctrl,
           "dest": str(dest), "route": str(route), "seed": seed, "queue": queue, "keep_trip": keep_trip,
           "vtype": twin[1], "twin": twin[0], "row": row, "cost": COST.get(label, COST.get(cfg_load, 1.0))}
    job.update({k2: v for k2, v in extra.items() if k2 in ("variant", "h", "plan", "plan_id", "tls_log")})
    if ctrl == "mp":
        row["controller_config"] = f"{extra['variant']} h={extra['h']}"
    elif ctrl == "webster":
        row["controller_config"] = extra["plan_id"]
    return job


def tune_jobs(args, out: Path, twin: tuple) -> list[dict]:
    jobs = []
    for load in args.loads:
        m = e13.LOADS[load]
        for e, route in files_of(m, args):
            for k in ks(args):
                name = f"e{e:02d}_k{k}.json"
                jobs.append(base_job("tune", "fixed", out / "tune" / load / "fixed" / name, route, e, k, "train", m,
                                     load, twin, False, False))
                for v in args.variants:
                    for h in args.h:
                        jobs.append(base_job("tune", "mp", out / "tune" / load / f"mp_{v}_h{h:g}" / name, route, e, k,
                                             "train", m, load, twin, False, False, cfg_load=load, variant=v, h=h))
    return jobs


def mp_config(out: Path, load: str, args) -> tuple[str, float]:
    if getattr(args, "mp_config", None):    # smoke tests only
        v, h = args.mp_config.split(":")
        return v, float(h) if "." in h else int(h)
    tuned = read_json(out / "tune" / "tuned.json")
    if not tuned or load not in tuned.get("loads", {}):
        sys.exit(f"no tuned MaxPressure for {load} in {out / 'tune' / 'tuned.json'}: run 'tune' to the end first")
    c = tuned["loads"][load]
    return c["variant"], c["h"]


def webster_plan(load: str) -> tuple[str, str]:
    p = PLAN_DIR / f"webster_{LOAD_TAG[load]}.add.xml"
    if not p.is_file():
        sys.exit(f"{p} missing: run 'plan' first")
    pid = ET.parse(p).getroot().find("tlLogic").get("programID")
    return str(p), pid


def set_maps(eval_set: str, args) -> list[tuple[str, str]]:
    loads, scs = e13.SETS[eval_set]
    maps = [(m, lab) for lab, m in loads.items()] + [(m, f"S{i}") for i, m in enumerate(scs, 1)]
    if getattr(args, "maps", None):
        maps = [x for x in maps if x[0] in args.maps]
    return maps


def eval_jobs(args, out: Path, twin: tuple, ctrls: tuple[str, ...], stage: str) -> list[dict]:
    jobs = []
    for m, lab in set_maps(args.set, args):
        load = lab if lab in LOADS else "x1.0"    # scenarios: the x1.0 configuration, as the x1.0 models (D12)
        for ctrl in ctrls:
            extra = {}
            if ctrl == "mp":
                v, h = mp_config(out, load, args)
                extra = dict(variant=v, h=h, cfg_load=load)
            elif ctrl == "webster":
                plan, pid = webster_plan(load)
                extra = dict(plan=plan, plan_id=pid, cfg_load=load)
            for e, route in files_of(m, args):
                for k in ks(args):
                    dest = out / stage / args.set / ctrl / m / f"e{e:02d}_k{k}.json"
                    jobs.append(base_job(stage, ctrl, dest, route, e, k, args.set, m, lab, twin, True,
                                         not args.no_tripinfo, **extra))
    return jobs


def b7_files() -> list[tuple[str, str, int, Path]]:
    out = []
    for p in sorted(B7_DEMAND.glob("*/*/*.rou.xml")):
        m = re.search(r"_s(\d+)\.rou\.xml$", p.name)
        if m and p.parent.parent.name in B7_LOAD:
            out.append((p.parent.parent.name, p.parent.name, int(m.group(1)), p))
    return out


def b7_jobs(args, out: Path, twin: tuple) -> list[dict]:
    jobs, count = [], {}
    for load_tag, variant, rseed, route in b7_files():
        if args.b7_only and f"{load_tag}/{variant}" not in args.b7_only:
            continue
        count[(load_tag, variant)] = count.get((load_tag, variant), 0) + 1
        if args.limit_files and count[(load_tag, variant)] > args.limit_files:
            continue
        e = rseed % 100                     # spec: 7001..7005 -> 1..5 (7101..7110 -> 1..10)
        load = B7_LOAD[load_tag]
        for ctrl in ("fixed", "actuated", "mp"):
            extra = dict(b7_load=load_tag, b7_variant=variant, b7_seed=rseed)
            if ctrl == "mp":
                v, h = mp_config(out, load, args)
                extra.update(variant=v, h=h, cfg_load=load)
            dest = out / "b7" / ctrl / f"{load_tag}_{variant}" / f"s{rseed}_k1.json"
            jobs.append(base_job("b7", ctrl, dest, route, e, 1, "B7", f"b7_{load_tag}_{variant}", variant, twin,
                                 True, not args.no_tripinfo, **extra))
    return jobs


def e14_jobs(args, out: Path, twin: tuple) -> list[dict]:
    """E14: every baseline with its x1.0 configuration on every E14 file, seeds k = 1..5 (the seeds of the final
    design's training runs in b7.py: 42 + 1000 + k + e, e = routeSampler seed % 100), so that each DRL episode has a
    baseline episode on the same file and SUMO seed."""
    jobs, count = [], {}
    for p in sorted(E14_DEMAND.glob("x10/*/*.rou.xml")):
        m = re.search(r"_s(\d+)\.rou\.xml$", p.name)
        if not m:
            continue
        variant, rseed = p.parent.name, int(m.group(1))
        count[variant] = count.get(variant, 0) + 1
        if args.limit_files and count[variant] > args.limit_files:
            continue
        e = rseed % 100
        for ctrl in ("fixed", "actuated", "mp", "webster"):
            extra = dict(b7_load="x10", b7_variant=variant, b7_seed=rseed)
            if ctrl == "mp":
                v, h = mp_config(out, "x1.0", args)
                extra.update(variant=v, h=h, cfg_load="x1.0")
            elif ctrl == "webster":
                plan, pid = webster_plan("x1.0")
                extra.update(plan=plan, plan_id=pid, cfg_load="x1.0")
            for k in ks(args):
                dest = out / "e14" / ctrl / f"x10_{variant}" / f"s{rseed}_k{k}.json"
                jobs.append(base_job("e14", ctrl, dest, p, e, k, "E14", f"e14_x10_{variant}", variant, twin,
                                     True, not args.no_tripinfo, **extra))
    return jobs


# ------------------------------------------------------------------ tuning selection (rule 5.1 on training files)
def load_rows(folder: Path) -> list[dict]:
    rows = []
    for p in sorted(folder.rglob("*.json")):
        if p.name.endswith(".failed.json"):
            continue
        r = read_json(p)
        if r and r.get("status") == "done":
            rows.append(r["row"] | {"_seconds": r.get("seconds")})
    return rows


def finalize_tuning(out: Path) -> dict:
    """Score 5.1 per load on the training files: (mean arrivals - paired fixed-plan arrivals) / mean demand, in %,
    paired by file and SUMO seed (D11). Ranking: e13.rank (deadlock-free first; within 0.1 pp lower mean delay).
    The deadlock condition of 5.1 refers to x1.0 and x1.2; at x1.5 it is not applied (counts are reported)."""
    tuned = {"written": now(), "rule": "pre-registration 6.2 with the score of 5.1 on the 20 training files per load",
             "loads": {}, "incomplete": []}
    for load in LOADS:
        base = out / "tune" / load
        if not base.is_dir():
            continue
        n_exp = len(e13.route_files(e13.LOADS[load])) * len(KS)
        fixed = {(int(r["episode"]), int(r["training_run"])): r for r in load_rows(base / "fixed") if r["tripinfo_ok"]}
        cands = []
        for d in sorted(p for p in base.iterdir() if p.is_dir() and p.name.startswith("mp_")):
            mine = [r for r in load_rows(d) if r["tripinfo_ok"]]
            pairs = [(r, fixed.get((int(r["episode"]), int(r["training_run"])))) for r in mine]
            pairs = [(r, f) for r, f in pairs if f is not None]
            if not pairs:
                continue
            v, h = re.match(r"mp_(free|field)_h([\d.]+)$", d.name).groups()
            dem = st.mean(r["demand"] for r, _ in pairs)
            dl = sum(r["deadlock"] for r, _ in pairs)
            cands.append({"variant": v, "h": float(h) if "." in h else int(h), "episodes": len(pairs),
                          "expected": n_exp, "fixed_episodes": len(fixed),
                          "arrived_1800": round(st.mean(r["arrived_1800"] for r, _ in pairs), 2),
                          "fixed_arrived_1800": round(st.mean(f["arrived_1800"] for _, f in pairs), 2),
                          "demand": round(dem, 2),
                          "score": round(100 * st.mean(r["arrived_1800"] - f["arrived_1800"] for r, f in pairs) / dem, 4),
                          "deadlocks": dl, "deadlock": int(dl > 0) if load in ("x1.0", "x1.2") else 0,
                          "delay": round(st.mean(r["mean_delay_s"] for r, _ in pairs), 2),
                          "fixed_delay": round(st.mean(f["mean_delay_s"] for _, f in pairs), 2),
                          "switches_median": st.median([r["switches"] for r, _ in pairs if r["switches"] != ""] or [0])})
        if not cands:
            continue
        ranked = e13.rank(cands)
        complete = (len(cands) == len(H_GRID) * len(VARIANTS) and len(fixed) == n_exp
                    and all(c["episodes"] == n_exp for c in cands))
        write_json(base.parent / f"tuning_{LOAD_TAG[load]}.json", {"load": load, "complete": complete, "ranking": ranked})
        write_csv(base.parent / f"tuning_{LOAD_TAG[load]}.csv", ranked, ["rank", "variant", "h", "score", "deadlock"])
        if complete:
            c = ranked[0]
            tuned["loads"][load] = {k: c[k] for k in ("variant", "h", "score", "deadlock", "deadlocks", "delay",
                                                      "episodes")}
        else:
            tuned["incomplete"].append(f"{load}: {len(cands)} grid points, "
                                       f"{min(c['episodes'] for c in cands)}-{max(c['episodes'] for c in cands)} of "
                                       f"{n_exp} paired episodes each, {len(fixed)} fixed-plan episodes")
    if tuned["loads"]:
        prev = read_json(out / "tune" / "tuned.json")
        if prev and any(prev["loads"].get(l) != c for l, c in tuned["loads"].items() if l in prev["loads"]):
            print("WARNING: tuned.json changes a selection that existed before; check that no evaluation used it")
        write_json(out / "tune" / "tuned.json", tuned)
    return tuned


# ------------------------------------------------------------------ Webster (6.3)
def counts_flows() -> tuple[dict, float]:
    tot, begin, end = {}, math.inf, -math.inf
    for iv in ET.parse(COUNTS).getroot().findall("interval"):
        begin, end = min(begin, float(iv.get("begin"))), max(end, float(iv.get("end")))
        for r in iv.findall("edgeRelation"):
            k = (r.get("from"), r.get("to"))
            tot[k] = tot.get(k, 0) + int(r.get("count"))
    return tot, end - begin


GROUPS = {    # lane group -> (approach edge, lanes, movement directions, phase)
    "SVB_N_through+right": ("nN_nC", (0, 1), ("s", "r"), 0), "SVB_S_through+right": ("nS_nC", (0, 1), ("s", "r"), 0),
    "SVB_N_left": ("nN_nC", (2,), ("l",), 1), "SVB_S_left": ("nS_nC", (2,), ("l",), 1),
    "PRB_E_through+right": ("nE_nC", (0, 1), ("s", "r"), 2), "PRB_W_through+right": ("nW_nC", (0, 1), ("s", "r"), 2),
    "PRB_E_left": ("nE_nC", (2,), ("l",), 3), "PRB_W_left": ("nW_nC", (2,), ("l",), 3)}
APPROACH = {"nN_nC": "SVB_N", "nS_nC": "SVB_S", "nE_nC": "PRB_E", "nW_nC": "PRB_W"}


def cmd_plan(args) -> int:
    """Repository: writes plan/. Kit (Colab): recomputes into <out>/plan_check/ and compares the programs with the
    shipped plan/ (the kit's plans are never overwritten)."""
    sat = read_json(PLAN_DIR / "satflow.json")
    if not sat:
        sys.exit(f"{PLAN_DIR / 'satflow.json'} missing: run 'satflow' on the laptop first")
    target = Path(args.out) / "plan_check" if KIT else PLAN_DIR
    rc = _plan(sat, target)
    if KIT:
        same = all(ET.tostring(ET.parse(target / f"webster_{t}.add.xml").getroot().find("tlLogic"))
                   == ET.tostring(ET.parse(PLAN_DIR / f"webster_{t}.add.xml").getroot().find("tlLogic"))
                   for t in LOAD_TAG.values())
        print("recomputed plans " + ("identical to" if same else "DIFFERENT from") + " the shipped plan/ files")
        rc |= 0 if same else 1
    return rc


def _plan(sat: dict, dest: Path) -> int:
    dirs = {}
    for c in ET.parse(FIXED_NET).getroot().findall("connection"):
        if c.get("tl") == TLS:
            dirs[(c.get("from"), c.get("to"))] = c.get("dir")
    counts, dur = counts_flows()
    tl = ET.parse(FIXED_NET).getroot().find("tlLogic")
    phases = [(int(p.get("duration")), p.get("state")) for p in tl.findall("phase")]
    green_idx = [i for i, (_, s) in enumerate(phases) if s in e13.GREENS]
    lost = sum(d for i, (d, _) in enumerate(phases) if i not in green_idx)
    L = 20.0
    assert lost == L, f"intergreen time of the field program is {lost} s, not 20 s"
    out_all, md = {}, []
    for load in LOADS:
        f = float(load[1:])
        groups = {}
        for g, (edge, lanes, dset, ph) in GROUPS.items():
            n = sum(v for (a, b), v in counts.items() if a == edge and dirs.get((a, b)) in dset)
            q = n * 3600.0 / dur * f
            s = sat["groups"][g]["sat_flow_vph"]
            groups[g] = {"phase": ph, "count_1500s_x1.0": n, "flow_vph": round(q, 1), "sat_flow_vph": s,
                         "y": q / s}
        y = []
        for ph in range(4):
            crit = max((g for g in groups if groups[g]["phase"] == ph), key=lambda g: groups[g]["y"])
            y.append((crit, groups[crit]["y"]))
        Y = sum(v for _, v in y)
        C0 = (1.5 * L + 5) / (1 - Y) if Y < 1 else math.inf
        C = min(150.0, max(60.0, C0))
        raw = [(C - L) * v / Y for _, v in y]
        bounded = [min(MAX_GREEN, max(MIN_GREEN, g)) for g in raw]
        # whole seconds by largest remainder, so that the greens keep the bounded total (cycle stays within 60-150 s)
        greens = [int(math.floor(g)) for g in bounded]
        extra = int(round(sum(bounded))) - sum(greens)
        for i in sorted(range(4), key=lambda i: bounded[i] - greens[i], reverse=True)[:extra]:
            greens[i] += 1
        cycle = sum(greens) + L
        pid = f"webster_{LOAD_TAG[load]}"
        body = []
        for i, (d, s) in enumerate(phases):
            if i in green_idx:
                d = greens[e13.GREENS[s]]
            body.append(f'    <phase duration="{d}" state="{s}"/>')
        xml = (f'<additional>\n  <!-- Webster plan {load} (pre-registration 6.3), s2c.py plan, {now()} -->\n'
               f'  <tlLogic id="{TLS}" type="static" programID="{pid}" offset="0">\n' + "\n".join(body)
               + "\n  </tlLogic>\n</additional>\n")
        write_atomic(dest / f"{pid}.add.xml", xml)
        out_all[load] = {"programID": pid, "L": L, "Y": round(Y, 4), "C0": None if math.isinf(C0) else round(C0, 1),
                         "C0_note": "Y >= 1: formula undefined, upper bound used" if Y >= 1 else "",
                         "C_bounded": round(C, 1), "greens_raw": [round(g, 2) for g in raw], "greens": greens,
                         "cycle": cycle, "critical": [{"phase": ph, "group": g, "y": round(v, 4)}
                                                      for ph, (g, v) in enumerate(y)],
                         "groups": {g: {**v, "y": round(v["y"], 4)} for g, v in groups.items()}}
    write_json(dest / "webster_plans.json", {"written": now(), "inputs": {
        "counts": "sumo/turn_counts_edges.xml", "counts_sha256": sha256(COUNTS), "counted_period_s": dur,
        "satflow": "plan/satflow.json", "satflow_sha256": sha256(PLAN_DIR / "satflow.json"),
        "rules": "C0 = (1.5 L + 5) / (1 - Y), L = 20 s, bounded 60-150 s (Y >= 1: 150 s); greens = (C - L) y_i / Y "
                 "bounded 12-60 s, whole seconds by largest remainder (sum kept); yellow 3 s, all-red 4 s at the two "
                 "street changes (states of the field program)"},
        "plans": out_all})
    md = ["# Webster plans per load (pre-registration 6.3)", "",
          f"Written by `s2c.py plan` on {now()}. Flows: `sumo/turn_counts_edges.xml` (0–{dur:.0f} s) × load, in veh/h. "
          "Saturation flow per lane group: 3600 / median saturated discharge headway in the default twin under the "
          "fixed plan (`plan/satflow.json`: through+right groups from `revision/runs/e8_validation/"
          "sim_discharge_headways.csv`, left groups measured with the same E8 extraction). L = 20 s (4 × 3-s yellow + "
          "2 × 4-s all-red). Phases: 0 Svobody through, 1 Svobody left, 2 Prybuzka through, 3 Prybuzka left.", "",
          "| Lane group | Phase | Count 0–1500 s (×1.0) | s, veh/h | q ×1.0 | y ×1.0 | q ×1.2 | y ×1.2 | q ×1.5 | y ×1.5 |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for g in GROUPS:
        r = [out_all[l]["groups"][g] for l in LOADS]
        md.append(f"| {g} | {r[0]['phase']} | {r[0]['count_1500s_x1.0']} | {r[0]['sat_flow_vph']:.0f} | "
                  + " | ".join(f"{x['flow_vph']:.0f} | {x['y']:.3f}" for x in r) + " |")
    md += ["", "| Load | Critical y (phases 0–3) | Y | C0, s | Cycle bound 60–150, s | Greens raw, s | Greens 12–60, s | "
           "Cycle used, s |", "|---|---|---|---|---|---|---|---|"]
    for l in LOADS:
        p = out_all[l]
        ys = ", ".join("%.3f" % c["y"] for c in p["critical"])
        raw = ", ".join("%.1f" % g for g in p["greens_raw"])
        c0 = "undefined (Y ≥ 1)" if p["C0"] is None else p["C0"]
        md.append(f"| {l} | {ys} | {p['Y']:.3f} | {c0} | {p['C_bounded']:.0f} | {raw} | "
                  f"{', '.join(map(str, p['greens']))} | {p['cycle']:.0f} |")
    write_atomic(dest / "webster_derivation.md", "\n".join(md) + "\n")
    for l in LOADS:
        p = out_all[l]
        print(f"Webster {l}: Y = {p['Y']:.3f}, C0 = {p['C0']}, cycle bound {p['C_bounded']:.0f} s, greens "
              f"{p['greens']} (raw {p['greens_raw']}), cycle used {p['cycle']:.0f} s")
    return 0


# ------------------------------------------------------------------ saturation flow (laptop; E8 runs and rules)
E8_LEAD, E8_SAT_FROM, E8_GAP, E8_FIRST, E8_CYCLES = 1.0, 4, 8.0, 8.0, (2, 12)
SAT_WINDOWS = {"SVB_through": (1, 49.0), "PRB_through": (5, 33.0), "SVB_left": (3, 15.0), "PRB_left": (7, 15.0)}


def satflow_run(job: tuple[str, int, str, str]) -> dict:
    """E8 extraction (revision/tools/e8_validation.py simulate()): stop-line crossings per approach and lane,
    interpolated with the odometer; green onsets = first green second of a link - 1 s."""
    route, seed, add, rid = job
    tc, _ = backend()
    end = 1500.0
    binary = "sumo" if backend()[1] == "libsumo" else e13.sumo_exe()
    tc.start([binary, "-n", str(FIXED_NET), "-r", route, "-a", add, "--begin", "0", "--end", str(int(end)), "--seed",
              str(seed), "--time-to-teleport", "-1", "--no-step-log", "true", "--no-warnings", "true",
              "--duration-log.disable", "true"])
    lanes = {a: [f"{e}_{i}" for i in range(3)] for e, a in APPROACH.items()}
    length = tc.lane.getLength("nN_nC_0")
    last, cross, rises, prev = {}, [], {w: [] for w in SAT_WINDOWS}, {w: None for w in SAT_WINDOWS}
    while tc.simulation.getTime() < end:
        tc.simulationStep()
        t = tc.simulation.getTime()
        s = tc.trafficlight.getRedYellowGreenState(TLS)
        for w, (li, _) in SAT_WINDOWS.items():
            on = s[li] in "Gg"
            if on and prev[w] is False:
                rises[w].append(t - E8_LEAD)
            prev[w] = on
        cur = {}
        for a, ls in lanes.items():
            for li, ln in enumerate(ls):
                for v in tc.lane.getLastStepVehicleIDs(ln):
                    cur[v] = (t, tc.vehicle.getDistance(v), tc.vehicle.getLanePosition(v), a, li)
        alive = None
        for v, (t0, odo0, pos0, a, li) in last.items():
            if v in cur:
                continue
            if alive is None:
                alive = set(tc.vehicle.getIDList())
            if v in alive:
                odo1 = tc.vehicle.getDistance(v)
                frac = (length - pos0) / (odo1 - odo0) if odo1 > odo0 else 1.0
                cross.append((a, li, t0 + min(max(frac, 0.0), 1.0) * (t - t0)))
        last = cur
    tc.close()
    out = []
    for g, (edge, glanes, _, _) in GROUPS.items():
        a = APPROACH[edge]
        w = ("SVB" if a.startswith("SVB") else "PRB") + ("_left" if 2 in glanes else "_through")
        window = SAT_WINDOWS[w][1]
        times = sorted(tc_ for aa, li, tc_ in cross if aa == a and li in glanes)
        for cyc, onset in enumerate(rises[w], 1):
            if not (E8_CYCLES[0] <= cyc <= E8_CYCLES[1]) or onset + window > end:
                continue
            prevc, pos, in_q = None, 0, True
            for tcr in (x for x in times if onset <= x < onset + window):
                if prevc is None:
                    pos, hw, in_q = 1, None, (tcr - onset) <= E8_FIRST
                else:
                    pos, hw = pos + 1, tcr - prevc
                    if tcr - prevc > E8_GAP:
                        in_q = False
                out.append({"run": rid, "group": g, "cycle": cyc, "onset": onset, "position": pos,
                            "t_after_green": round(tcr - onset, 3), "headway": None if hw is None else round(hw, 3),
                            "in_queue": in_q, "saturated": in_q and pos >= E8_SAT_FROM})
                prevc = tcr
    return {"run": rid, "rows": out}


def cmd_satflow(args) -> int:
    if KIT:
        sys.exit("satflow runs on the laptop (needs the E8 demand files); the kit ships plan/satflow.json")
    e8 = HERE.parent / "runs" / "e8_validation"
    meta = read_json(e8 / "run_meta.json")
    add = str(e8 / f"tls_offset_{meta['tls_offset']}.add.xml")
    jobs = [(str(REPO_ROOT / r["route"]), int(r["seed"]), add, r["run"]) for r in meta["runs"]]
    with Pool(max(1, args.jobs)) as pool:
        res = pool.map(satflow_run, jobs)
    rows = [r for x in res for r in x["rows"]]
    groups = {}
    for g in GROUPS:
        hs = [r["headway"] for r in rows if r["group"] == g and r["saturated"] and r["headway"] is not None]
        groups[g] = {"n_saturated_headways": len(hs), "median_headway_s": round(st.median(hs), 4) if hs else None,
                     "mean_headway_s": round(st.mean(hs), 4) if hs else None,
                     "sat_flow_measured_vph": round(3600 / st.median(hs), 1) if hs else None}
    # E8's own file for the through(+right) groups: pooled saturated headways per approach
    e8rows = list(csv.DictReader(open(e8 / "sim_discharge_headways.csv", encoding="utf-8")))
    for g, (edge, glanes, _, _) in GROUPS.items():
        a = APPROACH[edge]
        if 2 in glanes:
            groups[g].update(source="measured here (E8 extraction and rules, left-turn window 15 s)",
                             sat_flow_vph=groups[g]["sat_flow_measured_vph"])
            continue
        hs = [float(r["headway"]) for r in e8rows if r["approach"] == a and r["saturated"] == "True" and r["headway"]]
        med = st.median(hs)
        groups[g].update(e8_n=len(hs), e8_median_headway_s=round(med, 4), sat_flow_vph=round(3600 / med, 1),
                         source="revision/runs/e8_validation/sim_discharge_headways.csv (approach " + a + ")",
                         equal_to_e8=bool(groups[g]["median_headway_s"] is not None
                                          and abs(groups[g]["median_headway_s"] - med) < 1e-9
                                          and groups[g]["n_saturated_headways"] == len(hs)))
    write_csv(PLAN_DIR / "satflow_headways.csv", rows)
    write_json(PLAN_DIR / "satflow.json", {
        "written": now(), "twin": "default (SUMO default vehicle type)", "plan": "field plan, offset 16 (E8)",
        "runs": [{"route": r["route"], "seed": r["seed"]} for r in meta["runs"]], "end_s": 1500,
        "rules": {"lead_s": E8_LEAD, "sat_from_position": E8_SAT_FROM, "gap_split_s": E8_GAP, "first_max_s": E8_FIRST,
                  "cycles": list(E8_CYCLES), "windows_s": {k: v[1] for k, v in SAT_WINDOWS.items()}},
        "e8_files": {"sim_discharge_headways.csv": sha256(e8 / "sim_discharge_headways.csv"),
                     "run_meta.json": sha256(e8 / "run_meta.json")},
        "groups": groups})
    for g, v in groups.items():
        print(f"{g:22s} s = {v['sat_flow_vph']} veh/h  (measured median {v['median_headway_s']} s, n "
              f"{v['n_saturated_headways']}" + (f"; E8 median {v['e8_median_headway_s']} s, n {v['e8_n']}, "
                                                 f"equal {v['equal_to_e8']}" if 'e8_n' in v else "") + ")")
    return 0


# ------------------------------------------------------------------ commands
def check_locked(args) -> None:
    if args.set == "locked":
        if not args.locked_ok:
            sys.exit("the locked test set runs once, after all choices, and only when the lead asks: add --locked-ok")
        if args.limit_files or args.maps or args.k or getattr(args, "mp_config", None):
            sys.exit("the locked set runs complete, with the tuned configuration (no subset options)")
        n = e13.check_locked_files()    # SHA-256 of the 50 files against locked_test_hashes.txt (exits if they differ)
        print(f"locked test files: {n}, hashes match locked_test_hashes.txt")


def locked_marker(out: Path, stage: str, args, jobs: list[dict]) -> None:
    if args.set != "locked":
        return
    p = out / f"locked_{stage}.json"
    m = read_json(p)
    if m and all(is_done(Path(j["dest"])) for j in jobs):
        sys.exit(f"the locked {stage} run is already complete ({p}); it runs once")
    if m and not args.rerun_reason:
        sys.exit(f"the locked {stage} run was started before ({m['started']}) and is incomplete; continue only after a "
                 "technical failure, with --rerun-reason \"<what failed>\" (logged)")
    m = m or {"started": now(), "episodes": len(jobs), "reruns": []}
    if args.rerun_reason:
        m["reruns"].append({"date": now(), "reason": args.rerun_reason})
    write_json(p, m)


def cmd_tune(args) -> int:
    out = Path(args.out)
    jobs = tune_jobs(args, out, twin_info())
    rc = run_pool(jobs, args.jobs, "tune")
    t = finalize_tuning(out)
    for l, c in t["loads"].items():
        print(f"tuned {l}: {c['variant']} order, h = {c['h']} (score {c['score']:+.3f}%, deadlocks {c['deadlocks']}, "
              f"delay {c['delay']} s/veh)")
    for x in t["incomplete"]:
        print(f"tuning incomplete: {x}")
    collect(out)
    return rc


def cmd_eval(args, stage: str, ctrls: tuple[str, ...]) -> int:
    out = Path(args.out)
    check_locked(args)
    jobs = eval_jobs(args, out, twin_info(), ctrls, stage)
    locked_marker(out, stage, args, jobs)
    rc = run_pool(jobs, args.jobs, f"{stage} {args.set}")
    if args.set == "locked":
        m = read_json(out / f"locked_{stage}.json")
        m.update(finished=now(), complete=rc == 0 and all(is_done(Path(j["dest"])) for j in jobs))
        write_json(out / f"locked_{stage}.json", m)
    collect(out)
    return rc


def cmd_b7(args) -> int:
    out = Path(args.out)
    jobs = b7_jobs(args, out, twin_info())
    rc = run_pool(jobs, args.jobs, "b7")
    collect(out)
    return rc


def cmd_e14(args) -> int:
    out = Path(args.out)
    jobs = e14_jobs(args, out, twin_info())
    rc = run_pool(jobs, args.jobs, "e14")
    collect(out)
    return rc


def collect(out: Path) -> None:
    """Tables in <out>/results/ and the SHA-256 manifest of every file in <out>."""
    res = out / "results"
    tables = {"tune_episodes.csv": out / "tune", "eval_episodes.csv": out / "eval", "queue_episodes.csv": out / "queue",
              "b7_episodes.csv": out / "b7", "e14_episodes.csv": out / "e14"}
    series = []
    for name, folder in tables.items():
        rows = []
        for p in sorted(folder.rglob("*.json")) if folder.is_dir() else []:
            if p.name.endswith(".failed.json"):
                continue
            r = read_json(p)
            if not r or r.get("status") != "done":
                continue
            row = dict(r["row"])
            if row.get("tripinfo"):
                row["tripinfo"] = rel_out(p.with_name(row["tripinfo"]), out)
            row.update(seconds=r.get("seconds"), backend=r.get("backend"), result=rel_out(p, out))
            rows.append(row)
            if r.get("queue") is not None:
                series.append({k: row[k] for k in ("policy", "controller_config", "eval_set", "map", "label", "episode",
                                                   "training_run", "sumo_seed") if k in row}
                              | {f"q_{t}": v for t, v in zip(QUEUE_TIMES, r["queue"])})
        write_csv(res / name, rows, FIELDS)
    write_csv(res / "queue_series.csv", series)
    if (out / "tune" / "tuned.json").is_file():
        write_atomic(res / "tuned.json", (out / "tune" / "tuned.json").read_bytes())
    cache_p = out / ".manifest_cache.json"    # (size, mtime) -> sha256, so that Drive files are read once
    cache, new, lines = read_json(cache_p) or {}, {}, []
    for p in sorted(out.rglob("*")):
        if p.is_file() and p.name not in ("MANIFEST.sha256", cache_p.name) and ".tmp" not in p.name:
            r, s = rel_out(p, out), p.stat()
            c = cache.get(r)
            h = c[2] if c and c[0] == s.st_size and c[1] == s.st_mtime_ns else sha256(p)
            new[r] = [s.st_size, s.st_mtime_ns, h]
            lines.append(f"{h}  {r}")
    write_json(cache_p, new)
    write_atomic(out / "MANIFEST.sha256", "\n".join(lines) + "\n")


def expected(out: Path) -> list[tuple[str, int, int, int]]:
    """(stage, expected, done, failed) for the full runs (subset options ignored)."""
    class A:    # full-run arguments
        loads, h, variants, k, limit_files, maps, mp_config, no_tripinfo, b7_only = LOADS, H_GRID, VARIANTS, None, \
            None, None, "free:0", False, None
    rows = []
    twin = ("", None)
    groups = {"tune": tune_jobs(A, out, twin)}
    for s in ("validation", "testA"):
        A.set = s
        groups[f"eval {s}"] = eval_jobs(A, out, twin, ("mp", "webster"), "eval") if (PLAN_DIR / "webster_x10.add.xml").is_file() else []
        groups[f"queue {s}"] = eval_jobs(A, out, twin, ("fixed", "actuated"), "queue")
    groups["b7"] = b7_jobs(A, out, twin)
    groups["e14"] = e14_jobs(A, out, twin) if (PLAN_DIR / "webster_x10.add.xml").is_file() else []
    for name, jobs in groups.items():
        done = sum(is_done(Path(j["dest"])) for j in jobs)
        failed = sum(Path(j["dest"].replace(".json", ".failed.json")).is_file() and not is_done(Path(j["dest"]))
                     for j in jobs)
        rows.append((name, len(jobs), done, failed))
    for stage in ("eval", "queue"):    # the locked set: counted from the result files only (never listed here)
        d = out / stage / "locked"
        n = sum(1 for p in d.rglob("*.json") if not p.name.endswith(".failed.json")) if d.is_dir() else 0
        rows.append((f"{stage} locked", 50 * len(KS) * 2, n, 0))
    return rows


def cmd_status(args) -> int:
    out = Path(args.out)
    print(f"out: {out}  ({'kit' if KIT else 'repository'} layout; e13.py {sha256(E13_DIR / 'e13.py')[:12]})")
    for name, n, done, failed in expected(out):
        print(f"  {name:18s} {done:5d}/{n:<5d} episodes done" + (f", {failed} failed" if failed else ""))
    t = read_json(out / "tune" / "tuned.json")
    if t:
        for l, c in t["loads"].items():
            print(f"  tuned {l}: {c['variant']} order, h = {c['h']} (score {c['score']:+.3f}%)")
    for p in sorted(out.glob("locked_*.json")):
        print(f"  {p.name}: {read_json(p)}")
    secs = {}
    for folder in ("tune", "eval", "queue", "b7", "e14"):
        for p in (out / folder).rglob("*.json") if (out / folder).is_dir() else []:
            r = read_json(p)
            if r and r.get("status") == "done" and "row" in r:
                row = r["row"]
                lab = B7_LOAD.get(row.get("b7_load"), row["label"])
                secs.setdefault((row["policy"], lab), []).append(r["seconds"])
    if secs:
        print("  seconds per episode (median, n):")
        for (pol, lab), v in sorted(secs.items()):
            print(f"    {pol:12s} {lab:5s}: {st.median(v):6.1f} s  (n {len(v)})")
    return 0


# ------------------------------------------------------------------ smoke and checks
def replay_job(job: dict) -> dict:
    """Replay of a RESCO E13 evaluation episode from its metrics_*.csv (green after each decision): the same
    clearance code as run_mp(); the tripinfo must be identical to RESCO's and the queue equal to its 'queue_lengths'."""
    tc, bname = backend()
    rows = []
    for line in Path(job["metrics"]).read_text(encoding="utf-8").splitlines():
        m = re.match(r"^([\d.]+), \{.*?\}, \{.*?\}, \{'nC': (\d+)\}, \{'nC': (\d+)\},\s*$", line)
        if m:
            rows.append((float(m.group(1)), int(m.group(2)), int(m.group(3))))
    work = Path(tempfile.mkdtemp(prefix="s2c_rp_"))
    trip = work / "tripinfo.xml"
    tc.start(sumo_cmd(Path(job["net"]), Path(job["route"]), job["seed"], trip, [], None, resco=True))
    ep = Episode(tc, False, end=math.inf)
    q = QueueLog(tc)
    q.observe()
    green, times_ok, mine = 0, True, []
    tc.trafficlight.setRedYellowGreenState(TLS, GREEN_STATES[0])
    for t_row, _, g in rows:
        if g != green:
            tc.trafficlight.setRedYellowGreenState(TLS, yellow_state(GREEN_STATES[green], GREEN_STATES[g]))
            ep.advance(YELLOW_S)
            if job["allred_every"] or STREET[green] != STREET[g]:
                tc.trafficlight.setRedYellowGreenState(TLS, ALLRED_STATE)
                ep.advance(ALLRED_S)
            tc.trafficlight.setRedYellowGreenState(TLS, GREEN_STATES[g])
            green = g
            ep.advance(STEP_S - YELLOW_S)
        else:
            ep.advance(STEP_S)
        times_ok &= abs(ep.t - t_row) < 1e-9
        mine.append(q.observe())
    tc.close()
    ref_q = [r[1] for r in rows]
    out = {"episode": job["name"], "decisions": len(rows), "times_equal": times_ok,
           "tripinfo_records_identical": e13.records_hash(trip) == e13.records_hash(Path(job["tripinfo"])),
           "queue_equal": mine == ref_q, "queue_differences": sum(a != b for a, b in zip(mine, ref_q)),
           "queue_mean": round(st.mean(mine), 2), "backend": bname}
    shutil.rmtree(work, ignore_errors=True)
    return out


def cmd_smoke(args) -> int:
    """Byte identity of the fixed and actuated episodes with E13's baselines (records hash, i.e. the tripinfo without
    its header comment), signal rules of MaxPressure and Webster from SUMO's own signal-state log (e13.check_tls),
    the queue log, and (repository only) the replay of RESCO E13 episodes."""
    out = Path(args.out)
    twin = twin_info()
    ref = read_json(REF_DIR / "e13_smoke_baseline_hashes.json") or {}
    jobs = []
    route = e13.route_files("prybuzka_va10")[0]
    for ctrl in ("fixed", "actuated"):
        jobs.append(base_job("smoke", ctrl, out / "smoke" / ctrl / "prybuzka_va10" / "e01_k1.json", route, 1, 1,
                             "validation", "prybuzka_va10", "x1.0", twin, True, True))
    for v in VARIANTS:
        jobs.append(base_job("smoke", "mp", out / "smoke" / f"mp_{v}_h4" / "prybuzka_va10" / "e01_k1.json", route, 1,
                             1, "validation", "prybuzka_va10", "x1.0", twin, True, True, variant=v, h=4, tls_log=True))
    for load, m in (("x1.0", "prybuzka_va10"), ("x1.5", "prybuzka_va15")):
        plan, pid = webster_plan(load)
        jobs.append(base_job("smoke", "webster", out / "smoke" / f"webster_{LOAD_TAG[load]}" / m / "e01_k1.json",
                             e13.route_files(m)[0], 1, 1, "validation", m, load, twin, True, True, plan=plan,
                             plan_id=pid, tls_log=True))
    rc = run_pool(jobs, args.jobs, "smoke")
    rep = {"written": now(), "host": platform.node(), "backend": backend()[1], "episodes": [], "checks": []}
    ok_all = rc == 0
    for j in jobs:
        r = read_json(Path(j["dest"])) or {}
        row = r.get("row", {})
        e = {"controller": j["row"]["policy"], "config": row.get("controller_config", ""), "map": j["row"]["map"],
             "seed": j["seed"], "seconds": r.get("seconds"), "arrived_1800": row.get("arrived_1800"),
             "demand": row.get("demand"), "mean_delay_s": row.get("mean_delay_s"), "deadlock": row.get("deadlock"),
             "switches": row.get("switches"), "clearance_s": row.get("clearance_s"),
             "queue_samples": len(r.get("queue") or []), "queue_mean": round(st.mean(r["queue"]), 2) if r.get("queue") else None,
             "records_sha256": r.get("records_sha256")}
        if j["ctrl"] in ("fixed", "actuated"):
            key = f"{'fixed' if j['ctrl'] == 'fixed' else 'actuated'}/prybuzka_va10/k1_e1"
            e["identical_to_e13_baseline"] = (r.get("records_sha256") == ref.get(key)) if key in ref else None
            ok_all &= e["identical_to_e13_baseline"] is not False
        if "signal_rules" in r:
            e["signal_rules"] = r["signal_rules"]
            ok_all &= r["signal_rules"]["n_violations"] == 0 and r["signal_rules"]["greens"] > 10
        ok_all &= e["queue_samples"] == len(QUEUE_TIMES)
        rep["episodes"].append(e)
    if not KIT:    # replay of RESCO E13 smoke evaluations (field order IDQN-queue, free order MPLight)
        ev = E13_DIR / "runs_smoke" / "eval"
        rjobs = []
        for mdl in ("L2_IDQN-queue_x1.0_run1", "L1_MPLight_x1.0_run1"):
            d = ev / mdl / "prybuzka_va10"
            ej = read_json(d / "eval.json")
            folder = e13.run_folder(d)
            if ej and folder:
                ep = ej["episodes"][0]
                rjobs.append({"name": f"{mdl} prybuzka_va10 e1", "metrics": str(folder / "metrics_1.csv"),
                              "tripinfo": str(folder / "tripinfo_1.xml"), "seed": ep["sumo_seed"],
                              "route": str(e13.route_files("prybuzka_va10")[0]),
                              "net": str(e13.BENCH / "environments" / "prybuzka_va10" / "intersection.net.xml"),
                              "allred_every": "e12" in ej["flags"]})
        if rjobs:
            with Pool(min(len(rjobs), max(1, args.jobs))) as pool:
                rep["replay"] = pool.map(replay_job, rjobs)
            ok_all &= all(x["tripinfo_records_identical"] and x["queue_equal"] and x["times_equal"]
                          for x in rep["replay"])
    rep["passed"] = bool(ok_all)
    write_json(out / "smoke" / "smoke_report.json", rep)
    print(json.dumps(rep, indent=1))
    return 0 if ok_all else 1


def cmd_verify_kit(args) -> int:
    man = HERE / "KIT_MANIFEST.sha256"
    if not man.is_file():
        sys.exit("no KIT_MANIFEST.sha256 (verify-kit is for the unzipped kit)")
    bad, n = [], 0
    for line in man.read_text(encoding="utf-8").splitlines():
        h, p = line.split("  ", 1)
        n += 1
        f = HERE / p
        if not f.is_file() or sha256(f) != h:
            bad.append(p)
    print(f"{n} files checked, {len(bad)} differ" + (f": {bad[:10]}" if bad else ""))
    try:
        import libsumo  # noqa: F401
        lib = "libsumo"
    except ImportError:
        lib = "libsumo MISSING (TraCI fallback, slower)"
    print(f"e13.py sha256 {sha256(E13_DIR / 'e13.py')}; twin {e13.twin()['twin']}; {lib}; SUMO {e13.sumo_home()}")
    return 1 if bad else 0


def cmd_kit(args) -> int:
    if KIT:
        sys.exit("kit is built in the repository (revision/s2c)")
    for need in (PLAN_DIR / "webster_x10.add.xml", REF_DIR / "e13_smoke_baseline_hashes.json", HERE / "s2c_colab.ipynb"):
        if not need.is_file():
            sys.exit(f"{need} missing")
    n_locked = e13.check_locked_files()
    root = "s2c_kit"
    files = [(HERE / "s2c.py", "s2c.py"), (HERE / "s2c_colab.ipynb", "s2c_colab.ipynb"),
             (HERE / "DEVIATIONS.md", "DEVIATIONS.md"), (COUNTS, "sumo/turn_counts_edges.xml")]
    files += [(p, f"plan/{p.name}") for p in sorted(PLAN_DIR.iterdir()) if p.is_file()]
    files += [(p, f"ref/{p.name}") for p in sorted(REF_DIR.iterdir()) if p.is_file()]
    for f in ("e13.py", "twin.json", "locked_test_hashes.txt", "baselines/intersection_act.net.xml"):
        files.append((E13_DIR / f, f"e13/{f}"))
    t = e13.twin()
    if t["twin"] == "calibrated":
        files.append((E13_DIR / t["vtype"], f"e13/{t['vtype']}"))
    env = "e13/resco/resco_benchmark/environments"
    files.append((FIXED_NET, f"{env}/prybuzka/intersection.net.xml"))
    maps = list(e13.LOADS.values())
    for s in ("validation", "testA", "locked"):
        maps += list(e13.SETS[s][0].values()) + e13.SETS[s][1]
    for m in maps:
        files += [(p, f"{env}/{m}/routes/{p.name}") for p in e13.route_files(m)]
    files += [(p, f"b7/demand/{p.parent.parent.name}/{p.parent.name}/{p.name}") for *_, p in b7_files()]
    zpath = Path(args.zip) if args.zip else HERE / "s2c_kit.zip"
    manifest = "".join(f"{sha256(src)}  {arc}\n" for src, arc in files)
    tmp = zpath.with_name(zpath.name + ".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for src, arc in files:
            z.write(src, f"{root}/{arc}")
        z.writestr(f"{root}/KIT_MANIFEST.sha256", manifest)
    os.replace(tmp, zpath)
    digest = sha256(zpath)
    write_atomic(zpath.with_name(zpath.name + ".sha256"), f"{digest}  {zpath.name}\n")
    print(f"{zpath}: {len(files)} files ({n_locked} locked-test files, hashes checked), "
          f"{zpath.stat().st_size / 1e6:.1f} MB, sha256 {digest}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = {}
    for name in ("tune", "plan", "eval", "queue", "b7", "e14", "status", "collect", "smoke", "satflow", "kit",
                 "verify-kit"):
        p[name] = sub.add_parser(name)
        p[name].add_argument("--out", default=str(HERE / "out"), help="results folder (default ./out)")
        p[name].add_argument("--jobs", type=int, default=os.cpu_count() or 2, help="parallel SUMO processes")
    for name in ("tune", "eval", "queue", "b7", "e14"):
        p[name].add_argument("--limit-files", type=int, help="smoke tests: first N route files per map")
        p[name].add_argument("--k", type=int, nargs="+", help="smoke tests: seeds k (default 1..5)")
        p[name].add_argument("--no-tripinfo", action="store_true", help="do not keep the gzipped tripinfo files")
    p["tune"].add_argument("--loads", nargs="+", choices=LOADS, default=list(LOADS))
    p["tune"].add_argument("--h", type=float, nargs="+", default=list(H_GRID))
    p["tune"].add_argument("--variants", nargs="+", choices=VARIANTS, default=list(VARIANTS))
    for name in ("eval", "queue"):
        p[name].add_argument("--set", required=True, choices=["validation", "testA", "locked"])
        p[name].add_argument("--maps", nargs="+", help="smoke tests: only these maps")
        p[name].add_argument("--locked-ok", action="store_true", help="confirm the one locked-test run")
        p[name].add_argument("--rerun-reason", help="locked set only: continue after a technical failure")
    for name in ("eval", "b7", "e14"):
        p[name].add_argument("--mp-config", help="smoke tests: VARIANT:H instead of the tuned configuration")
    p["b7"].add_argument("--b7-only", nargs="+", help="e.g. x10/base")
    p["kit"].add_argument("--zip", help="output zip (default ./s2c_kit.zip)")
    args = ap.parse_args()
    if getattr(args, "h", None):
        args.h = [int(x) if float(x).is_integer() else x for x in args.h]
    if args.cmd == "queue":
        args.mp_config = None
    fn = {"tune": cmd_tune, "plan": cmd_plan, "eval": lambda a: cmd_eval(a, "eval", ("mp", "webster")),
          "queue": lambda a: cmd_eval(a, "queue", ("fixed", "actuated")), "b7": cmd_b7, "e14": cmd_e14,
          "status": cmd_status,
          "collect": lambda a: collect(Path(a.out)) or 0, "smoke": cmd_smoke, "satflow": cmd_satflow,
          "kit": cmd_kit, "verify-kit": cmd_verify_kit}[args.cmd]
    return fn(args)


if __name__ == "__main__":
    sys.exit(main())
