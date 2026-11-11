"""Tests of the E13 kit (pre-registration v1, build check before any E13 run).

T1  legacy equivalence: with default flags the E13 RESCO copy gives byte-identical episodes (tripinfo records)
    to the E12 copy: frozen IDQN-queue x1.0 run 4 (2 episodes) and short training of IDQN-pressure and MPLight.
T2  E13 signal rules, from SUMO's own signal-state log (SaveTLSStates), in short training runs with exploration:
    every green 12-60 s (the last green may be cut by the end), 3 s yellow after every green, 4 s all-red exactly at
    street changes (--allred_mode street), field order 0->1->2->3->0 in --mode field; state shape and MPLight fix.

  revision/.venv-resco/Scripts/python.exe revision/tools/test_e13_kit.py --e12-kit revision/e12_kit \
      --e13-kit revision/e12_kit/e13 --out revision/e12_kit/e13/runs_test
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

GREENS = {"GGGrsrrrGGGrsrrr": 0, "srrGsrrrsrrGsrrr": 1, "srrrGGGrsrrrGGGr": 2, "srrrsrrGsrrrsrrG": 3}
STREET = [0, 0, 1, 1]


def env_for(resco: Path) -> dict:
    import sumo
    env = os.environ.copy()
    env.update(PYTHONPATH=str(resco), SUMO_HOME=sumo.SUMO_HOME, LIBSUMO_AS_TRACI="1", OMP_NUM_THREADS="1",
               MKL_NUM_THREADS="1", RESCO_NO_BEEP="1", CUDA_VISIBLE_DEVICES="")
    return env


def run(resco: Path, log_dir: Path, *args: str) -> int:
    log_dir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "main.py", "--procs", "1", "--libsumo", "True", "--log_dir", str(log_dir) + os.sep, *args]
    with (log_dir / "main.log").open("w", encoding="utf-8") as f:
        return subprocess.run(cmd, cwd=resco / "resco_benchmark", env=env_for(resco), stdout=f,
                              stderr=subprocess.STDOUT).returncode


def records_hash(path: Path) -> str:
    text = re.sub(r"<!--.*?-->", "", path.read_text(encoding="utf-8"), flags=re.S)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def tripinfos(log_dir: Path) -> dict:
    return {p.name: records_hash(p) for p in sorted(log_dir.glob("*/tripinfo_*.xml"))}


def check_tls(path: Path, end: float, mode: str) -> dict:
    """Green, yellow and all-red intervals from SaveTLSStates; returns counts and the list of violations."""
    ev = [(float(t), s) for t, s in re.findall(r'<tlsState time="([\d.]+)"[^>]*state="([^"]+)"', path.read_text())]
    ev.append((end, None))
    segs = [(ev[i][1], ev[i][0], ev[i + 1][0]) for i in range(len(ev) - 1) if ev[i + 1][0] > ev[i][0]]
    merged = []    # merge consecutive identical states
    for s, a, b in segs:
        if merged and merged[-1][0] == s and merged[-1][2] == a:
            merged[-1] = (s, merged[-1][1], b)
        else:
            merged.append((s, a, b))
    bad, greens, prev_green = [], [], None
    for i, (s, a, b) in enumerate(merged):
        dur, last = b - a, i == len(merged) - 1
        if s in GREENS:
            g = GREENS[s]
            greens.append(dur)
            if (dur < 12 and not last) or dur > 60:
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
        elif not any(c in s for c in "GgYy"):
            if dur != 4 and not last:
                bad.append(f"all-red {dur} s at {a}")
    return {"greens": len(greens), "min_green": min(greens[:-1]) if len(greens) > 1 else None,
            "max_green": max(greens), "violations": bad[:10], "n_violations": len(bad)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--e12-kit", type=Path, required=True)
    ap.add_argument("--e13-kit", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    r12, r13 = (args.e12_kit / "resco").resolve(), (args.e13_kit / "resco").resolve()
    ckpt = (args.e12_kit / "verify" / "idqn_queue_x10_run4.pt").resolve()
    out = args.out.resolve()

    t1 = {"eval_idqn_queue": ["--agent", "IDQN_pressure", "--map", "prybuzka_ho10", "--tr", "1004", "--eps", "2",
                              "--allred", "4", "--ckpt", str(ckpt)],
          "train_idqn_pressure": ["--agent", "IDQN_pressure_inout", "--map", "prybuzka_tr10", "--tr", "1", "--eps", "2",
                                  "--allred", "4", "--seed", "43", "--save_freq", "2"],
          "train_mplight": ["--agent", "MPLight", "--map", "prybuzka_tr10", "--tr", "1", "--eps", "2",
                            "--allred", "4", "--seed", "43", "--save_freq", "2"]}
    tls_add = {}
    t2 = {}
    for name, agent, extra in [("field_idqn_pressure", "IDQN_pressure_inout", ["--mode", "field", "--mplight_phase", "fixed"]),
                               ("free_idqn_wait", "IDQN", ["--mode", "free"]),
                               ("free_mplight_fixed", "MPLight", ["--mode", "free", "--mplight_phase", "fixed"])]:
        d = out / "T2" / name
        d.mkdir(parents=True, exist_ok=True)
        add = d / "tls.add.xml"
        add.write_text(f'<additional><timedEvent type="SaveTLSStates" source="nC" dest="{(d / "tls_states.xml").as_posix()}"/>'
                       f'</additional>\n', encoding="utf-8")
        tls_add[name] = d
        t2[name] = ["--agent", agent, "--map", "prybuzka_tr10", "--tr", "1", "--eps", "2", "--allred", "4",
                    "--allred_mode", "street", "--seed", "43", "--save_freq", "2", "--undeparted",
                    "--vtype", str(add), *extra]

    jobs = [(r, out / "T1" / tag / name, a) for name, a in t1.items() for tag, r in [("e12", r12), ("e13", r13)]]
    jobs += [(r13, tls_add[name] / "run", a) for name, a in t2.items()]
    with ThreadPoolExecutor(max_workers=min(7, len(jobs))) as ex:
        codes = list(ex.map(lambda j: run(j[0], j[1], *j[2]), jobs))
    report = {"exit_codes": {str(j[1].relative_to(out)): c for j, c in zip(jobs, codes)}, "T1": {}, "T2": {}}
    for name in t1:
        h12, h13 = tripinfos(out / "T1" / "e12" / name), tripinfos(out / "T1" / "e13" / name)
        report["T1"][name] = {"episodes": len(h12), "identical": bool(h12) and h12 == h13}
    for name in t2:
        d = tls_add[name]
        res = check_tls(d / "tls_states.xml", 1500.0, "field" if "field" in name else "free")
        log = (d / "run" / "main.log").read_text(encoding="utf-8", errors="replace")
        trip = sorted((d / "run").glob("*/tripinfo_1.xml"))
        res["undeparted_written"] = bool(trip) and 'depart="-1' in trip[0].read_text(encoding="utf-8")
        res["state_fn"] = re.findall(r"prybuzka_tr10 \S+ (\S+) (\S+)", log)[:1]
        report["T2"][name] = res
    ok = all(c == 0 for c in codes) and all(v["identical"] for v in report["T1"].values()) \
        and all(v["n_violations"] == 0 for v in report["T2"].values())
    report["all_ok"] = ok
    (out / "test_report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps(report, indent=1))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
