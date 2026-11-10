#!/usr/bin/env python3
"""B7 (pre-registration section 9; revision/twin/B7/B7_run_spec.md): the frozen E13 final design on the B7
perception-error demand.

Run on MyPC with the kit's Python, after 'e13.py select' has written runs/selection_final.json and E13 has stopped:

  python e13/b7.py run    --demand <B7 demand folder> [--workers N] [--only x10/base x12/fovp10 ...]
  python e13/b7.py status --demand <B7 demand folder>

<B7 demand folder> holds <load>/<variant>/b7_<variant>_<load>_s<seed>.rou.xml (load x10 or x12), as
revision/twin/B7/demand on the laptop; copy that folder to this PC (for example to e13/b7_demand/) and pass its path.

The final design of selection_final.json (rung, reward) runs with each of its training runs k = 1..5, frozen and
greedy, through RESCO's main.py with the E13 flags of the design (e13.design_flags) and the twin of twin.json, 1800 s
per episode: one RESCO evaluation per (model, load, variant) with trial 1000 + k over the variant's files in
routeSampler-seed order, so that episode e has SUMO seed 42 + 1000 + k + e, e = seed index (7001..7005 -> 1..5,
7101..7110 -> 1..10): the same seed for base and every variant, and with k = 1 the seed of the fixed, actuated and
MaxPressure runs (revision/s2c/s2c.py b7). Per-load rungs (L1-L3) use the x1.0 model on x10 files and the x1.2 model
on x12 files; L4 uses its one model on both. Metrics: e13.safe_metrics (section 4).

Output (--out, default runs/b7): <model>/<load>_<variant>/b7.json per evaluation, written atomically (a restart skips
finished ones), and b7_final_episodes.csv in the E13 episode format (eval_job rows + b7_load, b7_variant, b7_seed).

RESCO's main.py and its configuration are not changed: this file runs main.py in a child process (as b1_replay.py
does) after pointing the route folder of one E13 map (prybuzka_va10: same network, signal and map settings) at a
folder with byte-identical copies of the B7 files, named so that RESCO's sorted() order is the seed order.
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True    # read-only use of e13.py and RESCO: no __pycache__ written next to them

import argparse  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402
from concurrent.futures import ThreadPoolExecutor, as_completed  # noqa: E402
from pathlib import Path  # noqa: E402

HERE = Path(__file__).resolve().parent
B7_LOADS = {"x10": "x1.0", "x12": "x1.2"}
CARRIER = "prybuzka_va10"
SEED_RE = re.compile(r"_s(\d+)\.rou\.xml$")


def child(argv: list[str]) -> None:
    """python b7.py _resco --routes DIR -- <main.py arguments> (cwd = resco/resco_benchmark, PYTHONPATH = resco)."""
    cut = argv.index("--")
    ap = argparse.ArgumentParser()
    ap.add_argument("--routes", required=True)
    a = ap.parse_args(argv[:cut])
    main_args = argv[cut + 1:]
    routes = Path(a.routes).resolve()
    bench = HERE / "resco" / "resco_benchmark"
    sys.path.insert(0, str(bench))
    os.chdir(bench)
    from resco_benchmark.config.map_config import map_configs
    name = main_args[main_args.index("--map") + 1]
    map_configs[name]["route"] = str(routes / "gen")    # absolute: main.py's os.path.join keeps it
    sys.argv = ["main.py"] + main_args
    import main as resco_main
    resco_main.main()


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "_resco":
    child(sys.argv[2:])
    sys.exit(0)

sys.path.insert(0, str(HERE))
import e13  # noqa: E402  (read-only)


def now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp{os.getpid()}")
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def demand_groups(folder: Path, only: list[str] | None, limit: int | None) -> list[tuple[str, str, list[tuple[int, Path]]]]:
    """(load, variant, [(seed, file), ...] in seed order) for every <load>/<variant> folder."""
    out = []
    for vdir in sorted(p for p in folder.glob("*/*") if p.is_dir() and p.parent.name in B7_LOADS):
        load, variant = vdir.parent.name, vdir.name
        if only and f"{load}/{variant}" not in only:
            continue
        files = sorted((int(m.group(1)), p) for p in vdir.glob("*.rou.xml") if (m := SEED_RE.search(p.name)))
        if not files:
            continue
        bad = [s for i, (s, _) in enumerate(files, 1) if s % 100 != i]
        if bad:
            sys.exit(f"{vdir}: seeds {[s for s, _ in files]} are not x001, x002, ... in order, so the episode index "
                     "would not equal the seed index of the spec; fix the folder first")
        out.append((load, variant, files[:limit] if limit else files))
    if not out:
        sys.exit(f"no B7 route files under {folder}/<x10|x12>/<variant>/")
    return out


def final_models(selection_file: str | None) -> tuple[dict, list[dict]]:
    sel = read_json(Path(selection_file)) if selection_file else e13.selection("final")
    if not sel:
        sys.exit(f"no {e13.RUNS / 'selection_final.json'}: the final design is chosen by 'e13.py select' after L34")
    f = sel["final"]
    mods = [m for stage in ("L12", "L34") for m in e13.models(stage) if m["rung"] == f["rung"] and m["policy"] == f["policy"]]
    if not mods:
        sys.exit(f"no trained models of the final design {f['rung']} {f['policy']} in {e13.TRAIN_DIR}")
    return f, mods


def model_for(mods: list[dict], load: str) -> list[dict]:
    want = "mix" if any(m["load"] == "mix" for m in mods) else B7_LOADS[load]
    return sorted((m for m in mods if m["load"] == want), key=lambda m: m["run"])


def routes_copy(work: Path, load: str, variant: str, files: list[tuple[int, Path]]) -> Path:
    """Byte-identical copies named gen_1.rou.xml, gen_1_r02_s<seed>.rou.xml, ... (RESCO's names: sorted() = seed
    order; MultiSignal reads gen_1.rou.xml once to detect the phases)."""
    d = work / "_routes" / f"{load}_{variant}_{len(files)}"
    names = ["gen_1.rou.xml"] + [f"gen_1_r{i:02d}_s{s}.rou.xml" for i, (s, _) in enumerate(files[1:], 2)]
    if not all((d / n).is_file() and e13.file_hash(d / n) == e13.file_hash(p) for n, (_, p) in zip(names, files)):
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True)
        for n, (_, p) in zip(names, files):
            shutil.copyfile(p, d / n)
    assert sorted(x.name for x in d.glob("*.rou.xml")) == names
    return d


def job(mdl: dict, load: str, variant: str, files: list[tuple[int, Path]], out: Path, t: dict) -> dict:
    d = out / e13.model_name(mdl) / f"{load}_{variant}"
    res = d / "b7.json"
    r = read_json(res)
    if r and r.get("status") == "done" and len(r.get("episodes", [])) == len(files):
        return {"status": "already done"}
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    routes = routes_copy(out, load, variant, files)
    trial = e13.TRIAL_OFFSET + mdl["run"]
    flags = e13.design_flags(mdl["mode"], t)
    cmd = [sys.executable, str(HERE / "b7.py"), "_resco", "--routes", str(routes), "--",
           "--agent", e13.POLICIES[mdl["policy"]], "--map", CARRIER, "--tr", str(trial), "--eps", str(len(files)),
           "--procs", "1", "--libsumo", "True", "--log_dir", str(d / "resco") + os.sep, *flags, "--ckpt", str(mdl["ckpt"])]
    env = e13.child_env() | {"PYTHONDONTWRITEBYTECODE": "1"}
    t0 = time.time()
    with (d / "main.log").open("w", encoding="utf-8") as f:
        rc = subprocess.run(cmd, cwd=e13.BENCH, env=env, stdout=f, stderr=subprocess.STDOUT).returncode
    folder = e13.run_folder(d / "resco")
    rows = []
    for e, (seed, route) in enumerate(files, 1):
        trip = folder / f"tripinfo_{e}.xml" if folder else d / "missing.xml"
        rec = {"rung": mdl["rung"], "policy": mdl["policy"], "train_load": mdl["load"], "training_run": mdl["run"],
               "eval_set": "B7", "map": f"b7_{load}_{variant}", "label": variant, "episode": e,
               "route_file": route.name, "sumo_seed": e13.GLOBAL_SEED + trial + e}
        rec.update(e13.safe_metrics(trip, route, e13.END, folder / f"metrics_{e}.csv" if folder else None,
                                    mdl["mode"] == "e12"))
        rec.update(tripinfo=e13.rel(trip) if folder else "", b7_load=load, b7_variant=variant, b7_seed=seed)
        rows.append(rec)
    ok = rc == 0 and all(r["tripinfo_ok"] for r in rows)
    info = {"status": "done" if ok else f"FAILED (exit {rc}; see {d / 'main.log'})", "model": e13.model_name(mdl),
            "load": load, "variant": variant, "trial": trial, "twin": e13.twin_tag(t), "flags": flags,
            "carrier_map": CARRIER, "checkpoint": e13.rel(mdl["ckpt"]),
            "checkpoint_sha256": e13.file_hash(mdl["ckpt"]) if mdl["ckpt"].is_file() else "missing",
            "routes": [{"file": p.name, "seed": s, "sha256": e13.file_hash(p)} for s, p in files],
            "minutes": round((time.time() - t0) / 60, 2), "finished": now(), "episodes": rows}
    write_atomic(res, json.dumps(info, indent=1))
    return info


def collect(out: Path) -> int:
    rows = []
    for p in sorted(out.glob("*/*/b7.json")):
        r = read_json(p)
        if r and r.get("status") == "done":
            rows += r["episodes"]
    if rows:
        tmp = out / "b7_final_episodes.csv.tmp"
        e13.write_csv(tmp, rows)
        os.replace(tmp, out / "b7_final_episodes.csv")
    return len(rows)


def run(args) -> int:
    lock = e13.read_lock()
    if lock:
        sys.exit(f"E13 is running ({lock['cmd']}, pid {lock['pid']}): run B7 after it has finished")
    t = e13.twin_for_runs()
    e13.check_twin_consistency(t)
    f, mods = final_models(args.selection)
    groups = demand_groups(Path(args.demand).resolve(), args.only, args.limit_files)
    out = (Path(args.out) if args.out else e13.RUNS / "b7").resolve()    # absolute: RESCO runs with cwd = resco_benchmark
    tasks = []
    for load, variant, files in groups:
        ms = model_for(mods, load)
        if len(ms) != len(e13.RUNS_K):
            print(f"WARNING: {len(ms)} trained models of {f['rung']} {f['policy']} for {load} (expected {len(e13.RUNS_K)})")
        tasks += [(f"{e13.model_name(m)} -> {load}/{variant}", m, load, variant, files) for m in ms]
    for load, variant, files in groups:    # copy each route folder once, before the workers start (no copy race)
        routes_copy(out, load, variant, files)
    print(f"{now()}  B7 final design {f['rung']} {f['policy']}: {len(tasks)} evaluations "
          f"({sum(len(x[4]) for x in tasks)} episodes), {args.workers} processes, out {out}", flush=True)
    failed, t0 = 0, time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(job, m, load, variant, files, out, t): name for name, m, load, variant, files in tasks}
        for i, fu in enumerate(as_completed(futs), 1):
            try:
                info = fu.result()
            except Exception as e:    # keep the other evaluations running
                info = {"status": f"FAILED ({e!r})"}
            failed += not info["status"].startswith(("done", "already"))
            print(f"{now()}  B7 [{i}/{len(tasks)}] {futs[fu]}: {info['status']}"
                  + (f", {info['minutes']:.1f} min" if "minutes" in info else "")
                  + f"  (elapsed {(time.time() - t0) / 60:.1f} min)", flush=True)
    n = collect(out)
    print(f"{now()}  B7: {failed} failed; {n} episodes in {out / 'b7_final_episodes.csv'}", flush=True)
    return 1 if failed else 0


def status(args) -> int:
    f, mods = final_models(args.selection)
    out = (Path(args.out) if args.out else e13.RUNS / "b7").resolve()
    done = total = 0
    for load, variant, files in demand_groups(Path(args.demand).resolve(), args.only, args.limit_files):
        for m in model_for(mods, load):
            total += 1
            r = read_json(out / e13.model_name(m) / f"{load}_{variant}" / "b7.json")
            done += bool(r and r.get("status") == "done")
    print(f"B7 final design {f['rung']} {f['policy']}: {done}/{total} evaluations done ({out})")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("run", "status"):
        p = sub.add_parser(name)
        p.add_argument("--demand", required=True, help="folder with <x10|x12>/<variant>/*.rou.xml")
        p.add_argument("--out", help="results folder (default runs/b7)")
        p.add_argument("--only", nargs="+", help="only these <load>/<variant> folders, e.g. x10/base")
        p.add_argument("--selection", help="selection file (default runs/selection_final.json)")
        p.add_argument("--limit-files", type=int, help="tests only: the first N files per folder")
        p.add_argument("--workers", type=int, default=e13.default_workers())
    args = ap.parse_args()
    return {"run": run, "status": status}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
