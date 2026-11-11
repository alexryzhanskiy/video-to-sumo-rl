"""Generate the perturbed demand scenarios S1-S4 (P01 Step 2, Comment 1.9).

All scenarios start from the x1.0 turn counts. Parameters come from scenario_params.json:
  S1 directional imbalance  - Svobody through + left counts x factor (largest-remainder rounding)
  S2 platooned arrivals     - x1.0 counts; departures concentrated in a window of every signal cycle,
                              via routeSampler --depart-distribution, one run per axis, merged
  S3 peak formation         - relation totals kept; peak_share of each relation in the peak window
  S4 turning-proportion     - left x factor per interval and approach, through reduced by the same

Writes <out-dir>/S{n}/scenario_S{n}_s{seed}.rou.xml, the turn-count files used, a rounding log per
scenario, <out-dir>/generation_log.json and <out-dir>/SCENARIOS.md. The S2 per-axis routeSampler
outputs go to --work-dir. Same parameters and seeds give byte-identical route files.

Example (from the repository root):
  python revision/tools/make_scenarios.py --candidate sumo/candidate.rou.xml \
      --base-counts sumo/turn_counts_edges.xml \
      --params revision/demand/scenarios/scenario_params.json \
      --out-dir revision/demand/scenarios --work-dir revision/demand/work/S2_parts
"""
from __future__ import annotations

import argparse
import copy
import csv
import json
import math
import re
import sys
from fractions import Fraction
from pathlib import Path

import demandlib as dl

ROUTES_OPEN_RE = re.compile(r"<routes[^>]*>")
CONFIG_RE = re.compile(r"<configuration>.*?</configuration>", re.S)


def frac(x) -> Fraction:
    return Fraction(str(x))


def fnum(x: Fraction | float, nd: int = 4) -> str:
    return f"{float(x):.{nd}f}".rstrip("0").rstrip(".")


def relation(iv: dl.Interval, f: str, t: str) -> list:
    for rel in iv.relations:
        if rel[0] == f and rel[1] == t:
            return rel
    raise KeyError(f"relation {f}->{t} missing in interval {iv.id}")


def write_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


# --------------------------------------------------------------------------- count transforms

def build_s1(base: list[dl.Interval], p: dict):
    out = copy.deepcopy(base)
    factor = frac(p["factor"])
    cells = [(iv, rel) for iv in out for rel in iv.relations
             if rel[0] in p["approaches"] and dl.MOVEMENT[(rel[0], rel[1])] in p["movements"]]
    base_vals = [rel[2] for _, rel in cells]
    raw = [factor * c for c in base_vals]
    target = dl.round_half_up(factor * sum(base_vals))
    new, bumped = dl.largest_remainder(raw, target)
    rows = []
    for (iv, rel), c, r, n, b in zip(cells, base_vals, raw, new, bumped):
        rel[2] = n
        rows.append({"interval": iv.id, "from": rel[0], "to": rel[1], "movement": dl.MOVEMENT[(rel[0], rel[1])],
                     "base": c, "raw": fnum(r), "floor": math.floor(r), "remainder": fnum(r - math.floor(r)),
                     "largest_remainder_bump": int(b), "final": n})
    info = {"affected_base_total": sum(base_vals), "affected_raw_total": fnum(factor * sum(base_vals)),
            "affected_target": target, "bumped_cells": sum(bumped)}
    return out, rows, info


def build_s3(base: list[dl.Interval], p: dict):
    out = copy.deepcopy(base)
    share = frac(p["peak_share"])
    peak = [k for k, iv in enumerate(base) if iv.b >= p["peak_begin"] and iv.e <= p["peak_end"]]
    off = [k for k in range(len(base)) if k not in peak]
    itot = dl.interval_totals(base)
    rows, fallbacks = [], 0
    for f, t, _ in base[0].relations:
        c = [relation(iv, f, t)[2] for iv in base]
        total = sum(c)
        raw = [Fraction(0)] * len(base)
        for block, part in ((peak, share * total), (off, (1 - share) * total)):
            w = [c[k] for k in block]
            if sum(w) == 0:  # relation absent in this block: use the overall interval profile
                w = [itot[k] for k in block]
                fallbacks += 1
            for k, wk in zip(block, w):
                raw[k] = part * wk / sum(w)
        new, bumped = dl.largest_remainder(raw, total)
        for k, iv in enumerate(out):
            relation(iv, f, t)[2] = new[k]
            rows.append({"interval": iv.id, "from": f, "to": t, "movement": dl.MOVEMENT[(f, t)],
                         "in_peak": int(k in peak), "base": c[k], "raw": fnum(raw[k]),
                         "floor": math.floor(raw[k]), "remainder": fnum(raw[k] - math.floor(raw[k])),
                         "largest_remainder_bump": int(bumped[k]), "final": new[k],
                         "relation_total": total})
    peak_total = sum(itot[k] for k in peak)
    new_peak = sum(dl.interval_totals(out)[k] for k in peak)
    info = {"peak_intervals": [base[k].id for k in peak], "base_peak_total": peak_total,
            "base_peak_share": fnum(Fraction(peak_total, dl.counts_total(base)), 6),
            "new_peak_total": new_peak, "new_peak_share": fnum(Fraction(new_peak, dl.counts_total(out)), 6),
            "profile_fallbacks": fallbacks}
    return out, rows, info


def build_s4(base: list[dl.Interval], p: dict):
    out = copy.deepcopy(base)
    lf = frac(p["left_factor"])
    by_move = {}
    for (f, t), m in dl.MOVEMENT.items():
        by_move[(f, m)] = t
    rows, shortfalls = [], 0
    for iv in out:
        for a in dl.APPROACHES:
            L = relation(iv, a, by_move[(a, "left")])
            T = relation(iv, a, by_move[(a, "through")])
            R = relation(iv, a, by_move[(a, "right")])
            l0, t0, r0 = L[2], T[2], R[2]
            l1 = dl.round_half_up(lf * l0)
            t1, r1, note = t0 - (l1 - l0), r0, ""
            if t1 < 0:
                r1, note = r0 + t1, f"through short by {-t1}, taken from right"
                t1 = 0
                shortfalls += 1
            if r1 < 0:
                sys.exit(f"S4: interval {iv.id} approach {a}: left increase exceeds through + right")
            L[2], T[2], R[2] = l1, t1, r1
            rows.append({"interval": iv.id, "approach": a, "left_base": l0, "left_raw": fnum(lf * l0),
                         "left_final": l1, "through_base": t0, "through_final": t1, "right_base": r0,
                         "right_final": r1, "approach_total": l1 + t1 + r1, "note": note})
    info = {"left_base_total": dl.movement_totals(base)["left"], "left_new_total": dl.movement_totals(out)["left"],
            "through_shortfalls": shortfalls}
    return out, rows, info


def split_axis(base: list[dl.Interval], approaches: tuple[str, ...]) -> list[dl.Interval]:
    return [dl.Interval(iv.id, iv.begin, iv.end, [list(r) for r in iv.relations if r[0] in approaches])
            for iv in base]


# --------------------------------------------------------------------------- S2 helpers

def s2_density(p: dict, offset: float) -> list[float]:
    """Relative departure density per bin over [begin, end): 1 inside the window, background outside."""
    cyc, win, bw, bg = p["cycle"], p["window"], p["bin"], p["background"]
    nbins = round((p["end"] - p["begin"]) / bw)
    vals = []
    for k in range(nbins):
        t0 = p["begin"] + k * bw
        t1 = t0 + bw
        overlap = 0.0
        for m in range(math.floor((t0 - offset - win) / cyc), math.floor((t1 - offset) / cyc) + 1):
            ws = offset + m * cyc
            overlap += max(0.0, min(t1, ws + win) - max(t0, ws))
        vals.append((overlap + (bw - overlap) * bg) / bw)
    return vals


def window_shares(vehicles: list[dl.Vehicle], p: dict) -> dict:
    hit = {"svobody": [0, 0], "prybuzka": [0, 0]}
    for v in vehicles:
        frm = v.edges.split()[0]
        axis = "svobody" if frm in dl.SVOBODY else "prybuzka"
        off = p["offset_svobody"] if axis == "svobody" else p["offset_prybuzka"]
        hit[axis][1] += 1
        hit[axis][0] += ((v.depart - off) % p["cycle"]) < p["window"]
    n_in = hit["svobody"][0] + hit["prybuzka"][0]
    n = hit["svobody"][1] + hit["prybuzka"][1]
    return {"all": n_in / n, "svobody": hit["svobody"][0] / hit["svobody"][1],
            "prybuzka": hit["prybuzka"][0] / hit["prybuzka"][1], "in_window": n_in, "n": n}


def merge_parts(parts: list[Path], out: Path, intervals: list[dl.Interval], title: str) -> None:
    """Merge routeSampler files into one, sorted by departure, in the routeSampler layout."""
    vehicles, configs, routes_open = [], [], None
    for part in parts:
        text = part.read_text(encoding="utf-8")
        m = CONFIG_RE.search(text)
        configs.append(m.group(0).replace("\r\n", "\n") if m else "")
        routes_open = routes_open or ROUTES_OPEN_RE.search(text.split("-->", 1)[1]).group(0)
        vehicles += dl.read_routes(part)
    vehicles.sort(key=lambda v: (v.depart, v.id))
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', "",
             f"<!-- generated by revision/tools/make_scenarios.py: {title}"]
    for c in configs:
        lines += c.split("\n")
    lines += ["-->", "", routes_open]
    nxt = 0
    for v in vehicles:
        while nxt < len(intervals) and v.depart >= intervals[nxt].b:
            lines.append(f'<!-- begin="{intervals[nxt].b:.1f}" end="{intervals[nxt].e:.1f}" -->')
            nxt += 1
        lines += [f'    <vehicle id="{v.id}" depart="{v.depart_str}">',
                  f'        <route edges="{v.edges}"/>',
                  "    </vehicle>"]
    lines.append("</routes>")
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="\r\n") as f:
        f.write("\n".join(lines) + "\n")


# --------------------------------------------------------------------------- report

def mlt(intervals: list[dl.Interval]) -> str:
    m = dl.movement_totals(intervals)
    return f"{m['left']} / {m['through']} / {m['right']}"


def write_scenarios_md(path: Path, params: dict, base: list[dl.Interval], counts: dict, infos: dict,
                       shares: dict, base_path: Path, seeds: list[int]) -> None:
    p1, p2, p3, p4 = params["S1"], params["S2"], params["S3"], params["S4"]
    ivs = ", ".join(f"{iv.begin}-{iv.end}" for iv in base)
    s = lambda c: ", ".join(str(x) for x in dl.interval_totals(c))
    seeds_txt = f"{seeds[0]}-{seeds[-1]}" if seeds == list(range(seeds[0], seeds[-1] + 1)) else str(seeds)
    sh = shares
    sh_all = [sh[k]["all"] for k in sorted(sh)] or [float("nan")]
    i1, i3, i4 = infos["S1"], infos["S3"], infos["S4"]
    L = [
        "# Perturbed demand scenarios S1-S4 (Comment 1.9)",
        "",
        f"Generated by `revision/tools/make_scenarios.py` from `{dl.posix(base_path)}` (x1.0, {dl.counts_total(base)} "
        f"vehicles in five 300-s intervals {ivs} s) with the parameters in `scenario_params.json`. Every scenario has "
        f"five realizations drawn with SUMO routeSampler seeds {seeds_txt}; the same seeds are used for every scenario, "
        "so that comparisons between scenarios are paired. All vehicles are SUMO default passenger cars, as in the "
        "original demand (no vType, departLane or departSpeed attributes). Every number below is computed from the "
        "turn-count files in this folder or, for S2, from the generated route files.",
        "",
        "| Scenario | Total vehicles | Interval totals (veh per 300 s) | Left / through / right |",
        "|---|---|---|---|",
        f"| x1.0 baseline | {dl.counts_total(base)} | {s(base)} | {mlt(base)} |",
    ]
    for n in ("S1", "S2", "S3", "S4"):
        c = counts[n]
        L.append(f"| {n} {params[n]['name']} | {dl.counts_total(c)} | {s(c)} | {mlt(c)} |")
    L += [
        "",
        "## S1 Directional imbalance",
        "",
        f"Definition: the through and left-turn counts of the two Svobody Street approaches (`nN_nC`, `nS_nC`) are "
        f"multiplied by {p1['factor']} in every 300-s interval; all other relations are unchanged. This represents a "
        "corridor-specific demand increase on the major street with unchanged side-street demand.",
        "",
        f"Parameters: factor = {p1['factor']}; affected relations `nN_nC->nC_nS`, `nN_nC->nC_nE`, `nS_nC->nC_nN`, "
        f"`nS_nC->nC_nW`. Rounding: the affected cells (5 intervals x 4 relations) were rounded by the largest-remainder "
        f"method so that their sum equals round({p1['factor']} x {i1['affected_base_total']} = "
        f"{i1['affected_raw_total']}) = {i1['affected_target']}; {i1['bumped_cells']} cells were rounded up (ties to "
        "the earlier cell in file order). Every decision is in `S1/rounding_log_S1.csv`.",
        "",
        f"Result: {dl.counts_total(counts['S1'])} vehicles ({dl.counts_total(counts['S1']) - dl.counts_total(base):+d} "
        f"vs x1.0); interval totals {s(counts['S1'])}; left / through / right {mlt(counts['S1'])}. Turn counts: "
        "`S1/turn_counts_S1.xml`.",
        "",
        "## S2 Platooned arrivals",
        "",
        f"Definition: the x1.0 counts per interval and relation are kept exactly, but departures are concentrated in a "
        f"{p2['window']}-s window of every {p2['cycle']}-s cycle (the cycle of the field fixed-time plan), approximating "
        "platoons released by upstream signals. The Svobody approaches (`nN_nC`, `nS_nC`) receive their window at offset "
        f"{p2['offset_svobody']} s and the Prybuzka approaches (`nE_nC`, `nW_nC`) at offset {p2['offset_prybuzka']} s "
        "within the cycle.",
        "",
        f"Parameters: window = {p2['window']} s, cycle = {p2['cycle']} s, offsets {p2['offset_svobody']} s / "
        f"{p2['offset_prybuzka']} s, background density = {p2['background']} of the in-window density, "
        f"{round((p2['end'] - p2['begin']) / p2['bin'])} bins of {p2['bin']} s over {p2['begin']}-{p2['end']} s. "
        "Method: the x1.0 turn counts were split by axis; routeSampler was run once per axis with "
        "`--depart-distribution` set to the binned density (Svobody: seed s, prefix `sv_`; Prybuzka: seed "
        f"s + {p2['prybuzka_seed_offset']}, prefix `pr_`); the two outputs were merged and sorted by departure time. "
        f"Expected in-window share: {p2['window']} / ({p2['window']} + {p2['cycle'] - p2['window']} x "
        f"{p2['background']}) = {fnum(p2['window'] / (p2['window'] + (p2['cycle'] - p2['window']) * p2['background']) * 100, 1)}%.",
        "",
        f"Result: {dl.counts_total(counts['S2'])} vehicles, counts per interval and relation identical to x1.0; "
        f"achieved in-window share {min(sh_all) * 100:.1f}-{max(sh_all) * 100:.1f}% over the five realizations:",
        "",
        "| Realization | In window (all) | Svobody | Prybuzka |",
        "|---|---|---|---|",
    ]
    for k in sorted(sh):
        L.append(f"| `{k}` | {sh[k]['in_window']} / {sh[k]['n']} = {sh[k]['all'] * 100:.1f}% | "
                 f"{sh[k]['svobody'] * 100:.1f}% | {sh[k]['prybuzka'] * 100:.1f}% |")
    L += [
        "",
        "## S3 Peak formation",
        "",
        f"Definition: each relation keeps its total over 0-1500 s, but the temporal profile is reshaped so that "
        f"{fnum(p3['peak_share'] * 100, 1)}% of the vehicles fall in {p3['peak_begin']}-{p3['peak_end']} s (baseline "
        f"{i3['base_peak_total']} / {dl.counts_total(base)} = "
        f"{100 * i3['base_peak_total'] / dl.counts_total(base):.1f}%). This "
        "represents a sharper peak inside the observed period with unchanged total demand and movement mix.",
        "",
        f"Parameters: peak_share = {p3['peak_share']}, peak = intervals {', '.join(i3['peak_intervals'])}. Method, per "
        f"relation: {p3['peak_share']} x the relation total is spread over the two peak intervals and the remainder "
        "over the other three intervals, each in proportion to the relation's observed counts in those intervals; "
        "the five values are rounded by the largest-remainder method so that the relation total is unchanged "
        f"(`S3/rounding_log_S3.csv`; profile fallbacks for relations absent from a block: {i3['profile_fallbacks']}).",
        "",
        f"Result: {dl.counts_total(counts['S3'])} vehicles; interval totals {s(counts['S3'])}; achieved peak share "
        f"{i3['new_peak_total']} / {dl.counts_total(counts['S3'])} = "
        f"{100 * i3['new_peak_total'] / dl.counts_total(counts['S3']):.2f}%; "
        f"left / through / right {mlt(counts['S3'])} (unchanged). Turn counts: `S3/turn_counts_S3.xml`.",
        "",
        "## S4 Turning-proportion shift",
        "",
        f"Definition: in every 300-s interval and on every approach, the left-turn count is multiplied by "
        f"{p4['left_factor']} (rounded half up) and the through count is reduced by the same number, so approach totals "
        "and the total demand are unchanged. This tests sensitivity to a heavier left-turn share, the movement served "
        "by the protected left phases and the full-length left lanes of the network.",
        "",
        f"Parameters: left_factor = {p4['left_factor']}; left relations `nN_nC->nC_nE`, `nS_nC->nC_nW`, "
        f"`nE_nC->nC_nS`, `nW_nC->nC_nN`. Cases where through would fall below zero (deficit taken from right turns): "
        f"{i4['through_shortfalls']} (`S4/rounding_log_S4.csv`).",
        "",
        f"Result: {dl.counts_total(counts['S4'])} vehicles; interval totals {s(counts['S4'])}; realized left-turn total "
        f"{i4['left_new_total']} (baseline {i4['left_base_total']}, x{fnum(i4['left_new_total'] / i4['left_base_total'], 3)}); "
        f"left / through / right {mlt(counts['S4'])}. Turn counts: `S4/turn_counts_S4.xml`.",
        "",
    ]
    path.write_text("\n".join(L), encoding="utf-8")


# --------------------------------------------------------------------------- main

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--candidate", type=Path, required=True, help="candidate routes (sumo/candidate.rou.xml)")
    ap.add_argument("--base-counts", type=Path, required=True, help="x1.0 turn counts (sumo/turn_counts_edges.xml)")
    ap.add_argument("--params", type=Path, required=True, help="scenario_params.json")
    ap.add_argument("--out-dir", type=Path, required=True, help="output folder (revision/demand/scenarios)")
    ap.add_argument("--work-dir", type=Path, required=True, help="folder for S2 per-axis routeSampler outputs")
    ap.add_argument("--only", nargs="*", choices=["S1", "S2", "S3", "S4"], help="regenerate only these scenarios")
    ap.add_argument("--sumo-home", help="SUMO installation (default: $SUMO_HOME or the eclipse-sumo wheel)")
    ap.add_argument("--python", default=sys.executable, help="interpreter for routeSampler (default: this one)")
    args = ap.parse_args()

    sumo_home = dl.find_sumo_home(args.sumo_home)
    version = dl.sumo_version(sumo_home)
    params = json.loads(args.params.read_text(encoding="utf-8"))
    seeds = params["seeds"]
    base = dl.read_counts(args.base_counts)
    base_total = dl.counts_total(base)
    log_path = args.out_dir / "generation_log.json"
    log = dl.load_log(log_path)
    todo = set(args.only or ["S1", "S2", "S3", "S4"])

    builders = {"S1": build_s1, "S3": build_s3, "S4": build_s4}
    counts, infos = {"S2": base}, {}
    for n, build in builders.items():
        c, rows, info = build(base, params[n])
        counts[n], infos[n] = c, info
        if n not in todo:
            continue
        cpath = args.out_dir / n / f"turn_counts_{n}.xml"
        dl.write_counts(c, cpath, f"{n} {params[n]['name']}: generated by revision/tools/make_scenarios.py from "
                                  f"{dl.posix(args.base_counts)} with {dl.posix(args.params)}")
        write_csv(rows, args.out_dir / n / f"rounding_log_{n}.csv")
        log[dl.posix(cpath)] = {"purpose": f"turn counts of scenario {n} ({params[n]['name']})", "group": "counts",
                                "load_or_scenario": n, "seeds": [], "counts_file": dl.posix(args.base_counts),
                                "expected_total": dl.counts_total(c), "sumo_version": "", "command":
                                f"python revision/tools/make_scenarios.py (from {dl.posix(args.base_counts)})",
                                "created_utc": dl.utc_now(), "info": info}
        for seed in seeds:
            out = args.out_dir / n / f"scenario_{n}_s{seed}.rou.xml"
            cmd = dl.routesampler_cmd(args.python, sumo_home, args.candidate, cpath, out, seed)
            dl.run_routesampler(cmd, sumo_home, out)
            log[dl.posix(out)] = {"purpose": f"perturbed scenario {n} ({params[n]['name']}, Comment 1.9)",
                                  "group": f"scenario_{n}", "load_or_scenario": n, "seeds": [seed],
                                  "counts_file": dl.posix(cpath), "counts_ref": dl.posix(cpath),
                                  "expected_total": dl.counts_total(c), "sumo_version": version,
                                  "command": dl.display_cmd(cmd, sumo_home), "created_utc": dl.utc_now()}
            print(f"{out.as_posix()}  ({len(dl.read_routes(out))} vehicles)")

    # S2: one routeSampler run per axis with a departure density, then merge.
    p2 = params["S2"]
    shares = {}
    axes = [("svobody", dl.SVOBODY, p2["offset_svobody"], p2["prefix_svobody"], 0),
            ("prybuzka", dl.PRYBUZKA, p2["offset_prybuzka"], p2["prefix_prybuzka"], p2["prybuzka_seed_offset"])]
    axis_counts = {}
    for name, appr, offset, prefix, seed_off in axes:
        cpath = args.out_dir / "S2" / f"turn_counts_S2_{name}.xml"
        axis_counts[name] = (cpath, offset, prefix, seed_off)
        if "S2" in todo:
            dl.write_counts(split_axis(base, appr), cpath,
                            f"S2 platooned arrivals: {name} approaches of {dl.posix(args.base_counts)} (counts unchanged)")
            log[dl.posix(cpath)] = {"purpose": f"S2 routeSampler input: x1.0 counts of the {name} approaches",
                                    "group": "counts", "load_or_scenario": "S2", "seeds": [],
                                    "counts_file": dl.posix(args.base_counts),
                                    "expected_total": dl.counts_total(split_axis(base, appr)), "sumo_version": "",
                                    "command": "python revision/tools/make_scenarios.py (axis split)",
                                    "created_utc": dl.utc_now()}
    for seed in seeds:
        out = args.out_dir / "S2" / f"scenario_S2_s{seed}.rou.xml"
        if "S2" in todo:
            parts, cmds = [], []
            for name, (cpath, offset, prefix, seed_off) in axis_counts.items():
                part = args.work_dir / f"S2_{prefix.rstrip('_')}_s{seed + seed_off}.rou.xml"
                dist = ",".join(f"{v:g}" for v in s2_density(p2, offset))
                cmd = dl.routesampler_cmd(args.python, sumo_home, args.candidate, cpath, part, seed + seed_off,
                                          ["--prefix", prefix, "--depart-distribution", dist])
                dl.run_routesampler(cmd, sumo_home, part)
                parts.append(part)
                cmds.append(dl.display_cmd(cmd, sumo_home))
            merge_parts(parts, out, base, f"S2 {p2['name']}, merge of {len(parts)} routeSampler runs "
                                          f"({version}), sorted by depart")
            print(f"{out.as_posix()}  ({len(dl.read_routes(out))} vehicles)")
        elif not out.is_file():
            continue
        sh = window_shares(dl.read_routes(out), p2)
        shares[out.name] = sh
        if "S2" in todo:
            log[dl.posix(out)] = {"purpose": f"perturbed scenario S2 ({p2['name']}, Comment 1.9)",
                                  "group": "scenario_S2", "load_or_scenario": "S2",
                                  "seeds": [seed, seed + p2["prybuzka_seed_offset"]],
                                  "counts_file": "; ".join(dl.posix(v[0]) for v in axis_counts.values()),
                                  "counts_ref": dl.posix(args.base_counts), "expected_total": base_total,
                                  "sumo_version": version, "command": " && ".join(cmds) + " && merge (sort by depart)",
                                  "created_utc": dl.utc_now(), "window_share": sh}

    dl.save_log(log, log_path)
    write_scenarios_md(args.out_dir / "SCENARIOS.md", params, base, counts, infos, shares, args.base_counts, seeds)
    print(json.dumps({n: infos[n] for n in infos}, indent=1))
    print({k: round(v["all"], 4) for k, v in shares.items()})


if __name__ == "__main__":
    main()
