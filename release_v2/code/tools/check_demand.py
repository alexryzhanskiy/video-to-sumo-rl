"""Automated checks of generated demand files (P01 Step 3).

Checks every route file listed in the generation logs:
  - XML parses; only id/depart vehicle attributes and inline <route edges>, no vType (same layout as
    the original sumo/demand*.rou.xml, K14);
  - vehicle IDs unique; departures sorted and in [begin, end) of the counts file;
  - every route is one of the candidate routes;
  - counts per (300-s interval, from-edge, to-edge) equal the reference counts file (x1.0 for S2);
  - total equals the reference total and, with --expect, the stated total of its group;
  - no two files are identical and none equals an original file.
Writes a CSV report and prints a pass/fail summary. Exit code 0 only if everything passes.

Example (from the repository root):
  python revision/tools/check_demand.py --candidate sumo/candidate.rou.xml \
      --log revision/demand/heldout/generation_log.json --log revision/demand/scenarios/generation_log.json \
      --original sumo/demand.rou.xml --original sumo/demand_12.rou.xml --original sumo/demand_15.rou.xml \
      --expect heldout_x10=1355 --expect heldout_x12=1626 --expect heldout_x15=2036 \
      --expect scenario_S1=1633 --expect scenario_S2=1355 --expect scenario_S3=1355 --expect scenario_S4=1355 \
      --report revision/demand/check_report.csv
"""
from __future__ import annotations

import argparse
import csv
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

import demandlib as dl

CHECKS = ["xml_ok", "structure_ok", "ids_unique", "sorted", "in_range", "routes_valid", "counts_match",
          "total_ok", "distinct", "differs_from_original"]


def structure_ok(path: Path) -> tuple[bool, str]:
    root = ET.parse(path).getroot()
    if root.tag != "routes":
        return False, f"root <{root.tag}>"
    for child in root:
        if child.tag != "vehicle":
            return False, f"unexpected <{child.tag}>"
        if set(child.attrib) != {"id", "depart"}:
            return False, f"vehicle attributes {sorted(child.attrib)}"
        kids = list(child)
        if len(kids) != 1 or kids[0].tag != "route" or set(kids[0].attrib) != {"edges"}:
            return False, f"vehicle {child.get('id')} children"
    return True, ""


def check_file(path: Path, entry: dict, routes: dict[str, str], expect: dict[str, int]) -> dict:
    row = {"file": dl.posix(path), "group": entry["group"], "load_or_scenario": entry["load_or_scenario"],
           "seeds": " ".join(map(str, entry["seeds"])), "counts_ref": entry["counts_ref"]}
    notes = []
    try:
        veh = dl.read_routes(path)
        row["xml_ok"] = True
    except ET.ParseError as e:
        row.update({c: False for c in CHECKS})
        row.update({"vehicles": 0, "pass": False, "notes": f"parse error: {e}"})
        return row
    ok, why = structure_ok(path)
    row["structure_ok"] = ok
    if why:
        notes.append(why)
    row["vehicles"] = len(veh)
    row["ids_unique"] = len({v.id for v in veh}) == len(veh)
    departs = [v.depart for v in veh]
    row["sorted"] = all(a <= b for a, b in zip(departs, departs[1:]))

    ref = dl.read_counts(Path(entry["counts_ref"]))
    lo, hi = ref[0].b, ref[-1].e
    row["in_range"] = all(lo <= d < hi for d in departs)
    row["routes_valid"] = all(v.edges in routes for v in veh)

    got = Counter()
    for v in veh:
        iv = next((i for i in ref if i.b <= v.depart < i.e), None)
        e = v.edges.split()
        got[(iv.begin if iv else "out", e[0], e[-1])] += 1
    want = {k: c for k, c in dl.counts_table(ref).items() if c}
    row["counts_match"] = dict(got) == want
    if not row["counts_match"]:
        bad = sorted(set(got) | set(want), key=str)
        bad = [k for k in bad if got.get(k, 0) != want.get(k, 0)]
        notes.append(f"{len(bad)} cells differ, e.g. {bad[:3]}")
    per_iv = [sum(c for (b, _, _), c in got.items() if b == iv.begin) for iv in ref]
    row["interval_counts"] = " ".join(map(str, per_iv))

    row["expected_total"] = entry["expected_total"]
    total_ok = len(veh) == entry["expected_total"] == dl.counts_total(ref)
    if entry["group"] in expect:
        total_ok = total_ok and len(veh) == expect[entry["group"]]
        row["stated_total"] = expect[entry["group"]]
    row["total_ok"] = total_ok
    row["signature"] = dl.vehicle_signature(veh)
    row["sha256"] = dl.sha256(path)
    row["notes"] = "; ".join(notes)
    return row


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--candidate", type=Path, required=True, help="candidate routes (sumo/candidate.rou.xml)")
    ap.add_argument("--log", type=Path, action="append", required=True, help="generation_log.json (repeatable)")
    ap.add_argument("--original", type=Path, action="append", default=[],
                    help="original route file that no generated file may equal (repeatable)")
    ap.add_argument("--expect", action="append", default=[], metavar="GROUP=N",
                    help="stated total of a group, e.g. heldout_x10=1355 (repeatable)")
    ap.add_argument("--report", type=Path, required=True, help="CSV report to write")
    args = ap.parse_args()

    routes = dl.candidate_routes(args.candidate)
    expect = {g: int(n) for g, n in (e.split("=", 1) for e in args.expect)}
    entries = {}
    for log in args.log:
        for path, entry in dl.load_log(log).items():
            if path.endswith(".rou.xml"):
                entries[path] = entry
    rows = [check_file(Path(p), entries[p], routes, expect) for p in sorted(entries)]

    orig_sigs = {dl.vehicle_signature(dl.read_routes(o)): dl.posix(o) for o in args.original}
    orig_sha = {dl.sha256(o) for o in args.original}
    sig_count = Counter(r["signature"] for r in rows)
    sha_count = Counter(r["sha256"] for r in rows)
    depart_sig = Counter()
    for r in rows:
        depart_sig[tuple(v.depart_str for v in dl.read_routes(Path(r["file"])))] += 1
    for r in rows:
        departs = tuple(v.depart_str for v in dl.read_routes(Path(r["file"])))
        r["distinct"] = sig_count[r["signature"]] == 1 and sha_count[r["sha256"]] == 1 and depart_sig[departs] == 1
        r["differs_from_original"] = r["signature"] not in orig_sigs and r["sha256"] not in orig_sha
        r["pass"] = all(bool(r.get(c)) for c in CHECKS)

    fields = ["file", "group", "load_or_scenario", "seeds", "counts_ref", "vehicles", "expected_total",
              "stated_total", "interval_counts"] + CHECKS + ["pass", "sha256", "notes"]
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with open(args.report, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    groups = Counter(r["group"] for r in rows)
    passed = Counter(r["group"] for r in rows if r["pass"])
    print(f"{'group':<14} files  pass")
    for g in sorted(groups):
        print(f"{g:<14} {groups[g]:>5} {passed[g]:>5}")
    failed = [r for r in rows if not r["pass"]]
    for r in failed:
        print(f"FAIL {r['file']}: " + ", ".join(c for c in CHECKS if not r.get(c)) + f"  {r.get('notes', '')}")
    print(f"{'ALL PASS' if not failed else 'FAILED'}: {len(rows) - len(failed)}/{len(rows)} files; "
          f"report {dl.posix(args.report)}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
