#!/usr/bin/env python3
"""Frozen evaluation of trained RESCO policies on held-out and scenario demand (Comments 1.5, 1.6, 1.7, 1.9).

Two steps:

  discover  Scan RESCO results folders for the trained runs (IDQN-wait, IDQN-queue, MPLight at x1.0, x1.2,
            x1.5; trials 1-5) and write a checkpoint list. Check it by hand before running.
  run       Evaluate every selected checkpoint with the patched RESCO copy (--ckpt, greedy policy, no learning)
            on the evaluation maps and write E3_runs.csv (one row per evaluation episode).

Evaluation plan per checkpoint (trial number = 1000 + training run, so SUMO seeds 42 + trial + episode never
overlap the training seeds):
  heldout    own training load: prybuzka_ho10 / prybuzka_ho12 / prybuzka_ho15, 10 route files each
  scenarios  x1.0-trained policies only: prybuzka_s1 ... prybuzka_s4, 5 route files each
  transfer   optional, x1.0-trained policies only: prybuzka_ho12, prybuzka_ho15

E12 additions: IDQN-pressure (reward pressure_inout), the training maps prybuzka_tr10/_tr12/_tr15 in discover,
--libsumo (identical results, 3-4 x faster), --only-run, and --no-table for parallel processes (e12.py eval).

Examples (Windows, from this folder):
  python eval_frozen.py discover --results C:/Work/RESCO/results --out checkpoints.csv
  python eval_frozen.py run --checkpoints checkpoints.csv --out-dir E3 --sets heldout scenarios --dry-run
  python eval_frozen.py run --checkpoints checkpoints.csv --out-dir E3 --sets heldout scenarios
  python eval_frozen.py run --checkpoints checkpoints.csv --out-dir E3 --sets heldout --allred 4
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

KIT = Path(__file__).resolve().parent
DEFAULT_RESCO = KIT / "resco"            # folder that contains resco_benchmark/
GLOBAL_SEED = 42                          # resco_benchmark/__init__.py

# RESCO run folder: <Alg>-tr<trial>-<map>-<n lights>-<state fn>-<reward fn>==<uuid hex>
RUN_RE = re.compile(r"^(?P<alg>[A-Za-z0-9]+)-tr(?P<tr>\d+)-(?P<map>[A-Za-z0-9_]+)-(?P<nlights>\d+)-"
                    r"(?P<state>[A-Za-z0-9_]+)-(?P<reward>[A-Za-z0-9_]+)==(?P<uuid>[0-9a-f]{32})$")

# (algorithm class, reward function) -> (policy label in the paper, --agent name in main.py)
POLICIES = {
    ("IDQN", "wait_norm"): ("IDQN-wait", "IDQN"),
    ("IDQN", "pressure_norm"): ("IDQN-queue", "IDQN_pressure"),
    ("MPLight", "pressure"): ("MPLight", "MPLight"),
    ("IDQN", "pressure_inout"): ("IDQN-pressure", "IDQN_pressure_inout"),    # E12
}
TRAIN_LOADS = {"prybuzka": "x1.0", "prybuzka_12": "x1.2", "prybuzka_15": "x1.5",
               "prybuzka_tr10": "x1.0", "prybuzka_tr12": "x1.2", "prybuzka_tr15": "x1.5"}    # E12 training maps
HELDOUT_MAP = {"x1.0": "prybuzka_ho10", "x1.2": "prybuzka_ho12", "x1.5": "prybuzka_ho15"}
SCENARIO_MAPS = ["prybuzka_s1", "prybuzka_s2", "prybuzka_s3", "prybuzka_s4"]
TRANSFER_MAPS = ["prybuzka_ho12", "prybuzka_ho15"]
MAP_LABEL = {"prybuzka_ho10": "x1.0", "prybuzka_ho12": "x1.2", "prybuzka_ho15": "x1.5",
             "prybuzka_s1": "S1", "prybuzka_s2": "S2", "prybuzka_s3": "S3", "prybuzka_s4": "S4"}

CKPT_FIELDS = ["selected", "policy", "agent", "train_map", "train_load", "training_run", "episodes",
               "checkpoint", "checkpoint_exists", "run_folder", "folder_mtime", "note"]
RUN_FIELDS = ["policy", "agent", "train_load", "training_run", "eval_set", "map", "load_or_scenario", "episode",
              "route_file", "sumo_seed", "trial", "clearance", "checkpoint_path", "run_folder", "tripinfo_path",
              "tripinfo_ok", "n_entries", "n_arrived_1500", "n_arrived_1800", "mean_wait_arrived_s", "returncode"]


# ------------------------------------------------------------------ discover
def episodes_in(folder: Path) -> int:
    eps = [int(m.group(1)) for f in folder.glob("tripinfo_*.xml") if (m := re.match(r"tripinfo_(\d+)\.xml$", f.name))]
    return max(eps) if eps else 0


def checkpoint_of(folder: Path, alg: str) -> Path:
    if alg == "MPLight":
        # SharedAgent.observe() saves log_dir + 'agent' (no separator): the file sits next to the run folder
        return folder.parent / (folder.name + "agent.pt")
    inside = folder / "agent_nC.pt"       # IDQN.save() after every episode
    sibling = folder.parent / (folder.name + "agent_nC.pt")    # IndependentAgent.observe() every save_freq
    return inside if inside.is_file() or not sibling.is_file() else sibling


def discover(args: argparse.Namespace) -> int:
    trials = parse_range(args.trials)
    rows, skipped = [], {}
    for results in args.results:
        root = Path(results)
        if not root.is_dir():
            print(f"not a folder: {root}", file=sys.stderr)
            return 2
        for folder in sorted(p for p in root.iterdir() if p.is_dir()):
            m = RUN_RE.match(folder.name)
            if not m:
                continue
            key = (m["alg"], m["reward"])
            if key not in POLICIES or m["map"] not in TRAIN_LOADS or int(m["tr"]) not in trials:
                skipped[f"{m['alg']}/{m['reward']}/{m['map']}"] = skipped.get(f"{m['alg']}/{m['reward']}/{m['map']}", 0) + 1
                continue
            policy, agent = POLICIES[key]
            ckpt = checkpoint_of(folder, m["alg"])
            rows.append({
                "selected": 0, "policy": policy, "agent": agent, "train_map": m["map"],
                "train_load": TRAIN_LOADS[m["map"]], "training_run": int(m["tr"]), "episodes": episodes_in(folder),
                "checkpoint": ckpt.as_posix(), "checkpoint_exists": int(ckpt.is_file()),
                "run_folder": folder.as_posix(),
                "folder_mtime": datetime.fromtimestamp(folder.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                "note": "",
            })
    # select the newest folder with a checkpoint per (policy, load, run), as src/seed_stats.py does
    groups: dict[tuple, list[dict]] = {}
    for r in rows:
        groups.setdefault((r["policy"], r["train_load"], r["training_run"]), []).append(r)
    for key, group in groups.items():
        usable = [r for r in group if r["checkpoint_exists"]]
        if usable:
            best = max(usable, key=lambda r: (r["folder_mtime"], r["run_folder"]))
            best["selected"] = 1
            if best["episodes"] < 100:
                best["note"] = f"only {best['episodes']} episodes found; check that this is the reported run"
        if len(group) > 1:
            for r in group:
                r["note"] = (r["note"] + "; " if r["note"] else "") + f"{len(group)} folders for this run"
        if not usable:
            for r in group:
                r["note"] = (r["note"] + "; " if r["note"] else "") + "no checkpoint file found"
    rows.sort(key=lambda r: (r["train_load"], r["policy"], r["training_run"], -r["selected"], r["run_folder"]))
    out = Path(args.out)
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CKPT_FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} run folders, {sum(r['selected'] for r in rows)} selected -> {out}")
    for policy in sorted({r["policy"] for r in rows}):
        for load in ("x1.0", "x1.2", "x1.5"):
            got = sorted(r["training_run"] for r in rows if r["selected"] and r["policy"] == policy and r["train_load"] == load)
            missing = sorted(set(trials) - set(got))
            print(f"  {policy:10s} {load}: runs {got}" + (f"  MISSING {missing}" if missing else ""))
    if skipped:
        print("ignored folders (other agents, maps or trials): " + ", ".join(f"{k} x{v}" for k, v in sorted(skipped.items())))
    return 0


# ------------------------------------------------------------------ run
def parse_range(text: str) -> list[int]:
    out: list[int] = []
    for part in text.split(","):
        a, _, b = part.partition("-")
        out += list(range(int(a), int(b or a) + 1))
    return out


def route_files(resco: Path, map_name: str) -> list[Path]:
    # same rule as MultiSignal.reset(): sorted(glob(<routes dir>/*.rou.xml))[(run - 1) % n]
    return sorted((resco / "resco_benchmark" / "environments" / map_name / "routes").glob("*.rou.xml"))


def tripinfo_stats(path: Path) -> dict:
    stats = {"tripinfo_ok": 0, "n_entries": "", "n_arrived_1500": "", "n_arrived_1800": "", "mean_wait_arrived_s": ""}
    if not path.is_file():
        return stats
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return stats
    trips = root.findall("tripinfo")
    arrived = [t for t in trips if float(t.get("arrival", "-1")) >= 0]
    stats.update({
        "tripinfo_ok": 1, "n_entries": len(trips),
        "n_arrived_1500": sum(float(t.get("arrival")) <= 1500 for t in arrived),
        "n_arrived_1800": sum(float(t.get("arrival")) <= 1800 for t in arrived),
        "mean_wait_arrived_s": round(sum(float(t.get("waitingTime")) for t in arrived) / len(arrived), 3) if arrived else "",
    })
    return stats


def newest_run_folder(log_dir: Path) -> Path | None:
    folders = [p for p in log_dir.iterdir() if p.is_dir() and RUN_RE.match(p.name)] if log_dir.is_dir() else []
    return max(folders, key=lambda p: (p.stat().st_mtime, p.name)) if folders else None


def plan(rows: list[dict], sets: list[str]) -> list[tuple[dict, str, str]]:
    jobs = []
    for r in rows:
        if "heldout" in sets:
            jobs.append((r, "heldout", HELDOUT_MAP[r["train_load"]]))
        if "scenarios" in sets and r["train_load"] == "x1.0":
            jobs += [(r, "scenario", m) for m in SCENARIO_MAPS]
        if "transfer" in sets and r["train_load"] == "x1.0":
            jobs += [(r, "transfer", m) for m in TRANSFER_MAPS]
    return jobs


def sumo_version(env: dict) -> str:
    home = env.get("SUMO_HOME")
    if not home:
        return "unknown (SUMO_HOME not set)"
    exe = Path(home) / "bin" / ("sumo.exe" if os.name == "nt" else "sumo")
    try:
        out = subprocess.run([str(exe), "--version"], capture_output=True, text=True, timeout=60).stdout
    except OSError as e:
        return f"unknown ({e})"
    return out.splitlines()[0].strip() if out else "unknown"


def eval_dir(out_dir: Path, r: dict, map_name: str) -> Path:
    return out_dir / f"{r['policy']}_{r['train_load']}_tr{r['training_run']}" / map_name


def collect(resco: Path, rows: list[dict], sets: list[str], out_dir: Path, clearance: str, args: argparse.Namespace,
            returncodes: dict) -> list[dict]:
    """One record per planned evaluation episode, from whatever is on disk now (safe with parallel processes)."""
    records = []
    for r, eval_set, map_name in plan(rows, sets):
        routes = route_files(resco, map_name)
        eps = min(len(routes), args.max_eps) if args.max_eps else len(routes)
        trial = args.trial_offset + int(r["training_run"])
        log_dir = eval_dir(out_dir, r, map_name)
        folder = newest_run_folder(log_dir)
        for e in range(1, eps + 1):
            trip = folder / f"tripinfo_{e}.xml" if folder else Path("")
            rec = {
                "policy": r["policy"], "agent": r["agent"], "train_load": r["train_load"],
                "training_run": r["training_run"], "eval_set": eval_set, "map": map_name,
                "load_or_scenario": MAP_LABEL[map_name], "episode": e, "route_file": routes[(e - 1) % len(routes)].name,
                "sumo_seed": GLOBAL_SEED + trial + e, "trial": trial, "clearance": clearance,
                "checkpoint_path": r["checkpoint"], "run_folder": folder.as_posix() if folder else "",
                "tripinfo_path": trip.as_posix() if folder else "", "returncode": returncodes.get(str(log_dir), ""),
            }
            rec.update(tripinfo_stats(trip))
            records.append(rec)
    return records


def run(args: argparse.Namespace) -> int:
    resco = Path(args.resco).resolve()
    bench = resco / "resco_benchmark"
    if not (bench / "main.py").is_file():
        print(f"no resco_benchmark/main.py under {resco}", file=sys.stderr)
        return 2
    with Path(args.checkpoints).open(newline="", encoding="utf-8") as f:
        all_rows = [r for r in csv.DictReader(f) if r["selected"].strip() == "1"]
    dup = {}
    for r in all_rows:
        dup.setdefault((r["policy"], r["train_load"], r["training_run"]), []).append(r["run_folder"])
    clashes = [k for k, v in dup.items() if len(v) > 1]
    if clashes:
        print("more than one selected checkpoint for: " + "; ".join(map(str, clashes)), file=sys.stderr)
        return 2
    rows = [r for r in all_rows if (not args.only_policy or r["policy"] in args.only_policy)
            and (not args.only_load or r["train_load"] in args.only_load)
            and (not args.only_run or int(r["training_run"]) in args.only_run)]
    missing = [r["checkpoint"] for r in rows if not Path(r["checkpoint"]).is_file()]
    if missing and not (args.dry_run or args.collect_only):
        print("checkpoint files not found:\n  " + "\n  ".join(missing), file=sys.stderr)
        return 2

    env = os.environ.copy()
    env["PYTHONPATH"] = str(resco) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    if args.sumo_home:
        env["SUMO_HOME"] = str(Path(args.sumo_home).resolve())
    if args.libsumo:
        env["LIBSUMO_AS_TRACI"] = "1"
    clearance = "yellow3" if args.allred == 0 else f"yellow3+allred{args.allred}"
    out_dir = Path(args.out_dir).resolve() / clearance
    jobs = [] if args.collect_only else plan(rows, args.sets)
    print(f"{len(rows)} checkpoints, {len(jobs)} evaluations to run, clearance {clearance}, output {out_dir}")

    returncodes, failed = {}, 0
    for i, (r, eval_set, map_name) in enumerate(jobs, 1):
        routes = route_files(resco, map_name)
        if not routes:
            print(f"no route files for map {map_name} in {resco}", file=sys.stderr)
            return 2
        eps = min(len(routes), args.max_eps) if args.max_eps else len(routes)
        trial = args.trial_offset + int(r["training_run"])
        log_dir = eval_dir(out_dir, r, map_name)
        cmd = [args.python, "main.py", "--agent", r["agent"], "--map", map_name, "--eps", str(eps),
               "--tr", str(trial), "--procs", "1", "--ckpt", str(Path(r["checkpoint"]).resolve()),
               "--allred", str(args.allred), "--log_dir", str(log_dir) + os.sep]
        if args.libsumo:
            cmd += ["--libsumo", "True"]
        label = f"[{i}/{len(jobs)}] {r['policy']} {r['train_load']} run {r['training_run']} -> {map_name} ({eps} eps)"
        if args.dry_run:
            print(label + "\n    " + subprocess.list2cmdline(cmd))
            continue
        folder = newest_run_folder(log_dir)
        if args.skip_existing and folder is not None and all(
                tripinfo_stats(folder / f"tripinfo_{e}.xml")["tripinfo_ok"] for e in range(1, eps + 1)):
            print(label + " already done, skipped")
            continue
        log_dir.mkdir(parents=True, exist_ok=True)
        t0 = time.time()
        print(label, flush=True)
        with (log_dir / "main.log").open("w", encoding="utf-8") as log:
            proc = subprocess.run(cmd, cwd=bench, env=env, stdout=log, stderr=subprocess.STDOUT)
        returncodes[str(log_dir)] = proc.returncode
        folder = newest_run_folder(log_dir)
        ok = folder is not None and all(
            tripinfo_stats(folder / f"tripinfo_{e}.xml")["tripinfo_ok"] for e in range(1, eps + 1))
        print(f"    exit {proc.returncode}, {time.time() - t0:.0f} s" + ("" if ok else ", TRIPINFO MISSING"), flush=True)
        if not ok:
            failed += 1
            if not args.keep_going:
                print(f"    see {log_dir / 'main.log'} (use --keep-going to continue)", file=sys.stderr)
                break
    if args.dry_run or args.no_table:
        return 1 if failed else 0
    records = collect(resco, all_rows, args.sets, out_dir, clearance, args, returncodes)
    write_runs(out_dir, records, env, args)
    done = sum(1 for x in records if x["tripinfo_ok"] == 1)
    print(f"{out_dir / 'E3_runs.csv'}: {len(records)} planned episodes for all selected checkpoints, {done} done, "
          f"{len(records) - done} not (yet) done")
    return 1 if failed else 0


def write_runs(out_dir: Path, records: list[dict], env: dict, args: argparse.Namespace) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "E3_runs.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=RUN_FIELDS)
        w.writeheader()
        w.writerows(records)
    meta = {
        "written": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "sumo_version": sumo_version(env),
        "python": sys.version.split()[0],
        "resco": str(Path(args.resco).resolve()),
        "checkpoints_csv": str(Path(args.checkpoints).resolve()),
        "sets": args.sets, "allred": args.allred, "trial_offset": args.trial_offset,
        "max_eps": args.max_eps or "all route files",
        "episodes_planned": len(records), "episodes_done": sum(1 for x in records if x["tripinfo_ok"] == 1),
    }
    (out_dir / "E3_runs_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("discover", help="list trained runs and their checkpoints")
    d.add_argument("--results", nargs="+", required=True, help="RESCO results folder(s), e.g. C:/Work/RESCO/results")
    d.add_argument("--out", default="checkpoints.csv", help="checkpoint list to write (default: checkpoints.csv)")
    d.add_argument("--trials", default="1-5", help="training runs to keep (default: 1-5)")
    r = sub.add_parser("run", help="evaluate the selected checkpoints and write E3_runs.csv")
    r.add_argument("--checkpoints", required=True, help="checkpoint list from 'discover' (rows with selected = 1)")
    r.add_argument("--out-dir", required=True, help="output folder; a subfolder per clearance is created")
    r.add_argument("--sets", nargs="+", default=["heldout", "scenarios"], choices=["heldout", "scenarios", "transfer"])
    r.add_argument("--allred", type=int, default=0, help="all-red seconds after each yellow (field plan: 4; default 0)")
    r.add_argument("--resco", default=str(DEFAULT_RESCO), help="patched RESCO root containing resco_benchmark/")
    r.add_argument("--python", default=sys.executable, help="Python of the RESCO environment (default: this one)")
    r.add_argument("--sumo-home", help="SUMO_HOME to use (default: the current environment variable)")
    r.add_argument("--trial-offset", type=int, default=1000, help="trial = offset + training run (default 1000)")
    r.add_argument("--only-policy", nargs="+", choices=["IDQN-wait", "IDQN-queue", "MPLight", "IDQN-pressure"])
    r.add_argument("--only-load", nargs="+", choices=["x1.0", "x1.2", "x1.5"])
    r.add_argument("--only-run", nargs="+", type=int, help="training runs to evaluate (default: all)")
    r.add_argument("--libsumo", action="store_true", help="run SUMO inside the Python process (identical results)")
    r.add_argument("--no-table", action="store_true", help="do not write E3_runs.csv (parallel processes)")
    r.add_argument("--skip-existing", action="store_true", help="do not rerun evaluations whose tripinfo files exist")
    r.add_argument("--keep-going", action="store_true", help="continue after an evaluation without tripinfo")
    r.add_argument("--max-eps", type=int, help="quick test only: evaluate just the first N route files of each map")
    r.add_argument("--collect-only", action="store_true",
                   help="run nothing; rescan the result folders and rewrite E3_runs.csv (after parallel runs)")
    r.add_argument("--dry-run", action="store_true", help="print the commands only")
    args = ap.parse_args()
    return discover(args) if args.cmd == "discover" else run(args)


if __name__ == "__main__":
    sys.exit(main())
