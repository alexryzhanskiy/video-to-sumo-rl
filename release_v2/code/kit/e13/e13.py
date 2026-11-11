#!/usr/bin/env python3
"""E13 (pre-registration v1, frozen 29 Oct 2026): DRL designs with the constraints of a real signal controller,
longer training and varied training demand, evaluated frozen (greedy, no learning) against the fixed and actuated
plans on new validation demand, on the E12 held-out demand ("test A") and, once, on the locked test.

Run from this folder (e13/) with the kit's Python (../.venv, made by ../setup.ps1):
  python e13.py verify      identity and signal-rule checks (about 3 min)
  python e13.py bench       training throughput with the E13 settings; saves the suggested --workers
  python e13.py baselines   fixed and actuated plans on validation and test A (SUMO only)
  python e13.py run L0      re-evaluate the E12 models (needs ../runs/train of E12)
  python e13.py replay      B1: per-second replay of 8 deadlocked E12 held-out x1.0 episodes (original twin)
  python e13.py run L12     train and evaluate L1 (free order) and L2 (field order): 4 rewards x 3 loads x 5 runs
  python e13.py select      rules 5.1/5.2 on validation: selection_L12.json; after L34 also selection_final.json
  python e13.py run L34     train and evaluate L3 (300 episodes) and L4 (one model, mixed demand, 300 episodes)
  python e13.py status      progress, state and time left (wait, running: as in E12)
  python e13.py pack        results/ (SUMMARY.md and CSVs) and runs/e13_pack_*.zip
  python e13.py publish     upload the zip (GitHub release, else a branch) and push e13/results/
  python e13.py all         verify, baselines, L0, replay, L12, select, L34, select, pack (--publish: also publish)
  python e13.py locked --go the locked test, ONCE, only when Pavlo asks (every model and both baselines)

Designs (pre-registration section 2; flags of resco_benchmark/main.py):
  L0  E12 models as trained: --mode e12 --allred_mode every --mplight_phase legacy
  L1  green 12-60 s by action masking, free order, phase/elapsed-green input: --mode free --allred_mode street
      --mplight_phase fixed; E12 training files; 100 episodes
  L2  as L1 with the field phase order: --mode field; 100 episodes
  L3  the better of L1/L2 (rule 5.2), the 2 best rewards, 300 episodes
  L4  as L3, one model for all loads trained on the 60 mixed files (map prybuzka_mix), 300 episodes
Every run: --allred 4, --undeparted (never-inserted vehicles written), and --vtype <calibrated vehicle> when
twin.json says "calibrated". Training run k: --tr k --seed 42+k (SUMO seed 42+k+episode). Evaluation of run k:
trial 1000+k (SUMO seed 1042+k+file index), every route file of the map once, 1800 s.

Only one train/eval/all/locked process runs at a time (runs/e13.lock). Everything restarts safely: finished
training runs and evaluations are kept; an interrupted training run starts again from episode 1.
E13_SMOKE=1: quick end-to-end test in runs_smoke/ (1 run, 2 episodes, 1 route file per map); never published,
never touches the locked test.
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

E13 = Path(__file__).resolve().parent
REPO = E13.parent                       # the E12 kit, root of the repository
RESCO = E13 / "resco"
BENCH = RESCO / "resco_benchmark"
SMOKE = bool(os.environ.get("E13_SMOKE"))
RUNS = E13 / ("runs_smoke" if SMOKE else "runs")
TRAIN_DIR, EVAL_DIR, BASE_DIR, REPLAY_DIR = (RUNS / d for d in ("train", "eval", "baselines", "replay"))
RESULTS = RUNS / "results" if SMOKE else E13 / "results"
LOG = RUNS / "e13.log"
E12_TRAIN = REPO / ("runs_smoke" if SMOKE else "runs") / "train"    # the E12 models (L0, B1)
E12_RESULTS = REPO / "results"                                    # E12 tables (B1 episode choice)
VERIFY12 = REPO / "verify"
TWIN = E13 / "twin.json"

POLICIES = {"IDQN-wait": "IDQN", "IDQN-queue": "IDQN_pressure", "MPLight": "MPLight",
            "IDQN-pressure": "IDQN_pressure_inout"}
LOADS = {"x1.0": "prybuzka_tr10", "x1.2": "prybuzka_tr12", "x1.5": "prybuzka_tr15"}
MIX = "prybuzka_mix"
VAL = {"x1.0": "prybuzka_va10", "x1.2": "prybuzka_va12", "x1.5": "prybuzka_va15"}
VAL_SC = ["prybuzka_vas1", "prybuzka_vas2", "prybuzka_vas3", "prybuzka_vas4"]
TESTA = {"x1.0": "prybuzka_ho10", "x1.2": "prybuzka_ho12", "x1.5": "prybuzka_ho15"}
TESTA_SC = ["prybuzka_s1", "prybuzka_s2", "prybuzka_s3", "prybuzka_s4"]
LOCKED = {"x1.0": "prybuzka_lt10", "x1.2": "prybuzka_lt12", "x1.5": "prybuzka_lt15"}
LOCKED_SC = ["prybuzka_lts1", "prybuzka_lts2", "prybuzka_lts3", "prybuzka_lts4"]
SETS = {"validation": (VAL, VAL_SC), "testA": (TESTA, TESTA_SC), "locked": (LOCKED, LOCKED_SC)}
SET_OF = {m: (s, lab) for s, (loads, scs) in SETS.items()
          for lab, m in list(loads.items()) + [(f"S{i}", m) for i, m in enumerate(scs, 1)]}
LABELS = ["x1.0", "x1.2", "x1.5", "S1", "S2", "S3", "S4"]
MAP_END = {"prybuzka_tr10": 1500.0}    # every other map: 1800 s
COST = {"x1.0": 1.0, "x1.2": 1.45, "x1.5": 2.0, "mix": 1.45}    # relative episode cost, estimates only
EVAL_COST = 1.3
RUNS_K = range(1, 2) if SMOKE else range(1, 6)
EPISODES = dict.fromkeys(("L1", "L2", "L3", "L4"), 2) if SMOKE else {"L1": 100, "L2": 100, "L3": 300, "L4": 300}
RUNG_MODE = {"L0": "e12", "L1": "free", "L2": "field"}    # L3, L4: the base design of selection_L12.json
STAGE_RUNGS = {"L0": ("L0",), "L12": ("L1", "L2"), "L34": ("L3", "L4")}
ALLRED, MIN_GREEN, MAX_GREEN = 4, 12, 60
GLOBAL_SEED, TRIAL_OFFSET, END, DEADLOCK_S = 42, 1000, 1800.0, 300.0
STREET = [0, 0, 1, 1]    # street of green phases 0-3 (Svobody, Svobody, Prybuzka, Prybuzka)
CONTROLLERS = {"Fixed plan": ("fixed", BENCH / "environments" / "prybuzka" / "intersection.net.xml"),
               "Actuated": ("actuated", E13 / "baselines" / "intersection_act.net.xml")}
PINNED = ["eclipse-sumo", "libsumo", "sumo-data", "torch", "pfrl", "gym", "numpy"]
RUN_RE = re.compile(r"^(?P<alg>[A-Za-z0-9]+)-tr(?P<tr>\d+)-(?P<map>[A-Za-z0-9_]+)-(?P<nlights>\d+)-"
                    r"(?P<state>[A-Za-z0-9_]+)-(?P<reward>[A-Za-z0-9_]+)==(?P<uuid>[0-9a-f]{32})$")
GREENS = {"GGGrsrrrGGGrsrrr": 0, "srrGsrrrsrrGsrrr": 1, "srrrGGGrsrrrGGGr": 2, "srrrsrrGsrrrsrrG": 3}
GREEN_RE = re.compile(r"^[\d.]+, \{.*?\}, \{.*?\}, \{.*?\}, \{'nC': (\d+)\},\s*$")


# ------------------------------------------------------------------ helpers
def log(msg: str) -> None:
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S}  {msg}"
    print(line, flush=True)
    RUNS.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def sumo_home() -> str:
    import sumo    # the eclipse-sumo wheel of this environment, never a system-wide SUMO
    return sumo.SUMO_HOME


def sumo_exe() -> str:
    return str(Path(sumo_home()) / "bin" / ("sumo.exe" if os.name == "nt" else "sumo"))


def child_env() -> dict:
    env = os.environ.copy()
    env.update(PYTHONPATH=str(RESCO), SUMO_HOME=sumo_home(), LIBSUMO_AS_TRACI="1", OMP_NUM_THREADS="1",
               MKL_NUM_THREADS="1", RESCO_NO_BEEP="1", CUDA_VISIBLE_DEVICES="")
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
    p = path.resolve()
    for base, prefix in ((E13, ""), (REPO, "../")):
        try:
            return prefix + p.relative_to(base).as_posix()
        except ValueError:
            pass
    return p.as_posix()


def episodes_in(folder: Path | None) -> int:
    if not folder:
        return 0
    eps = [int(m.group(1)) for f in folder.glob("tripinfo_*.xml") if (m := re.match(r"tripinfo_(\d+)\.xml$", f.name))]
    return max(eps) if eps else 0


def run_folder(log_dir: Path) -> Path | None:
    folders = [p for p in log_dir.iterdir() if p.is_dir() and RUN_RE.match(p.name)] if log_dir.is_dir() else []
    return max(folders, key=lambda p: (p.stat().st_mtime, p.name)) if folders else None


def checkpoint_of(folder: Path, alg: str) -> Path:
    if alg == "MPLight":    # SharedAgent saves log_dir + 'agent': the file sits next to the run folder
        return folder.parent / (folder.name + "agent.pt")
    inside = folder / "agent_nC.pt"
    sibling = folder.parent / (folder.name + "agent_nC.pt")
    return inside if inside.is_file() or not sibling.is_file() else sibling


_routes: dict[str, list[Path]] = {}


def route_files(map_name: str) -> list[Path]:
    """Same rule as MultiSignal.reset(): episode e uses sorted(glob(routes/*.rou.xml))[(e - 1) % n]."""
    if map_name not in _routes:
        _routes[map_name] = sorted((BENCH / "environments" / map_name / "routes").glob("*.rou.xml"))
    return _routes[map_name]


def n_eval_eps(map_name: str) -> int:
    return 1 if SMOKE else len(route_files(map_name))


def main_cmd(agent: str, map_name: str, trial: int, eps: int, log_dir: Path, extra: list[str]) -> list[str]:
    return [sys.executable, "main.py", "--agent", agent, "--map", map_name, "--tr", str(trial), "--eps", str(eps),
            "--procs", "1", "--libsumo", "True", "--log_dir", str(log_dir) + os.sep, *extra]


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
    for bench in (RUNS / "bench.json", REPO / "runs" / "bench.json"):    # E13 bench, else the E12 one
        if bench.is_file():
            return json.loads(bench.read_text(encoding="utf-8"))["suggested_workers"]
    return max(1, (os.cpu_count() or 2) - 1)


def pool(tasks: list[tuple[str, callable]], workers: int, what: str) -> list[dict]:
    t0, out = time.time(), []
    if not tasks:
        return out
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
                + (f", {info['minutes']:.1f} min" if "minutes" in info else "") + f"  (elapsed {el / 3600:.2f} h)")
    return out


def ok_status(info: dict) -> bool:
    return info["status"].startswith(("done", "already"))


# ------------------------------------------------------------------ twin (pre-registration sections 1 and 8)
def twin() -> dict:
    """twin.json: {"twin": "pending" | "default" | "calibrated", "vtype": file relative to e13/ and "sha256"
    (calibrated only), "decided": date, "note": text}. Written on the laptop after B6 and pushed."""
    t = json.loads(TWIN.read_text(encoding="utf-8"))
    if t["twin"] == "calibrated":
        p = E13 / t["vtype"]
        if not p.is_file() or file_hash(p) != t["sha256"]:
            sys.exit(f"twin.json: {t['vtype']} is missing or its SHA-256 differs; stop and tell Pavlo")
    elif t["twin"] not in ("default", "pending"):
        sys.exit(f"twin.json: unknown twin {t['twin']!r}")
    return t


def twin_for_runs() -> dict:
    t = twin()
    if t["twin"] == "pending":
        if SMOKE:
            return {"twin": "default", "note": "smoke test while the twin decision is pending"}
        sys.exit("twin.json says 'pending': the B6 twin decision (due Sun 1 Nov 20:00) is not in yet. "
                 "E13 runs start only after it; 'git pull' brings it.")
    return t


def twin_tag(t: dict) -> str:
    return t["twin"] + (f":{t['sha256'][:12]}" if t["twin"] == "calibrated" else "")


def vtype_args(t: dict) -> list[str]:
    return ["--vtype", str(E13 / t["vtype"])] if t["twin"] == "calibrated" else []


def check_twin_consistency(t: dict) -> None:
    tag = twin_tag(t)
    for p in (list(TRAIN_DIR.glob("*/done.json")) + list(EVAL_DIR.glob("*/*/eval.json"))
              + list(BASE_DIR.glob("*/*/baseline.json"))):
        other = json.loads(p.read_text(encoding="utf-8")).get("twin")
        if other and other != tag:
            sys.exit(f"{rel(p)} was made with twin {other}, but twin.json now says {tag}: stop and tell Pavlo")


def design_flags(mode: str, t: dict) -> list[str]:
    if mode == "e12":    # L0: all-red after every change, free order, no green limits, MPLight phase as in E12
        f = ["--mode", "e12", "--allred_mode", "every", "--mplight_phase", "legacy"]
    else:    # L1-L4: green limits by masking, all-red only at street changes, MPLight phase fixed (K32)
        f = ["--mode", mode, "--min_green", str(MIN_GREEN), "--max_green", str(MAX_GREEN), "--allred_mode", "street",
             "--mplight_phase", "fixed"]
    return f + ["--allred", str(ALLRED), "--undeparted"] + vtype_args(t)


# ------------------------------------------------------------------ metrics (pre-registration section 4)
_departs: dict[Path, dict[str, float]] = {}


def route_departs(route: Path) -> dict[str, float]:
    if route not in _departs:
        d = {}
        for _, el in ET.iterparse(route):
            if el.tag in ("vehicle", "trip"):
                d[el.get("id")] = float(el.get("depart"))
                el.clear()
        _departs[route] = d
    return _departs[route]


def switches(metrics_csv: Path | None, allred_every: bool) -> tuple:
    """Green changes between decisions and the seconds of yellow + all-red they cost (RESCO metrics log, E13)."""
    if metrics_csv is None or not metrics_csv.is_file():
        return "", ""
    greens = [int(m.group(1)) for line in metrics_csv.read_text(encoding="utf-8").splitlines()
              if (m := GREEN_RE.match(line))]
    if not greens:
        return "", ""
    ch = [(a, b) for a, b in zip(greens, greens[1:]) if a != b]
    return len(ch), float(sum(3 + (ALLRED if allred_every or STREET[a] != STREET[b] else 0) for a, b in ch))


def episode_metrics(trip: Path, route: Path, end: float, metrics_csv: Path | None = None,
                    allred_every: bool = False) -> dict:
    """E12 definitions (arrivals, deadlock, full demand) plus the total delay including unserved vehicles:
    sum of departDelay + timeLoss over the tripinfo (unfinished and never-inserted vehicles included), plus
    end - planned departure for any route-file vehicle due before the end and missing from the tripinfo."""
    ids, dep, arr, wait_s, delay, undeparted = set(), [], [], [], 0.0, 0
    for _, el in ET.iterparse(trip):
        if el.tag == "tripinfo":
            ids.add(el.get("id"))
            delay += float(el.get("departDelay", "0")) + float(el.get("timeLoss", "0"))
            d = float(el.get("depart"))
            if d >= 0:
                dep.append(d)
                arr.append(float(el.get("arrival")))
                wait_s.append(float(el.get("waitingTime")))
            else:
                undeparted += 1
            el.clear()
    planned = route_departs(route)
    delay += sum(end - t for v, t in planned.items() if v not in ids and t < end)
    done = sorted(a for a in arr if a >= 0)
    events = sorted(dep)
    longest, prev = 0.0, None    # longest interval without an arrival while vehicles are in the network
    for i, t in enumerate(done + [end]):
        start = prev if prev is not None else (events[0] if events else 0.0)
        if bisect.bisect_right(events, start) - i > 0:
            longest = max(longest, t - start)
        prev = t
    aw = [w for w, a in zip(wait_s, arr) if a >= 0]
    n = len(planned)
    sw, clear = switches(metrics_csv, allred_every)
    return {"demand": n, "entries": len(dep), "arrived_1500": sum(0 <= a <= 1500 for a in arr),
            "arrived_1800": sum(0 <= a <= 1800 for a in arr), "unfinished": sum(a < 0 for a in arr),
            "not_inserted": n - len(dep), "undeparted_written": undeparted, "full": int(len(dep) >= 0.99 * n),
            "longest_no_arrival_s": round(longest, 1), "deadlock": int(longest >= DEADLOCK_S),
            "mean_wait_arrived_s": round(st.mean(aw), 2) if aw else "",
            "total_delay_vh": round(delay / 3600, 3), "mean_delay_s": round(delay / n, 2) if n else "",
            "switches": sw, "clearance_s": clear}


def safe_metrics(trip: Path, route: Path, end: float, metrics_csv: Path | None = None, allred_every: bool = False) -> dict:
    try:
        return {"tripinfo_ok": 1} | episode_metrics(trip, route, end, metrics_csv, allred_every)
    except (OSError, ET.ParseError, ValueError, TypeError):
        return {"tripinfo_ok": 0}


# ------------------------------------------------------------------ verify
def check_tls(path: Path, end: float, mode: str) -> dict:
    """Green, yellow and all-red intervals from SUMO's SaveTLSStates log (as revision/tools/test_e13_kit.py)."""
    ev = [(float(t), s) for t, s in re.findall(r'<tlsState time="([\d.]+)"[^>]*state="([^"]+)"', path.read_text())]
    ev.append((end, None))
    segs = [(ev[i][1], ev[i][0], ev[i + 1][0]) for i in range(len(ev) - 1) if ev[i + 1][0] > ev[i][0]]
    merged = []    # merge consecutive identical states
    for s, a, b in segs:
        if merged and merged[-1][0] == s and merged[-1][2] == a:
            merged[-1] = (s, merged[-1][1], b)
        else:
            merged.append((s, a, b))
    bad, greens, prev_green, prev_idx = [], [], None, 0
    for i, (s, a, b) in enumerate(merged):
        dur, last = b - a, i == len(merged) - 1
        if s in GREENS:
            g = GREENS[s]
            greens.append(dur)
            if (dur < MIN_GREEN and not last) or dur > MAX_GREEN:
                bad.append(f"green {g} lasted {dur} s at {a}")
            if prev_green is not None:
                between = [x[0] for x in merged[prev_idx + 1:i]]
                n_allred = sum(1 for x in between if not any(c in x for c in "GgYy"))
                n_yellow = sum(1 for x in between if "y" in x)
                if n_yellow != 1:
                    bad.append(f"{n_yellow} yellows between greens at {a}")
                if n_allred != (1 if STREET[prev_green] != STREET[g] else 0):
                    bad.append(f"all-red count {n_allred} for {prev_green}->{g} at {a}")
                if mode == "field" and g != (prev_green + 1) % 4:
                    bad.append(f"order {prev_green}->{g} at {a}")
            prev_green, prev_idx = g, i
        elif "y" in s:
            if dur != 3 and not last:
                bad.append(f"yellow {dur} s at {a}")
        elif not any(c in s for c in "GgYy") and dur != ALLRED and not last:
            bad.append(f"all-red {dur} s at {a}")
    return {"greens": len(greens), "min_green": min(greens[:-1]) if len(greens) > 1 else None,
            "max_green": max(greens) if greens else None, "violations": bad[:10], "n_violations": len(bad)}


def verify(args: argparse.Namespace) -> int:
    ref = json.loads((VERIFY12 / "reference.json").read_text(encoding="utf-8"))["hashes"]
    vdir = RUNS / "verify"
    if vdir.exists():
        shutil.rmtree(vdir)
    v = versions()
    t = twin()
    if t["twin"] == "pending":
        t = {"twin": "default"}
    log("verify: " + ", ".join(f"{p} {v[p]}" for p in PINNED) + f"; Python {v['python']}; {v['platform']}")
    got: dict[str, str] = {}

    # 1. SUMO alone: the fixed signal plan of the network, x1.0 demand, 1500 s, seed 1 (as E12)
    env_dir = BENCH / "environments" / "prybuzka"
    trip = vdir / "fixed" / "tripinfo.xml"
    trip.parent.mkdir(parents=True)
    subprocess.run([sumo_exe(), "-n", str(env_dir / "intersection.net.xml"), "-r", str(env_dir / "routes" / "gen_1.rou.xml"),
                    "--end", "1500", "--seed", "1", "--tripinfo-output", str(trip), "--no-step-log", "true"],
                   check=True, capture_output=True)
    got["fixed_plan"] = records_hash(trip)

    # 2.-4. in parallel: an original policy with the E12 settings on the E13 code; an E13 (L2) training run twice;
    # an L2 training run with SUMO's signal-state log
    tls_dir = vdir / "tls"
    tls_dir.mkdir(parents=True)
    add = tls_dir / "tls.add.xml"    # passed through --vtype: the default vehicle, the signal log only
    add.write_text(f'<additional><timedEvent type="SaveTLSStates" source="nC" dest="{(tls_dir / "tls_states.xml").as_posix()}"/>'
                   f'</additional>\n', encoding="utf-8")
    train = ["--seed", str(GLOBAL_SEED + 1), "--save_freq", "2"]
    jobs = {"policy": main_cmd("IDQN_pressure", "prybuzka_ho10", 1004, 2, vdir / "policy",
                               ["--allred", "0", "--ckpt", str(VERIFY12 / "idqn_queue_x10_run4.pt")]),
            "trainA": main_cmd("IDQN_pressure_inout", "prybuzka_tr10", 1, 2, vdir / "trainA", design_flags("field", t) + train),
            "trainB": main_cmd("IDQN_pressure_inout", "prybuzka_tr10", 1, 2, vdir / "trainB", design_flags("field", t) + train),
            "tls": main_cmd("IDQN_pressure_inout", "prybuzka_tr10", 1, 2, tls_dir / "run",
                            design_flags("field", {"twin": "default"}) + train + ["--vtype", str(add)])}
    with ThreadPoolExecutor(max_workers=4) as ex:
        codes = dict(zip(jobs, ex.map(lambda k: run_main(jobs[k], (tls_dir / "run") if k == "tls" else vdir / k), jobs)))
    for name in ("policy", "trainA", "trainB"):
        folder = run_folder(vdir / name)
        for e in (1, 2):
            p = folder / f"tripinfo_{e}.xml" if folder else None
            got[f"{name}_ep{e}"] = records_hash(p) if p and p.is_file() else "missing"
    tls = check_tls(tls_dir / "tls_states.xml", 1500.0, "field") if (tls_dir / "tls_states.xml").is_file() else None
    checks = [
        ("SUMO fixed plan identical to the reference PC", got["fixed_plan"] == ref["fixed_plan"], True),
        ("E13 code with E12 settings: original policy, 2 frozen episodes identical to the reference PC",
         all(got[f"policy_ep{e}"] == ref[f"policy_ep{e}"] for e in (1, 2)), False),
        ("E13 training repeatable on this PC (L2 design, same seed twice)",
         all(got[f"trainA_ep{e}"] == got[f"trainB_ep{e}"] != "missing" for e in (1, 2)), False),
        ("E13 signal rules: greens 12-60 s, one 3-s yellow, 4-s all-red only at street changes, field order",
         codes["tls"] == 0 and tls is not None and tls["n_violations"] == 0 and tls["greens"] > 10, True),
    ]
    blocking = False
    for text, ok, required in checks:
        log(f"verify: {'OK  ' if ok else ('FAIL' if required is not None else 'no  ')}  {text}")
        blocking |= bool(required) and not ok
    (RUNS / "verify.json").write_text(json.dumps({"written": now(), "versions": v, "twin": twin_tag(t), "hashes": got,
                                                  "reference": ref, "exit_codes": codes, "signal_rules": tls,
                                                  "checks": [(x, ok) for x, ok, _ in checks]}, indent=2), encoding="utf-8")
    if not checks[1][1] or not checks[2][1]:
        log("verify: a non-blocking check differs; E13 can still run on this PC, but report it (runs/verify.json)")
    return 1 if blocking else 0


# ------------------------------------------------------------------ bench
def bench(args: argparse.Namespace) -> int:
    n = os.cpu_count() or 2
    counts = sorted({int(x) for x in args.workers_list.split(",")} if args.workers_list else {1, max(2, n // 2), max(2, n - 1)})
    t = twin()
    flags = design_flags("free", t if t["twin"] != "pending" else {"twin": "default"})
    bdir = RUNS / "bench"
    results = []
    for k in counts:
        if bdir.exists():
            shutil.rmtree(bdir)
        tasks = [(bdir / f"p{i}", main_cmd("IDQN_pressure_inout", "prybuzka_tr10", 100 + i, 3, bdir / f"p{i}",
                                           flags + ["--seed", str(GLOBAL_SEED + 100 + i)])) for i in range(k)]
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=k) as ex:
            codes = list(ex.map(lambda x: run_main(x[1], x[0]), tasks))
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
    best = min((r for r in good if r["episodes_per_s"] >= 0.95 * best["episodes_per_s"]), key=lambda r: r["processes"])
    p = progress()
    hours = p["cost_total"] / best["episodes_per_s"] / 3600
    out = {"written": now(), "results": results, "suggested_workers": best["processes"],
           "estimated_hours_all": round(hours, 1), "versions": versions()}
    (RUNS / "bench.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    log(f"bench: suggested --workers {best['processes']}; estimated time for L0-L4 (without the locked test): "
        f"about {hours:.1f} h")
    return 0


# ------------------------------------------------------------------ plans
def selection(name: str) -> dict | None:
    p = RUNS / f"selection_{name}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def job_name(j: dict) -> str:
    return f"{j['rung']}_{j['policy']}_{j['load']}_run{j['run']}"


def l34_jobs(rewards: list[str], mode: str) -> list[dict]:
    jobs = [dict(rung="L3", policy=p, load=l, run=k, map=m, mode=mode, eps=EPISODES["L3"])
            for p in rewards for l, m in LOADS.items() for k in RUNS_K]
    return jobs + [dict(rung="L4", policy=p, load="mix", run=k, map=MIX, mode=mode, eps=EPISODES["L4"])
                   for p in rewards for k in RUNS_K]


def train_plan(stage: str) -> list[dict]:
    if stage == "L12":
        return [dict(rung=r, policy=p, load=l, run=k, map=m, mode=RUNG_MODE[r], eps=EPISODES[r])
                for r in ("L1", "L2") for p in POLICIES for l, m in LOADS.items() for k in RUNS_K]
    if stage == "L34":
        sel = selection("L12")
        if sel is None:
            sys.exit("L34 needs runs/selection_L12.json: run 'select' after L12")
        return l34_jobs(sel["rewards"], sel["base_mode"])
    return []


def eval_maps(load: str, sets: tuple[str, ...]) -> list[str]:
    """Own load first; x1.0 models also on the scenarios (and, outside validation, on x1.2 and x1.5: transfer);
    the general model (L4) on every load and scenario."""
    out = []
    for s in sets:
        loads, scs = SETS[s]
        if load == "mix":
            out += list(loads.values()) + scs
        elif load == "x1.0":
            out += [loads["x1.0"]] + scs + ([] if s == "validation" else [loads["x1.2"], loads["x1.5"]])
        else:
            out.append(loads[load])
    return out


def model_name(m: dict) -> str:
    return f"{m['rung']}_{m['policy']}_{m['load']}_run{m['run']}"


def models(stage: str) -> list[dict]:
    """Trained models of a stage: E12 done.json files for L0, E13 done.json files for the other stages."""
    out = []
    if stage == "L0":
        for p in POLICIES:
            for l in LOADS:
                for k in RUNS_K:
                    done = E12_TRAIN / f"{p}_{l}_run{k}" / "done.json"
                    if done.is_file():
                        i = json.loads(done.read_text(encoding="utf-8"))
                        out.append(dict(rung="L0", policy=p, load=l, run=k, mode="e12", ckpt=REPO / i["checkpoint"]))
        return out
    for done in sorted(TRAIN_DIR.glob("*/done.json")):
        i = json.loads(done.read_text(encoding="utf-8"))
        if i["rung"] in STAGE_RUNGS[stage]:
            out.append(dict(rung=i["rung"], policy=i["policy"], load=i["load"], run=i["run"], mode=i["mode"],
                            ckpt=E13 / i["checkpoint"]))
    return out


# ------------------------------------------------------------------ train
TRAIN_FIELDS = ["rung", "policy", "load", "run", "episode", "route_file", "sumo_seed", "tripinfo_ok", "demand", "entries",
                "arrived_1500", "arrived_1800", "unfinished", "not_inserted", "full", "longest_no_arrival_s", "deadlock",
                "mean_wait_arrived_s", "total_delay_vh", "mean_delay_s", "switches", "clearance_s"]


def train_job(j: dict, t: dict) -> dict:
    job = TRAIN_DIR / job_name(j)
    if (job / "done.json").is_file():
        return {"status": "already done"}
    if job.exists():
        shutil.rmtree(job)
    seed = GLOBAL_SEED + j["run"]
    flags = design_flags(j["mode"], t)
    started, t0 = now(), time.time()
    # --save_freq: RESCO saves the final checkpoint when the episode number is a multiple of it
    rc = run_main(main_cmd(POLICIES[j["policy"]], j["map"], j["run"], j["eps"], job,
                           flags + ["--seed", str(seed), "--save_freq", str(j["eps"])]), job)
    minutes = (time.time() - t0) / 60
    folder = run_folder(job)
    n = episodes_in(folder)
    m = RUN_RE.match(folder.name) if folder else None
    ckpt = checkpoint_of(folder, m["alg"]) if m else None
    routes, end = route_files(j["map"]), MAP_END.get(j["map"], END)
    rows = []
    for e in range(1, n + 1):
        route = routes[(e - 1) % len(routes)]
        rec = {"rung": j["rung"], "policy": j["policy"], "load": j["load"], "run": j["run"], "episode": e,
               "route_file": route.name, "sumo_seed": GLOBAL_SEED + j["run"] + e}
        rec.update(safe_metrics(folder / f"tripinfo_{e}.xml", route, end, folder / f"metrics_{e}.csv", j["mode"] == "e12"))
        rows.append(rec)
    with (job / "episodes.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=TRAIN_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    ok = rc == 0 and n == j["eps"] and ckpt is not None and ckpt.is_file()
    info = {"status": "done" if ok else f"FAILED (exit {rc}, {n} episodes; see {rel(job / 'main.log')})",
            "rung": j["rung"], "policy": j["policy"], "agent": POLICIES[j["policy"]], "load": j["load"], "map": j["map"],
            "run": j["run"], "mode": j["mode"], "episodes": n, "seed": seed,
            "sumo_seeds": f"{GLOBAL_SEED + j['run'] + 1}-{GLOBAL_SEED + j['run'] + j['eps']}", "flags": flags,
            "twin": twin_tag(t), "returncode": rc, "minutes": round(minutes, 2), "started": started, "finished": now(),
            "run_folder": rel(folder) if folder else "", "checkpoint": rel(ckpt) if ckpt else "",
            "checkpoint_sha256": file_hash(ckpt) if ok else ""}
    (job / ("done.json" if ok else "failed.json")).write_text(json.dumps(info, indent=2), encoding="utf-8")
    return info


def train(stage: str, t: dict, workers: int, only: list[str] | None) -> int:
    jobs = [j for j in train_plan(stage) if not only or j["policy"] in only]
    jobs.sort(key=lambda j: (-j["eps"] * COST[j["load"]], j["run"], j["policy"]))
    todo = [j for j in jobs if not (TRAIN_DIR / job_name(j) / "done.json").is_file()]
    log(f"train {stage}: {len(jobs)} runs, {len(jobs) - len(todo)} already done, {len(todo)} to run with {workers} processes")
    infos = pool([(job_name(j), (lambda j=j: train_job(j, t))) for j in todo], workers, f"train {stage}")
    failed = [i for i in infos if not ok_status(i)]
    log(f"train {stage}: finished; {len(failed)} failed" + ("" if not failed else " (run again to retry them)"))
    return 1 if failed else 0


# ------------------------------------------------------------------ eval
def eval_job(mdl: dict, map_name: str, t: dict) -> dict:
    d = EVAL_DIR / model_name(mdl) / map_name
    out = d / "eval.json"
    if out.is_file() and json.loads(out.read_text(encoding="utf-8"))["status"] == "done":
        return {"status": "already done"}
    if d.exists():
        shutil.rmtree(d)
    routes, eps = route_files(map_name), n_eval_eps(map_name)
    trial = TRIAL_OFFSET + mdl["run"]
    flags = design_flags(mdl["mode"], t)
    t0 = time.time()
    rc = run_main(main_cmd(POLICIES[mdl["policy"]], map_name, trial, eps, d, flags + ["--ckpt", str(mdl["ckpt"])]), d)
    folder = run_folder(d)
    eval_set, label = SET_OF[map_name]
    rows = []
    for e in range(1, eps + 1):
        trip = folder / f"tripinfo_{e}.xml" if folder else d / "missing.xml"
        rec = {"rung": mdl["rung"], "policy": mdl["policy"], "train_load": mdl["load"], "training_run": mdl["run"],
               "eval_set": eval_set, "map": map_name, "label": label, "episode": e, "route_file": routes[e - 1].name,
               "sumo_seed": GLOBAL_SEED + trial + e}
        rec.update(safe_metrics(trip, routes[e - 1], END, folder / f"metrics_{e}.csv" if folder else None,
                                mdl["mode"] == "e12"))
        rec["tripinfo"] = rel(trip) if folder else ""
        rows.append(rec)
    ok = rc == 0 and all(r["tripinfo_ok"] for r in rows)
    info = {"status": "done" if ok else f"FAILED (exit {rc}; see {rel(d / 'main.log')})", "model": model_name(mdl),
            "map": map_name, "trial": trial, "twin": twin_tag(t), "flags": flags, "checkpoint": rel(mdl["ckpt"]),
            "checkpoint_sha256": file_hash(mdl["ckpt"]) if mdl["ckpt"].is_file() else "missing",
            "minutes": round((time.time() - t0) / 60, 2), "finished": now(), "episodes": rows}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(info, indent=1), encoding="utf-8")
    return info


def evaluate(mods: list[dict], sets: tuple[str, ...], t: dict, workers: int, what: str) -> int:
    jobs = [(mdl, m) for mdl in mods for m in eval_maps(mdl["load"], sets)]
    todo = [(mdl, m) for mdl, m in jobs
            if not ((p := EVAL_DIR / model_name(mdl) / m / "eval.json").is_file()
                    and json.loads(p.read_text(encoding="utf-8"))["status"] == "done")]
    todo.sort(key=lambda x: -n_eval_eps(x[1]))
    log(f"eval {what}: {len(mods)} models, {len(jobs)} evaluations, {len(jobs) - len(todo)} already done, "
        f"{len(todo)} to run with {workers} processes")
    infos = pool([(f"{model_name(mdl)} -> {m}", (lambda mdl=mdl, m=m: eval_job(mdl, m, t))) for mdl, m in todo],
                 workers, f"eval {what}")
    failed = [i for i in infos if not ok_status(i)]
    log(f"eval {what}: finished; {len(failed)} failed" + ("" if not failed else " (run again to retry them)"))
    return 1 if failed else 0


def run_stage(stage: str, args: argparse.Namespace) -> int:
    t = twin_for_runs()
    check_twin_consistency(t)
    take_lock(f"run {stage}")
    keep_awake()
    rc = 0
    if stage == "L0":
        mods = models("L0")
        if not mods:
            log(f"run L0: no E12 models in {rel(E12_TRAIN)}; L0 needs the E12 training runs of this PC")
            return 1
    else:
        rc |= train(stage, t, args.workers, args.only_policy)
        mods = [m for m in models(stage) if not args.only_policy or m["policy"] in args.only_policy]
    rc |= evaluate(mods, ("validation", "testA"), t, args.workers, stage)
    return rc


def run_cmd(args: argparse.Namespace) -> int:
    return run_stage(args.stage, args)


# ------------------------------------------------------------------ baselines (pre-registration 6.1)
def baseline_job(ctrl: str, map_name: str, t: dict) -> dict:
    tag, net = CONTROLLERS[ctrl]
    d = BASE_DIR / tag / map_name
    out = d / "baseline.json"
    if out.is_file() and json.loads(out.read_text(encoding="utf-8"))["status"] == "done":
        return {"status": "already done"}
    d.mkdir(parents=True, exist_ok=True)
    eval_set, label = SET_OF[map_name]
    rows, t0, codes = [], time.time(), []
    vt = ["-a", str(E13 / t["vtype"])] if t["twin"] == "calibrated" else []
    for e, route in enumerate(route_files(map_name)[:n_eval_eps(map_name)], 1):
        for k in RUNS_K:    # the seed of the matching DRL evaluation episode of training run k
            seed = GLOBAL_SEED + TRIAL_OFFSET + k + e
            trip = d / f"k{k}_e{e}.tripinfo.xml"
            codes.append(subprocess.run(
                [sumo_exe(), "-n", str(net), "-r", str(route), "--begin", "0", "--end", str(int(END)), "--seed", str(seed),
                 "--time-to-teleport", "-1", "--tripinfo-output", str(trip), "--tripinfo-output.write-unfinished",
                 "--tripinfo-output.write-undeparted", "--device.emissions.probability", "1.0", "--no-step-log", "true",
                 "--no-warnings", "true", *vt], capture_output=True).returncode)
            rec = {"rung": "baseline", "policy": ctrl, "train_load": "", "training_run": k, "eval_set": eval_set,
                   "map": map_name, "label": label, "episode": e, "route_file": route.name, "sumo_seed": seed}
            rec.update(safe_metrics(trip, route, END))
            rec["tripinfo"] = rel(trip)
            rows.append(rec)
    ok = all(c == 0 for c in codes) and all(r["tripinfo_ok"] for r in rows)
    info = {"status": "done" if ok else "FAILED (SUMO error or missing tripinfo)", "controller": ctrl, "map": map_name,
            "net": rel(net), "net_sha256": file_hash(net), "twin": twin_tag(t),
            "minutes": round((time.time() - t0) / 60, 2), "finished": now(), "episodes": rows}
    out.write_text(json.dumps(info, indent=1), encoding="utf-8")
    return info


def run_baselines(sets: tuple[str, ...], t: dict, workers: int) -> int:
    maps = [m for s in sets for m in list(SETS[s][0].values()) + SETS[s][1]]
    jobs = [(c, m) for c in CONTROLLERS for m in maps]
    infos = pool([(f"{c} {m}", (lambda c=c, m=m: baseline_job(c, m, t))) for c, m in jobs], workers, "baselines")
    failed = [i for i in infos if not ok_status(i)]
    log(f"baselines ({', '.join(sets)}): {len(jobs)} controller x map jobs, {len(failed)} failed")
    return 1 if failed else 0


def baselines_cmd(args: argparse.Namespace) -> int:
    t = twin_for_runs()
    check_twin_consistency(t)
    take_lock("baselines")
    return run_baselines(("validation", "testA"), t, args.workers)


# ------------------------------------------------------------------ B1 replay (pre-registration section 9)
E12_FLAGS = ["--mode", "e12", "--allred_mode", "every", "--mplight_phase", "legacy", "--allred", str(ALLRED)]


def replay(args: argparse.Namespace) -> int:
    """For each policy, the first two deadlocked E12 held-out x1.0 episodes in order (run, file), replayed on the
    original twin with the E12 settings; b1_replay.py records every second and every decision. The replayed
    tripinfo must be identical to the E12 one (checked when the E12 file is on this PC)."""
    take_lock("replay")
    keep_awake()
    groups: dict[tuple[str, int], dict] = {}
    if SMOKE:    # the original IDQN-queue policy of verify/, episode 1, yellow only: reference hash in verify/
        ref = json.loads((VERIFY12 / "reference.json").read_text(encoding="utf-8"))["hashes"]["policy_ep1"]
        groups[("IDQN-queue", 4)] = {"ckpt": VERIFY12 / "idqn_queue_x10_run4.pt", "flags": ["--allred", "0"],
                                     "episodes": {1: ref}}
    else:
        table = E12_RESULTS / "eval_episodes.csv"
        if not table.is_file():
            log(f"replay: {rel(table)} not found (E12 results)")
            return 1
        with table.open(newline="", encoding="utf-8") as f:
            dead = [r for r in csv.DictReader(f) if r["eval_set"] == "heldout" and r["load_or_scenario"] == "x1.0"
                    and r["deadlock"] == "1"]
        trips = {}
        with (E12_RESULTS / "eval_runs.csv").open(newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r["eval_set"] == "heldout" and r["map"] == "prybuzka_ho10":
                    trips[(r["policy"], int(r["training_run"]), int(r["episode"]))] = REPO / r["tripinfo_path"]
        for p in POLICIES:
            for k, e in sorted((int(r["training_run"]), int(r["episode"])) for r in dead if r["policy"] == p)[:2]:
                done = E12_TRAIN / f"{p}_x1.0_run{k}" / "done.json"
                if not done.is_file():
                    log(f"replay: {rel(done)} not found; the E12 models are needed")
                    return 1
                g = groups.setdefault((p, k), {"ckpt": REPO / json.loads(done.read_text(encoding="utf-8"))["checkpoint"],
                                               "flags": E12_FLAGS, "episodes": {}})
                trip = trips.get((p, k, e))
                g["episodes"][e] = records_hash(trip) if trip and trip.is_file() else None

    def job(p: str, k: int, g: dict) -> dict:
        d = REPLAY_DIR / f"{p}_x1.0_run{k}"
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)
        eps = sorted(g["episodes"])
        cmd = [sys.executable, str(E13 / "b1_replay.py"), "--out", str(d), "--record", ",".join(map(str, eps)), "--",
               "--agent", POLICIES[p], "--map", "prybuzka_ho10", "--tr", str(TRIAL_OFFSET + k), "--eps", str(max(eps)),
               "--procs", "1", "--libsumo", "True", "--log_dir", str(d / "resco") + os.sep, "--ckpt", str(g["ckpt"]),
               *g["flags"]]
        t0 = time.time()
        with (d / "replay.log").open("w", encoding="utf-8") as f:
            rc = subprocess.run(cmd, cwd=BENCH, env=child_env(), stdout=f, stderr=subprocess.STDOUT).returncode
        folder = run_folder(d / "resco")
        out = []
        for e in eps:
            trip = folder / f"tripinfo_{e}.xml" if folder else None
            h = records_hash(trip) if trip and trip.is_file() else None
            out.append({"policy": p, "training_run": k, "episode": e, "route_file": route_files("prybuzka_ho10")[e - 1].name,
                        "sumo_seed": GLOBAL_SEED + TRIAL_OFFSET + k + e, "seconds_csv": rel(d / f"seconds_e{e}.csv"),
                        "decisions_csv": rel(d / f"decisions_e{e}.csv"), "tripinfo": rel(trip) if trip else "",
                        "checkpoint": rel(g["ckpt"]), "flags": " ".join(g["flags"]),
                        "identical_to_e12": None if g["episodes"][e] is None or h is None else h == g["episodes"][e]})
        ok = rc == 0 and all((d / f"seconds_e{e}.csv").is_file() for e in eps)
        return {"status": "done" if ok else f"FAILED (exit {rc}; see {rel(d / 'replay.log')})",
                "minutes": (time.time() - t0) / 60, "episodes": out}

    infos = pool([(f"{p} run {k}", (lambda p=p, k=k, g=g: job(p, k, g))) for (p, k), g in groups.items()],
                 args.workers, "replay")
    eps = [e for i in infos for e in i.get("episodes", [])]
    (REPLAY_DIR / "replay.json").write_text(json.dumps({"written": now(), "twin": "original (SUMO default vehicle)",
                                                        "episodes": eps}, indent=2), encoding="utf-8")
    differ = [e for e in eps if e["identical_to_e12"] is False]
    log(f"replay: {len(eps)} episodes; identical to E12: {sum(e['identical_to_e12'] is True for e in eps)}, "
        f"differ: {len(differ)}, not checked: {sum(e['identical_to_e12'] is None for e in eps)}")
    return 1 if differ or any(not ok_status(i) for i in infos) else 0


# ------------------------------------------------------------------ selection (pre-registration 5.1, 5.2)
def collect(base: Path, fname: str) -> list[dict]:
    rows = []
    for p in sorted(base.glob(f"*/*/{fname}")):
        rows += json.loads(p.read_text(encoding="utf-8"))["episodes"]
    return rows


def fixed_index(base_rows: list[dict]) -> dict:
    return {(r["map"], int(r["training_run"]), int(r["episode"])): r for r in base_rows
            if r["policy"] == "Fixed plan" and r["tripinfo_ok"]}


def candidate(rows: list[dict], fixed: dict, rung: str, policy: str) -> dict:
    """Score 5.1: mean over x1.0 and x1.2 of (mean arrivals - fixed-plan arrivals) / mean demand, in %, on the
    validation files; per-load models on their own load, the general model (L4) on each load. Paired with the
    fixed-plan run of the same file and SUMO seed."""
    c = {"rung": rung, "policy": policy, "loads": {}}
    for load in ("x1.0", "x1.2"):
        vmap = VAL[load]
        mine = [r for r in rows if r["rung"] == rung and r["policy"] == policy and r["map"] == vmap and r["tripinfo_ok"]
                and (rung == "L4" or r["train_load"] == load)]
        if not mine:
            c["loads"][load] = None
            continue
        pairs = [(r, fixed.get((vmap, int(r["training_run"]), int(r["episode"])))) for r in mine]
        if any(f is None for _, f in pairs):
            sys.exit(f"select: fixed-plan runs missing on {vmap}: run 'baselines' first")
        dem = st.mean(r["demand"] for r in mine)
        c["loads"][load] = {
            "episodes": len(mine), "expected": n_eval_eps(vmap) * len(RUNS_K),
            "arrived_1800": round(st.mean(r["arrived_1800"] for r in mine), 2),
            "fixed_arrived_1800": round(st.mean(f["arrived_1800"] for _, f in pairs), 2), "demand": round(dem, 2),
            "score": round(100 * st.mean(r["arrived_1800"] - f["arrived_1800"] for r, f in pairs) / dem, 4),
            "deadlocks": sum(r["deadlock"] for r in mine), "mean_delay_s": round(st.mean(r["mean_delay_s"] for r in mine), 2)}
    v = list(c["loads"].values())
    c["scored"] = all(v)
    c["complete"] = c["scored"] and all(x["episodes"] == x["expected"] for x in v)
    if c["scored"]:
        c["score"] = round(st.mean(x["score"] for x in v), 4)
        c["deadlock"] = int(any(x["deadlocks"] for x in v))
        c["delay"] = round(st.mean(x["mean_delay_s"] for x in v), 2)
    return c


def rank(cands: list[dict]) -> list[dict]:
    """Rule 5.1: deadlock-free candidates first, then by score; scores within 0.1 percentage points go to the
    lower mean total delay (adjacent swaps until stable: each swap removes one delay inversion, so it ends)."""
    order = sorted(cands, key=lambda c: (c["deadlock"], -c["score"]))
    changed = True
    while changed:
        changed = False
        for i in range(len(order) - 1):
            a, b = order[i], order[i + 1]
            if a["deadlock"] == b["deadlock"] and abs(a["score"] - b["score"]) <= 0.1 and b["delay"] < a["delay"]:
                order[i], order[i + 1] = b, a
                changed = True
    for i, c in enumerate(order, 1):
        c["rank"] = i
    return order


def select(args: argparse.Namespace) -> int:
    rows, fixed = collect(EVAL_DIR, "eval.json"), fixed_index(collect(BASE_DIR, "baseline.json"))
    t = twin()
    p12 = RUNS / "selection_L12.json"
    sel12 = selection("L12")
    if sel12:
        log(f"select: {rel(p12)} exists and is kept: base {sel12['base_rung']} ({sel12['base_mode']} order), "
            f"rewards {', '.join(sel12['rewards'])}")
    else:
        cands = [candidate(rows, fixed, r, p) for r in ("L1", "L2") for p in POLICIES]
        missing = [f"{c['rung']} {c['policy']}" for c in cands if not c["scored"]]
        if missing:
            log("select: no validation results yet for " + ", ".join(missing) + "; run 'run L12' first")
            return 1
        ranked = rank(cands)
        means = {r: round(st.mean(c["score"] for c in cands if c["rung"] == r), 4) for r in ("L1", "L2")}
        base = "L1" if means["L1"] > means["L2"] else "L2"
        sel12 = {"written": now(), "twin": twin_tag(t), "rule": "pre-registration 5.2: base = higher mean score over the "
                 "4 rewards (L1 or L2); rewards = the 2 best-ranked rewards of the base design (5.1 ranking)",
                 "rung_mean_scores": means, "base_rung": base, "base_mode": RUNG_MODE[base],
                 "rewards": [c["policy"] for c in ranked if c["rung"] == base][:2],
                 "warnings": [f"{c['rung']} {c['policy']}: incomplete validation results" for c in cands if not c["complete"]],
                 "ranking": ranked}
        p12.write_text(json.dumps(sel12, indent=2), encoding="utf-8")
        log(f"select: L1 mean score {means['L1']:+.2f}%, L2 {means['L2']:+.2f}% -> base {base}; rewards for L3/L4: "
            f"{', '.join(sel12['rewards'])}" + (f"; WARNINGS: {'; '.join(sel12['warnings'])}" if sel12["warnings"] else ""))
    late = [candidate(rows, fixed, r, p) for r in ("L3", "L4") for p in sel12["rewards"]]
    if not all(c["scored"] for c in late):
        log("select: L3/L4 validation results not complete yet; the final design is chosen after 'run L34'")
        return 0
    if (RUNS / "locked.json").is_file():
        log("select: the locked test has started; selection_final.json is kept")
        return 0
    cands = [candidate(rows, fixed, r, p) for r in ("L1", "L2") for p in POLICIES] + late
    ranked = rank(cands)
    final = {"written": now(), "twin": twin_tag(t), "rule": "pre-registration 5.2 (3): best 5.1 ranking over L1-L4",
             "final": {k: ranked[0][k] for k in ("rung", "policy", "score", "deadlock", "delay")},
             "base_rung": sel12["base_rung"], "base_mode": sel12["base_mode"], "rewards": sel12["rewards"],
             "warnings": [f"{c['rung']} {c['policy']}: incomplete validation results" for c in cands if not c["complete"]],
             "ranking": ranked}
    (RUNS / "selection_final.json").write_text(json.dumps(final, indent=2), encoding="utf-8")
    f = final["final"]
    log(f"select: final design {f['rung']} {f['policy']} (score {f['score']:+.2f}%, deadlock {f['deadlock']}, "
        f"delay {f['delay']} s/veh)" + (f"; WARNINGS: {'; '.join(final['warnings'])}" if final["warnings"] else ""))
    return 0


# ------------------------------------------------------------------ locked test (pre-registration 3, 7.2)
def check_locked_files() -> int:
    listed = {line.split()[0] for line in (E13 / "locked_test_hashes.txt").read_text(encoding="utf-8").splitlines()
              if line.strip()}
    files = [f for m in list(LOCKED.values()) + LOCKED_SC for f in route_files(m)]
    bad = [rel(f) for f in files if file_hash(f) not in listed]
    if bad or len(files) != 50:
        sys.exit(f"locked test files differ from the pre-registered hashes ({len(files)} files; differing: {bad[:5]})")
    return len(files)


def locked(args: argparse.Namespace) -> int:
    if SMOKE:
        sys.exit("the locked test is never run in a smoke test")
    if not args.go:
        sys.exit("the locked test runs once, only when Pavlo asks for it: add --go")
    t = twin_for_runs()
    check_twin_consistency(t)
    final = selection("final")
    if final is None:
        sys.exit("no runs/selection_final.json: the final design must be chosen ('select' after L34) before the locked test")
    mods = models("L0") + models("L12") + models("L34")
    planned = train_plan("L12") + train_plan("L34")
    if len(models("L12")) + len(models("L34")) != len(planned):
        sys.exit("not every L1-L4 training run is done; finish 'run L12' and 'run L34' first")
    n = check_locked_files()
    marker = RUNS / "locked.json"
    if marker.is_file():
        m = json.loads(marker.read_text(encoding="utf-8"))
        if m.get("complete"):
            sys.exit(f"the locked test was already run (finished {m.get('finished')}); it runs once")
        if not args.rerun_reason:
            sys.exit("the locked test was started before and is incomplete. A rerun is allowed only after a technical "
                     "failure: add --rerun-reason \"<what failed>\" (it is logged)")
        m.setdefault("reruns", []).append({"date": now(), "reason": args.rerun_reason})
    else:
        m = {"started": now(), "twin": twin_tag(t), "final_design": final["final"], "files_checked": n,
             "selection_final_sha256": file_hash(RUNS / "selection_final.json"), "reruns": []}
    take_lock("locked")
    keep_awake()
    marker.write_text(json.dumps(m, indent=2), encoding="utf-8")
    log(f"locked: {len(mods)} models and 2 baselines on the locked test ({n} files, hashes checked)")
    rc = run_baselines(("locked",), t, args.workers) | evaluate(mods, ("locked",), t, args.workers, "locked")
    m["finished"], m["complete"] = now(), rc == 0
    marker.write_text(json.dumps(m, indent=2), encoding="utf-8")
    log(f"locked: finished, {'complete' if rc == 0 else 'NOT complete (technical failure: see the log)'}")
    return rc


# ------------------------------------------------------------------ run state, status, wait
LOCK = RUNS / "e13.lock"
FINISHED = RUNS / "e13_finished.json"


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
        sys.exit(f"E13 is already running ({lock['cmd']}, pid {lock['pid']}, since {lock['started']}); see 'status'")
    RUNS.mkdir(parents=True, exist_ok=True)
    FINISHED.unlink(missing_ok=True)
    LOCK.write_text(json.dumps({"pid": os.getpid(), "cmd": cmd, "started": now(), "start_ts": time.time(),
                                "cost_at_start": progress()["cost_done"]}), encoding="utf-8")
    atexit.register(release_lock)


def eval_done(mdl_name: str, map_name: str) -> bool:
    p = EVAL_DIR / mdl_name / map_name / "eval.json"
    return p.is_file() and json.loads(p.read_text(encoding="utf-8"))["status"] == "done"


def progress() -> dict:
    """Training episodes and evaluations of L0-L4 (validation and test A); L3/L4 counted with 2 rewards before
    the selection exists."""
    p = dict(train_runs=0, train_done=0, train_failed=0, train_eps=0, train_eps_total=0, eval_jobs=0, eval_done=0,
             cost_done=0.0, cost_total=0.0)
    sel = selection("L12")
    plan = train_plan("L12") + (l34_jobs(sel["rewards"], sel["base_mode"]) if sel else l34_jobs(list(POLICIES)[:2], "?"))
    mods = [(model_name(m), m["load"]) for m in models("L0")]
    for j in plan:
        job = TRAIN_DIR / job_name(j)
        p["train_runs"] += 1
        if (job / "done.json").is_file():
            p["train_done"] += 1
            n = j["eps"]
        else:
            p["train_failed"] += (job / "failed.json").is_file()
            n = episodes_in(run_folder(job)) if job.is_dir() else 0
        p["train_eps"] += n
        p["train_eps_total"] += j["eps"]
        p["cost_done"] += n * COST[j["load"]]
        p["cost_total"] += j["eps"] * COST[j["load"]]
        mods.append((job_name(j), j["load"]))
    for name, load in mods:
        for m in eval_maps(load, ("validation", "testA")):
            cost = n_eval_eps(m) * EVAL_COST
            p["eval_jobs"] += 1
            p["cost_total"] += cost
            if eval_done(name, m):
                p["eval_done"] += 1
                p["cost_done"] += cost
    return p


def state() -> str:
    if read_lock():
        return "running"
    return "finished" if FINISHED.is_file() else "stopped"


def status(args: argparse.Namespace) -> int:
    p = progress()
    t = json.loads(TWIN.read_text(encoding="utf-8"))["twin"]
    sel, fin = selection("L12"), selection("final")
    print(f"twin:       {t}")
    print(f"training:   {p['train_done']}/{p['train_runs']} runs done, {p['train_failed']} failed, "
          f"{p['train_eps']}/{p['train_eps_total']} episodes" + ("" if sel else " (L3/L4 counted with 2 rewards)"))
    print(f"evaluation: {p['eval_done']}/{p['eval_jobs']} model x map evaluations done (validation and test A)")
    print("selection:  " + (f"base {sel['base_rung']}, rewards {', '.join(sel['rewards'])}" if sel else "not yet")
          + (f"; final design {fin['final']['rung']} {fin['final']['policy']}" if fin else ""))
    if (RUNS / "locked.json").is_file():
        lk = json.loads((RUNS / "locked.json").read_text(encoding="utf-8"))
        print(f"locked:     started {lk['started']}" + (f", finished {lk['finished']}" if lk.get("finished") else ""))
    pct = 100 * p["cost_done"] / p["cost_total"] if p["cost_total"] else 0
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
        print(f"state: NOT RUNNING, about {pct:.0f}% done" + (" (L0-L4 complete)" if pct >= 99.95 else
                                                               " (start it again to continue)" if pct > 0 else ""))
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
    print(f"E13 state: {state()}")
    return 0


def running(args: argparse.Namespace) -> int:
    return 0 if read_lock() else 1


# ------------------------------------------------------------------ summary, pack, publish
def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    fields = list(dict.fromkeys(k for r in rows for k in r))
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def fmt(x, spec: str = ".0f") -> str:
    return "" if x in ("", None) else format(x, spec)


def write_summary(eval_rows: list[dict], base_rows: list[dict]) -> None:
    fixed = fixed_index(base_rows)
    md = [f"# E13 summary ({platform.node()}, {now()})", "",
          f"Twin: {twin_tag(json.loads(TWIN.read_text(encoding='utf-8')))}. Computed by `e13.py pack` from the files in "
          "`runs/`; the analysis is done on the main PC. Every evaluation episode lasts 1800 s. Full = at least 99% of "
          "the demand entered the network. Deadlock = no arrival for at least 300 s while vehicles are in the network. "
          "Delay = total delay including unserved vehicles, per demanded vehicle. Δ fixed = mean paired difference in "
          "arrivals by 1800 s against the fixed plan (same file and SUMO seed), in % of the mean demand. Switches = "
          "green changes between decisions (median).", ""]
    for name in ("L12", "final"):
        sel = selection(name)
        if not sel:
            continue
        head = (f"base {sel['base_rung']} ({sel['base_mode']} order), rewards {', '.join(sel['rewards'])}" if name == "L12"
                else f"final design {sel['final']['rung']} {sel['final']['policy']}")
        md += [f"## Selection {name}: {head}", "", "| Rank | Rung | Reward | Score x1.0, % | Score x1.2, % | Score, % | "
               "Deadlock | Delay, s/veh | Complete |", "|---|---|---|---|---|---|---|---|---|"]
        for c in sel["ranking"]:
            md.append(f"| {c['rank']} | {c['rung']} | {c['policy']} | {c['loads']['x1.0']['score']:+.2f} | "
                      f"{c['loads']['x1.2']['score']:+.2f} | {c['score']:+.2f} | {c['deadlock']} | {c['delay']:.1f} | "
                      f"{'yes' if c['complete'] else 'NO'} |")
        md += [""] + [f"Warning: {w}" for w in sel["warnings"]] + ([""] if sel["warnings"] else [])
    rows = [r for r in eval_rows + base_rows if r["tripinfo_ok"]]
    for s, title in (("validation", "Validation"), ("testA", "Test A (E12 held-out and scenario files)"),
                     ("locked", "Locked test")):
        srows = [r for r in rows if r["eval_set"] == s]
        if not srows:
            continue
        md += [f"## {title}", "", "| Demand | Controller | Episodes | Full | Deadlocks | Arrived by 1800 s (mean) | "
               "Δ fixed, % | Delay, s/veh (mean) | Not inserted (mean) | Switches (median) |",
               "|---|---|---|---|---|---|---|---|---|---|"]
        groups: dict[tuple, list[dict]] = {}
        for r in srows:
            key = ("0" if r["rung"] == "baseline" else r["rung"], r["policy"],
                   "" if r["rung"] in ("baseline", "L4") else r["train_load"])
            groups.setdefault((r["label"], key), []).append(r)
        for lab in LABELS:
            for key in sorted(k for l, k in groups if l == lab):
                rr = groups[(lab, key)]
                name = key[1] if key[0] == "0" else f"{key[0]} {key[1]}" + (f" ({key[2]} model)" if key[2] and key[2] != lab
                                                                             else "")
                pairs = [(r, fixed.get((r["map"], int(r["training_run"]), int(r["episode"])))) for r in rr]
                diff = ("" if key[0] == "0" and key[1] == "Fixed plan" or any(f is None for _, f in pairs) else
                        100 * st.mean(r["arrived_1800"] - f["arrived_1800"] for r, f in pairs) / st.mean(r["demand"] for r in rr))
                sw = [r["switches"] for r in rr if r["switches"] != ""]
                md.append(f"| {lab} | {name} | {len(rr)} | {100 * sum(r['full'] for r in rr) / len(rr):.0f}% | "
                          f"{sum(r['deadlock'] for r in rr)} | {st.mean(r['arrived_1800'] for r in rr):.0f} | "
                          f"{fmt(diff, '+.2f')} | {st.mean(r['mean_delay_s'] for r in rr):.1f} | "
                          f"{st.mean(r['not_inserted'] for r in rr):.0f} | {fmt(st.median(sw) if sw else '')} |")
        md.append("")
    md += ["## Training (last 10 episodes of each run, online learning on)", "",
           "| Rung | Reward | Load | Runs | Entered (mean) | Arrived by the end (mean) | Deadlocks | Demand (mean) |",
           "|---|---|---|---|---|---|---|---|"]
    train_rows = []
    for f in sorted(TRAIN_DIR.glob("*/episodes.csv")):
        with f.open(newline="", encoding="utf-8") as fh:
            rr = [r for r in csv.DictReader(fh) if r["tripinfo_ok"] == "1"]
        last = max((int(r["episode"]) for r in rr), default=0)
        train_rows += [r for r in rr if int(r["episode"]) > last - 10]
    keys = sorted({(r["rung"], r["policy"], r["load"]) for r in train_rows})
    for rung, pol, load in keys:
        rr = [r for r in train_rows if (r["rung"], r["policy"], r["load"]) == (rung, pol, load)]
        md.append(f"| {rung} | {pol} | {load} | {len({r['run'] for r in rr})} | {st.mean(int(r['entries']) for r in rr):.0f} | "
                  f"{st.mean(int(r['arrived_1800']) for r in rr):.0f} | {sum(int(r['deadlock']) for r in rr)} | "
                  f"{st.mean(int(r['demand']) for r in rr):.0f} |")
    rp = REPLAY_DIR / "replay.json"
    if rp.is_file():
        eps = json.loads(rp.read_text(encoding="utf-8"))["episodes"]
        md += ["", "## B1 replay", "", f"{len(eps)} episodes; identical to E12: "
               f"{sum(e['identical_to_e12'] is True for e in eps)}, differ: {sum(e['identical_to_e12'] is False for e in eps)}, "
               f"not checked: {sum(e['identical_to_e12'] is None for e in eps)}. Files: `runs/replay/`."]
    (RESULTS / "SUMMARY.md").write_text("\n".join(md) + "\n", encoding="utf-8")


def pack(args: argparse.Namespace) -> int:
    if RESULTS.exists():
        shutil.rmtree(RESULTS)
    RESULTS.mkdir(parents=True)
    dones = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(TRAIN_DIR.glob("*/done.json"))]
    write_csv(RESULTS / "train_runs.csv", [{k: (" ".join(v) if isinstance(v, list) else v) for k, v in d.items()
                                            if k != "status"} for d in dones])
    train_rows = []
    for p in sorted(TRAIN_DIR.glob("*/episodes.csv")):
        with p.open(newline="", encoding="utf-8") as f:
            train_rows += list(csv.DictReader(f))
    write_csv(RESULTS / "train_episodes.csv", train_rows)
    eval_rows, base_rows = collect(EVAL_DIR, "eval.json"), collect(BASE_DIR, "baseline.json")
    write_csv(RESULTS / "eval_episodes.csv", eval_rows)
    write_csv(RESULTS / "baseline_episodes.csv", base_rows)
    for p in [RUNS / n for n in ("selection_L12.json", "selection_final.json", "locked.json", "verify.json", "bench.json",
                                 "e13.log")] + [REPLAY_DIR / "replay.json", TWIN]:
        if p.is_file():
            (RESULTS / p.name).write_text(p.read_text(encoding="utf-8").replace(E13.as_posix() + "/", ""), encoding="utf-8")
    (RESULTS / "environment.json").write_text(json.dumps(versions(), indent=2), encoding="utf-8")
    write_summary(eval_rows, base_rows)

    light = getattr(args, "light", False)    # intermediate pack: no evaluation tripinfo files
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    zpath = RUNS / f"e13_pack_{platform.node()}{'_light' if light else ''}_{stamp}.zip"
    n = 0
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for p in sorted(RESULTS.iterdir()):
            z.write(p, f"results/{p.name}")
            n += 1
        final = {(E13 / d["checkpoint"]).resolve() for d in dones}    # the one final checkpoint per run
        for job in sorted(TRAIN_DIR.glob("*")):
            last = f"tripinfo_{json.loads((job / 'done.json').read_text(encoding='utf-8'))['episodes']}.xml" \
                if (job / "done.json").is_file() else ""
            for p in sorted(job.rglob("*")):
                if p.is_file() and (p.suffix in (".json", ".log") or p.resolve() in final or p.name == "episodes.csv"
                                    or p.name.startswith("metrics_") or p.name == last):
                    z.write(p, rel(p))
                    n += 1
        for base in (EVAL_DIR, BASE_DIR, REPLAY_DIR):
            for p in sorted(base.rglob("*")) if base.is_dir() else []:
                if p.is_file() and p.suffix != ".pt" and not (light and p.suffix == ".xml"):
                    z.write(p, rel(p))    # (evaluation folders only hold copies of the frozen checkpoint)
                    n += 1
    log(f"pack: results/ written (SUMMARY.md); {zpath.name}: {n} files, {zpath.stat().st_size / 1e6:.0f} MB")
    return 0


def git(*a: str, cwd: Path = REPO, capture: bool = False, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *a], cwd=cwd, check=check, text=True, capture_output=capture)


def git_ident() -> list[str]:
    """Commit identity: the user's git config, else a neutral one for these commits only."""
    if git("config", "user.email", capture=True, check=False).stdout.strip():
        return []
    return ["-c", "user.name=E13 runner", "-c", f"user.email=e13@{platform.node()}.invalid"]


def push_pack_branch(z: Path, stamp: str, digest: str) -> str:
    """Without the GitHub CLI: push the zip in 95-MB parts to a new branch (GitHub refuses files over 100 MB)."""
    url = git("remote", "get-url", "origin", capture=True).stdout.strip()
    branch = f"pack-e13-{stamp}"
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
    git(*git_ident(), "commit", "-q", "-m", f"E13 pack {stamp}", cwd=tmp)
    git("push", "-q", url, branch, cwd=tmp)
    shutil.rmtree(tmp, ignore_errors=True)
    return f"git branch {branch} ({n} parts)"


def publish(args: argparse.Namespace) -> int:
    """Upload the newest pack zip (GitHub release, else a branch) and push e13/results/ to the main branch."""
    lock = read_lock()
    if lock and lock["pid"] != os.getpid():
        sys.exit("E13 is still running; publish after it has finished")
    zips = sorted(RUNS.glob("e13_pack_*.zip"), key=lambda p: p.stat().st_mtime)
    if SMOKE or not zips or not (RESULTS / "SUMMARY.md").is_file():
        sys.exit("nothing to publish: run 'pack' first (a smoke test is never published)")
    z = zips[-1]
    stamp = re.search(r"_(\d{8}_\d{4})\.zip$", z.name).group(1)
    digest = file_hash(z)
    uploaded = RUNS / "uploaded.json"    # a retried publish does not upload the same zip again
    prev = json.loads(uploaded.read_text(encoding="utf-8")) if uploaded.is_file() else {}
    where = prev.get("where") if prev.get("sha256") == digest else None
    if where is None and shutil.which("gh") and subprocess.run(["gh", "auth", "status"], capture_output=True).returncode == 0:
        tag = f"e13-{stamp}"
        r = subprocess.run(["gh", "release", "create", tag, str(z), "--title", f"E13 pack {stamp}",
                            "--notes", f"{z.name}, sha256 {digest}"], cwd=REPO, capture_output=True, text=True)
        if r.returncode == 0:
            where = f"GitHub release {tag} {r.stdout.strip()}"
        else:
            log(f"publish: gh release failed ({r.stderr.strip()[:200]}); pushing a branch instead")
    if where is None:
        where = push_pack_branch(z, stamp, digest)
    uploaded.write_text(json.dumps({"zip": z.name, "sha256": digest, "where": where}, indent=2), encoding="utf-8")
    (RESULTS / "PACK.txt").write_text(f"{z.name}\nsha256 {digest}\n{z.stat().st_size} bytes\n{where}\n", encoding="utf-8")
    ident = git_ident()
    git("add", "e13/results")
    if git("diff", "--cached", "--quiet", check=False).returncode != 0:
        git(*ident, "commit", "-q", "-m", f"E13 results ({platform.node()}, {stamp})")
    git(*ident, "pull", "-q", "--rebase", "--autostash")
    git("push", "-q")
    (RUNS / "published.json").write_text(json.dumps({"published": now(), "zip": z.name, "sha256": digest,
                                                     "where": where}, indent=2), encoding="utf-8")
    log(f"publish: e13/results/ pushed to the main branch; pack: {where}")
    return 0


def pack_and_publish(args: argparse.Namespace, light: bool = False) -> bool:
    args.light = light
    if pack(args) != 0:
        return False
    if not args.publish or SMOKE:
        return False
    try:
        return publish(args) == 0
    except (subprocess.CalledProcessError, OSError, SystemExit) as e:
        log(f"all: publish failed ({e}); run 'e13.py publish' again")
        return False


def run_all(args: argparse.Namespace) -> int:
    if FINISHED.is_file() and not args.again:
        f = json.loads(FINISHED.read_text(encoding="utf-8"))
        if f.get("complete") and (f.get("published") or not args.publish):
            print(f"E13 already finished at {f['finished']}: {f['summary']} (--again repeats the checks and the pack)")
            return 0
    t = twin_for_runs()
    check_twin_consistency(t)
    take_lock("all")
    keep_awake()
    if verify(args) != 0:
        log("all: stopped, a blocking verify check failed (see above)")
        return 1
    rc = {"baselines": baselines_cmd(args), "L0": run_stage("L0", args), "replay": replay(args),
          "L12": run_stage("L12", args)}
    rc["select L12"] = select(args)
    published = False
    if selection("L12") and args.until != "L12":
        if args.publish:    # intermediate results for the main PC while L3/L4 train
            pack_and_publish(args, light=True)
        rc["L34"] = run_stage("L34", args)
        rc["select final"] = select(args)
    published = pack_and_publish(args)
    p = progress()
    zips = sorted(RUNS.glob("e13_pack_*.zip"), key=lambda q: q.stat().st_mtime)
    complete = all(v == 0 for v in rc.values()) and (args.until == "L12" or selection("final") is not None)
    failed = [k for k, v in rc.items() if v != 0]
    info = {"finished": now(), "complete": complete, "published": published, "until": args.until,
            "summary": f"{p['train_done']}/{p['train_runs']} training runs, {p['eval_done']}/{p['eval_jobs']} "
                       f"evaluations, pack {zips[-1].name if zips else 'missing'}"
                       + ("" if complete else f"; NOT complete ({', '.join(failed) or 'final selection missing'}), "
                                              "run again")}
    FINISHED.write_text(json.dumps(info, indent=2), encoding="utf-8")
    log(f"all: finished; {info['summary']}" + ("; published" if published else ""))
    return 0 if complete else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("verify", help="identity and signal-rule checks")
    b = sub.add_parser("bench", help="throughput test; saves the suggested --workers")
    b.add_argument("--workers-list", help="process counts to test, e.g. 1,8,15 (default: 1, N/2, N-1)")
    parsers = {}
    for name, text in (("run", "train and evaluate one stage"), ("baselines", "fixed and actuated plans"),
                       ("replay", "B1 replay of deadlocked E12 episodes"), ("all", "everything except the locked test"),
                       ("locked", "the locked test, once")):
        p = parsers[name] = sub.add_parser(name, help=text)
        p.add_argument("--workers", type=int, default=default_workers(),
                       help="parallel processes (default: from 'bench', else logical CPUs - 1)")
    parsers["run"].add_argument("stage", choices=["L0", "L12", "L34"])
    for name in ("run", "all"):
        parsers[name].add_argument("--only-policy", nargs="+", choices=list(POLICIES))
    parsers["all"].add_argument("--publish", action="store_true", help="publish after L12 and at the end")
    parsers["all"].add_argument("--again", action="store_true", help="repeat even if a complete run has finished")
    parsers["all"].add_argument("--until", choices=["L12", "L34"], default="L34", help="last stage (default L34)")
    parsers["locked"].add_argument("--go", action="store_true", help="confirm: Pavlo asked for the locked test")
    parsers["locked"].add_argument("--rerun-reason", help="only after a technical failure of the locked run")
    sub.add_parser("select", help="selection rules 5.1/5.2 on the validation results")
    sub.add_parser("status", help="progress, state and time left")
    w = sub.add_parser("wait", help="block until the run ends or the time is up, then print the status")
    w.add_argument("--minutes", type=float, default=9.0, help="maximum wait (default 9)")
    sub.add_parser("running", help="exit code 0 if a run is active, else 1")
    pk = sub.add_parser("pack", help="results/ with SUMMARY.md, and the pack zip")
    pk.add_argument("--light", action="store_true", help="leave out the evaluation tripinfo files")
    sub.add_parser("publish", help="upload the pack zip and push e13/results/")
    args = ap.parse_args()
    fn = {"verify": verify, "bench": bench, "run": run_cmd, "baselines": baselines_cmd, "replay": replay,
          "select": select, "locked": locked, "status": status, "wait": wait, "running": running, "pack": pack,
          "publish": publish, "all": run_all}[args.cmd]
    return fn(args)


if __name__ == "__main__":
    sys.exit(main())
