"""E3: check and summarize Ryzhanskyi's frozen-evaluation runs (28 Oct 2026) from the tripinfo files.

For every row of <E3>/<clearance>/E3_runs_flags.csv the tripinfo file is re-read and the kit's columns are
recomputed (entries, arrived by 1500/1800 s, mean wait of arrived vehicles), plus: demand of the route file,
not-inserted vehicles, unfinished vehicles, the longest period without any arrival while vehicles are in the
network (deadlock if >= 300 s), and the arrival time of the last vehicle.

    python revision/tools/e3_summary.py --e3 revision/incoming/2026-10-28/answers/step_1.5_1.9/E3 \
        --envs revision/resco_eval/resco/resco_benchmark/environments --out revision/analysis/e3
"""
import argparse
import bisect
import csv
import re
import statistics as st
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--e3", type=Path, required=True)
ap.add_argument("--envs", type=Path, required=True)
ap.add_argument("--out", type=Path, required=True)
args = ap.parse_args()
args.out.mkdir(parents=True, exist_ok=True)

_demand = {}


def demand(map_name, route_file):
    key = (map_name, route_file)
    if key not in _demand:
        txt = (args.envs / map_name / "routes" / route_file).read_text(encoding="utf-8")
        _demand[key] = len(re.findall(r"<(?:vehicle|trip)\s", txt))
    return _demand[key]


def episode(path):
    dep, arr, wait = [], [], []
    for _, el in ET.iterparse(path):
        if el.tag == "tripinfo":
            dep.append(float(el.get("depart")))
            arr.append(float(el.get("arrival")))
            wait.append(float(el.get("waitingTime")))
            el.clear()
    done = sorted(a for a in arr if a >= 0)
    # longest interval without an arrival while vehicles are in the network (end of simulation = 1800 s)
    events = sorted(dep)
    longest, prev = 0.0, None
    for i, t in enumerate(done + [1800.0]):
        start = prev if prev is not None else (events[0] if events else 0.0)
        in_net = bisect.bisect_right(events, start) - i   # departed by `start` minus the i arrivals before it
        if in_net > 0:
            longest = max(longest, t - start)
        prev = t
    aw = [w for w, a in zip(wait, arr) if a >= 0]
    return {"entries": len(arr), "arrived_1500": sum(0 <= a <= 1500 for a in arr),
            "arrived_1800": sum(0 <= a <= 1800 for a in arr), "unfinished": sum(a < 0 for a in arr),
            "mean_wait_arrived": st.mean(aw) if aw else float("nan"), "longest_no_arrival": longest,
            "last_arrival": done[-1] if done else -1}


rows = []
mismatch = []
for clr in ("yellow3", "yellow3+allred4"):
    with open(args.e3 / clr / "E3_runs_flags.csv", encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            local = args.e3 / clr / r["tripinfo_path"].split(f"/E3/{clr}/", 1)[1]
            e = episode(local)
            dem = demand(r["map"], r["route_file"])
            e.update(demand=dem, not_inserted=dem - e["entries"], full_mine=e["entries"] >= 0.99 * dem,
                     deadlock_mine=e["longest_no_arrival"] >= 300)
            for k_kit, k_me in (("n_entries", "entries"), ("n_arrived_1500", "arrived_1500"), ("n_arrived_1800", "arrived_1800")):
                if int(r[k_kit]) != e[k_me]:
                    mismatch.append((clr, r["policy"], r["training_run"], r["map"], r["episode"], k_kit, r[k_kit], e[k_me]))
            if abs(float(r["mean_wait_arrived_s"]) - e["mean_wait_arrived"]) > 0.01:
                mismatch.append((clr, r["policy"], r["training_run"], r["map"], r["episode"], "wait", r["mean_wait_arrived_s"], e["mean_wait_arrived"]))
            if (r["full"] == "True") != e["full_mine"] or (r["deadlock"] == "True") != e["deadlock_mine"]:
                mismatch.append((clr, r["policy"], r["training_run"], r["map"], r["episode"], "flags",
                                 (r["full"], r["deadlock"]), (e["full_mine"], e["deadlock_mine"], round(e["longest_no_arrival"]))))
            rows.append({**{k: r[k] for k in ("policy", "training_run", "eval_set", "map", "load_or_scenario", "episode",
                                               "route_file", "sumo_seed", "clearance")}, **e})

with open(args.out / "e3_episodes.csv", "w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)

POL = ["IDQN-wait", "IDQN-queue", "MPLight"]
SETS = ["x1.0", "x1.2", "x1.5", "S1", "S2", "S3", "S4"]
g = defaultdict(list)
for r in rows:
    g[(r["clearance"], r["policy"], r["load_or_scenario"])].append(r)

md = ["# E3 check: frozen policies on held-out demand and scenarios (Ryzhanskyi's runs of 27-28 Oct 2026)", "",
      f"Episodes re-read: {len(rows)}. Differences between the kit's CSV columns / Ryzhanskyi's flags and the values "
      f"recomputed here: {len(mismatch)}.", ""]
for m in mismatch[:30]:
    md.append(f"- mismatch: {m}")
md += ["", "Full = at least 99% of the route file's vehicles entered the network by 1800 s. Deadlock = no arrival for "
       "at least 300 s while vehicles are in the network. Means over all episodes (10 route files × 5 training runs, "
       "or 5 × 5 for the scenarios).", ""]
for clr in ("yellow3", "yellow3+allred4"):
    md += [f"## Clearance {clr}", "",
           "| Policy | Set | Episodes | Full | Deadlocks | Arrived by 1500 s (mean) | Arrived by 1800 s (median / mean) | "
           "Not inserted (mean) | Unfinished (mean) | Mean wait of arrived, s (median) | Demand |",
           "|---|---|---|---|---|---|---|---|---|---|---|"]
    for s in SETS:
        for p in POL:
            rr = g.get((clr, p, s), [])
            if not rr:
                continue
            md.append(f"| {p} | {s} | {len(rr)} | {100 * sum(r['full_mine'] for r in rr) / len(rr):.0f}% | "
                      f"{sum(r['deadlock_mine'] for r in rr)} | {st.mean(r['arrived_1500'] for r in rr):.0f} | "
                      f"{st.median(r['arrived_1800'] for r in rr):.0f} / {st.mean(r['arrived_1800'] for r in rr):.0f} | "
                      f"{st.mean(r['not_inserted'] for r in rr):.0f} | {st.mean(r['unfinished'] for r in rr):.0f} | "
                      f"{st.median(r['mean_wait_arrived'] for r in rr):.1f} | {st.mean(r['demand'] for r in rr):.0f} |")
    md += ["", "Episodes with the full demand served, ×1.0 held-out, per training run (of 10):", "",
           "| Policy | run 1 | run 2 | run 3 | run 4 | run 5 |", "|---|---|---|---|---|---|"]
    for p in POL:
        rr = g.get((clr, p, "x1.0"), [])
        md.append(f"| {p} | " + " | ".join(str(sum(r["full_mine"] for r in rr if r["training_run"] == str(k))) for k in range(1, 6)) + " |")
    md.append("")
(args.out / "E3_check.md").write_text("\n".join(md) + "\n", encoding="utf-8")
print("\n".join(md))
