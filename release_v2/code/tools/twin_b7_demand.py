"""B7 / E10 perturbed demand: field-of-view (FOV) reassignment of heading-fallback exits (prereg section 9, B7;
kb/07_EXPERIMENT_SPECS.md E10 (iii)). Design approved by the lead on 29 Oct 2026.

The movement files of 28 Oct reproduce sumo/turn_counts_edges.xml exactly (owned approaches: center SVB_N and PRB_E,
zarich SVB_S and PRB_W; t_common in 300-s bins; U-turns excluded); this is checked before anything is written. So the
number of heading-classified exits h is known per interval and relation. Only heading-classified vehicles move, and the
approach total of every interval is kept (the entry is counted reliably; only the exit is uncertain).

  fovpF (through -> turn), F = 10, 20: in each approach and interval, F% of the heading-classified through vehicles move
      to the approach's out-of-view turns, i.e. the turns that also have heading-classified exits, in proportion to their
      heading counts over 0-1500 s (gate counts if an approach has none).
  fovmF (turn -> through): F% of the heading-classified turning vehicles move to through.
  At load L the moved amount of a cell is F x (h / n at x1.0) x (count at load L). Rounding: the approach total is
  rounded half up, then spread over intervals (and over turns) by largest remainder (demandlib.largest_remainder).
  base: the unperturbed counts of the load, generated with the same seeds (paired design).

Every variant and load gets routeSampler files with seeds 7001-7005 (default options, as make_heldout.py; timestamp
removed, byte-reproducible). Each route file is checked: vehicles per relation and planned-departure interval equal its
counts file exactly. Output: <out>/counts/, <out>/<load>/<variant>/b7_<variant>_<load>_s<seed>.rou.xml,
<out>/moved_vehicles.csv, <out>/generation_log.json, <out>/README.md (design, moved vehicles, SHA-256 of every file).

    revision/.venv/Scripts/python.exe revision/tools/twin_b7_demand.py fov --candidate sumo/candidate.rou.xml \
        --load x10=sumo/turn_counts_edges.xml --load x12=sumo/turn_counts_12.xml --seeds 7001-7005 \
        --out-dir revision/twin/B7/demand

Counting-error variants (`ce`), from A1's blind hand counts (perception_metrics.py: counting_cells.csv). Since
1 Nov (decision C-3) these are two 5-min clips, one per camera, so every relation has one 5-min cell; since 3 Nov
(decision C-13) center_i300 and zarich_i300 (the x1.0 interval 300); owned approaches; U-turns are not in the demand and are left out. The pipeline column must equal
the x1.0 counts of the clip's interval (checked), and every approach must have been watched in full
(counting_clips.csv).
  ce_bias: each relation (approach x movement) is scaled by its ratio rho = sum manual / sum pipeline over the clips;
      a relation with fewer than --min-pipeline (30) pipeline vehicles takes its approach's ratio. Rounding as above:
      the relation total is rounded half up, then spread over intervals by largest remainder. Seeds 7001-7005.
      ce_bias is written before the dispersion is estimated.
  ce_rand: --draws (10) plausible true demands given the measured error. Model per 5-min cell: manual = rho x
      pipeline + e, Var(e) = phi x pipeline (rho = sum manual / sum pipeline is then the weighted least-squares
      estimate). phi = Pearson chi-square / (cells - approaches), computed around the approach ratios: with one cell per
      relation a relation's own ratio fits its cell exactly, so it carries no information on phi (around the approach
      ratios phi also absorbs movement-specific bias, which is conservative). se of every relation = sqrt(phi /
      max(p, 1)), p = its own pipeline count. Draw d: relation factor max(0, rho + se x z), where z is the relation's
      own normal for a relation-level ratio and the approach's normal for the relations that take the approach ratio
      (they share one estimate); then per interval and relation count' = factor x count + sqrt(phi x count) x u,
      rounded half up, floored at 0. The normals come from numpy.random.default_rng(7000) in this order: relation z
      (draws x 12), cell u (draws x 5 x 12), approach z (draws x 4); they are drawn before the hand counts are read and
      written to ce_rand_draws.csv, and the same values serve both loads. Draw d uses seed 7100 + d (7101-7110). If phi
      cannot be estimated (df <= 0), ce_bias is still written and the command stops with a message for ce_rand.
  Approach totals change in both (the counting error includes the entries).
Measured heading-exit confusion (`fov_meas`), from the blind movement checks of A1's tracking review
(perception_metrics.py: heading_exit_checks.csv; "cannot tell" left out; "U-turn" answers stay in the denominator and
are not moved, since U-turns are not in the demand): for each approach and pipeline movement with at least
--min-checks (5) answered heading checks, rate(src -> dst) = share of the reviewer's answers dst != src.
The moved amount is rate x (heading share at x1.0) x (count at the load), rounded as fovp (rows with fewer checks stay
unchanged). Gate exits are not changed; their accuracy is reported as the control. Seeds 7001-7005.

    revision/.venv/Scripts/python.exe revision/tools/twin_b7_demand.py ce --candidate sumo/candidate.rou.xml \
        --cells revision/analysis/perception/counting_cells.csv --load x10=sumo/turn_counts_edges.xml \
        --load x12=sumo/turn_counts_12.xml --out-dir revision/twin/B7/demand
    revision/.venv/Scripts/python.exe revision/tools/twin_b7_demand.py fov_meas --candidate sumo/candidate.rou.xml \
        --checks revision/analysis/perception/heading_exit_checks.csv --load x10=sumo/turn_counts_edges.xml \
        --load x12=sumo/turn_counts_12.xml --out-dir revision/twin/B7/demand
"""
from __future__ import annotations

import argparse
import copy
import csv
import json
import math
import re
import sys
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction
from pathlib import Path

import numpy as np

import demandlib as dl

ROOT = Path(__file__).resolve().parents[2]
MOVDIR = ROOT / "revision" / "incoming" / "2026-10-28" / "answers" / "step_1.2_1.3" / "manual_counting"
OWNED = {"center": ("SVB_N", "PRB_E"), "zarich": ("SVB_S", "PRB_W")}
EDGE = {"SVB_N": "nN", "SVB_S": "nS", "PRB_E": "nE", "PRB_W": "nW"}
NAME = {f"{v}_nC": k for k, v in EDGE.items()}
END = 1500.0
VARIANTS = {"fovp10": (+1, Fraction(10, 100)), "fovp20": (+1, Fraction(20, 100)),
            "fovm10": (-1, Fraction(10, 100)), "fovm20": (-1, Fraction(20, 100))}
MOVS = ("left", "through", "right")
CODE = {"L": "left", "T": "through", "R": "right"}


def half_up(x: Fraction) -> int:
    return math.floor(x + Fraction(1, 2))


def relation(ap: str, mv: str):
    fr = f"{EDGE[ap]}_nC"
    return fr, next(to for (f, to), m in dl.MOVEMENT.items() if f == fr and m == mv)


def seed_range(s: str) -> list[int]:
    lo, hi = (int(x) for x in s.split("-"))
    return list(range(lo, hi + 1))


def write_rows(path: Path, rows: list[dict]):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def movements(folder: Path):
    """(interval begin, from, to) -> [n, h] from the movement files (owned approaches, no U-turns)."""
    cell = {}
    for cam, own in OWNED.items():
        for r in csv.DictReader(open(folder / f"movements_{cam}.csv", encoding="utf-8")):
            t = float(r["t_common"])
            if r["entry"] not in own or r["movement_en"] == "U-turn" or not 0 <= t < END:
                continue
            k = (f"{300 * int(t // 300)}", f"{EDGE[r['entry']]}_nC", f"nC_{EDGE[r['exit']]}")
            c = cell.setdefault(k, [0, 0])
            c[0] += 1
            c[1] += r["method"] == "heading"
    return cell


def perturb(counts: list, cell: dict, sign: int, f: Fraction):
    """Return the perturbed intervals and the list of moves (begin, from, to_src, to_dst, n)."""
    tab = dl.counts_table(counts)
    begins = [iv.begin for iv in counts]
    moves = []
    for a in dl.APPROACHES:
        rel = {m: to for (fr, to), m in dl.MOVEMENT.items() if fr == a}
        thr, turns = rel["through"], [rel["left"], rel["right"]]
        h = lambda b, to: cell.get((b, a, to), [0, 0])[1]                        # noqa: E731
        n = lambda b, to: cell.get((b, a, to), [0, 0])[0]                        # noqa: E731
        share = lambda b, to: Fraction(h(b, to), n(b, to)) if n(b, to) else Fraction(0)   # noqa: E731
        if sign > 0:
            w = {to: sum(h(b, to) for b in begins) for to in turns}
            if not sum(w.values()):
                w = {to: sum(n(b, to) - h(b, to) for b in begins) for to in turns}
            x = [f * share(b, thr) * tab[(b, a, thr)] for b in begins]
            m_i, _ = dl.largest_remainder(x, half_up(sum(x, Fraction(0))))
            for b, m in zip(begins, m_i):
                assert m <= tab[(b, a, thr)]
                if m:
                    W = sum(w.values())
                    split, _ = dl.largest_remainder([Fraction(m * w[to], W) for to in turns], m)
                    moves += [(b, a, thr, to, k) for to, k in zip(turns, split) if k]
        else:
            keys = [(b, to) for b in begins for to in turns]
            x = [f * share(b, to) * tab[(b, a, to)] for b, to in keys]
            m_k, _ = dl.largest_remainder(x, half_up(sum(x, Fraction(0))))
            moves += [(b, a, to, thr, k) for (b, to), k in zip(keys, m_k) if k]
    return apply_moves(counts, moves), moves


def apply_moves(counts: list, moves: list):
    out = copy.deepcopy(counts)
    for iv in out:
        for r in iv.relations:
            r[2] -= sum(k for b, fr, src, _, k in moves if (b, fr, src) == (iv.begin, r[0], r[1]))
            r[2] += sum(k for b, fr, _, dst, k in moves if (b, fr, dst) == (iv.begin, r[0], r[1]))
            assert r[2] >= 0, (iv.begin, r)
    return out


def reassign(counts: list, cell: dict, rates: dict):
    """rates: (from, src to, dst to) -> Fraction. Per source relation, the moved amount of an interval is
    (sum of its rates) x (heading share at x1.0) x (count at the load); the approach total is rounded half up and
    spread over intervals by largest remainder, then over the destinations in proportion to their rates."""
    tab = dl.counts_table(counts)
    begins = [iv.begin for iv in counts]
    moves = []
    for a, src in dict.fromkeys((fr, s) for fr, s, _ in rates):
        dst = {d: r for (fr, s, d), r in rates.items() if (fr, s) == (a, src)}
        R = sum(dst.values())

        def share(b):
            n, h = cell.get((b, a, src), [0, 0])
            return Fraction(h, n) if n else Fraction(0)

        x = [R * share(b) * tab[(b, a, src)] for b in begins]
        m_i, _ = dl.largest_remainder(x, half_up(sum(x, Fraction(0))))
        for b, m in zip(begins, m_i):
            assert m <= tab[(b, a, src)]
            if m:
                split, _ = dl.largest_remainder([m * r / R for r in dst.values()], m)
                moves += [(b, a, src, d, k) for d, k in zip(dst, split) if k]
    return apply_moves(counts, moves), moves


def scale(counts: list, ratio: dict):
    """ratio: (from, to) -> Fraction. Relation total = ratio x count summed over intervals, rounded half up, spread over
    intervals by largest remainder."""
    tab = dl.counts_table(counts)
    begins = [iv.begin for iv in counts]
    new = {}
    for (fr, to), rho in ratio.items():
        x = [rho * tab.get((b, fr, to), 0) for b in begins]
        new.update({(b, fr, to): c for b, c in zip(begins, dl.largest_remainder(x, half_up(sum(x, Fraction(0))))[0])})
    out = copy.deepcopy(counts)
    for iv in out:
        for r in iv.relations:
            r[2] = new.pop((iv.begin, r[0], r[1]), r[2])
    assert not any(new.values()), new
    return out


def scale_random(counts: list, rho: dict, se: dict, phi: float, z: dict, u: dict):
    """count' = (rho + se x z) x count + sqrt(phi x count) x u per interval and relation, rounded half up, floored at 0."""
    out = copy.deepcopy(counts)
    for iv in out:
        for r in iv.relations:
            k, c = (r[0], r[1]), r[2]
            if k in rho:
                f = max(0.0, float(rho[k]) + se[k] * z[k])
                r[2] = max(0, math.floor(f * c + math.sqrt(phi * c) * u[(iv.begin, *k)] + 0.5))
    return out


def depart_table(route: Path, counts: list):
    ivs = [(float(iv.begin), float(iv.end), iv.begin) for iv in counts]
    n = {}
    for v in dl.read_routes(route):
        t = float(v.depart_str if hasattr(v, "depart_str") else v.depart)
        b = next((lab for lo, hi, lab in ivs if lo <= t < hi), None)
        if b is not None:
            fr, to = v.edges.split()
            n[(b, fr, to)] = n.get((b, fr, to), 0) + 1
    return n


def checked_movements(a):
    cell = movements(a.movements)
    base10 = dl.counts_table(dl.read_counts(a.check_counts))
    diff = {k: (v, cell.get(k, [0, 0])[0]) for k, v in base10.items() if cell.get(k, [0, 0])[0] != v}
    if diff or sum(c[0] for c in cell.values()) != sum(base10.values()):
        sys.exit(f"movement files do not reproduce {a.check_counts}: {list(diff.items())[:5]}")
    return cell


def loads(a):
    return [(load, Path(path)) for load, path in (spec.split("=", 1) for spec in a.load)]


def generate(a, items):
    """items: (load, variant, seed, counts path, counts, counts source, purpose). Runs routeSampler, checks every file
    (vehicles per relation and planned-departure interval equal its counts) and logs it. Returns the checks and the
    SUMO version."""
    sumo_home = dl.find_sumo_home(a.sumo_home)
    version = dl.sumo_version(sumo_home)
    log_path = a.out_dir / "generation_log.json"
    log = dl.load_log(log_path)
    outs = [a.out_dir / load / var / f"b7_{var}_{load}_s{s}.rou.xml" for load, var, s, *_ in items]
    cmds = [dl.routesampler_cmd(a.python, sumo_home, a.candidate, it[3], out, it[2]) for it, out in zip(items, outs)]
    with ThreadPoolExecutor(a.jobs) as ex:
        list(ex.map(lambda job: dl.run_routesampler(job[0], sumo_home, job[1]), zip(cmds, outs)))
    checks = []
    for (load, var, s, cpath, counts, ref, purpose), out, cmd in zip(items, outs, cmds):
        want, got = dl.counts_table(counts), depart_table(out, counts)
        bad = sum(got.get(k, 0) != v for k, v in want.items()) + sum(k not in want for k in got)
        checks.append(dict(file=dl.posix(out), vehicles=len(dl.read_routes(out)), expected=dl.counts_total(counts),
                           cells_differing=bad))
        log[dl.posix(out)] = dict(purpose=purpose, group=f"b7_{var}_{load}", load_or_scenario=f"{load}_{var}", seeds=[s],
                                  counts_file=dl.posix(cpath), counts_ref=dl.posix(ref), expected_total=dl.counts_total(counts),
                                  sumo_version=version, command=dl.display_cmd(cmd, sumo_home), created_utc=dl.utc_now())
    dl.save_log(log, log_path)
    return checks, version


def finish(checks):
    nbad = sum(c["cells_differing"] > 0 or c["vehicles"] != c["expected"] for c in checks)
    print(f"{len(checks)} route files, {nbad} failing the count check")
    if nbad:
        sys.exit(1)


def sha_table(a, files):
    return ["## Files and SHA-256", "", "| File | SHA-256 |", "|---|---|",
            *(f"| `{dl.posix(p.relative_to(a.out_dir))}` | `{dl.sha256(p)}` |" for p in sorted(files))]


def cmd_fov(a):
    cell = checked_movements(a)
    seeds = seed_range(a.seeds)
    items, move_rows, counts_of = [], [], {}
    for load, path in loads(a):
        counts = dl.read_counts(path)
        counts_of[(load, "base")] = (path, counts)
        for var, (sign, f) in VARIANTS.items():
            pert, moves = perturb(counts, cell, sign, f)
            cpath = a.out_dir / "counts" / f"turn_counts_{var}_{load}.xml"
            dl.write_counts(pert, cpath, comment=f"B7 {var} at {load}: {'through -> out-of-view turn' if sign > 0 else 'turn -> through'}, "
                                                 f"{int(f * 100)}% of heading-classified exits; source {dl.posix(path)}")
            counts_of[(load, var)] = (cpath, pert)
            assert dl.counts_total(pert) == dl.counts_total(counts)
            move_rows += [dict(load=load, variant=var, interval_begin=b, approach=NAME[fr], from_movement=dl.MOVEMENT[(fr, src)],
                               to_movement=dl.MOVEMENT[(fr, dst)], moved=k) for b, fr, src, dst, k in moves]
        for var in ["base", *VARIANTS]:
            cpath, cnt = counts_of[(load, var)]
            items += [(load, var, s, cpath, cnt, path, f"B7/E10 perturbed demand ({var}; prereg section 9)") for s in seeds]
    checks, version = generate(a, items)
    write_rows(a.out_dir / "moved_vehicles.csv", move_rows)
    write_rows(a.out_dir / "route_checks.csv", checks)
    write_readme(a, cell, move_rows, checks, version, seeds)
    finish(checks)


def ce_ratios(a, base10: dict):
    """Ratios of the hand-count cells after the coverage and pipeline checks (see the docstring)."""
    rows = [r for r in csv.DictReader(open(a.cells, encoding="utf-8")) if r["movement"] in CODE]
    clips_csv = a.cells.parent / "counting_clips.csv"
    cover = [r for r in csv.DictReader(open(clips_csv, encoding="utf-8"))] if clips_csv.exists() else []
    short = [(r["clip"], k, r[k]) for r in cover for k in r if k.startswith("watched_") and r[k] and float(r[k]) < 99.0]
    if short and not a.allow_partial:
        sys.exit(f"approaches not watched in full: {short}")
    bad = []
    for r in rows:
        b = re.search(r"_i(\d+)$", r["clip"]).group(1)
        if base10.get((b, *relation(r["approach"], CODE[r["movement"]])), 0) != int(r["pipeline"]):
            bad.append((r["clip"], r["approach"], r["movement"], r["pipeline"]))
    if bad:
        sys.exit(f"pipeline counts differ from {a.check_counts}: {bad[:5]}")
    SM, SP, AM, AP = {}, {}, {}, {}
    for r in rows:
        k, ap = (r["approach"], CODE[r["movement"]]), r["approach"]
        SM[k], SP[k] = SM.get(k, 0) + int(r["manual"]), SP.get(k, 0) + int(r["pipeline"])
        AM[ap], AP[ap] = AM.get(ap, 0) + int(r["manual"]), AP.get(ap, 0) + int(r["pipeline"])
    rel = {}
    for ap in EDGE:
        for mv in MOVS:
            k = (ap, mv)
            if SP.get(k, 0) >= a.min_pipeline:
                rel[k] = dict(rho=Fraction(SM[k], SP[k]), source="relation", basis=SP[k])
            elif AP.get(ap, 0):
                rel[k] = dict(rho=Fraction(AM[ap], AP[ap]), source="approach", basis=AP[ap])
            else:
                rel[k] = dict(rho=Fraction(1), source="none (no pipeline vehicles)", basis=0)
    return dict(rel=rel, rows=rows, manual=SM, pipeline=SP, approach_manual=AM, approach_pipeline=AP, coverage=cover,
                clips=sorted({r["clip"] for r in rows}))


def ce_dispersion(P: dict) -> dict:
    """phi = Pearson chi-square / df of the 5-min cells around the approach ratios (manual = rho_ap x pipeline + e,
    Var(e) = phi x pipeline; df = cells with pipeline vehicles - approaches); None if df <= 0. With one cell per
    relation (C-3) a relation's own ratio fits its cell exactly, so the relation ratios carry no information on phi."""
    x2, used, excluded = 0.0, 0, 0
    for r in P["rows"]:
        ap, m, p = r["approach"], int(r["manual"]), int(r["pipeline"])
        if p:
            x2 += float((m - Fraction(P["approach_manual"][ap], P["approach_pipeline"][ap]) * p) ** 2 / p)
            used += 1
        elif m:
            excluded += 1
    estimates = len({r["approach"] for r in P["rows"] if int(r["pipeline"])})
    df = used - estimates
    return dict(phi=x2 / df if df > 0 else None, x2=x2, df=df, cells_used=used, estimates=estimates, cells_excluded=excluded)


def cmd_ce(a):
    base_counts = dl.read_counts(a.check_counts)
    base10, begins = dl.counts_table(base_counts), [iv.begin for iv in base_counts]
    order = [(ap, mv) for ap in EDGE for mv in MOVS]
    aps = list(EDGE)
    # the random draws come first and do not depend on the data (approach z last, so the relation z and cell u values
    # are those of the 29 Oct design)
    rng = np.random.default_rng(a.rng_seed)
    Z = rng.standard_normal((a.draws, len(order)))
    U = rng.standard_normal((a.draws, len(begins), len(order)))
    ZA = rng.standard_normal((a.draws, len(aps)))
    rseeds = seed_range(a.rand_seeds)
    if len(rseeds) != a.draws:
        sys.exit(f"--rand-seeds gives {len(rseeds)} seeds for {a.draws} draws")
    a.out_dir.mkdir(parents=True, exist_ok=True)
    write_rows(a.out_dir / "ce_rand_draws.csv",
               [dict(draw=d + 1, seed=rseeds[d], level="relation", interval_begin="", approach=ap, movement=mv, z=round(float(Z[d, j]), 6))
                for d in range(a.draws) for j, (ap, mv) in enumerate(order)] +
               [dict(draw=d + 1, seed=rseeds[d], level="cell", interval_begin=b, approach=ap, movement=mv, z=round(float(U[d, i, j]), 6))
                for d in range(a.draws) for i, b in enumerate(begins) for j, (ap, mv) in enumerate(order)] +
               [dict(draw=d + 1, seed=rseeds[d], level="approach", interval_begin="", approach=ap, movement="", z=round(float(ZA[d, i]), 6))
                for d in range(a.draws) for i, ap in enumerate(aps)])
    P = ce_ratios(a, base10)
    rho = {relation(*k): v["rho"] for k, v in P["rel"].items()}
    seeds = seed_range(a.seeds)
    items, totals, counts_of = [], [], []
    for load, path in loads(a):
        counts = dl.read_counts(path)
        counts_of.append((load, path, counts))
        bias = scale(counts, rho)
        cpath = a.out_dir / "counts" / f"turn_counts_ce_bias_{load}.xml"
        dl.write_counts(bias, cpath, comment=f"B7 ce_bias at {load}: relations scaled by the hand-count ratio "
                                             f"(min pipeline {a.min_pipeline}); source {dl.posix(path)}")
        items += [(load, "ce_bias", s, cpath, bias, path, "B7 counting-error demand (ce_bias; prereg section 9)") for s in seeds]
        totals.append(dict(load=load, variant="base", draw="", seed="", vehicles=dl.counts_total(counts)))
        totals.append(dict(load=load, variant="ce_bias", draw="", seed="", vehicles=dl.counts_total(bias)))
    # ce_rand: dispersion around the approach ratios; se of every relation from its own pipeline count
    D = ce_dispersion(P)
    phi = D["phi"]
    sek = {k: (math.sqrt(phi / max(P["pipeline"].get(k, 0), 1)) if phi is not None and v["basis"] else 0.0)
           for k, v in P["rel"].items()}
    se = {relation(*k): v for k, v in sek.items()}
    if phi is not None:
        for load, path, counts in counts_of:
            for d in range(a.draws):
                z = {relation(*k): float(Z[d, j] if P["rel"][k]["source"] == "relation" else ZA[d, aps.index(k[0])])
                     for j, k in enumerate(order)}
                u = {(b, *relation(*k)): float(U[d, i, j]) for i, b in enumerate(begins) for j, k in enumerate(order)}
                rnd = scale_random(counts, rho, se, phi, z, u)
                cpath = a.out_dir / "counts" / f"turn_counts_ce_rand_d{d + 1:02d}_{load}.xml"
                dl.write_counts(rnd, cpath, comment=f"B7 ce_rand draw {d + 1} at {load} (default_rng({a.rng_seed}), "
                                                    f"ce_rand_draws.csv); source {dl.posix(path)}")
                items.append((load, "ce_rand", rseeds[d], cpath, rnd, path, f"B7 counting-error demand (ce_rand draw {d + 1}; prereg section 9)"))
                totals.append(dict(load=load, variant="ce_rand", draw=d + 1, seed=rseeds[d], vehicles=dl.counts_total(rnd)))
    params = dict(source_cells=dl.posix(a.cells), source_sha256=dl.sha256(a.cells), clips=P["clips"], min_pipeline=a.min_pipeline,
                  rng_seed=a.rng_seed, draws=a.draws, rand_seeds=rseeds, ce_rand_generated=phi is not None,
                  dispersion=dict(model="Pearson chi-square / df around the approach ratios", phi=round(phi, 6) if phi is not None else None,
                                  pearson_x2=round(D["x2"], 6), cells_used=D["cells_used"], estimates=D["estimates"], df=D["df"],
                                  cells_excluded_pipeline_zero=D["cells_excluded"]),
                  relations=[dict(approach=ap, movement=mv, manual=P["manual"].get((ap, mv), 0), pipeline=P["pipeline"].get((ap, mv), 0),
                                  ratio=round(float(v["rho"]), 6), ratio_exact=str(v["rho"]), ratio_source=v["source"],
                                  ratio_basis_pipeline=v["basis"], se=round(sek[(ap, mv)], 6) if phi is not None else None,
                                  se_basis_pipeline=max(P["pipeline"].get((ap, mv), 0), 1) if v["basis"] else 0,
                                  z_level="relation" if v["source"] == "relation" else "approach") for (ap, mv), v in P["rel"].items()],
                  coverage=P["coverage"])
    (a.out_dir / "ce_params.json").write_text(json.dumps(params, indent=1) + "\n", encoding="utf-8")
    checks, version = generate(a, items)
    write_rows(a.out_dir / "ce_totals.csv", totals)
    write_rows(a.out_dir / "ce_route_checks.csv", checks)
    write_readme_ce(a, params, totals, checks, version, seeds, rseeds)
    finish(checks)
    if phi is None:
        sys.exit(f"ce_bias written; ce_rand NOT generated: the dispersion cannot be estimated ({D['cells_used']} cells with "
                 f"pipeline vehicles, {D['estimates']} approach ratios, df {D['df']})")


def write_readme_ce(a, params, totals, checks, version, seeds, rseeds):
    dp = params["dispersion"]
    L = ["# B7 counting-error demand (ce_bias, ce_rand)", "",
         f"Generated by `revision/tools/twin_b7_demand.py ce` from `{params['source_cells']}` (SHA-256 `{params['source_sha256']}`; "
         f"clips {', '.join(params['clips'])}). The rule is in the script's docstring. SUMO "
         f"{version} routeSampler, default options; ce_bias seeds {seeds[0]}–{seeds[-1]} (paired with `base`), ce_rand draw d with "
         f"seed {rseeds[0] - 1} + d ({rseeds[0]}–{rseeds[-1]}). The draws were made with `numpy.random.default_rng({params['rng_seed']})` "
         "before the counts were read (`ce_rand_draws.csv`).", "",
         "## Ratios (hand count / pipeline, U-turns excluded)", "",
         f"A relation with fewer than {params['min_pipeline']} pipeline vehicles takes its approach's ratio. SE = √(φ / max(p, 1)) "
         "with p the relation's own pipeline count; the relations that take the approach ratio share the approach's z.", "",
         "| Approach | Movement | Hand | Pipeline | Ratio | Source | SE | z |", "|---|---|---|---|---|---|---|---|"]
    L += [f"| {r['approach']} | {r['movement']} | {r['manual']} | {r['pipeline']} | {r['ratio']:.3f} | {r['ratio_source']} | "
          f"{'–' if r['se'] is None else format(r['se'], '.3f')} | {r['z_level']} |" for r in params["relations"]]
    L += ["", (f"Dispersion φ = {dp['phi']:.3f} (Pearson χ² {dp['pearson_x2']:.2f} around the approach ratios over {dp['cells_used']} "
               f"cells, {dp['estimates']} approach ratios, df {dp['df']})" if dp["phi"] is not None else
               f"**ce_rand not generated:** φ cannot be estimated ({dp['cells_used']} cells, {dp['estimates']} approach ratios, "
               f"df {dp['df']})") + f"; {dp['cells_excluded_pipeline_zero']} cells with hand counts but no pipeline "
              "vehicles are left out of φ (they are in the ratios).", "",
          "## Vehicles over 0–1500 s", "", "| Load | base | ce_bias | ce_rand, mean (min–max) over draws |", "|---|---|---|---|"]
    for load in dict.fromkeys(t["load"] for t in totals):
        t = {(x["variant"]): x["vehicles"] for x in totals if x["load"] == load and x["variant"] != "ce_rand"}
        r = [x["vehicles"] for x in totals if x["load"] == load and x["variant"] == "ce_rand"]
        L.append(f"| {load} | {t['base']} | {t['ce_bias']} | " + (f"{sum(r) / len(r):.1f} ({min(r)}–{max(r)}) |" if r else "not generated |"))
    nbad = sum(c["cells_differing"] > 0 or c["vehicles"] != c["expected"] for c in checks)
    L += ["", "## Check", "", f"{len(checks)} route files; {len(checks) - nbad} reproduce their counts file exactly (`ce_route_checks.csv`).", ""]
    L += sha_table(a, [*a.out_dir.glob("counts/turn_counts_ce_*.xml"), *a.out_dir.glob("x*/ce_*/*.rou.xml"),
                       *(a.out_dir / f for f in ("ce_params.json", "ce_rand_draws.csv", "ce_totals.csv", "ce_route_checks.csv"))])
    (a.out_dir / "README_ce.md").write_text("\n".join(L) + "\n", encoding="utf-8")


def cmd_fov_meas(a):
    cell = checked_movements(a)
    checks_in = [r for r in csv.DictReader(open(a.checks, encoding="utf-8"))]
    tally = {}
    for r in checks_in:
        if r["reviewer"] != "cannot tell":
            t = tally.setdefault((r["method"], r["approach"], r["pipeline"]), {})
            t[r["reviewer"]] = t.get(r["reviewer"], 0) + 1
    rates, rate_rows = {}, []
    for meth in ("heading", "gate"):
        for ap in EDGE:
            for src in MOVS:
                t = tally.get((meth, ap, src), {})
                n = sum(t.values())
                if not n:
                    continue
                applied = meth == "heading" and n >= a.min_checks
                for dst in MOVS:
                    if applied and dst != src and t.get(dst, 0):
                        rates[(relation(ap, src)[0], relation(ap, src)[1], relation(ap, dst)[1])] = Fraction(t[dst], n)
                rate_rows.append(dict(method=meth, approach=ap, pipeline=src, answered=n, correct=t.get(src, 0),
                                      **{f"reviewer_{m}": t.get(m, 0) for m in (*MOVS, "U-turn")},
                                      cannot_tell=sum(r["reviewer"] == "cannot tell" for r in checks_in
                                                      if (r["method"], r["approach"], r["pipeline"]) == (meth, ap, src)),
                                      applied=applied))
    if not rate_rows:
        sys.exit(f"no answered checks in {a.checks}")
    seeds = seed_range(a.seeds)
    items, move_rows = [], []
    for load, path in loads(a):
        counts = dl.read_counts(path)
        pert, moves = reassign(counts, cell, rates)
        assert dl.counts_total(pert) == dl.counts_total(counts)
        cpath = a.out_dir / "counts" / f"turn_counts_fov_meas_{load}.xml"
        dl.write_counts(pert, cpath, comment=f"B7 fov_meas at {load}: heading-exit confusion from the tracking review "
                                             f"(min {a.min_checks} checks); source {dl.posix(path)}")
        move_rows += [dict(load=load, variant="fov_meas", interval_begin=b, approach=NAME[fr], from_movement=dl.MOVEMENT[(fr, src)],
                           to_movement=dl.MOVEMENT[(fr, dst)], moved=k) for b, fr, src, dst, k in moves]
        items += [(load, "fov_meas", s, cpath, pert, path, "B7/E10 measured heading-exit confusion (fov_meas; prereg section 9)")
                  for s in seeds]
    a.out_dir.mkdir(parents=True, exist_ok=True)
    write_rows(a.out_dir / "fov_meas_rates.csv", rate_rows)
    checks, version = generate(a, items)
    if move_rows:
        write_rows(a.out_dir / "fov_meas_moved_vehicles.csv", move_rows)
    write_rows(a.out_dir / "fov_meas_route_checks.csv", checks)
    write_readme_fov_meas(a, rate_rows, move_rows, checks, version, seeds)
    finish(checks)


def write_readme_fov_meas(a, rate_rows, move_rows, checks, version, seeds):
    L = ["# B7 / E10 demand with the measured heading-exit confusion (fov_meas)", "",
         f"Generated by `revision/tools/twin_b7_demand.py fov_meas` from `{dl.posix(a.checks)}` (SHA-256 `{dl.sha256(a.checks)}`). "
         f"The rule is in the script's docstring: only heading-classified exits move, approach totals per 5-min interval are kept, "
         f"rows with at least {a.min_checks} answered heading checks are applied. SUMO {version} routeSampler, default options, "
         f"seeds {seeds[0]}–{seeds[-1]} (paired with `base`).", "",
         "## Reviewer answers (blind; \"cannot tell\" left out of the rates)", "",
         "\"U-turn\" answers stay in the denominator (Answered) and are not moved: U-turns are not in the demand, so such a "
         "vehicle keeps the pipeline's movement.", "",
         "| Exit method | Approach | Pipeline movement | Answered | Correct | Reviewer left / through / right / U-turn | Cannot tell | Applied |",
         "|---|---|---|---|---|---|---|---|"]
    L += [f"| {r['method']} | {r['approach']} | {r['pipeline']} | {r['answered']} | {r['correct']} | "
          f"{r['reviewer_left']} / {r['reviewer_through']} / {r['reviewer_right']} / {r['reviewer_U-turn']} | {r['cannot_tell']} | "
          f"{'yes' if r['applied'] else 'no'} |" for r in rate_rows]
    L += ["", "## Moved vehicles over 0–1500 s", "", "| Load | Approach | Moves | Vehicles |", "|---|---|---|---|"]
    agg = {}
    for r in move_rows:
        k = (r["load"], r["approach"], f"{r['from_movement']} → {r['to_movement']}")
        agg[k] = agg.get(k, 0) + r["moved"]
    L += [f"| {load} | {ap} | {mv} | {k} |" for (load, ap, mv), k in sorted(agg.items())] or ["| – | – | none | 0 |"]
    nbad = sum(c["cells_differing"] > 0 or c["vehicles"] != c["expected"] for c in checks)
    L += ["", "## Check", "", f"{len(checks)} route files; {len(checks) - nbad} reproduce their counts file exactly "
          "(`fov_meas_route_checks.csv`).", ""]
    L += sha_table(a, [*a.out_dir.glob("counts/turn_counts_fov_meas_*.xml"), *a.out_dir.glob("x*/fov_meas/*.rou.xml"),
                       *(p for p in (a.out_dir / f for f in ("fov_meas_rates.csv", "fov_meas_moved_vehicles.csv",
                                                             "fov_meas_route_checks.csv")) if p.exists())])
    (a.out_dir / "README_fov_meas.md").write_text("\n".join(L) + "\n", encoding="utf-8")


def write_readme(a, cell, move_rows, checks, version, seeds):
    hz = {}
    for (b, fr, to), (n, h) in cell.items():
        hz.setdefault((NAME[fr], dl.MOVEMENT[(fr, to)]), [0, 0])
        hz[(NAME[fr], dl.MOVEMENT[(fr, to)])][0] += h
        hz[(NAME[fr], dl.MOVEMENT[(fr, to)])][1] += n - h
    L = ["# B7 / E10 perturbed demand (field-of-view reassignment)", "",
         "Generated by `revision/tools/twin_b7_demand.py` (design approved by the lead on 29 Oct 2026; prereg section 9, B7; "
         "kb/07_EXPERIMENT_SPECS.md E10 (iii)). The rule is in the script's docstring; in short: only heading-classified exits move, "
         "approach totals per 5-min interval are kept, the moved amount of a cell is F × (heading share at ×1.0) × (count at the load), "
         "and the approach total is rounded half up and spread by largest remainder.", "",
         f"SUMO {version} routeSampler, default options, seeds {seeds[0]}–{seeds[-1]} for every load and variant (paired with `base`). "
         "These seeds are disjoint from every earlier set (1001–1010, 2001–2005, 3001–3020, 4001–4010, 4101–4102, 5001–5010, 5101–5105, "
         "6001–6060 and the 5xxxx second seeds). No locked-test file is read or written.", "",
         "## Heading-classified and gate-classified exits (×1.0, 0–1500 s, U-turns excluded)", "",
         "| Approach | Left (heading / gate) | Through (heading / gate) | Right (heading / gate) |", "|---|---|---|---|"]
    for ap in EDGE:
        L.append(f"| {ap} | " + " | ".join(f"{hz.get((ap, m), [0, 0])[0]} / {hz.get((ap, m), [0, 0])[1]}" for m in ("left", "through", "right")) + " |")
    L += ["", "## Moved vehicles over 0–1500 s", "", "| Load | Variant | Approach | Moves | Vehicles |", "|---|---|---|---|---|"]
    agg = {}
    for r in move_rows:
        k = (r["load"], r["variant"], r["approach"], f"{r['from_movement']} → {r['to_movement']}")
        agg[k] = agg.get(k, 0) + r["moved"]
    for (load, var, ap, mv), k in sorted(agg.items()):
        L.append(f"| {load} | {var} | {ap} | {mv} | {k} |")
    nbad = sum(c["cells_differing"] > 0 or c["vehicles"] != c["expected"] for c in checks)
    L += ["", f"## Check", "", f"{len(checks)} route files; {len(checks) - nbad} reproduce their counts file exactly "
          "(vehicles per relation and planned-departure interval; `route_checks.csv`).", "",
          "## Files and SHA-256", "", "| File | SHA-256 |", "|---|---|"]
    files = sorted([*(p for p in a.out_dir.glob("counts/*.xml") if p.stem.split("_")[2] in VARIANTS),
                    *(p for p in a.out_dir.glob("x*/*/*.rou.xml") if p.parent.name in ("base", *VARIANTS)),
                    a.out_dir / "moved_vehicles.csv", a.out_dir / "route_checks.csv"])
    for p in files:
        L.append(f"| `{dl.posix(p.relative_to(a.out_dir))}` | `{dl.sha256(p)}` |")
    (a.out_dir / "README.md").write_text("\n".join(L) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    f, c, m = sub.add_parser("fov"), sub.add_parser("ce"), sub.add_parser("fov_meas")
    for p in (f, c, m):
        p.add_argument("--candidate", type=Path, required=True)
        p.add_argument("--load", action="append", required=True, metavar="NAME=COUNTS")
        p.add_argument("--check-counts", type=Path, default=ROOT / "sumo" / "turn_counts_edges.xml",
                       help="x1.0 counts that the movement files (or the pipeline column) must reproduce")
        p.add_argument("--seeds", default="7001-7005")
        p.add_argument("--out-dir", type=Path, required=True)
        p.add_argument("--jobs", type=int, default=6)
        p.add_argument("--sumo-home")
        p.add_argument("--python", default=sys.executable)
    for p in (f, m):
        p.add_argument("--movements", type=Path, default=MOVDIR)
    c.add_argument("--cells", type=Path, required=True, help="counting_cells.csv of perception_metrics.py")
    c.add_argument("--min-pipeline", type=int, default=30,
                   help="relations with fewer pipeline vehicles take the approach's ratio (default 30)")
    c.add_argument("--draws", type=int, default=10)
    c.add_argument("--rand-seeds", default="7101-7110")
    c.add_argument("--rng-seed", type=int, default=7000)
    c.add_argument("--allow-partial", action="store_true", help="accept clips whose approaches were not watched in full")
    m.add_argument("--checks", type=Path, required=True, help="heading_exit_checks.csv of perception_metrics.py")
    m.add_argument("--min-checks", type=int, default=5)
    a = ap.parse_args()
    {"fov": cmd_fov, "ce": cmd_ce, "fov_meas": cmd_fov_meas}[a.cmd](a)


if __name__ == "__main__":
    main()
