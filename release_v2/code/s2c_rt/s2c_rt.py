#!/usr/bin/env python3
"""Right-turn MaxPressure (post hoc exploratory baseline; decision C-20 of 8 Nov 2026, approved by Pavlo Radiuk).

Not pre-registered. The pre-registered tuned MaxPressure (S2c, revision/s2c/s2c.py, reading C1 of DEVIATIONS.md) sums
the pressure over the through and left movements of each phase; right turns are in no phase. This driver imports s2c
read-only (no copy, no edit of s2c.py or e13.py) and overrides ONE thing: the movement map. Each phase's movements also
include the right-turn connections (dir "r") of signal nC that are green ("G" or "g") in that phase's green state;
incoming lanes = their from-lanes, outgoing lanes = their to-lanes, grouped per (approach, exit edge) exactly as
s2c.movements(). Everything else (decision every 5 s, 3-s yellow, 4-s all-red at street changes, greens 12-60 s, the
threshold rule and its ties, the free/field orders, the grid h in {0,2,4,6,8,12} x {free, field}, the score and ranking
of rule 5.1, seeds 1042 + k + e, metrics from e13.py, end 1800 s, the default twin) is s2c's own code.

    python s2c_rt.py movements                 write the movement maps (pre-registered and right-turn) to <out>/movements.json
    python s2c_rt.py regress                   right turns removed again: reproduce existing S2c MaxPressure episodes byte for byte
    python s2c_rt.py smoke                     a few right-turn episodes with SUMO's signal-state log (rules 12-57/60 s)
    python s2c_rt.py tune                      full grid on the 20 training files per load, k = 1..5, paired fixed plan;
                                               writes tune/tuned.json (s2c's selection code) and tune/tuned_rt.json
    python s2c_rt.py eval --set locked --locked-ok   locked test set (x1.0/x1.2/x1.5 + S1-S4 with the x1.0 configuration)
    python s2c_rt.py e14                       second real window (x1.0 configuration), k = 1..5
    python s2c_rt.py collect                   CSV tables and the SHA-256 manifest of <out>

Output: revision/runs/s2c_rt/out (never revision/runs/s2c). The movement map is chosen by the environment variable
S2C_RT_MOVEMENTS (rt, the default, or prereg for the regression), read at import so that the spawned SUMO workers use
the same map as the parent.
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True    # no __pycache__ next to s2c.py / e13.py

import argparse  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import platform  # noqa: E402
import xml.etree.ElementTree as ET  # noqa: E402
from pathlib import Path  # noqa: E402

HERE = Path(__file__).resolve().parent
REV = HERE.parent
sys.path.insert(0, str(REV / "s2c"))
import s2c  # noqa: E402  (read-only; imports e13 read-only)

e13 = s2c.e13
DEFAULT_OUT = REV / "runs" / "s2c_rt" / "out"
S2C_OUT = REV / "runs" / "s2c" / "out"
MODE_ENV = "S2C_RT_MOVEMENTS"
POLICY_RT = "MaxPressure-RT"


# ------------------------------------------------------------------ movement maps
def movement_map(include_right: bool) -> dict[int, list[tuple[list[str], list[str]]]]:
    """s2c.movements() with the right turns optionally added: connections of nC with dir s, l (and r) whose link is
    green (G or g) in the phase's green state, grouped per (phase, approach edge, exit edge)."""
    dirs = ("s", "l", "r") if include_right else ("s", "l")
    mv: dict = {}
    for c in ET.parse(s2c.FIXED_NET).getroot().findall("connection"):
        if c.get("tl") != s2c.TLS or c.get("dir") not in dirs:
            continue
        li = int(c.get("linkIndex"))
        for p, state in enumerate(s2c.GREEN_STATES):
            if state[li] in "Gg":
                ins, outs = mv.setdefault((p, c.get("from"), c.get("to")), (set(), set()))
                ins.add(f"{c.get('from')}_{c.get('fromLane')}")
                outs.add(f"{c.get('to')}_{c.get('toLane')}")
    out = {p: [] for p in range(4)}
    for (p, _, _), (ins, outs) in sorted(mv.items()):
        out[p].append((sorted(ins), sorted(outs)))
    return out


def right_turn_links() -> list[dict]:
    """Every right-turn link of nC with its state in the four green states and the all-red state."""
    rows = []
    for c in ET.parse(s2c.FIXED_NET).getroot().findall("connection"):
        if c.get("tl") == s2c.TLS and c.get("dir") == "r":
            li = int(c.get("linkIndex"))
            states = [s[li] for s in s2c.GREEN_STATES]
            rows.append({"linkIndex": li, "from_lane": f"{c.get('from')}_{c.get('fromLane')}",
                         "to_lane": f"{c.get('to')}_{c.get('toLane')}", "states_phase0_3": "".join(states),
                         "allred_state": s2c.ALLRED_STATE[li],
                         "green_in_phases": [p for p, ch in enumerate(states) if ch in "Gg"]})
    return sorted(rows, key=lambda r: r["linkIndex"])


def map_digest(m: dict) -> str:
    return hashlib.sha256(json.dumps({str(k): v for k, v in m.items()}, sort_keys=True).encode()).hexdigest()


PREREG_MAP = s2c.movements()                # the original function, before the override
RT_MAP = movement_map(True)
assert movement_map(False) == PREREG_MAP, "movement_map(False) differs from s2c.movements()"
MODE = os.environ.get(MODE_ENV, "rt")
if MODE not in ("rt", "prereg"):
    raise SystemExit(f"{MODE_ENV} must be rt or prereg, not {MODE!r}")
ACTIVE_MAP = RT_MAP if MODE == "rt" else movement_map(False)
MAP_TAG = f"{MODE}-{map_digest(ACTIVE_MAP)[:12]}"

# the override: s2c.pressures() looks up `movements` in s2c's module globals at call time
s2c.movements = lambda: ACTIVE_MAP
if MODE == "rt":
    s2c.CTRL_NAME["mp"] = POLICY_RT
_base_job = s2c.base_job


def base_job_rt(stage, ctrl, *a, **kw):
    job = _base_job(stage, ctrl, *a, **kw)
    if ctrl == "mp":
        job["row"]["movement_map"] = MAP_TAG
    return job


s2c.base_job = base_job_rt


def check_out(out: Path) -> Path:
    o = out.resolve()
    if o == S2C_OUT.resolve() or S2C_OUT.resolve() in o.parents or o in S2C_OUT.resolve().parents:
        sys.exit(f"refusing to write into {S2C_OUT} (pre-registered S2c outputs)")
    o.mkdir(parents=True, exist_ok=True)
    return o


def maps_json() -> dict:
    return {"pre_registered": {str(p): v for p, v in PREREG_MAP.items()},
            "pre_registered_sha256": map_digest(PREREG_MAP),
            "right_turn": {str(p): v for p, v in RT_MAP.items()}, "right_turn_sha256": map_digest(RT_MAP),
            "right_turn_links": right_turn_links(), "green_states": s2c.GREEN_STATES, "allred_state": s2c.ALLRED_STATE,
            "net": str(s2c.FIXED_NET), "net_sha256": s2c.sha256(Path(s2c.FIXED_NET)),
            "reading": "a right turn counts in a phase where its link is G or g in that phase's green state; 's' "
                       "(stop, then turn) is not green. Shared lane 0 of each approach is then an incoming lane of "
                       "both the through and the right-turn movement of the phase and counts in both terms."}


# ------------------------------------------------------------------ commands
def cmd_movements(args) -> int:
    out = check_out(Path(args.out))
    s2c.write_json(out / "movements.json", maps_json())
    print(json.dumps(maps_json(), indent=1))
    return 0


REGRESS_SAMPLE = [    # existing pre-registered S2c MaxPressure episodes (relative to revision/runs/s2c/out)
    "tune/x1.0/mp_free_h8/e01_k1.json", "tune/x1.0/mp_field_h4/e13_k3.json",
    "tune/x1.2/mp_field_h8/e07_k2.json", "tune/x1.2/mp_free_h0/e19_k5.json",
    "tune/x1.5/mp_field_h12/e10_k4.json", "tune/x1.5/mp_free_h6/e04_k1.json",
    "eval/validation/mp/prybuzka_vas3/e02_k4.json", "eval/testA/mp/prybuzka_ho15/e06_k2.json"]


def job_from_existing(rel: str, out: Path, twin: tuple, stage: str) -> tuple[dict, dict]:
    ref = s2c.read_json(S2C_OUT / rel)
    row = ref["row"]
    m, e, k = row["map"], int(row["episode"]), int(row["training_run"])
    route = e13.route_files(m)[e - 1]
    assert route.name == row["route_file"] and s2c.SEED0 + k + e == int(row["sumo_seed"]), rel
    v, h = row["controller_config"].split(" h=")
    h = float(h) if "." in h else int(h)
    queue = ref.get("queue") is not None
    job = s2c.base_job(stage, "mp", out / stage / rel, route, e, k, row["eval_set"], m, row["label"], twin, queue,
                       False, cfg_load=row["train_load"], variant=v, h=h)
    return job, ref


def cmd_regress(args) -> int:
    if MODE != "prereg":
        sys.exit(f"regress needs {MODE_ENV}=prereg (main() sets it)")
    out = check_out(Path(args.out))
    twin = s2c.twin_info()
    pairs = [job_from_existing(rel, out, twin, "regression") for rel in REGRESS_SAMPLE]
    rc = s2c.run_pool([j for j, _ in pairs], args.jobs, "regression (right turns removed)")
    rep = {"written": s2c.now(), "host": platform.node(), "backend": s2c.backend()[1], "movement_map": MAP_TAG,
           "equal_to_s2c_movements": movement_map(False) == PREREG_MAP, "episodes": []}
    ok = rc == 0
    skip = {"tripinfo", "policy", "movement_map"}
    for job, ref in pairs:
        r = s2c.read_json(Path(job["dest"])) or {}
        same_rows = {k: v for k, v in r.get("row", {}).items() if k not in skip} == \
                    {k: v for k, v in ref["row"].items() if k not in skip}
        x = {"episode": job["id"], "config": ref["row"]["controller_config"], "sumo_seed": job["seed"],
             "records_sha256": r.get("records_sha256"), "s2c_records_sha256": ref["records_sha256"],
             "records_identical": r.get("records_sha256") == ref["records_sha256"],
             "decisions_identical": r.get("decisions") == ref.get("decisions"),
             "metrics_identical": same_rows,
             "queue_identical": (r.get("queue") == ref.get("queue")) if ref.get("queue") is not None else None,
             "s2c_host": ref.get("host"), "s2c_sumo": ref.get("sumo"), "sumo": r.get("sumo")}
        ok &= x["records_identical"] and x["decisions_identical"] and x["metrics_identical"] and x["queue_identical"] is not False
        rep["episodes"].append(x)
    rep["passed"] = bool(ok)
    s2c.write_json(out / "regression" / "regression_report.json", rep)
    print(json.dumps(rep, indent=1))
    return 0 if ok else 1


SMOKE = [("x1.0", "free", 8, 1, 1), ("x1.0", "field", 0, 2, 2), ("x1.2", "field", 8, 3, 3), ("x1.2", "free", 4, 4, 4),
         ("x1.5", "field", 8, 5, 5), ("x1.5", "free", 0, 6, 1)]    # (load, variant, h, file e, k) on training files


def cmd_smoke(args) -> int:
    if MODE != "rt":
        sys.exit("smoke runs with the right-turn map")
    out = check_out(Path(args.out))
    twin = s2c.twin_info()
    jobs = []
    for load, v, h, e, k in SMOKE:
        m = e13.LOADS[load]
        route = e13.route_files(m)[e - 1]
        jobs.append(s2c.base_job("smoke", "mp", out / "smoke" / load / f"mp_{v}_h{h}" / f"e{e:02d}_k{k}.json", route, e,
                                 k, "train", m, load, twin, False, False, cfg_load=load, variant=v, h=h, tls_log=True))
    rc = s2c.run_pool(jobs, args.jobs, "smoke (right turns)")
    rep = {"written": s2c.now(), "movement_map": MAP_TAG, "episodes": []}
    ok = rc == 0
    for j in jobs:
        r = s2c.read_json(Path(j["dest"])) or {}
        row = r.get("row", {})
        name = Path(j["dest"]).relative_to(out / "smoke").as_posix()
        ref = s2c.read_json(S2C_OUT / "tune" / name) or {}
        rr = ref.get("row", {})
        sr = r.get("signal_rules", {})
        x ={"episode": name, "seed": j["seed"], "seconds": r.get("seconds"), "signal_rules": sr,
             "demand": row.get("demand"), "arrived_1800": row.get("arrived_1800"), "deadlock": row.get("deadlock"),
             "longest_no_arrival_s": row.get("longest_no_arrival_s"), "mean_delay_s": row.get("mean_delay_s"),
             "total_delay_vh": row.get("total_delay_vh"), "switches": row.get("switches"),
             "prereg_arrived_1800": rr.get("arrived_1800"), "prereg_deadlock": rr.get("deadlock"),
             "prereg_total_delay_vh": rr.get("total_delay_vh"), "prereg_switches": rr.get("switches"),
             "records_differ_from_prereg": r.get("records_sha256") != ref.get("records_sha256")}
        ok &= sr.get("n_violations", 1) == 0 and (sr.get("min_green") or 0) >= s2c.MIN_GREEN \
            and (sr.get("max_green") or 99) <= s2c.MAX_GREEN
        rep["episodes"].append(x)
    rep["passed"] = bool(ok)
    s2c.write_json(out / "smoke" / "smoke_report.json", rep)
    print(json.dumps(rep, indent=1))
    return 0 if ok else 1


def cmd_tune(args) -> int:
    if MODE != "rt":
        sys.exit("tune runs with the right-turn map")
    out = check_out(Path(args.out))
    rc = s2c.cmd_tune(args)    # grid + paired fixed plan, s2c.finalize_tuning (rule 5.1, e13.rank), collect
    tuned = s2c.read_json(out / "tune" / "tuned.json")
    # fixed-plan tuning episodes were rerun here; compare with the pre-registered S2c ones (same inputs)
    cmp, n_same, n = [], 0, 0
    for p in sorted((out / "tune").glob("*/fixed/*.json")):
        if p.name.endswith(".failed.json"):
            continue
        rel = p.relative_to(out).as_posix()
        a, b = s2c.read_json(p), s2c.read_json(S2C_OUT / rel)
        n += 1
        same = bool(a and b and a.get("records_sha256") == b.get("records_sha256"))
        n_same += same
        if not same:
            cmp.append(rel)
    fx = {"fixed_episodes": n, "records_identical_to_s2c": n_same, "differing": cmp}
    s2c.write_json(out / "tune" / "fixed_vs_s2c.json", fx)
    print(f"fixed-plan tuning episodes: {n_same}/{n} records identical to revision/runs/s2c/out")
    if tuned:
        rt = {"baseline": f"{POLICY_RT} (post hoc, decision C-20, 8 Nov 2026; not pre-registered)",
              "movement_map": MAP_TAG, "movement_map_sha256": map_digest(RT_MAP),
              "selection": "tune/tuned.json, written by s2c.finalize_tuning (pre-registration 6.2 grid, score and "
                           "ranking of rule 5.1 on the 20 training files per load, e13.rank)",
              "fixed_plan_episodes": fx, **tuned}
        s2c.write_json(out / "tune" / "tuned_rt.json", rt)
        s2c.write_atomic(out / "results" / "tuned_rt.json", (out / "tune" / "tuned_rt.json").read_bytes())
    s2c.collect(out)
    return rc


def cmd_eval(args) -> int:
    if MODE != "rt":
        sys.exit("eval runs with the right-turn map")
    check_out(Path(args.out))
    return s2c.cmd_eval(args, "eval", ("mp",))    # locked: --locked-ok, file hashes, run-once marker, as S2c


def cmd_e14(args) -> int:
    if MODE != "rt":
        sys.exit("e14 runs with the right-turn map")
    out = check_out(Path(args.out))
    jobs = [j for j in s2c.e14_jobs(args, out, s2c.twin_info()) if j["ctrl"] == "mp"]
    rc = s2c.run_pool(jobs, args.jobs, "e14 (right-turn MaxPressure)")
    s2c.collect(out)
    return rc


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = {}
    for name in ("movements", "regress", "smoke", "tune", "eval", "e14", "collect"):
        p[name] = sub.add_parser(name)
        p[name].add_argument("--out", default=str(DEFAULT_OUT))
        p[name].add_argument("--jobs", type=int, default=7)
    for name in ("tune", "eval", "e14"):
        p[name].add_argument("--limit-files", type=int)
        p[name].add_argument("--k", type=int, nargs="+")
        p[name].add_argument("--no-tripinfo", action="store_true")
    p["tune"].add_argument("--loads", nargs="+", choices=s2c.LOADS, default=list(s2c.LOADS))
    p["tune"].add_argument("--h", type=float, nargs="+", default=list(s2c.H_GRID))
    p["tune"].add_argument("--variants", nargs="+", choices=s2c.VARIANTS, default=list(s2c.VARIANTS))
    p["eval"].add_argument("--set", required=True, choices=["validation", "testA", "locked"])
    p["eval"].add_argument("--maps", nargs="+")
    p["eval"].add_argument("--locked-ok", action="store_true")
    p["eval"].add_argument("--rerun-reason")
    for name in ("eval", "e14"):
        p[name].add_argument("--mp-config")
    args = ap.parse_args()
    if getattr(args, "h", None):
        args.h = [int(x) if float(x).is_integer() else x for x in args.h]
    want = "prereg" if args.cmd == "regress" else "rt"
    if args.cmd in ("regress", "smoke", "tune", "eval", "e14") and MODE != want:
        # restart with the right map in the environment, so that every spawned worker imports it
        import subprocess
        env = dict(os.environ, **{MODE_ENV: want})
        return subprocess.call([sys.executable, str(Path(__file__).resolve())] + sys.argv[1:], env=env)
    fn = {"movements": cmd_movements, "regress": cmd_regress, "smoke": cmd_smoke, "tune": cmd_tune, "eval": cmd_eval,
          "e14": cmd_e14, "collect": lambda a: s2c.collect(check_out(Path(a.out))) or 0}[args.cmd]
    return fn(args)


if __name__ == "__main__":
    sys.exit(main())
