"""E6: non-learning baselines (fixed plan, actuated) on the E12 evaluation files, paired with the E12 episodes.

For every evaluation map of the E12 kit (held-out x1.0/x1.2/x1.5, scenarios S1-S4), every route file e (sorted, as
RESCO uses them) and k = 1..5, SUMO runs with the seed of the matching E12 episode, 42 + (1000 + k) + e, for 1800 s
with --time-to-teleport -1 and unfinished vehicles written (as RESCO does). Metrics come from the E12 kit's own
functions (e12.episode_metrics, e12.demand), so every number is defined exactly as in results/eval_episodes.csv.

  fixed     sumo/intersection.net.xml       static field program (120-s cycle; all-red 4 s on the two street changes)
  actuated  sumo/intersection_act.net.xml   actuated version of the same program (K10 parameters)

From the repository root, with revision/.venv-resco (SUMO 1.26.0):
  revision/.venv-resco/Scripts/python.exe revision/tools/e6_baselines.py --kit revision/e12_kit --out revision/runs/e6
"""
from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

NETS = {"Fixed plan": Path("sumo/intersection.net.xml"), "Actuated": Path("sumo/intersection_act.net.xml")}
MAPS = {"prybuzka_ho10": ("heldout", "x1.0"), "prybuzka_ho12": ("heldout", "x1.2"), "prybuzka_ho15": ("heldout", "x1.5"),
        "prybuzka_s1": ("scenario", "S1"), "prybuzka_s2": ("scenario", "S2"), "prybuzka_s3": ("scenario", "S3"),
        "prybuzka_s4": ("scenario", "S4")}
RUNS = range(1, 6)
GLOBAL_SEED, TRIAL_OFFSET, END = 42, 1000, 1800


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--kit", type=Path, required=True, help="E12 kit folder (route files and metric code)")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()
    sys.path.insert(0, str(args.kit.resolve()))
    import e12    # the kit's metric definitions

    exe = Path(e12.sumo_home()) / "bin" / "sumo.exe"
    version = subprocess.run([str(exe), "--version"], capture_output=True, text=True).stdout.splitlines()[0]
    jobs = []
    for policy, net in NETS.items():
        for map_name, (eval_set, label) in MAPS.items():
            routes = sorted((e12.BENCH / "environments" / map_name / "routes").glob("*.rou.xml"))
            for e, route in enumerate(routes, 1):
                for k in RUNS:
                    seed = GLOBAL_SEED + TRIAL_OFFSET + k + e
                    trip = args.out / ("fixed" if policy == "Fixed plan" else "actuated") / map_name / f"k{k}_e{e}.tripinfo.xml"
                    jobs.append((policy, net, map_name, eval_set, label, e, route, k, seed, trip))

    def run(job):
        policy, net, map_name, eval_set, label, e, route, k, seed, trip = job
        trip.parent.mkdir(parents=True, exist_ok=True)
        if not trip.is_file():
            subprocess.run([str(exe), "-n", str(net), "-r", str(route), "--begin", "0", "--end", str(END),
                            "--time-to-teleport", "-1", "--seed", str(seed), "--tripinfo-output", str(trip),
                            "--tripinfo-output.write-unfinished", "--device.emissions.probability", "1.0",
                            "--no-step-log", "true", "--no-warnings", "true"], check=True, capture_output=True)
        m = e12.episode_metrics(trip, END)
        dem = e12.demand(map_name, route.name)
        m.update(demand=dem, not_inserted=dem - m["entries"], full=int(m["entries"] >= 0.99 * dem),
                 deadlock=int(m["longest_no_arrival_s"] >= 300))
        return {"policy": policy, "train_load": "", "training_run": k, "eval_set": eval_set, "map": map_name,
                "load_or_scenario": label, "episode": e, "route_file": route.name, "sumo_seed": seed} | m

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        rows = list(ex.map(run, jobs))
    out = args.out / "e6_episodes.csv"
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    (args.out / "e6_meta.txt").write_text(f"{version}\n{len(rows)} episodes; seeds 42 + 1000 + k + e; end {END} s; "
                                          f"--time-to-teleport -1\n", encoding="utf-8")
    print(f"{out}: {len(rows)} episodes ({version})")


if __name__ == "__main__":
    main()
