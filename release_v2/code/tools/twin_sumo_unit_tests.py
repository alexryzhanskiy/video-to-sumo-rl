"""Two unit tests of SUMO behaviour that the E13 pre-registration and B6 calibration rely on.

Test 1 (tripinfo): how SUMO writes vehicles that are unfinished (inserted, not arrived) or never inserted at the
end of a run, with --tripinfo-output.write-unfinished alone and together with --tripinfo-output.write-undeparted.
A synthetic route file on the repository network has one vehicle of each kind:
  arrived     departs at 0 s on the Svobody green and leaves the network;
  running     departs at 55 s, still on the network at the end (60 s);
  backlog_*   40 vehicles that all want to depart at 30 s on one lane of a red approach (more than the lane
              holds), so some are still waiting for insertion at the end;
  future_120  depart 120 s: after the end but inside the default route look-ahead (200 s), so it is loaded;
  future_1000 depart 1000 s: after the end and outside the look-ahead.

Test 2 (vType): the route files define no vType, so every vehicle uses DEFAULT_VEHTYPE. An additional file that
redefines DEFAULT_VEHTYPE with SUMO's default values (or with startupDelay="0") must give a tripinfo identical to the
run without it; a non-zero startupDelay must change it. The comparison drops the XML header comment, which
contains the command line.

    revision/.venv/Scripts/python.exe revision/tools/twin_sumo_unit_tests.py --net sumo/intersection.net.xml \
        --route sumo/demand.rou.xml --out revision/twin/unit_tests
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import demandlib as dl  # noqa: E402

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--net", type=Path, required=True)
ap.add_argument("--route", type=Path, required=True, help="a real demand file for test 2")
ap.add_argument("--out", type=Path, required=True)
ap.add_argument("--sumo-home", default=None)
args = ap.parse_args()
home = dl.find_sumo_home(args.sumo_home)
os.environ["SUMO_HOME"] = str(home)
SUMO = str(home / "bin" / ("sumo.exe" if os.name == "nt" else "sumo"))
args.out.mkdir(parents=True, exist_ok=True)
version = subprocess.run([SUMO, "--version"], capture_output=True, text=True).stdout.splitlines()[0]


def run(route, out, extra=(), add=None, end=60):
    cmd = [SUMO, "-n", str(args.net), "-r", str(route), "--end", str(end), "--time-to-teleport", "-1",
           "--no-step-log", "true", "--no-warnings", "true", "--duration-log.disable", "true",
           "--tripinfo-output", str(out), *extra]
    if add:
        cmd += ["-a", str(add)]
    subprocess.run(cmd, check=True)
    return cmd


def body(path):
    """tripinfo without the header comment (it holds the command line and file paths)."""
    txt = Path(path).read_text(encoding="utf-8")
    return re.sub(r"<!--.*?-->", "", txt, flags=re.S).strip()


# --- test 1
veh = ['    <vehicle id="arrived" depart="0" departLane="1" departSpeed="max"><route edges="nN_nC nC_nS"/></vehicle>']
veh += [f'    <vehicle id="backlog_{i:02d}" depart="30" departLane="0" departPos="base" departSpeed="0">'
        f'<route edges="nE_nC nC_nW"/></vehicle>' for i in range(40)]
veh += ['    <vehicle id="running" depart="55" departLane="2"><route edges="nS_nC nC_nN"/></vehicle>',
        '    <vehicle id="future_120" depart="120"><route edges="nW_nC nC_nE"/></vehicle>',
        '    <vehicle id="future_1000" depart="1000"><route edges="nW_nC nC_nE"/></vehicle>']
rou = args.out / "t1_cases.rou.xml"
rou.write_text("<routes>\n" + "\n".join(veh) + "\n</routes>\n", encoding="utf-8")
variants = {"plain": [], "write_unfinished": ["--tripinfo-output.write-unfinished", "true"],
            "write_unfinished+undeparted": ["--tripinfo-output.write-unfinished", "true",
                                            "--tripinfo-output.write-undeparted", "true"]}
t1 = {}
for name, extra in variants.items():
    out = args.out / f"t1_tripinfo_{name}.xml"
    cmd = run(rou, out, extra)
    rows = {}
    for ti in ET.parse(out).getroot().iter("tripinfo"):
        rows[ti.get("id")] = {k: ti.get(k) for k in ("depart", "departDelay", "arrival", "duration", "routeLength",
                                                      "waitingTime", "timeLoss", "vaporized")}
    backlog_written = sorted(k for k in rows if k.startswith("backlog_"))
    t1[name] = dict(options=extra, entries=len(rows),
                    arrived=rows.get("arrived"), running=rows.get("running"),
                    future_120=rows.get("future_120"), future_1000=rows.get("future_1000"),
                    backlog_written=len(backlog_written),
                    backlog_inserted=sum(float(rows[k]["depart"]) >= 0 for k in backlog_written),
                    backlog_not_inserted=sum(float(rows[k]["depart"]) < 0 for k in backlog_written),
                    backlog_examples={k: rows[k] for k in backlog_written[:1] + backlog_written[-1:]})

# --- test 2
t2 = {}
vt = {"none": None,
      "default_values": '<vType id="DEFAULT_VEHTYPE"/>',
      "startupDelay_0": '<vType id="DEFAULT_VEHTYPE" startupDelay="0"/>',
      "explicit_defaults": '<vType id="DEFAULT_VEHTYPE" tau="1" accel="2.6" decel="4.5" sigma="0.5" startupDelay="0"/>',
      "startupDelay_1.5": '<vType id="DEFAULT_VEHTYPE" startupDelay="1.5"/>'}
ref = None
for name, xml in vt.items():
    add = None
    if xml:
        add = args.out / f"t2_vtype_{name}.add.xml"
        add.write_text(f"<additional>\n    {xml}\n</additional>\n", encoding="utf-8")
    out = args.out / f"t2_tripinfo_{name}.xml"
    run(args.route, out, ["--seed", "1"], add=add, end=1500)
    b = body(out)
    root = ET.fromstring(b)
    arrived = [t for t in root.iter("tripinfo")]
    sha = hashlib.sha256(b.encode()).hexdigest()
    ref = ref or sha
    t2[name] = dict(vtype=xml, arrived=len(arrived), types=sorted({t.get("vType") for t in arrived}),
                    mean_timeLoss=round(sum(float(t.get("timeLoss")) for t in arrived) / len(arrived), 3),
                    sha256_body=sha, identical_to_none=sha == ref)

res = dict(sumo_version=version, sumo_home=dl.posix(home), net=dl.posix(args.net), route_test2=dl.posix(args.route),
           test1_tripinfo=t1, test2_vtype=t2)
(args.out / "unit_tests.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
print(json.dumps(res, indent=1))
