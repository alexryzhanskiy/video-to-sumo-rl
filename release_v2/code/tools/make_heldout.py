"""Generate held-out (or training) demand realizations with SUMO routeSampler (P01 Step 1, Comment 1.5; E12).

For every load and seed: routeSampler -r <candidate> -t <turn counts> -o <out> --seed <s>, default
options otherwise (as for the original sumo/demand*.rou.xml, which used the default seed 42).
Output: <out-dir>/<load>/<kind>_<load>_s<seed>.rou.xml, plus <out-dir>/generation_log.json.

The routeSampler timestamp is removed from the generator comment, so the same seed gives a
byte-identical file.

Example (from the repository root):
  python revision/tools/make_heldout.py --candidate sumo/candidate.rou.xml \
      --load x10=sumo/turn_counts_edges.xml --load x12=sumo/turn_counts_12.xml \
      --load x15=sumo/turn_counts_15.xml --seeds 1001-1010 --out-dir revision/demand/heldout
  E12 training demand: the same with --kind train --seeds 3001-3020 --out-dir revision/demand/train
  E13 (prereg section 3): --kind validation --seeds 4001-4010 --out-dir revision/demand/e13/validation;
      --kind locked --seeds 5001-5010 --out-dir revision/demand/e13/locked_test;
      --kind mix (one --load per call, 6 seeds each, 6001-6030) --out-dir revision/demand/e13/mix
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import demandlib as dl

# Logged purpose per --kind; heldout and train are unchanged from P01 / E12.
PURPOSE = {
    "heldout": "held-out demand realization (Comment 1.5)",
    "train": "training demand realization (E12)",
    "validation": "E13 validation demand realization (prereg section 3)",
    "locked": "E13 locked-test demand realization (prereg section 3; not simulated before step 7.3)",
    "mix": "E13 L4 training mix, proportional load (prereg section 3)",
}


def parse_seeds(text: str) -> list[int]:
    seeds = []
    for part in text.split(","):
        if "-" in part:
            a, b = part.split("-")
            seeds += list(range(int(a), int(b) + 1))
        else:
            seeds.append(int(part))
    return seeds


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--candidate", type=Path, required=True, help="candidate routes (sumo/candidate.rou.xml)")
    ap.add_argument("--load", action="append", required=True, metavar="NAME=COUNTS",
                    help="load name and turn-count file, e.g. x10=sumo/turn_counts_edges.xml (repeatable)")
    ap.add_argument("--seeds", default="1001-1010", help="seeds, e.g. 1001-1010 or 1,2,3 (default 1001-1010)")
    ap.add_argument("--out-dir", type=Path, required=True, help="output folder (revision/demand/heldout)")
    ap.add_argument("--kind", choices=list(PURPOSE), default="heldout", help="file prefix and logged purpose")
    ap.add_argument("--sumo-home", help="SUMO installation (default: $SUMO_HOME or the eclipse-sumo wheel)")
    ap.add_argument("--python", default=sys.executable, help="interpreter for routeSampler (default: this one)")
    args = ap.parse_args()

    sumo_home = dl.find_sumo_home(args.sumo_home)
    version = dl.sumo_version(sumo_home)
    log_path = args.out_dir / "generation_log.json"
    log = dl.load_log(log_path)
    seeds = parse_seeds(args.seeds)

    for spec in args.load:
        name, counts = spec.split("=", 1)
        counts = Path(counts)
        total = dl.counts_total(dl.read_counts(counts))
        for seed in seeds:
            out = args.out_dir / name / f"{args.kind}_{name}_s{seed}.rou.xml"
            cmd = dl.routesampler_cmd(args.python, sumo_home, args.candidate, counts, out, seed)
            dl.run_routesampler(cmd, sumo_home, out)
            log[dl.posix(out)] = {
                "purpose": PURPOSE[args.kind],
                "group": f"{args.kind}_{name}",
                "load_or_scenario": name,
                "seeds": [seed],
                "counts_file": dl.posix(counts),
                "counts_ref": dl.posix(counts),
                "expected_total": total,
                "sumo_version": version,
                "command": dl.display_cmd(cmd, sumo_home),
                "created_utc": dl.utc_now(),
            }
            print(f"{out.as_posix()}  ({len(dl.read_routes(out))} vehicles)")
    dl.save_log(log, log_path)


if __name__ == "__main__":
    main()
