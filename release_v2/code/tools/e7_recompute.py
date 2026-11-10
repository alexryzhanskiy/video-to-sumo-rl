"""E7: recompute Tables 4-5 from the original final-episode tripinfo files (Step 0 files of 28 Oct 2026).

Two rules per run:
  paper      = src/seed_stats.py / src/baselines_stats.py: every <tripinfo> counts as throughput (including the
               unfinished vehicles of --tripinfo-output.write-unfinished), means over all of them; IDQN and MPLight
               drop runs with throughput < 0.8 x median.
  harmonized = kb/07 metric definitions: T1500 = arrived with 0 <= arrival <= 1500, means over arrived vehicles,
               unfinished and not-inserted vehicles reported separately; no run dropped.

    python revision/tools/e7_recompute.py --step0 revision/incoming/2026-10-28/answers/step_0 --out revision/runs/e7
"""
import argparse
import csv
import statistics as st
import xml.etree.ElementTree as ET
from pathlib import Path

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--step0", type=Path, required=True)
ap.add_argument("--out", type=Path, required=True)
args = ap.parse_args()
args.out.mkdir(parents=True, exist_ok=True)

DEMAND = {"x1.0": 1355, "x1.2": 1626, "x1.5": 2036}
MAP = {"x1.0": "prybuzka", "x1.2": "prybuzka_12", "x1.5": "prybuzka_15"}
SUF = {"x1.0": "10", "x1.2": "12", "x1.5": "15"}
# submitted Tables 4-5 (kb/source/manuscript_v1_latex/main.tex): throughput, travel, waiting, time loss (x1.0 only), CO2
PAPER = {
    ("x1.0", "Fixed"): (1285, 62.6, 34.2, 45.2, 184), ("x1.0", "Actuated"): (1277, 59.1, 31.0, 41.7, 175),
    ("x1.0", "MaxPressure"): (1335, 72.3, 33.6, 55.7, 208), ("x1.0", "MPLight"): (1304, 73.6, 36.6, 56.8, 204),
    ("x1.0", "IDQN-wait"): (1351, 41.5, 13.4, 24.4, 152), ("x1.0", "IDQN-queue"): (1352, 42.1, 14.3, 25.1, 153),
    ("x1.2", "Fixed"): (1607, 83.1, 52.2, None, 278), ("x1.2", "Actuated"): (1394, 75.4, 47.0, None, 224),
    ("x1.2", "MaxPressure"): (1012, 196.6, 156.1, None, 341), ("x1.2", "MPLight"): (1516, 82.8, 45.8, None, 263),
    ("x1.2", "IDQN-wait"): (1626, 57.5, 26.6, None, 223), ("x1.2", "IDQN-queue"): (1626, 50.8, 21.0, None, 207),
    ("x1.5", "Fixed"): (1784, 99.4, 66.4, None, 352), ("x1.5", "Actuated"): (1404, 90.0, 60.9, None, 256),
    ("x1.5", "MaxPressure"): (799, 272.4, 234.0, None, 362), ("x1.5", "MPLight"): (1512, 95.1, 60.0, None, 288),
    ("x1.5", "IDQN-wait"): (1400, 116.8, 83.3, None, 299), ("x1.5", "IDQN-queue"): (1874, 67.0, 35.4, None, 279),
}
CTRL = ["Fixed", "Actuated", "MaxPressure", "MPLight", "IDQN-wait", "IDQN-queue"]


def trips(path):
    out = []
    for _, el in ET.iterparse(path):
        if el.tag == "tripinfo":
            em = el.find("emissions")
            out.append((float(el.get("depart")), float(el.get("arrival")), float(el.get("duration")),
                        float(el.get("waitingTime")), float(el.get("timeLoss")),
                        float(em.get("CO2_abs")) if em is not None else 0.0))
            el.clear()
    return out


def metrics(path, load):
    t = trips(path)
    arr = [x for x in t if x[1] >= 0]
    m = lambda xs, i: st.mean(x[i] for x in xs) if xs else float("nan")  # noqa: E731
    return {
        "file": str(path), "entries": len(t), "arrived": len(arr), "T1500": sum(0 <= x[1] <= 1500 for x in t),
        "T1800": sum(0 <= x[1] <= 1800 for x in t), "unfinished": len(t) - len(arr),
        "not_inserted": DEMAND[load] - len(t), "last_arrival": max((x[1] for x in arr), default=-1),
        "p_travel": m(t, 2), "p_wait": m(t, 3), "p_timeloss": m(t, 4), "p_co2": sum(x[5] for x in t) / 1e6,
        "h_travel": m(arr, 2), "h_wait": m(arr, 3), "h_timeloss": m(arr, 4), "h_co2": sum(x[5] for x in arr) / 1e6,
    }


def rd(p):
    with open(p, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


runs = []  # (load, controller, run, path)
for load in DEMAND:
    for s in range(1, 6):
        runs.append((load, "Fixed", s, args.step0 / "b_sumo_seeds" / f"fix_{SUF[load]}_s{s}.xml"))
        runs.append((load, "Actuated", s, args.step0 / "b_sumo_seeds" / f"act_{SUF[load]}_s{s}.xml"))
for r in rd(args.step0 / "maxpressure_runs.csv"):
    load = {v: k for k, v in MAP.items()}[r["train_map"]]
    d = args.step0 / "a_resco_results" / r["run_folder"]
    final = max(d.glob("tripinfo_*.xml"), key=lambda p: int(p.stem.split("_")[-1]))
    runs.append((load, "MaxPressure", int(r["training_run"]), final))
for r in rd(args.step0 / "reported_runs.csv"):
    if r["reported"] == "y":
        runs.append((r["load"], r["policy"], int(r["trial"]), args.step0 / "a_resco_results" / r["run_folder"] / r["final_tripinfo"]))

rows = []
for load, ctrl, run, path in runs:
    m = metrics(path, load)
    rows.append({"load": load, "controller": ctrl, "run": run, **m})
    print(load, ctrl, run, m["entries"], m["T1500"], m["arrived"], m["unfinished"], m["not_inserted"], flush=True)
with open(args.out / "e7_per_run.csv", "w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)


def ms(xs, nd=1):
    if not xs:
        return "–"
    return f"{st.mean(xs):.{nd}f} ± {st.stdev(xs) if len(xs) > 1 else 0:.{nd}f}"


md = ["# E7: Tables 4-5 recomputed from the Step 0 files", "",
      "Paper rule = `src/seed_stats.py` / `baselines_stats.py` (all tripinfo entries; IDQN and MPLight drop runs "
      "< 0.8 × median throughput). Harmonized = kb/07 definitions (arrived vehicles only, T1500, nothing dropped).", ""]
for load in DEMAND:
    md += [f"## {load} (demand {DEMAND[load]})", "",
           "| Controller | Paper: throughput / travel / waiting / CO2 | Recomputed, paper rule (n kept) | "
           "Harmonized: T1500 | arrived (any time) | unfinished | not inserted | travel / waiting over arrived | runs < 0.8 × median |",
           "|---|---|---|---|---|---|---|---|---|"]
    for c in CTRL:
        rr = [r for r in rows if r["load"] == load and r["controller"] == c]
        thr = [r["entries"] for r in rr]
        med = st.median(thr)
        keep = [r for r in rr if c not in ("IDQN-wait", "IDQN-queue", "MPLight") or r["entries"] >= 0.8 * med]
        dropped = [f"run {r['run']}: {r['entries']}" for r in rr if r not in keep]
        p = PAPER[(load, c)]
        md.append(
            f"| {c} | {p[0]} / {p[1]} / {p[2]} / {p[4]} | {ms([r['entries'] for r in keep], 0)} / "
            f"{ms([r['p_travel'] for r in keep])} / {ms([r['p_wait'] for r in keep])} / {ms([r['p_co2'] for r in keep], 0)} "
            f"(n = {len(keep)}) | {ms([r['T1500'] for r in rr], 0)} | {ms([r['arrived'] for r in rr], 0)} | "
            f"{ms([r['unfinished'] for r in rr], 0)} | {ms([r['not_inserted'] for r in rr], 0)} | "
            f"{ms([r['h_travel'] for r in rr])} / {ms([r['h_wait'] for r in rr])} | {'; '.join(dropped) or '–'} |")
    md.append("")
(args.out / "E7_results.md").write_text("\n".join(md) + "\n", encoding="utf-8")
print("\n".join(md))
