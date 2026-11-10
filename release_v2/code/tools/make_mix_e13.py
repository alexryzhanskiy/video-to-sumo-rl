"""E13 mixed training demand for rung L4 (prereg section 3): new load factors and perturbed S1-S4 files.

The existing tools cannot scale a scenario to a base load: make_scenarios.py always starts from the
x1.0 counts, and no repository tool writes scaled turn counts (sumo/turn_counts_12.xml and
sumo/turn_counts_15.xml are fixed inputs). This script adds only those two steps and reuses the
unchanged functions of make_scenarios.py and demandlib.py for everything else.

Subcommands
  draw       Write the plan of all 60 mix files to mix_params.json, with the perturbed parameters drawn
             from numpy.random.default_rng(6000). Refuses to overwrite an existing file: the parameters
             are fixed before any file is generated.
  counts     Write turn counts for new proportional load factors (e.g. 0.8, 1.4, 1.6). Rule (the one that
             produced sumo/turn_counts_12.xml and sumo/turn_counts_15.xml from sumo/turn_counts_edges.xml):
             every (interval, relation) count is multiplied by the factor and rounded to the nearest
             integer, ties to even (Python round()); no adjustment of the total. The rule is checked
             against both repository files before anything is written.
  perturbed  Generate the perturbed files listed in mix_params.json: x1.0 counts scaled to the file's base
             load with the same rule, then the S-type transform of make_scenarios.py (build_s1, build_s3,
             build_s4; S2: axis split, departure density, one routeSampler run per axis, merge), then
             routeSampler with the file's seed. The proportional files are made with make_heldout.py
             --kind mix (see the README of revision/demand/e13).

Same parameters and seeds give byte-identical files (routeSampler timestamp removed by demandlib).

Examples (from the repository root):
  python revision/tools/make_mix_e13.py draw --test-params revision/demand/scenarios/scenario_params.json \
      --out revision/demand/e13/mix/mix_params.json
  python revision/tools/make_mix_e13.py counts --base-counts sumo/turn_counts_edges.xml \
      --check x12=sumo/turn_counts_12.xml --check x15=sumo/turn_counts_15.xml \
      --factor x08=0.8 --factor x14=1.4 --factor x16=1.6 --out-dir revision/demand/e13/mix/counts
  python revision/tools/make_mix_e13.py perturbed --candidate sumo/candidate.rou.xml \
      --base-counts sumo/turn_counts_edges.xml --params revision/demand/e13/mix/mix_params.json \
      --out-dir revision/demand/e13/mix --work-dir revision/demand/e13/work/mix_S2_parts
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from fractions import Fraction
from pathlib import Path

import numpy as np

import demandlib as dl
import make_scenarios as ms

TYPES = ("S1", "S2", "S3", "S4")
RNG_SEED = 6000
PROPORTIONAL = (("x08", "0.8"), ("x10", "1.0"), ("x12", "1.2"), ("x14", "1.4"), ("x16", "1.6"))
PER_LOAD = 6
FIRST_PROP_SEED = 6001
FIRST_PERT_SEED = 6031
N_PERTURBED = 30
BASE_LOAD = (1.0, 1.4)
BOUNDS = {
    "S1": {"factor": (1.1, 1.4)},
    "S2": {"window": (30.0, 50.0), "offset_shift": (-20.0, 20.0)},
    "S3": {"peak_share": (0.4, 0.6)},
    "S4": {"left_factor": (1.2, 1.6)},
}
TEST_KEYS = {"S1": ("factor",), "S2": ("window", "offset_svobody", "offset_prybuzka"),
             "S3": ("peak_share",), "S4": ("left_factor",)}
BUILD = {"S1": ms.build_s1, "S3": ms.build_s3, "S4": ms.build_s4}


def scale_counts(base: list[dl.Interval], factor) -> list[dl.Interval]:
    """Every (interval, relation) count x factor, rounded half to even (Python round), total not adjusted."""
    f = Fraction(str(factor))
    out = copy.deepcopy(base)
    for iv in out:
        for rel in iv.relations:
            rel[2] = round(f * rel[2])
    return out


def same_counts(a: list[dl.Interval], b: list[dl.Interval]) -> bool:
    key = lambda ivs: [(iv.id, iv.begin, iv.end, [tuple(r) for r in iv.relations]) for iv in ivs]
    return key(a) == key(b)


# --------------------------------------------------------------------------- draw

def draw_type(typ: str, rng: np.random.Generator, test: dict) -> dict:
    p = {k: v for k, v in copy.deepcopy(test[typ]).items() if not k.startswith("_")}
    b = BOUNDS[typ]
    if typ == "S1":
        p["factor"] = round(float(rng.uniform(*b["factor"])), 4)
    elif typ == "S2":
        p["window"] = round(float(rng.uniform(*b["window"])), 1)
        shift = round(float(rng.uniform(*b["offset_shift"])), 1)
        p["offset_shift"] = shift
        p["offset_svobody"] = round((test["S2"]["offset_svobody"] + shift) % p["cycle"], 1)
        p["offset_prybuzka"] = round((test["S2"]["offset_prybuzka"] + shift) % p["cycle"], 1)
    elif typ == "S3":
        p["peak_share"] = round(float(rng.uniform(*b["peak_share"])), 4)
    else:
        p["left_factor"] = round(float(rng.uniform(*b["left_factor"])), 4)
    return p


def equals_test(typ: str, p: dict, test: dict) -> bool:
    return all(float(p[k]) == float(test[typ][k]) for k in TEST_KEYS[typ])


def cmd_draw(args) -> None:
    if args.out.exists():
        sys.exit(f"{args.out} exists: the mix parameters are drawn once, before generation")
    test = json.loads(args.test_params.read_text(encoding="utf-8"))
    rng = np.random.default_rng(args.rng_seed)
    proportional, seed = [], FIRST_PROP_SEED
    for name, f in PROPORTIONAL:
        for _ in range(PER_LOAD):
            proportional.append({"seed": seed, "load": name, "factor": float(f)})
            seed += 1
    perturbed, redraws = [], 0
    for i in range(N_PERTURBED):
        seed = FIRST_PERT_SEED + i
        typ = TYPES[i % len(TYPES)]
        while True:
            load = round(float(rng.uniform(*BASE_LOAD)), 4)
            p = draw_type(typ, rng, test)
            if load != 1.0 and not equals_test(typ, p, test):
                break
            redraws += 1
        perturbed.append({"seed": seed, "type": typ, "name": test[typ]["name"], "base_load": load, "params": p})
    plan = {
        "_comment": "E13 L4 training mix (prereg section 3). Written by revision/tools/make_mix_e13.py draw "
                    "before any mix file was generated. Do not edit; regenerate the files from this plan.",
        "_method": {
            "rng": f"numpy.random.default_rng({args.rng_seed}) (numpy {np.__version__}); for each perturbed file in "
                   "seed order: base_load = uniform(1.0, 1.4), then the type's parameters in the order listed in "
                   "bounds; values rounded (base_load, factors and peak_share to 4 decimals, S2 times to 0.1 s)",
            "assignment": "perturbed seeds 6031-6060 cycle through S1, S2, S3, S4 (seed 6031 + i -> type i mod 4): "
                          "S1 and S2 8 files, S3 and S4 7 files",
            "base_load": "x1.0 counts (sumo/turn_counts_edges.xml) x base_load per (interval, relation), rounded half "
                         "to even, total not adjusted (the rule of sumo/turn_counts_12.xml and turn_counts_15.xml); "
                         "the S-type transform is then applied to these scaled counts",
            "bounds": {"base_load": list(BASE_LOAD), **{t: {k: list(v) for k, v in b.items()} for t, b in BOUNDS.items()}},
            "S2_offsets": "offset_svobody = (0 + offset_shift) mod 120, offset_prybuzka = (60 + offset_shift) mod 120: "
                          "both platoon windows move together, the 60-s separation of the test scenario is kept",
            "fixed_from_test": "all other scenario parameters are those of revision/demand/scenarios/scenario_params.json "
                               "(S1 approaches/movements, S2 cycle/background/bin/prefixes/seed offset, S3 peak window)",
            "exclusion": "a draw is repeated if base_load == 1.0 or the randomised parameters equal the test scenario's "
                         "values (S1 factor 1.3; S2 window 40, offsets 0/60; S3 peak_share 0.5; S4 left_factor 1.4)",
            "redraws": redraws,
            "test_params": dl.posix(args.test_params),
            "test_params_sha256": dl.sha256(args.test_params),
        },
        "proportional": proportional,
        "perturbed": perturbed,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(plan, indent=1) + "\n", encoding="utf-8")
    for it in perturbed:
        keys = [k for k in ("factor", "window", "offset_svobody", "offset_prybuzka", "peak_share", "left_factor")
                if k in it["params"] and k in TEST_KEYS[it["type"]]]
        print(it["seed"], it["type"], it["base_load"], {k: it["params"][k] for k in keys})
    print(f"redraws: {redraws}; wrote {dl.posix(args.out)}")


# --------------------------------------------------------------------------- counts

def cmd_counts(args) -> None:
    base = dl.read_counts(args.base_counts)
    for spec in args.check:
        name, path = spec.split("=", 1)
        factor = Fraction(int(name[1:]), 10)
        if not same_counts(scale_counts(base, factor), dl.read_counts(Path(path))):
            sys.exit(f"rule does not reproduce {path}")
        print(f"rule reproduces {path} (x{float(factor):g}): {dl.counts_total(dl.read_counts(Path(path)))} vehicles")
    for spec in args.factor:
        name, f = spec.split("=", 1)
        c = scale_counts(base, f)
        out = args.out_dir / f"turn_counts_{name}.xml"
        dl.write_counts(c, out, f"x{f}: generated by revision/tools/make_mix_e13.py from {dl.posix(args.base_counts)} "
                                f"(count x {f} per interval and relation, rounded half to even)")
        print(f"{dl.posix(out)}: x{f}, {dl.counts_total(c)} vehicles, intervals {dl.interval_totals(c)}")


# --------------------------------------------------------------------------- perturbed

def cmd_perturbed(args) -> None:
    sumo_home = dl.find_sumo_home(args.sumo_home)
    version = dl.sumo_version(sumo_home)
    plan = json.loads(args.params.read_text(encoding="utf-8"))
    base = dl.read_counts(args.base_counts)
    cdir = args.out_dir / "perturbed" / "counts"
    log_path = args.out_dir / "generation_log.json"
    log = dl.load_log(log_path)
    for item in plan["perturbed"]:
        seed, typ, load, p = item["seed"], item["type"], item["base_load"], item["params"]
        if args.only_seed and seed not in args.only_seed:
            continue
        scaled = scale_counts(base, load)
        lpath = cdir / f"turn_counts_s{seed}_base.xml"
        dl.write_counts(scaled, lpath, f"mix seed {seed}: base load x{load} of {dl.posix(args.base_counts)} "
                                       "(count x load, rounded half to even), before the S-type transform")
        out = args.out_dir / "perturbed" / f"mix_{typ}_s{seed}.rou.xml"
        entry = {"purpose": f"E13 L4 training mix, perturbed {typ} ({item['name']}) on base load x{load}",
                 "group": f"mix_{typ}", "load_or_scenario": typ, "base_load": load, "params": p,
                 "sumo_version": version}
        if typ in BUILD:
            c, rows, info = BUILD[typ](scaled, p)
            cpath = cdir / f"turn_counts_s{seed}_{typ}.xml"
            dl.write_counts(c, cpath, f"mix seed {seed}: {typ} {item['name']} on base load x{load}, "
                                      f"generated by revision/tools/make_mix_e13.py from {dl.posix(args.params)}")
            ms.write_csv(rows, cdir / f"rounding_log_s{seed}_{typ}.csv")
            cmd = dl.routesampler_cmd(args.python, sumo_home, args.candidate, cpath, out, seed)
            dl.run_routesampler(cmd, sumo_home, out)
            entry.update({"seeds": [seed], "counts_file": dl.posix(cpath), "counts_ref": dl.posix(cpath),
                          "expected_total": dl.counts_total(c), "command": dl.display_cmd(cmd, sumo_home),
                          "info": info})
        else:
            axes = [("svobody", dl.SVOBODY, p["offset_svobody"], p["prefix_svobody"], 0),
                    ("prybuzka", dl.PRYBUZKA, p["offset_prybuzka"], p["prefix_prybuzka"], p["prybuzka_seed_offset"])]
            parts, cmds, apaths = [], [], []
            for name, appr, offset, prefix, seed_off in axes:
                apath = cdir / f"turn_counts_s{seed}_S2_{name}.xml"
                dl.write_counts(ms.split_axis(scaled, appr), apath,
                                f"mix seed {seed}: S2 {name} approaches of the base-load counts (counts unchanged)")
                part = args.work_dir / f"mix_S2_{prefix.rstrip('_')}_s{seed + seed_off}.rou.xml"
                dist = ",".join(f"{v:g}" for v in ms.s2_density(p, offset))
                cmd = dl.routesampler_cmd(args.python, sumo_home, args.candidate, apath, part, seed + seed_off,
                                          ["--prefix", prefix, "--depart-distribution", dist])
                dl.run_routesampler(cmd, sumo_home, part)
                parts.append(part)
                apaths.append(dl.posix(apath))
                cmds.append(dl.display_cmd(cmd, sumo_home))
            ms.merge_parts(parts, out, scaled, f"mix seed {seed}, S2 {item['name']} on base load x{load} "
                                               f"(window {p['window']} s, offsets {p['offset_svobody']}/"
                                               f"{p['offset_prybuzka']} s), merge of {len(parts)} routeSampler "
                                               f"runs ({version}), sorted by depart")
            data = out.read_bytes()
            out.write_bytes(data.replace(b"generated by revision/tools/make_scenarios.py:",
                                         b"generated by revision/tools/make_mix_e13.py (make_scenarios.merge_parts):", 1))
            w = p["window"]
            entry.update({"seeds": [seed, seed + p["prybuzka_seed_offset"]], "counts_file": "; ".join(apaths),
                          "counts_ref": dl.posix(lpath), "expected_total": dl.counts_total(scaled),
                          "command": " && ".join(cmds) + " && merge (sort by depart)",
                          "window_share": ms.window_shares(dl.read_routes(out), p),
                          "expected_window_share": w / (w + (p["cycle"] - w) * p["background"])})
        entry["base_counts"] = dl.posix(lpath)
        entry["created_utc"] = dl.utc_now()
        log[dl.posix(out)] = entry
        print(f"{out.as_posix()}  ({len(dl.read_routes(out))} vehicles, expected {entry['expected_total']})")
    dl.save_log(log, log_path)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("draw", help="draw the mix parameters and write mix_params.json")
    d.add_argument("--test-params", type=Path, required=True, help="scenario_params.json of the test scenarios")
    d.add_argument("--out", type=Path, required=True, help="mix_params.json to write (must not exist)")
    d.add_argument("--rng-seed", type=int, default=RNG_SEED, help=f"numpy default_rng seed (default {RNG_SEED})")
    c = sub.add_parser("counts", help="write proportional turn counts for new load factors")
    c.add_argument("--base-counts", type=Path, required=True, help="x1.0 turn counts (sumo/turn_counts_edges.xml)")
    c.add_argument("--check", action="append", default=[], metavar="xNN=FILE",
                   help="existing scaled counts the rule must reproduce, e.g. x12=sumo/turn_counts_12.xml")
    c.add_argument("--factor", action="append", required=True, metavar="NAME=FACTOR", help="e.g. x08=0.8")
    c.add_argument("--out-dir", type=Path, required=True)
    g = sub.add_parser("perturbed", help="generate the perturbed files of mix_params.json")
    g.add_argument("--candidate", type=Path, required=True, help="candidate routes (sumo/candidate.rou.xml)")
    g.add_argument("--base-counts", type=Path, required=True, help="x1.0 turn counts (sumo/turn_counts_edges.xml)")
    g.add_argument("--params", type=Path, required=True, help="mix_params.json")
    g.add_argument("--out-dir", type=Path, required=True, help="mix folder (revision/demand/e13/mix)")
    g.add_argument("--work-dir", type=Path, required=True, help="folder for the S2 per-axis routeSampler outputs")
    g.add_argument("--only-seed", type=int, nargs="*", help="regenerate only these seeds")
    g.add_argument("--sumo-home", help="SUMO installation (default: $SUMO_HOME or the eclipse-sumo wheel)")
    g.add_argument("--python", default=sys.executable, help="interpreter for routeSampler (default: this one)")
    args = ap.parse_args()
    {"draw": cmd_draw, "counts": cmd_counts, "perturbed": cmd_perturbed}[args.cmd](args)


if __name__ == "__main__":
    main()
