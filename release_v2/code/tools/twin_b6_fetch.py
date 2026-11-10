"""B6: take the Colab grid results from the synced Google Drive folder (Google Drive for desktop) into revision/twin/B6/.

The Drive files are data only (JSON); nothing from Drive is executed. Checks, in order:
  1. the SHA-256 list written on Colab (grid_sha256.txt) covers exactly the expected number of points;
  2. every JSON on Drive matches its listed SHA-256;
  3. every JSON parses, its "id" equals its file name and its point is on the protocol grid; SUMO 1.26.0 through libsumo;
  4. the default point's runs equal the laptop gate run (revision/twin/B6/gate_laptop) exactly.
Only if all pass are the files copied to --dst; a fetch_report.json is written either way.

    revision/.venv-resco/Scripts/python.exe -I revision/tools/twin_b6_fetch.py --src "I:/My Drive/B6_grid" \
        --dst revision/twin/B6/grid --laptop-default revision/twin/B6/gate_laptop/sd0.00_tau1.0_acc2.6.json
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import shutil
import sys
from pathlib import Path

GRID = dict(startupDelay=[round(0.25 * i, 2) for i in range(13)], tau=[round(1.0 + 0.1 * i, 1) for i in range(11)],
            accel=[1.0, 1.4, 1.8, 2.2, 2.6, 3.0])
DEFAULT_ID = "sd0.00_tau1.0_acc2.6"


def point_id(sd, tau, acc):
    return f"sd{sd:.2f}_tau{tau:.1f}_acc{acc:.1f}"


def runs_hash(res):
    return hashlib.sha256(json.dumps(res["runs"], sort_keys=True).encode()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", type=Path, required=True)
    ap.add_argument("--dst", type=Path, required=True)
    ap.add_argument("--laptop-default", type=Path, required=True)
    ap.add_argument("--expect", type=int, default=858)
    a = ap.parse_args()
    expected = {point_id(*p) for p in itertools.product(GRID["startupDelay"], GRID["tau"], GRID["accel"])}
    assert len(expected) == a.expect
    listed = {}
    for line in (a.src / "grid_sha256.txt").read_text(encoding="utf-8").splitlines():
        h, name = line.split()
        listed[Path(name).stem] = h
    rep = dict(src=str(a.src), listed=len(listed), missing_from_list=sorted(expected - set(listed)),
               not_on_grid=sorted(set(listed) - expected), hash_mismatch=[], parse_errors=[], meta_issues=[])
    data = {}
    for pid in sorted(set(listed) & expected):
        p = a.src / "grid" / f"{pid}.json"
        if not p.is_file():
            rep["parse_errors"].append(f"{pid}: file missing")
            continue
        raw = p.read_bytes()
        if hashlib.sha256(raw).hexdigest() != listed[pid]:
            rep["hash_mismatch"].append(pid)
            continue
        try:
            res = json.loads(raw.decode("utf-8"))
        except ValueError as e:
            rep["parse_errors"].append(f"{pid}: {e}")
            continue
        pt = res.get("point", {})
        if res.get("id") != pid or point_id(pt.get("startupDelay"), pt.get("tau"), pt.get("accel")) != pid \
                or res.get("sumo") != "SUMO 1.26.0" or res.get("backend") != "libsumo" or len(res.get("runs", [])) != 15:
            rep["meta_issues"].append(pid)
        data[pid] = (raw, res)
    lap = json.loads(a.laptop_default.read_text(encoding="utf-8"))
    rep["default_equal_to_laptop"] = DEFAULT_ID in data and runs_hash(data[DEFAULT_ID][1]) == runs_hash(lap)
    rep["hosts"] = sorted({r["host"] for _, r in data.values()})
    rep["platforms"] = sorted({r["platform"] for _, r in data.values()})
    rep["seconds_per_point_median"] = sorted(r["seconds"] for _, r in data.values())[len(data) // 2] if data else None
    rep["passed"] = (len(data) == a.expect and not rep["missing_from_list"] and not rep["not_on_grid"] and not rep["hash_mismatch"]
                     and not rep["parse_errors"] and not rep["meta_issues"] and rep["default_equal_to_laptop"])
    if rep["passed"]:
        a.dst.mkdir(parents=True, exist_ok=True)
        for pid, (raw, _) in data.items():
            (a.dst / f"{pid}.json").write_bytes(raw)
        shutil.copyfile(a.src / "grid_sha256.txt", a.dst.parent / "grid_sha256_colab.txt")
        if (a.src / "grid_run.log").is_file():
            shutil.copyfile(a.src / "grid_run.log", a.dst.parent / "grid_run_colab.log")
    (a.dst.parent / "fetch_report.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in rep.items() if not isinstance(v, list) or v}, indent=1))
    sys.exit(0 if rep["passed"] else 1)


if __name__ == "__main__":
    main()
