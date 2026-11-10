"""B6 reported quantities (protocol revision/twin/B6_protocol_draft.md, section 6): throughput of the field-phased fixed
plan on the 15 calibration runs, and the plausibility flag.

Every run: sumo/intersection.net.xml, the E8 field plan (offset 16 s), --end 1800, --time-to-teleport -1, tripinfo with
--tripinfo-output.write-unfinished and --tripinfo-output.write-undeparted (unit test: revision/twin/unit_tests/), plus an
optional vehicle-type file. Per run: demand (vehicles in the route file), arrived by 1500 s and by 1800 s, still in the
network at 1800 s, never inserted, unserved by 1800 s = demand - arrived by 1800 s.

Plausibility flag: the mean unserved share over the original demand with seeds 1-5 exceeds 1% of the demand.

    revision/.venv-resco/Scripts/python.exe revision/tools/twin_b6_throughput.py --label default --out revision/twin/B6/throughput
    revision/.venv-resco/Scripts/python.exe revision/tools/twin_b6_throughput.py --label calibrated \
        --vtype revision/twin/calibrated_vtype.add.xml --out revision/twin/B6/throughput
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import statistics as st
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNS = [("original", ROOT / "sumo" / "demand.rou.xml", s) for s in (1, 2, 3, 4, 5)] + \
       [("train", ROOT / "revision" / "demand" / "train" / "x10" / f"train_x10_s{s}.rou.xml", 1) for s in range(3001, 3011)]
END, FLAG_SHARE = 1800, 0.01

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--label", required=True)
ap.add_argument("--vtype", type=Path)
ap.add_argument("--out", type=Path, required=True)
ap.add_argument("--jobs", type=int, default=6)
args = ap.parse_args()
home = Path(os.environ.get("SUMO_HOME") or __import__("sumo").SUMO_HOME)
sumo = next(p for p in (home / "bin" / "sumo.exe", home / "bin" / "sumo") if p.is_file())
version = subprocess.run([str(sumo), "--version"], capture_output=True, text=True).stdout.splitlines()[0]
tls = ROOT / "revision" / "runs" / "e8_validation" / "tls_offset_16.add.xml"
adds = [tls] + ([args.vtype.resolve()] if args.vtype else [])
args.out.mkdir(parents=True, exist_ok=True)


def run(job):
    lab, route, seed = job
    with tempfile.TemporaryDirectory() as tmp:
        ti = Path(tmp) / "tripinfo.xml"
        subprocess.run([str(sumo), "-n", str(ROOT / "sumo" / "intersection.net.xml"), "-r", str(route), "-a", ",".join(map(str, adds)),
                        "--begin", "0", "--end", str(END), "--seed", str(seed), "--time-to-teleport", "-1", "--no-step-log", "true",
                        "--no-warnings", "true", "--duration-log.disable", "true", "--tripinfo-output", str(ti),
                        "--tripinfo-output.write-unfinished", "true", "--tripinfo-output.write-undeparted", "true"], check=True)
        trips = list(ET.parse(ti).getroot().iter("tripinfo"))
    demand = sum(1 for _ in ET.parse(route).getroot().iter("vehicle"))
    arr = [float(t.get("arrival")) for t in trips if float(t.get("arrival")) >= 0]
    never = sum(t.get("depart") == "-1" or float(t.get("depart")) < 0 for t in trips)
    unfinished = sum(float(t.get("arrival")) < 0 and float(t.get("depart")) >= 0 for t in trips)
    assert len(trips) == demand, (route, len(trips), demand)
    return dict(label=args.label, set=lab, route=route.name, seed=seed, demand=demand, arrived_1500=sum(a <= 1500 for a in arr),
                arrived_1800=len(arr), in_network_1800=unfinished, never_inserted=never, unserved_1800=demand - len(arr),
                mean_time_loss_arrived=round(st.mean(float(t.get("timeLoss")) for t in trips if float(t.get("arrival")) >= 0), 3))


with ThreadPoolExecutor(args.jobs) as ex:
    rows = list(ex.map(run, RUNS))
with open(args.out / f"throughput_{args.label}.csv", "w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)
orig = [r for r in rows if r["set"] == "original"]
share = st.mean(r["unserved_1800"] / r["demand"] for r in orig)
summ = dict(label=args.label, vtype=str(args.vtype) if args.vtype else None, sumo=version, end=END,
            original_seeds_1_5=dict(unserved_share_mean=share, unserved_mean=st.mean(r["unserved_1800"] for r in orig),
                                    arrived_1500_mean=st.mean(r["arrived_1500"] for r in orig),
                                    arrived_1800_mean=st.mean(r["arrived_1800"] for r in orig),
                                    never_inserted_mean=st.mean(r["never_inserted"] for r in orig)),
            all_15=dict(arrived_1500_mean=st.mean(r["arrived_1500"] for r in rows), arrived_1800_mean=st.mean(r["arrived_1800"] for r in rows),
                        unserved_mean=st.mean(r["unserved_1800"] for r in rows), never_inserted_mean=st.mean(r["never_inserted"] for r in rows)),
            plausibility_flag=share > FLAG_SHARE)
(args.out / f"throughput_{args.label}.json").write_text(json.dumps(summ, indent=1), encoding="utf-8")
print(json.dumps(summ, indent=1))
