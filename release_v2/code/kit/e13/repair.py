#!/usr/bin/env python3
"""E13 recovery after a power cut (or any crash in the middle of a write).

e13.py writes its state files in place (Path.write_text, no temporary file, no fsync), so a power cut can leave one
empty, cut short or full of NUL bytes. e13.py then stops at its next start with a JSON decode error
(check_twin_consistency, models, evaluate, selection, ...). This script finds such files and, with --apply, moves them
aside so that e13.py redoes exactly the affected job on the next start. It never deletes anything and never
touches the pre-registered artefacts.

  python e13/repair.py            dry run: list what is wrong and what --apply would do (changes nothing)
  python e13/repair.py --apply    move the damaged files (or job folders) to runs/_corrupt/<YYYYmmdd_HHMMSS>/
  options: --runs DIR (default e13/runs; e13/runs_smoke needs --smoke for the smoke settings)

Checked (every state file e13.py reads, plus the ones it only writes):
  runs/train/<job>/done.json        damaged: the whole job folder is moved (train_job deletes the folder before a
                                    rerun anyway, so moving keeps its checkpoint and episodes); the run is trained
                                    again from episode 1 with the same seed
  runs/train/<job>/failed.json      damaged: the file is moved (the job has no done.json and reruns anyway)
  runs/eval/<model>/<map>/eval.json damaged: the folder is moved (eval_job deletes it before a rerun); evaluated again
  runs/baselines/<ctrl>/<map>/baseline.json  damaged: the file is moved; that controller x map runs again
  runs/bench.json, e13.lock, e13_finished.json, replay/replay.json, uploaded.json, published.json, verify.json:
                                    damaged: moved; the effect on the next start is printed
  runs/selection_L12.json, selection_final.json, locked.json, e13/twin.json, the E12 done.json files used by L0:
                                    damaged: STOP, never moved (pre-registered or E12 artefacts): tell Pavlo, who
                                    contacts the lead
  every valid done.json: episodes.csv must hold one complete row per episode (e13.py EPISODES: 100 for L1/L2,
  300 for L3/L4) with every column, and the checkpoint must match checkpoint_sha256: anomalies are reported only.

Exit code: 0 clean; 1 something found (or moved); 2 STOP (a protected file is damaged, or E13 is running).
With a STOP, --apply moves nothing.
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True    # read-only use of e13.py: no __pycache__

import argparse  # noqa: E402
import csv  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402
from datetime import datetime  # noqa: E402
from pathlib import Path  # noqa: E402

HERE = Path(__file__).resolve().parent

REQUIRED = {    # keys e13.py reads from each file (a file without them is as broken as a cut one)
    "done.json": ("status", "rung", "policy", "load", "run", "mode", "episodes", "checkpoint", "checkpoint_sha256"),
    "failed.json": ("status",),
    "eval.json": ("status", "model", "map", "episodes"),
    "baseline.json": ("status", "controller", "map", "episodes"),
    "bench.json": ("suggested_workers",),
    "e13.lock": ("pid", "cmd", "started"),
    "e13_finished.json": ("finished", "complete", "summary"),
    "replay.json": ("episodes",),
    "uploaded.json": ("zip", "sha256", "where"),
    "published.json": ("published", "zip"),
    "verify.json": ("checks",),
    "selection_L12.json": ("base_rung", "base_mode", "rewards", "ranking"),
    "selection_final.json": ("final", "ranking"),
    "locked.json": ("started",),
    "twin.json": ("twin",),
}
EFFECT = {
    "bench.json": "--workers falls back to the E12 bench (../runs/bench.json) or CPUs - 1; 'e13.py bench' writes a new one",
    "e13.lock": "none: e13.py already treats an unreadable lock as 'not running' (read_lock); moved for tidiness",
    "e13_finished.json": "the run is no longer marked finished: start_e13.ps1 repeats verify, skips every finished "
                         "training run and evaluation, reruns the B1 replay, then pack (and publish)",
    "replay.json": "pack needs it: the next 'all' (or 'e13.py replay') reruns the B1 replay and writes it again",
    "uploaded.json": "the next publish uploads the pack zip again (one more release or pack branch)",
    "published.json": "information only (e13.py never reads it); the next publish writes it again",
    "verify.json": "information only (e13.py never reads it); the next verify (start of every 'all') writes it again",
}
STOP_KINDS = ("selection_L12.json", "selection_final.json", "locked.json", "twin.json", "E12 done.json")


def problem(path: Path, kind: str) -> tuple[str | None, dict | None]:
    """None if the file parses and has the keys e13.py reads, else a short description."""
    try:
        raw = path.read_bytes()
    except OSError as e:
        return f"unreadable ({e})", None
    if not raw.strip(b"\x00 \t\r\n"):
        return f"empty ({len(raw)} bytes" + (", NUL bytes" if raw else "") + ")", None
    try:
        d = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        return f"not valid JSON ({type(e).__name__}: {str(e)[:80]}; {len(raw)} bytes)", None
    if not isinstance(d, dict):
        return "not a JSON object", None
    missing = [k for k in REQUIRED[kind] if k not in d]
    if missing:
        return f"keys missing: {', '.join(missing)}", None
    if kind in ("eval.json", "baseline.json", "replay.json") and not isinstance(d["episodes"], list):
        return "'episodes' is not a list", None
    return None, d


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def checkpoint_path(runs: Path, recorded: str) -> Path:
    """done.json stores the checkpoint relative to e13/ (runs/train/<job>/...): re-anchor it on --runs."""
    parts = Path(recorded).parts
    return runs.joinpath(*parts[parts.index("train"):]) if "train" in parts else runs.parent / recorded


def check_episodes(runs: Path, job: Path, d: dict, e13) -> list[str]:
    out = []
    want = e13.EPISODES.get(d["rung"])
    if want is not None and d["episodes"] != want:
        out.append(f"done.json says {d['episodes']} episodes, e13.py settings {want} for {d['rung']}")
    n = want if want is not None else d["episodes"]
    ep = job / "episodes.csv"
    if not ep.is_file():
        out.append("episodes.csv missing")
    else:
        raw = ep.read_bytes()
        rows = list(csv.reader(raw.decode("utf-8", errors="replace").splitlines()))
        if not rows or rows[0] != e13.TRAIN_FIELDS:
            out.append("episodes.csv header differs from e13.py TRAIN_FIELDS")
        body = rows[1:]
        short = [i for i, r in enumerate(body, 1) if len(r) != len(e13.TRAIN_FIELDS)]
        if short:
            out.append(f"episodes.csv rows with missing columns: {short[:5]}")
        if raw and not raw.endswith(b"\n"):
            out.append("episodes.csv does not end with a newline (last row cut)")
        if len(body) != n:
            out.append(f"episodes.csv has {len(body)} rows, expected {n}")
        else:
            eps = [r[4] for r in body if len(r) > 4]
            if eps != [str(i) for i in range(1, n + 1)]:
                out.append("episodes.csv episode numbers are not 1..N in order")
            bad = [r[4] for r in body if len(r) > 7 and r[7] != "1"]
            if bad:
                out.append(f"episodes.csv: tripinfo unreadable for episodes {bad[:5]}")
    ck = checkpoint_path(runs, d["checkpoint"])
    if not ck.is_file():
        out.append(f"checkpoint missing ({ck.name})")
    elif sha256(ck) != d["checkpoint_sha256"]:
        out.append(f"checkpoint {ck.name}: SHA-256 differs from done.json (file changed or cut)")
    return out


def pid_alive(e13, pid) -> bool:
    try:
        return e13.pid_alive(int(pid))
    except (TypeError, ValueError):
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="move the damaged files (default: dry run)")
    ap.add_argument("--runs", help="runs folder to check (default: e13/runs)")
    ap.add_argument("--smoke", action="store_true", help="smoke settings (2 episodes per run), for runs_smoke copies")
    args = ap.parse_args()
    if args.smoke:
        os.environ["E13_SMOKE"] = "1"
    else:
        os.environ.pop("E13_SMOKE", None)
    sys.path.insert(0, str(HERE))
    import e13  # noqa: E402  (read-only: EPISODES, TRAIN_FIELDS, pid_alive)

    runs = Path(args.runs).resolve() if args.runs else e13.RUNS
    if not runs.is_dir():
        print(f"{runs}: no such folder")
        return 2
    default = args.runs is None
    lock = runs / "e13.lock"
    if lock.is_file():
        _, d = problem(lock, "e13.lock")
        if d and pid_alive(e13, d["pid"]):
            print(f"STOP: E13 is running (pid {d['pid']}, {d['cmd']}, since {d['started']}): files being written can "
                  "look damaged. Run repair.py only when E13 has stopped. Nothing was checked or moved.")
            return 2
    found, stops, info = [], [], []    # found: (kind, path, problem, move_target, effect)

    def chk(path: Path, kind: str, move: Path | None, effect: str, stop: bool = False):
        if not path.is_file():
            return None
        p, d = problem(path, kind)
        if p:
            (stops if stop else found).append((kind, path, p, None if stop else move, effect))
        return d

    # 1. training runs
    train = runs / "train"
    for job in sorted(x for x in train.iterdir() if x.is_dir()) if train.is_dir() else []:
        done, failed = job / "done.json", job / "failed.json"
        if done.is_file():
            d = chk(done, "done.json", job, f"training run {job.name} is trained again from episode 1 (same seed) on the "
                    f"next start; its evaluations in eval/{job.name}/ were made with the moved checkpoint: after the "
                    "rerun, compare the new done.json checkpoint_sha256 with theirs and tell the lead if they differ")
            if d:
                for a in check_episodes(runs, job, d, e13):
                    found.append(("anomaly", job, a, None, "reported only, nothing changed: tell the lead"))
        elif not failed.is_file():
            info.append(f"train/{job.name}: no done.json (cut off): e13.py trains it again from episode 1")
        chk(failed, "failed.json", failed, f"none beyond e13.py's own retry: {job.name} has no done.json and reruns")
    # 2. evaluations and baselines
    for p in sorted(runs.glob("eval/*/*/eval.json")):
        chk(p, "eval.json", p.parent, f"evaluation {p.parent.parent.name} -> {p.parent.name} runs again")
    for d in sorted(x for x in runs.glob("eval/*/*") if x.is_dir() and not (x / "eval.json").is_file()):
        info.append(f"eval/{d.parent.name}/{d.name}: no eval.json (cut off): e13.py evaluates it again")
    for p in sorted(runs.glob("baselines/*/*/baseline.json")):
        chk(p, "baseline.json", p, f"{p.parent.parent.name} on {p.parent.name} runs again (all files and seeds)")
    # 3. single files
    for name in ("bench.json", "e13.lock", "e13_finished.json", "uploaded.json", "published.json", "verify.json"):
        chk(runs / name, name, runs / name, EFFECT[name])
    chk(runs / "replay" / "replay.json", "replay.json", runs / "replay" / "replay.json", EFFECT["replay.json"])
    stop_msg = "pre-registered artefact: never moved"
    for name in ("selection_L12.json", "selection_final.json", "locked.json"):
        chk(runs / name, name, None, stop_msg, stop=True)
    chk(runs.parent / "twin.json", "twin.json", None, stop_msg, stop=True)
    if default:    # files outside e13/runs that e13.py also reads (E12 results of this PC)
        for p in sorted((e13.REPO / "runs" / "train").glob("*/done.json")):
            chk(p, "done.json", None, "E12 result used by L0 and status: never moved", stop=True)
        p = e13.REPO / "runs" / "bench.json"
        if p.is_file() and not (runs / "bench.json").is_file():
            chk(p, "bench.json", None, "E12 file read by e13.py when runs/bench.json is missing: never moved", stop=True)

    # report
    print(f"E13 repair ({'APPLY' if args.apply else 'dry run'}): {runs}")
    for line in info:
        print(f"  info: {line}")
    for kind, path, prob, move, effect in found:
        what = "ANOMALY" if kind == "anomaly" else "DAMAGED"
        print(f"  {what}: {path.relative_to(runs) if path.is_relative_to(runs) else path}: {prob}")
        if move is not None:
            print(f"      --apply moves {'the folder ' if move.is_dir() else ''}{move.relative_to(runs)} "
                  f"-> _corrupt/<time>/{move.relative_to(runs)}")
        print(f"      effect: {effect}")
    for kind, path, prob, _, effect in stops:
        print(f"  STOP: {path}: {prob} ({effect})")
    if stops:
        print("STOP: a pre-registered or E12 file is damaged. Do not start E13 and do not edit or move the file: "
              "tell Pavlo, who contacts the lead. Nothing was moved.")
        return 2
    if not found:
        print("clean: every state file parses" + (", every episodes.csv and checkpoint is complete" if train.is_dir() else ""))
        return 0
    movable = [(k, p, pr, m, e) for k, p, pr, m, e in found if m is not None]
    if not args.apply:
        print(f"{len(movable)} item(s) to move with --apply; {len(found) - len(movable)} anomaly(ies) to report")
        return 1
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest_root = runs / "_corrupt" / stamp
    moved, done_dirs = [], []
    for kind, path, prob, move, effect in sorted(movable, key=lambda x: len(x[3].parts)):
        if any(move == d or d in move.parents for d in done_dirs):
            continue    # already moved with its folder
        target = dest_root / move.relative_to(runs)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(move), str(target))
        done_dirs.append(move)
        moved.append({"kind": kind, "from": move.relative_to(runs).as_posix(), "to": target.relative_to(runs).as_posix(),
                      "problem": prob, "effect": effect})
        print(f"  moved {move.relative_to(runs)} -> {target.relative_to(runs)}")
    (dest_root / "REPAIR_LOG.json").write_text(json.dumps({"time": stamp, "runs": str(runs), "moved": moved},
                                                          indent=2), encoding="utf-8")
    print(f"{len(moved)} moved (log: {(dest_root / 'REPAIR_LOG.json').relative_to(runs)}); now start E13 again "
          "(start_e13.ps1); anomalies above are unchanged")
    return 1


if __name__ == "__main__":
    sys.exit(main())
