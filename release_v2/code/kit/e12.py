#!/usr/bin/env python3
"""E12: retrain the RESCO policies with the field clearance and randomized training demand, then evaluate them
frozen (greedy, no learning) on held-out, scenario and transfer demand.

Run from this folder with the kit's Python (.venv, made by setup.ps1):
  python e12.py verify   identity checks against the reference PC (about 2 min)
  python e12.py bench    training throughput with 1, N/2 and N-1 processes; saves the suggested --workers
  python e12.py train    4 policies x 3 loads x 5 runs x 100 episodes; finished runs are skipped
  python e12.py eval     frozen evaluation of every finished run (held-out, scenarios, transfer), field clearance
  python e12.py status   progress, state (running / finished / stopped) and time left
  python e12.py wait     block until the run ends or --minutes pass, then print the status
  python e12.py pack     results/ (SUMMARY.md and small CSVs, for git) and runs/e12_pack_*.zip
  python e12.py publish  upload the zip (GitHub release, else a pack-* branch) and push results/
  python e12.py all      verify, train, eval, pack; with --publish also publish (run_e12.ps1 does this)

Only one train/eval/all process runs at a time (runs/e12.lock).

Everything restarts safely: run the same command again after a stop. An interrupted training run starts again
from episode 1 (RESCO cannot resume a run); finished runs and evaluations are kept.

Settings (fixed): SUMO 1.26.0 through libsumo (identical results to TraCI), one torch thread per process,
--allred 4 (3 s yellow + 4 s all-red, as in the field), 100 training episodes per run, RESCO hyperparameters
unchanged. Training run k uses torch/numpy/random seed 42 + k and SUMO seed 42 + k + episode; training demand
is 20 routeSampler realizations per load (seeds 3001-3020), one per episode in turn. Evaluation trial = 1000 + k.
"""
from __future__ import annotations

import argparse
import atexit
import bisect
import csv
import ctypes
import hashlib
import json
import os
import platform
import re
import shutil
import statistics as st
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from importlib import metadata
from pathlib import Path

import eval_frozen as ef

KIT = Path(__file__).resolve().parent
RESCO = KIT / "resco"
BENCH = RESCO / "resco_benchmark"
# E12_SMOKE=1: quick end-to-end test (1 run per policy and load, 2 episodes, 1 route file per evaluation map)
SMOKE = bool(os.environ.get("E12_SMOKE"))
RUNS = KIT / ("runs_smoke" if SMOKE else "runs")
TRAIN_DIR = RUNS / "train"
EVAL_DIR = RUNS / "eval"
RESULTS = RUNS / "results" if SMOKE else KIT / "results"
VERIFY = KIT / "verify"
LOG = RUNS / "e12.log"

POLICIES = {"IDQN-wait": "IDQN", "IDQN-queue": "IDQN_pressure", "MPLight": "MPLight",
            "IDQN-pressure": "IDQN_pressure_inout"}
LOADS = {"x1.0": "prybuzka_tr10", "x1.2": "prybuzka_tr12", "x1.5": "prybuzka_tr15"}
COST = {"x1.0": 1.0, "x1.2": 1.45, "x1.5": 2.0}    # relative episode cost, for ordering and estimates only
# mean cost of an evaluation episode (1800 s): per trained policy, own held-out (10 episodes), plus for x1.0
# policies the scenarios (4 x 5) and transfer (2 x 10)
EVAL_COST = (10 * 1.2 + 20 * 1.3 + 2 * (10 * 1.45 + 10 * 2.0)) / 70
TRAIN_RUNS = range(1, 2) if SMOKE else range(1, 6)
EPISODES = 2 if SMOKE else 100
ALLRED = 4
GLOBAL_SEED = 42
EVAL_SETS = ["heldout", "scenarios", "transfer"]
EVAL_CLEARANCE = f"yellow3+allred{ALLRED}"
PINNED = ["eclipse-sumo", "libsumo", "sumo-data", "torch", "pfrl", "gym", "numpy"]
EP_FIELDS = ["policy", "load", "run", "episode", "route_file", "sumo_seed", "tripinfo_ok", "n_entries",
             "n_arrived_1500", "n_arrived_1800", "mean_wait_arrived_s"]


# ------------------------------------------------------------------ helpers
def log(msg: str) -> None:
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S}  {msg}"
    print(line, flush=True)
    RUNS.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def sumo_home() -> str:
    import sumo    # the eclipse-sumo wheel of this environment, never a system-wide SUMO
    return sumo.SUMO_HOME


def child_env() -> dict:
    env = os.environ.copy()
    env.update(PYTHONPATH=str(RESCO), SUMO_HOME=sumo_home(), LIBSUMO_AS_TRACI="1", OMP_NUM_THREADS="1",
               MKL_NUM_THREADS="1", RESCO_NO_BEEP="1",
               CUDA_VISIBLE_DEVICES="")    # RESCO uses a GPU when torch sees one; E12 runs on the CPU
    return env


def keep_awake() -> None:
    """Ask Windows not to sleep while this process runs (no setting is changed; ends with the process)."""
    if os.name == "nt":
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)


def records_hash(path: Path) -> str:
    """SHA-256 of a SUMO output without its comments (date, paths): equal hashes mean identical results."""
    text = re.sub(r"<!--.*?-->", "", path.read_text(encoding="utf-8"), flags=re.S)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(KIT).as_posix()
    except ValueError:
        return path.as_posix()


def run_folder(log_dir: Path) -> Path | None:
    return ef.newest_run_folder(log_dir)


def episodes_in(folder: Path | None) -> int:
    return ef.episodes_in(folder) if folder else 0


def main_cmd(agent: str, map_name: str, trial: int, eps: int, log_dir: Path, allred: int,
             seed: int | None = None, ckpt: Path | None = None) -> list[str]:
    cmd = [sys.executable, "main.py", "--agent", agent, "--map", map_name, "--tr", str(trial), "--eps", str(eps),
           "--procs", "1", "--allred", str(allred), "--libsumo", "True", "--log_dir", str(log_dir) + os.sep]
    if seed is not None:
        cmd += ["--seed", str(seed)]
    if ckpt is not None:
        cmd += ["--ckpt", str(ckpt)]
    return cmd


def run_main(cmd: list[str], log_dir: Path) -> int:
    log_dir.mkdir(parents=True, exist_ok=True)
    with (log_dir / "main.log").open("w", encoding="utf-8") as f:
        return subprocess.run(cmd, cwd=BENCH, env=child_env(), stdout=f, stderr=subprocess.STDOUT).returncode


def versions() -> dict:
    out = {"python": sys.version.split()[0], "platform": platform.platform(), "machine": platform.machine(),
           "processor": platform.processor(), "logical_cpus": os.cpu_count(), "host": platform.node()}
    for p in PINNED:
        try:
            out[p] = metadata.version(p)
        except metadata.PackageNotFoundError:
            out[p] = "missing"
    return out


def default_workers() -> int:
    bench = RUNS / "bench.json"
    if bench.is_file():
        return json.loads(bench.read_text(encoding="utf-8"))["suggested_workers"]
    return max(1, (os.cpu_count() or 2) - 1)


def pool(tasks: list[tuple[str, callable]], workers: int, what: str) -> list[dict]:
    t0, out = time.time(), []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(fn): name for name, fn in tasks}
        for i, fut in enumerate(as_completed(futures), 1):
            try:
                info = fut.result()
            except Exception as e:    # keep the other jobs running
                info = {"status": f"FAILED ({e!r})"}
            out.append(info)
            el = time.time() - t0
            log(f"{what} [{i}/{len(tasks)}] {futures[fut]}: {info['status']}"
                + (f", {info['minutes']:.1f} min" if "minutes" in info else "")
                + f"  (elapsed {el / 3600:.2f} h)")
    return out


# ------------------------------------------------------------------ verify
def verify(args: argparse.Namespace) -> int:
    ref_path = VERIFY / "reference.json"
    vdir = RUNS / "verify"
    if vdir.exists():
        shutil.rmtree(vdir)
    v = versions()
    log("verify: " + ", ".join(f"{p} {v[p]}" for p in PINNED) + f"; Python {v['python']}; {v['platform']}")
    got: dict[str, str] = {}

    # 1. SUMO alone: the fixed signal plan of the network, x1.0 demand, 1500 s, seed 1
    env_dir = BENCH / "environments" / "prybuzka"
    trip = vdir / "fixed" / "tripinfo.xml"
    trip.parent.mkdir(parents=True)
    exe = Path(sumo_home()) / "bin" / ("sumo.exe" if os.name == "nt" else "sumo")
    subprocess.run([str(exe), "-n", str(env_dir / "intersection.net.xml"), "-r", str(env_dir / "routes" / "gen_1.rou.xml"),
                    "--end", "1500", "--seed", "1", "--tripinfo-output", str(trip), "--no-step-log", "true"],
                   check=True, capture_output=True)
    got["fixed_plan"] = records_hash(trip)

    # 2. an original trained policy (IDQN-queue, x1.0, run 4), frozen, 2 held-out episodes, yellow only
    pdir = vdir / "policy"
    run_main(main_cmd("IDQN_pressure", "prybuzka_ho10", 1004, 2, pdir, 0, ckpt=VERIFY / "idqn_queue_x10_run4.pt"), pdir)
    folder = run_folder(pdir)
    for e in (1, 2):
        p = folder / f"tripinfo_{e}.xml" if folder else None
        got[f"policy_ep{e}"] = records_hash(p) if p and p.is_file() else "missing"

    # 3. training repeatability on this machine: the same 2-episode training run twice
    tasks = []
    for tag in ("A", "B"):
        d = vdir / f"train{tag}"
        tasks.append((d, main_cmd("IDQN_pressure_inout", "prybuzka_tr10", 1, 2, d, ALLRED, seed=GLOBAL_SEED + 1)))
    with ThreadPoolExecutor(max_workers=2) as ex:
        list(ex.map(lambda t: run_main(t[1], t[0]), tasks))
    for tag in ("A", "B"):
        folder = run_folder(vdir / f"train{tag}")
        for e in (1, 2):
            p = folder / f"tripinfo_{e}.xml" if folder else None
            got[f"train{tag}_ep{e}"] = records_hash(p) if p and p.is_file() else "missing"

    if args.write_reference:
        ref = {"written": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "versions": v, "hashes": got}
        ref_path.write_text(json.dumps(ref, indent=2), encoding="utf-8")
        log(f"verify: reference written to {rel(ref_path)}")
        return 0

    ref = json.loads(ref_path.read_text(encoding="utf-8"))["hashes"]
    checks = [
        ("SUMO fixed plan identical to the reference PC", got["fixed_plan"] == ref["fixed_plan"], True),
        ("original policy, 2 frozen episodes identical to the reference PC",
         all(got[f"policy_ep{e}"] == ref[f"policy_ep{e}"] for e in (1, 2)), False),
        ("training repeatable on this PC (same seed twice)",
         all(got[f"trainA_ep{e}"] == got[f"trainB_ep{e}"] != "missing" for e in (1, 2)), False),
        ("training identical to the reference PC (information only)",
         all(got[f"trainA_ep{e}"] == ref[f"trainA_ep{e}"] for e in (1, 2)), None),
    ]
    blocking = False
    for text, ok, required in checks:
        log(f"verify: {'OK  ' if ok else ('FAIL' if required is not None else 'no  ')}  {text}")
        blocking |= bool(required) and not ok
    (RUNS / "verify.json").write_text(json.dumps({"versions": v, "hashes": got, "reference": ref,
                                                  "checks": [(t, ok) for t, ok, _ in checks]}, indent=2), encoding="utf-8")
    if not checks[1][1] or not checks[2][1]:
        log("verify: a non-blocking check differs; E12 can still run (train and evaluate on this PC only), "
            "but report it (runs/verify.json)")
    return 1 if blocking else 0


# ------------------------------------------------------------------ bench
def bench(args: argparse.Namespace) -> int:
    n = os.cpu_count() or 2
    counts = sorted({int(x) for x in args.workers_list.split(",")} if args.workers_list else {1, max(2, n // 2), max(2, n - 1)})
    bdir = RUNS / "bench"
    results = []
    for k in counts:
        if bdir.exists():
            shutil.rmtree(bdir)
        tasks = [(bdir / f"p{i}", main_cmd("IDQN_pressure_inout", "prybuzka_tr10", 100 + i, 3, bdir / f"p{i}", ALLRED,
                                           seed=GLOBAL_SEED + 100 + i)) for i in range(k)]
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=k) as ex:
            codes = list(ex.map(lambda t: run_main(t[1], t[0]), tasks))
        wall = time.time() - t0
        ok = all(c == 0 for c in codes) and all(episodes_in(run_folder(d)) == 3 for d, _ in tasks)
        rate = 3 * k / wall
        results.append({"processes": k, "seconds": round(wall, 1), "episodes_per_s": round(rate, 3), "ok": ok})
        log(f"bench: {k:2d} processes x 3 episodes: {wall:.0f} s, {rate:.2f} episodes/s" + ("" if ok else "  (FAILED)"))
    shutil.rmtree(bdir, ignore_errors=True)
    good = [r for r in results if r["ok"]]
    if not good:
        log("bench: every test failed; see runs/bench/*/main.log")
        return 1
    best = max(good, key=lambda r: r["episodes_per_s"])
    # prefer fewer processes when they are within 5% of the best rate
    best = min((r for r in good if r["episodes_per_s"] >= 0.95 * best["episodes_per_s"]), key=lambda r: r["processes"])
    train_eq = len(POLICIES) * len(TRAIN_RUNS) * EPISODES * sum(COST.values())
    eval_eq = len(POLICIES) * len(TRAIN_RUNS) * 70 * EVAL_COST
    hours = (train_eq + eval_eq) / best["episodes_per_s"] / 3600
    out = {"written": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "results": results,
           "suggested_workers": best["processes"], "estimated_hours_all": round(hours, 1), "versions": versions()}
    (RUNS / "bench.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    log(f"bench: suggested --workers {best['processes']}; estimated time for train + eval: about {hours:.1f} h")
    return 0


# ------------------------------------------------------------------ train
def train_job(policy: str, load: str, run: int) -> dict:
    name = f"{policy}_{load}_run{run}"
    job = TRAIN_DIR / name
    if (job / "done.json").is_file():
        return {"status": "already done"}
    if job.exists():
        shutil.rmtree(job)
    seed = GLOBAL_SEED + run
    started = datetime.now()
    t0 = time.time()
    # --save_freq: RESCO saves the final checkpoint when the episode number is a multiple of it
    rc = run_main(main_cmd(POLICIES[policy], LOADS[load], run, EPISODES, job, ALLRED, seed=seed)
                  + ["--save_freq", str(EPISODES)], job)
    minutes = (time.time() - t0) / 60
    folder = run_folder(job)
    n = episodes_in(folder)
    m = ef.RUN_RE.match(folder.name) if folder else None
    ckpt = ef.checkpoint_of(folder, m["alg"]) if m else None
    routes = ef.route_files(RESCO, LOADS[load])
    rows = []
    for e in range(1, n + 1):
        rec = {"policy": policy, "load": load, "run": run, "episode": e, "route_file": routes[(e - 1) % len(routes)].name,
               "sumo_seed": GLOBAL_SEED + run + e}
        rec.update(ef.tripinfo_stats(folder / f"tripinfo_{e}.xml"))
        rows.append(rec)
    with (job / "episodes.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=EP_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    ok = rc == 0 and n == EPISODES and ckpt is not None and ckpt.is_file()
    info = {"status": "done" if ok else f"FAILED (exit {rc}, {n} episodes; see {rel(job / 'main.log')})",
            "policy": policy, "agent": POLICIES[policy], "load": load, "map": LOADS[load], "run": run,
            "seed": seed, "sumo_seeds": f"{GLOBAL_SEED + run + 1}-{GLOBAL_SEED + run + EPISODES}",
            "allred": ALLRED, "episodes": n, "returncode": rc, "minutes": round(minutes, 2),
            "started": started.strftime("%Y-%m-%d %H:%M:%S"), "finished": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "run_folder": rel(folder) if folder else "", "checkpoint": rel(ckpt) if ckpt else "",
            "checkpoint_sha256": file_hash(ckpt) if ok else ""}
    (job / ("done.json" if ok else "failed.json")).write_text(json.dumps(info, indent=2), encoding="utf-8")
    return info


def train(args: argparse.Namespace) -> int:
    take_lock("train")
    keep_awake()
    jobs = sorted(((p, l, r) for p in POLICIES for l in LOADS for r in TRAIN_RUNS), key=lambda j: (-COST[j[1]], j[2], j[0]))
    if args.only_policy:
        jobs = [j for j in jobs if j[0] in args.only_policy]
    todo = [j for j in jobs if not (TRAIN_DIR / f"{j[0]}_{j[1]}_run{j[2]}" / "done.json").is_file()]
    log(f"train: {len(jobs)} runs, {len(jobs) - len(todo)} already done, {len(todo)} to run with {args.workers} processes")
    infos = pool([(f"{p} {l} run {r}", (lambda p=p, l=l, r=r: train_job(p, l, r))) for p, l, r in todo],
                 args.workers, "train")
    failed = [i for i in infos if not i["status"].startswith(("done", "already"))]
    log(f"train: finished; {len(failed)} failed" + ("" if not failed else " (run 'train' again to retry them)"))
    return 1 if failed else 0


# ------------------------------------------------------------------ eval
def write_checkpoints() -> Path:
    rows = []
    for done in sorted(TRAIN_DIR.glob("*/done.json")):
        i = json.loads(done.read_text(encoding="utf-8"))
        rows.append({"selected": 1, "policy": i["policy"], "agent": i["agent"], "train_map": i["map"],
                     "train_load": i["load"], "training_run": i["run"], "episodes": i["episodes"],
                     "checkpoint": (KIT / i["checkpoint"]).as_posix(), "checkpoint_exists": 1,
                     "run_folder": (KIT / i["run_folder"]).as_posix(), "folder_mtime": i["finished"], "note": ""})
    path = RUNS / "checkpoints_e12.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=ef.CKPT_FIELDS)
        w.writeheader()
        w.writerows(rows)
    return path


def eval_cmd(ckpts: Path, *extra: str) -> list[str]:
    return [sys.executable, "eval_frozen.py", "run", "--checkpoints", str(ckpts), "--out-dir", str(EVAL_DIR),
            "--sets", *EVAL_SETS, "--allred", str(ALLRED), "--libsumo", "--python", sys.executable, *extra] + (
        ["--max-eps", "1"] if SMOKE else [])


def eval_job(ckpts: Path, policy: str, load: str, run: int) -> dict:
    t0 = time.time()
    logf = RUNS / "eval_logs" / f"{policy}_{load}_run{run}.log"
    logf.parent.mkdir(parents=True, exist_ok=True)
    cmd = eval_cmd(ckpts, "--only-policy", policy, "--only-load", load, "--only-run", str(run),
                   "--skip-existing", "--keep-going", "--no-table")
    with logf.open("w", encoding="utf-8") as f:
        rc = subprocess.run(cmd, cwd=KIT, env=child_env(), stdout=f, stderr=subprocess.STDOUT).returncode
    return {"status": "done" if rc == 0 else f"FAILED (exit {rc}; see {rel(logf)})", "minutes": (time.time() - t0) / 60}


def evaluate(args: argparse.Namespace) -> int:
    take_lock("eval")
    keep_awake()
    ckpts = write_checkpoints()
    with ckpts.open(newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if not args.only_policy or r["policy"] in args.only_policy]
    if not rows:
        log("eval: no finished training runs")
        return 1
    rows.sort(key=lambda r: (r["train_load"] != "x1.0", r["policy"], int(r["training_run"])))    # x1.0 runs have 5 sets
    log(f"eval: {len(rows)} trained policies, {args.workers} processes, clearance {EVAL_CLEARANCE}")
    infos = pool([(f"{r['policy']} {r['train_load']} run {r['training_run']}",
                   (lambda r=r: eval_job(ckpts, r["policy"], r["train_load"], int(r["training_run"])))) for r in rows],
                 args.workers, "eval")
    with (RUNS / "eval_logs" / "collect.log").open("w", encoding="utf-8") as f:
        subprocess.run(eval_cmd(ckpts, "--collect-only"), cwd=KIT, env=child_env(), stdout=f, stderr=subprocess.STDOUT)
    table = EVAL_DIR / EVAL_CLEARANCE / "E3_runs.csv"
    with table.open(newline="", encoding="utf-8") as f:
        recs = list(csv.DictReader(f))
    done = sum(r["tripinfo_ok"] == "1" for r in recs)
    log(f"eval: {done}/{len(recs)} evaluation episodes done -> {rel(table)}")
    return 0 if done == len(recs) and all(i["status"] == "done" for i in infos) else 1


# ------------------------------------------------------------------ run state, status, wait
LOCK = RUNS / "e12.lock"
FINISHED = RUNS / "e12_finished.json"


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def pid_alive(pid: int) -> bool:
    if os.name == "nt":    # never os.kill(pid, 0) here: on Windows it terminates the process
        k32 = ctypes.windll.kernel32
        handle = k32.OpenProcess(0x1000, False, pid)    # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        ok = k32.GetExitCodeProcess(handle, ctypes.byref(code))
        k32.CloseHandle(handle)
        return bool(ok) and code.value == 259    # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def read_lock() -> dict | None:
    """The lock of a live train/eval/all process, or None."""
    try:
        lock = json.loads(LOCK.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return lock if pid_alive(int(lock["pid"])) else None


def release_lock() -> None:
    try:
        if json.loads(LOCK.read_text(encoding="utf-8"))["pid"] == os.getpid():
            LOCK.unlink()
    except (OSError, ValueError):
        pass


def take_lock(cmd: str) -> None:
    lock = read_lock()
    if lock and lock["pid"] == os.getpid():
        return
    if lock:
        sys.exit(f"E12 is already running ({lock['cmd']}, pid {lock['pid']}, since {lock['started']}); see 'status'")
    RUNS.mkdir(parents=True, exist_ok=True)
    FINISHED.unlink(missing_ok=True)
    LOCK.write_text(json.dumps({"pid": os.getpid(), "cmd": cmd, "started": now(), "start_ts": time.time(),
                                "cost_at_start": progress()["cost_done"]}), encoding="utf-8")
    atexit.register(release_lock)


def progress() -> dict:
    p = dict(train_runs=0, train_done=0, train_failed=0, train_eps=0, eval_eps=0, eval_total=0, cost_done=0.0,
             cost_total=0.0)
    for pol in POLICIES:
        for load in LOADS:
            for r in TRAIN_RUNS:
                job = TRAIN_DIR / f"{pol}_{load}_run{r}"
                p["train_runs"] += 1
                if (job / "done.json").is_file():
                    p["train_done"] += 1
                    n = EPISODES
                else:
                    p["train_failed"] += (job / "failed.json").is_file()
                    n = episodes_in(run_folder(job)) if job.is_dir() else 0
                p["train_eps"] += n
                p["cost_done"] += n * COST[load]
                p["cost_total"] += EPISODES * COST[load]
    p["eval_total"] = len(POLICIES) * len(TRAIN_RUNS) * (9 if SMOKE else 70)
    edir = EVAL_DIR / EVAL_CLEARANCE
    p["eval_eps"] = len(list(edir.glob("*/*/*/tripinfo_*.xml"))) if edir.is_dir() else 0
    p["cost_done"] += p["eval_eps"] * EVAL_COST
    p["cost_total"] += p["eval_total"] * EVAL_COST
    return p


def state() -> str:
    if read_lock():
        return "running"
    return "finished" if FINISHED.is_file() else "stopped"


def status(args: argparse.Namespace) -> int:
    p = progress()
    print(f"training:   {p['train_done']}/{p['train_runs']} runs done, {p['train_failed']} failed, "
          f"{p['train_eps']}/{p['train_runs'] * EPISODES} episodes")
    print(f"evaluation: {p['eval_eps']}/{p['eval_total']} episodes written")
    pct = 100 * p["cost_done"] / p["cost_total"]
    lock = read_lock()
    if lock:
        el = time.time() - lock["start_ts"]
        rate = (p["cost_done"] - lock["cost_at_start"]) / el if el > 60 else 0
        left = f", about {(p['cost_total'] - p['cost_done']) / rate / 3600:.1f} h left (estimate)" if rate > 0 else ""
        print(f"state: RUNNING ({lock['cmd']}, pid {lock['pid']}, since {lock['started']}); about {pct:.0f}% done{left}")
    elif FINISHED.is_file():
        f = json.loads(FINISHED.read_text(encoding="utf-8"))
        print(f"state: FINISHED at {f['finished']}: {f['summary']}" + ("; published" if f.get("published") else ""))
    else:
        print(f"state: NOT RUNNING, about {pct:.0f}% done" + (" (start it again to continue)" if pct > 0 else ""))
    if LOG.is_file():
        lines = LOG.read_text(encoding="utf-8").splitlines()
        print("last log lines:\n  " + "\n  ".join(lines[-4:]))
    return 0


def wait(args: argparse.Namespace) -> int:
    """Block until the run ends or the time is up, then print the status (one check per minute)."""
    end = time.time() + args.minutes * 60
    while state() == "running" and time.time() < end:
        time.sleep(min(60.0, max(1.0, end - time.time())))
    status(args)
    print(f"E12 state: {state()}")
    return 0


def running(args: argparse.Namespace) -> int:
    return 0 if read_lock() else 1


# ------------------------------------------------------------------ summary, pack, publish
def episode_metrics(path: Path, end: float = 1800.0) -> dict:
    dep, arr, wait_s = [], [], []
    for _, el in ET.iterparse(path):
        if el.tag == "tripinfo":
            dep.append(float(el.get("depart")))
            arr.append(float(el.get("arrival")))
            wait_s.append(float(el.get("waitingTime")))
            el.clear()
    done = sorted(a for a in arr if a >= 0)
    events = sorted(dep)
    longest, prev = 0.0, None    # longest interval without an arrival while vehicles are in the network
    for i, t in enumerate(done + [end]):
        start = prev if prev is not None else (events[0] if events else 0.0)
        if bisect.bisect_right(events, start) - i > 0:
            longest = max(longest, t - start)
        prev = t
    aw = [w for w, a in zip(wait_s, arr) if a >= 0]
    return {"entries": len(arr), "arrived_1500": sum(0 <= a <= 1500 for a in arr),
            "arrived_1800": sum(0 <= a <= 1800 for a in arr), "unfinished": sum(a < 0 for a in arr),
            "mean_wait_arrived_s": round(st.mean(aw), 2) if aw else "", "longest_no_arrival_s": round(longest, 1)}


_demand: dict[tuple[str, str], int] = {}


def demand(map_name: str, route_file: str) -> int:
    if (map_name, route_file) not in _demand:
        text = (BENCH / "environments" / map_name / "routes" / route_file).read_text(encoding="utf-8")
        _demand[(map_name, route_file)] = len(re.findall(r"<(?:vehicle|trip)\s", text))
    return _demand[(map_name, route_file)]


def write_summary() -> None:
    """results/eval_episodes.csv (harmonized per-episode metrics) and results/SUMMARY.md."""
    table = EVAL_DIR / EVAL_CLEARANCE / "E3_runs.csv"
    rows = []
    if table.is_file():
        with table.open(newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r["tripinfo_ok"] != "1":
                    continue
                m = episode_metrics(Path(r["tripinfo_path"]))
                dem = demand(r["map"], r["route_file"])
                m.update(demand=dem, not_inserted=dem - m["entries"], full=int(m["entries"] >= 0.99 * dem),
                         deadlock=int(m["longest_no_arrival_s"] >= 300))
                rows.append({k: r[k] for k in ("policy", "train_load", "training_run", "eval_set", "map",
                                               "load_or_scenario", "episode", "route_file", "sumo_seed")} | m)
    if rows:
        with (RESULTS / "eval_episodes.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    p = progress()
    md = [f"# E12 summary ({platform.node()}, {now()})", "",
          f"Training runs done: {p['train_done']}/{p['train_runs']} ({p['train_failed']} failed). Evaluation episodes "
          f"analysed: {len(rows)}/{p['eval_total']}. Settings: README.md. Computed from the files in `runs/` by "
          "`e12.py pack`; the full analysis is done on the main PC.", "",
          "Full = at least 99% of the route file's vehicles entered the network by 1800 s. Deadlock = no arrival for at "
          "least 300 s while vehicles are in the network. Not inserted = demand minus vehicles that entered. All "
          "evaluation episodes last 1800 s and use the field clearance (3 s yellow + 4 s all-red).", "",
          "## Frozen evaluation", "",
          "| Set | Policy | Episodes | Full | Deadlocks | Arrived by 1500 s (mean) | Arrived by 1800 s (median / mean) | "
          "Not inserted (mean) | Unfinished (mean) | Mean wait of arrived, s (median) | Demand (mean) |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    groups: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        name = {"heldout": f"held-out {r['load_or_scenario']}", "transfer": f"transfer {r['load_or_scenario']}"}.get(
            r["eval_set"], f"scenario {r['load_or_scenario']}")
        groups.setdefault((name, r["policy"]), []).append(r)
    order = ["held-out x1.0", "held-out x1.2", "held-out x1.5", "scenario S1", "scenario S2", "scenario S3",
             "scenario S4", "transfer x1.2", "transfer x1.5"]
    for name in order:
        for pol in POLICIES:
            rr = groups.get((name, pol))
            if not rr:
                continue
            waits = [r["mean_wait_arrived_s"] for r in rr if r["mean_wait_arrived_s"] != ""]
            md.append(f"| {name} | {pol} | {len(rr)} | {100 * sum(r['full'] for r in rr) / len(rr):.0f}% | "
                      f"{sum(r['deadlock'] for r in rr)} | {st.mean(r['arrived_1500'] for r in rr):.0f} | "
                      f"{st.median(r['arrived_1800'] for r in rr):.0f} / {st.mean(r['arrived_1800'] for r in rr):.0f} | "
                      f"{st.mean(r['not_inserted'] for r in rr):.0f} | {st.mean(r['unfinished'] for r in rr):.0f} | "
                      f"{st.median(waits) if waits else float('nan'):.1f} | {st.mean(r['demand'] for r in rr):.0f} |")
    md += ["", f"## Training (last 10 of {EPISODES} episodes of each run, online learning on)", "",
           "| Policy | Load | Runs | Entered (mean) | Arrived by the end (mean) | Demand |", "|---|---|---|---|---|---|"]
    train_rows = []
    for f in sorted(TRAIN_DIR.glob("*/episodes.csv")):
        with f.open(newline="", encoding="utf-8") as fh:
            train_rows += [r for r in csv.DictReader(fh)
                           if int(r["episode"]) > EPISODES - 10 and r["tripinfo_ok"] == "1"]
    for pol in POLICIES:
        for load, map_name in LOADS.items():
            rr = [r for r in train_rows if r["policy"] == pol and r["load"] == load]
            if not rr:
                continue
            key = "n_arrived_1500" if load == "x1.0" else "n_arrived_1800"
            dem = st.mean(demand(map_name, r["route_file"]) for r in rr)
            md.append(f"| {pol} | {load} | {len({r['run'] for r in rr})} | "
                      f"{st.mean(int(r['n_entries']) for r in rr):.0f} | {st.mean(int(r[key]) for r in rr):.0f} | {dem:.0f} |")
    (RESULTS / "SUMMARY.md").write_text("\n".join(md) + "\n", encoding="utf-8")


def pack(args: argparse.Namespace) -> int:
    if RESULTS.exists():
        shutil.rmtree(RESULTS)
    RESULTS.mkdir(parents=True)
    dones = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(TRAIN_DIR.glob("*/done.json"))]
    if dones:
        with (RESULTS / "train_runs.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=[k for k in dones[0] if k != "status"], extrasaction="ignore")
            w.writeheader()
            w.writerows(dones)
    with (RESULTS / "train_episodes.csv").open("w", newline="", encoding="utf-8") as out:
        w = csv.DictWriter(out, fieldnames=EP_FIELDS)
        w.writeheader()
        for p in sorted(TRAIN_DIR.glob("*/episodes.csv")):
            with p.open(newline="", encoding="utf-8") as f:
                w.writerows(csv.DictReader(f))
    table = EVAL_DIR / EVAL_CLEARANCE / "E3_runs.csv"
    if table.is_file():
        text = table.read_text(encoding="utf-8").replace(KIT.as_posix() + "/", "")
        (RESULTS / "eval_runs.csv").write_text(text, encoding="utf-8")
        shutil.copy2(table.with_name("E3_runs_meta.json"), RESULTS / "eval_runs_meta.json")
    for name in ("verify.json", "bench.json", "e12.log", "checkpoints_e12.csv"):
        if (RUNS / name).is_file():
            text = (RUNS / name).read_text(encoding="utf-8").replace(KIT.as_posix() + "/", "")
            (RESULTS / name).write_text(text, encoding="utf-8")
    (RESULTS / "environment.json").write_text(json.dumps(versions(), indent=2), encoding="utf-8")
    write_summary()

    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    zpath = RUNS / f"e12_pack_{platform.node()}_{stamp}.zip"
    n = 0
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for p in sorted(RESULTS.iterdir()):
            z.write(p, f"results/{p.name}")
            n += 1
        final = {(KIT / d["checkpoint"]).resolve() for d in dones}    # the one final checkpoint per run
        for job in sorted(TRAIN_DIR.glob("*")):
            for p in sorted(job.rglob("*")):
                if p.is_file() and (p.suffix in (".json", ".log") or p.resolve() in final or p.name == "episodes.csv"
                                    or p.name.startswith("metrics_") or p.name == f"tripinfo_{EPISODES}.xml"):
                    z.write(p, rel(p))
                    n += 1
        for p in sorted(EVAL_DIR.rglob("*")) if EVAL_DIR.is_dir() else []:
            if p.is_file() and p.suffix != ".pt":    # evaluation folders only hold copies of the frozen checkpoint
                z.write(p, rel(p))
                n += 1
    log(f"pack: results/ written (SUMMARY.md); {zpath.name}: {n} files, {zpath.stat().st_size / 1e6:.0f} MB")
    return 0


def git(*a: str, cwd: Path = KIT, capture: bool = False, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *a], cwd=cwd, check=check, text=True, capture_output=capture)


def git_ident() -> list[str]:
    """Commit identity: the user's git config, else a neutral one for these commits only."""
    if git("config", "user.email", capture=True, check=False).stdout.strip():
        return []
    return ["-c", "user.name=E12 runner", "-c", f"user.email=e12@{platform.node()}.invalid"]


def push_pack_branch(z: Path, stamp: str, digest: str) -> str:
    """Without the GitHub CLI: push the zip in 95-MB parts to a new branch (GitHub refuses files over 100 MB)."""
    url = git("remote", "get-url", "origin", capture=True).stdout.strip()
    branch = f"pack-{stamp}"
    tmp = RUNS / f"pack_branch_{stamp}"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir()
    n = 0
    with z.open("rb") as f:
        while chunk := f.read(95 * 1024 * 1024):
            n += 1
            (tmp / f"{z.name}.part{n:02d}").write_bytes(chunk)
    (tmp / "README.txt").write_text(
        f"Join the parts in order to get {z.name} (sha256 {digest}):\n"
        f"  Git Bash:   cat {z.name}.part* > {z.name}\n"
        f"  PowerShell: cmd /c copy /b {'+'.join(f'{z.name}.part{i:02d}' for i in range(1, n + 1))} {z.name}\n",
        encoding="utf-8")
    git("init", "-q", "-b", branch, cwd=tmp)
    git("add", ".", cwd=tmp)
    git(*git_ident(), "commit", "-q", "-m", f"E12 pack {stamp}", cwd=tmp)
    git("push", "-q", url, branch, cwd=tmp)
    shutil.rmtree(tmp, ignore_errors=True)
    return f"git branch {branch} ({n} parts)"


def publish(args: argparse.Namespace) -> int:
    """Upload the newest pack zip (GitHub release, else a branch) and push results/ to the main branch."""
    lock = read_lock()
    if lock and lock["pid"] != os.getpid():
        sys.exit("E12 is still running; publish after it has finished")
    zips = sorted(RUNS.glob("e12_pack_*.zip"), key=lambda p: p.stat().st_mtime)
    if SMOKE or not zips or not (RESULTS / "SUMMARY.md").is_file():
        sys.exit("nothing to publish: run 'pack' first (a smoke test is never published)")
    z = zips[-1]
    stamp = re.search(r"_(\d{8}_\d{4})\.zip$", z.name).group(1)
    digest = file_hash(z)
    uploaded = RUNS / "uploaded.json"    # a retried publish does not upload the same zip again
    prev = json.loads(uploaded.read_text(encoding="utf-8")) if uploaded.is_file() else {}
    where = prev.get("where") if prev.get("sha256") == digest else None
    if where is None and shutil.which("gh") and subprocess.run(["gh", "auth", "status"], capture_output=True).returncode == 0:
        tag = f"e12-{stamp}"
        r = subprocess.run(["gh", "release", "create", tag, str(z), "--title", f"E12 pack {stamp}",
                            "--notes", f"{z.name}, sha256 {digest}"], cwd=KIT, capture_output=True, text=True)
        if r.returncode == 0:
            where = f"GitHub release {tag} {r.stdout.strip()}"
        else:
            log(f"publish: gh release failed ({r.stderr.strip()[:200]}); pushing a branch instead")
    if where is None:
        where = push_pack_branch(z, stamp, digest)
    uploaded.write_text(json.dumps({"zip": z.name, "sha256": digest, "where": where}, indent=2), encoding="utf-8")
    (RESULTS / "PACK.txt").write_text(f"{z.name}\nsha256 {digest}\n{z.stat().st_size} bytes\n{where}\n",
                                      encoding="utf-8")
    ident = git_ident()
    git("add", "results")
    if git("diff", "--cached", "--quiet", check=False).returncode != 0:
        git(*ident, "commit", "-q", "-m", f"E12 results ({platform.node()}, {stamp})")
    git(*ident, "pull", "-q", "--rebase", "--autostash")
    git("push", "-q")
    (RUNS / "published.json").write_text(json.dumps({"published": now(), "zip": z.name, "sha256": digest,
                                                     "where": where}, indent=2), encoding="utf-8")
    log(f"publish: results/ pushed to the main branch; pack: {where}")
    return 0


def run_all(args: argparse.Namespace) -> int:
    if FINISHED.is_file() and not args.again:
        f = json.loads(FINISHED.read_text(encoding="utf-8"))
        if f.get("complete") and (f.get("published") or not args.publish):
            print(f"E12 already finished at {f['finished']}: {f['summary']} (--again repeats verify, eval and pack)")
            return 0
    take_lock("all")
    keep_awake()
    if verify(argparse.Namespace(write_reference=False)) != 0:
        log("all: stopped, SUMO differs from the reference PC (see above)")
        return 1
    rc_train = train(args)
    rc_eval = evaluate(args)
    rc_pack = pack(args)
    p = progress()
    zips = sorted(RUNS.glob("e12_pack_*.zip"), key=lambda q: q.stat().st_mtime)
    complete = rc_train == 0 and rc_eval == 0 and rc_pack == 0
    info = {"finished": now(), "complete": complete, "published": False,
            "summary": f"{p['train_done']}/{p['train_runs']} training runs, {p['eval_eps']}/{p['eval_total']} "
                       f"evaluation episodes, pack {zips[-1].name if zips else 'missing'}"
                       + ("" if complete else "; NOT complete, run again")}
    if args.publish and complete and not SMOKE:
        try:
            info["published"] = publish(args) == 0
        except (subprocess.CalledProcessError, OSError, SystemExit) as e:
            log(f"all: publish failed ({e}); run 'e12.py publish' again")
    FINISHED.write_text(json.dumps(info, indent=2), encoding="utf-8")
    log(f"all: finished; {info['summary']}" + ("; published" if info["published"] else ""))
    return 0 if complete else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("verify", help="identity checks against the reference PC")
    v.add_argument("--write-reference", action="store_true", help="reference PC only: write verify/reference.json")
    b = sub.add_parser("bench", help="throughput test; saves the suggested --workers")
    b.add_argument("--workers-list", help="process counts to test, e.g. 1,8,15 (default: 1, N/2, N-1)")
    for name in ("train", "eval", "all"):
        p = sub.add_parser(name, help={"train": "training runs", "eval": "frozen evaluation",
                                       "all": "verify, train, eval, pack (and publish with --publish)"}[name])
        p.add_argument("--workers", type=int, default=default_workers(),
                       help="parallel processes (default: from 'bench', else logical CPUs - 1)")
        p.add_argument("--only-policy", nargs="+", choices=list(POLICIES))
        if name == "all":
            p.add_argument("--publish", action="store_true", help="publish the results at the end")
            p.add_argument("--again", action="store_true", help="repeat even if a complete run has finished")
    sub.add_parser("status", help="progress, state and time left")
    w = sub.add_parser("wait", help="block until the run ends or the time is up, then print the status")
    w.add_argument("--minutes", type=float, default=9.0, help="maximum wait (default 9)")
    sub.add_parser("running", help="exit code 0 if a run is active, else 1")
    sub.add_parser("pack", help="results/ with SUMMARY.md, and the pack zip")
    sub.add_parser("publish", help="upload the pack zip and push results/")
    args = ap.parse_args()
    fn = {"verify": verify, "bench": bench, "train": train, "eval": evaluate, "status": status, "wait": wait,
          "running": running, "pack": pack, "publish": publish, "all": run_all}[args.cmd]
    return fn(args)


if __name__ == "__main__":
    sys.exit(main())
