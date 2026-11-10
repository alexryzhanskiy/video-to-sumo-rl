"""Fixed-plan sanity runs of demand files (P01 Step 4).

Runs SUMO with the network's static program (field fixed-time plan, 3-s yellow + 4-s all-red) for
every route file in the generation logs and for the original files, with --end 1800,
--time-to-teleport -1, tripinfo incl. unfinished vehicles, emissions device and a fixed SUMO seed.
Metrics follow kb/07_EXPERIMENT_SPECS.md: T1500 and T1800 (arrivals by 1500 / 1800 s), unfinished
vehicles, vehicles never inserted, mean waiting / travel time / time loss over arrived vehicles, mean
and max departDelay over inserted vehicles, CO2 (kg) over arrived vehicles.

A file is flagged if T1800 < --min-t1800-share x demand, if mean waiting > --wait-factor x the mean
waiting of the --wait-baseline run, or if mean departDelay > --max-depart-delay s.

Example (from the repository root):
  python revision/tools/sanity_fixed.py --net sumo/intersection.net.xml \
      --log revision/demand/heldout/generation_log.json --log revision/demand/scenarios/generation_log.json \
      --original original_x10=sumo/demand.rou.xml --original original_x12=sumo/demand_12.rou.xml \
      --original original_x15=sumo/demand_15.rou.xml --wait-baseline original_x10 \
      --run-dir revision/runs/sanity_fixed --csv revision/demand/sanity_fixed.csv \
      --summary revision/demand/sanity_fixed_summary.md
"""
from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from statistics import mean

import demandlib as dl


def run_sumo(sumo: Path, net: Path, route: Path, run_dir: Path, args) -> tuple[Path, Path, str]:
    stem = route.name.replace(".rou.xml", "")
    trip = run_dir / f"{stem}.tripinfo.xml"
    stat = run_dir / f"{stem}.stats.xml"
    cmd = [str(sumo), "-n", dl.posix(net), "-r", dl.posix(route), "--begin", "0", "--end", str(args.end),
           "--time-to-teleport", "-1", "--tripinfo-output", dl.posix(trip), "--tripinfo-output.write-unfinished",
           "--device.emissions.probability", "1.0", "--seed", str(args.seed), "--statistic-output", dl.posix(stat),
           "--no-step-log", "--no-warnings"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        sys.exit(f"SUMO failed on {route}:\n{res.stderr}")
    return trip, stat, " ".join(["sumo"] + cmd[1:])


def metrics(trip: Path, stat: Path, demand: int) -> dict:
    rows = []
    for t in ET.parse(trip).getroot().iter("tripinfo"):
        em = t.find("emissions")
        rows.append({"depart": float(t.get("depart")), "arrival": float(t.get("arrival")),
                     "duration": float(t.get("duration")), "wait": float(t.get("waitingTime")),
                     "timeloss": float(t.get("timeLoss")), "dd": float(t.get("departDelay")),
                     "co2": float(em.get("CO2_abs")) if em is not None else 0.0})
    arrived = [r for r in rows if r["arrival"] >= 0]
    inserted = [r for r in rows if r["depart"] >= 0]
    veh = ET.parse(stat).getroot().find("vehicles")
    m = {
        "demand": demand,
        "loaded": int(veh.get("loaded")),
        "inserted": int(veh.get("inserted")),
        "not_inserted": int(veh.get("waiting")),
        "T1500": sum(1 for r in arrived if r["arrival"] <= 1500),
        "T1800": sum(1 for r in arrived if r["arrival"] <= 1800),
        "unfinished": sum(1 for r in rows if r["arrival"] < 0),
        "mean_wait_s": mean(r["wait"] for r in arrived),
        "mean_travel_s": mean(r["duration"] for r in arrived),
        "mean_timeloss_s": mean(r["timeloss"] for r in arrived),
        "mean_depart_delay_s": mean(r["dd"] for r in inserted),
        "max_depart_delay_s": max(r["dd"] for r in inserted),
        "co2_kg_arrived": sum(r["co2"] for r in arrived) / 1e6,
    }
    m["T1800_share"] = m["T1800"] / demand
    return m


def fmt(v) -> str:
    return f"{v:.2f}" if isinstance(v, float) else str(v)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--net", type=Path, required=True, help="network with the fixed plan (sumo/intersection.net.xml)")
    ap.add_argument("--log", type=Path, action="append", default=[], help="generation_log.json (repeatable)")
    ap.add_argument("--original", action="append", default=[], metavar="LABEL=FILE",
                    help="original route file to run as baseline, e.g. original_x10=sumo/demand.rou.xml")
    ap.add_argument("--wait-baseline", required=True, help="label of the --original run used for the waiting flag")
    ap.add_argument("--run-dir", type=Path, required=True, help="folder for tripinfo/statistics outputs")
    ap.add_argument("--csv", type=Path, required=True, help="per-file CSV to write")
    ap.add_argument("--summary", type=Path, required=True, help="Markdown summary table to write")
    ap.add_argument("--end", type=int, default=1800, help="simulation end (s), default 1800")
    ap.add_argument("--seed", type=int, default=1, help="SUMO --seed, default 1")
    ap.add_argument("--min-t1800-share", type=float, default=0.85, help="flag if T1800 < share x demand")
    ap.add_argument("--wait-factor", type=float, default=3.0, help="flag if mean waiting > factor x baseline")
    ap.add_argument("--max-depart-delay", type=float, default=60.0, help="flag if mean departDelay > this (s)")
    ap.add_argument("--accept", action="append", default=[], metavar="GROUP=REASON",
                    help="record flags of a group as accepted, with the reason (repeatable)")
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 1), help="parallel SUMO runs")
    ap.add_argument("--sumo-home", help="SUMO installation (default: $SUMO_HOME or the eclipse-sumo wheel)")
    args = ap.parse_args()

    sumo_home = dl.find_sumo_home(args.sumo_home)
    sumo = dl.sumo_binary(sumo_home)
    version = dl.sumo_version(sumo_home)
    accepted = dict(a.split("=", 1) for a in args.accept)
    args.run_dir.mkdir(parents=True, exist_ok=True)

    jobs = []  # (label/group, load_or_scenario, path)
    for spec in args.original:
        label, path = spec.split("=", 1)
        jobs.append((label, label.replace("original_", ""), Path(path)))
    for log in args.log:
        for path, entry in sorted(dl.load_log(log).items()):
            if path.endswith(".rou.xml"):
                jobs.append((entry["group"], entry["load_or_scenario"], Path(path)))

    def work(job):
        group, los, path = job
        trip, stat, cmd = run_sumo(sumo, args.net, path, args.run_dir, args)
        m = metrics(trip, stat, len(dl.read_routes(path)))
        return {"file": dl.posix(path), "group": group, "load_or_scenario": los, **m,
                "tripinfo": dl.posix(trip), "sumo_version": version, "command": cmd}

    with ThreadPoolExecutor(args.jobs) as ex:
        rows = list(ex.map(work, jobs))

    base = next(r for r in rows if r["group"] == args.wait_baseline)
    for r in rows:
        r["flag_T1800"] = r["T1800_share"] < args.min_t1800_share
        r["flag_wait"] = r["mean_wait_s"] > args.wait_factor * base["mean_wait_s"]
        r["flag_depart_delay"] = r["mean_depart_delay_s"] > args.max_depart_delay
        r["flagged"] = r["flag_T1800"] or r["flag_wait"] or r["flag_depart_delay"]
        r["flag_resolution"] = accepted.get(r["group"], "") if r["flagged"] else ""

    fields = list(rows[0].keys())
    for c in ("tripinfo", "sumo_version", "command"):
        fields.remove(c)
        fields.append(c)
    args.csv.parent.mkdir(parents=True, exist_ok=True)
    with open(args.csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: fmt(v) if isinstance(v, float) else v for k, v in r.items()})

    # Summary per group: mean over realizations (min-max in brackets for the key columns).
    cols = ["demand", "T1500", "T1800", "unfinished", "not_inserted", "mean_wait_s", "mean_travel_s",
            "mean_timeloss_s", "mean_depart_delay_s", "max_depart_delay_s", "co2_kg_arrived"]
    groups = list(dict.fromkeys(r["group"] for r in rows))
    lines = [f"Fixed-plan sanity runs: SUMO {version}, `{dl.posix(args.net)}`, end {args.end} s, seed {args.seed}, "
             f"no teleports. Values are means over the files of a group; [min-max] for groups with several files. "
             f"Flags: T1800 < {args.min_t1800_share:g} x demand; mean waiting > {args.wait_factor:g} x "
             f"{args.wait_baseline} ({base['mean_wait_s']:.2f} s); mean departDelay > {args.max_depart_delay:g} s.",
             "", "| Group | n | " + " | ".join(cols) + " | flagged |", "|---" * (len(cols) + 3) + "|"]
    for g in groups:
        rs = [r for r in rows if r["group"] == g]
        cells = []
        for c in cols:
            vals = [r[c] for r in rs]
            mv = mean(vals)
            txt = f"{mv:.1f}" if isinstance(vals[0], float) or len(rs) > 1 else str(vals[0])
            if len(rs) > 1 and c in ("T1500", "T1800", "mean_wait_s", "mean_depart_delay_s"):
                txt += f" [{min(vals):.0f}-{max(vals):.0f}]" if c.startswith("T") else f" [{min(vals):.1f}-{max(vals):.1f}]"
            cells.append(txt)
        lines.append(f"| {g} | {len(rs)} | " + " | ".join(cells) + f" | {sum(r['flagged'] for r in rs)} |")
    for g, reason in accepted.items():
        if any(r["flagged"] for r in rows if r["group"] == g):
            lines.append(f"\nFlags of `{g}` accepted: {reason}")
    args.summary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    flagged = [r for r in rows if r["flagged"]]
    for r in flagged:
        why = [k for k in ("flag_T1800", "flag_wait", "flag_depart_delay") if r[k]]
        print(f"FLAG {r['file']}: {', '.join(why)}" + (f"  [accepted]" if r["flag_resolution"] else ""))
    open_flags = [r for r in flagged if not r["flag_resolution"]]
    print(f"{len(rows)} runs, {len(flagged)} flagged, {len(open_flags)} unresolved; CSV {dl.posix(args.csv)}")


if __name__ == "__main__":
    main()
