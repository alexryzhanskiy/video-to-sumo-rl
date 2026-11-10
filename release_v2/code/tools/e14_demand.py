"""E14 (exploratory, approved by Pavlo on 2 Nov 2026; kb/07_EXPERIMENT_SPECS.md E14): route files for the second real
demand window, the pipeline counts of the 09:38 camera pair (31 Mar 2025, common window 09:38:05-10:00:43) that
Ryzhanskyi sent on 2 Nov (revision/reports/incoming_2026-11-02_assessment.md, item 1).

Input: his 1_turn_counts_edges_0938.xml (edge ids, U-turns left out, intervals 87-387, ..., 1287-1445 s of the common
clock). The intervals are shifted by -87 s so that the demand starts at 0 s, as sumo/turn_counts_edges.xml. Only the
four complete 300-s intervals are kept (0-1200 s): the last one (158 s, 132 vehicles) is marked complete=no in his
1_movements_5min_0938.csv, and routeSampler assumes intervals of equal length (with it, departures and counts no
longer match: tested 2 Nov). No count is changed.

Ten route files, routeSampler seeds 1401-1410 (default options, as make_heldout.py and twin_b7_demand.py; timestamp
removed, byte-reproducible). Each file is checked: vehicles per relation and planned-departure interval equal the
counts exactly. Layout as b7.py and s2c.py expect: <load>/<variant>/<name>_s<seed>.rou.xml with x10 = the x1.0 models
and configurations, and seed % 100 = episode index 1..10.

Run from the repository root (routeSampler writes its file paths into an XML comment; a "--" in a path breaks it):

    revision/.venv/Scripts/python.exe -I revision/tools/e14_demand.py

Output: revision/twin/E14/counts_0938_shifted.xml, revision/twin/E14/demand/x10/real0938/e14_real0938_x10_s14NN.rou.xml,
revision/twin/E14/generation_log.json, revision/twin/E14/README.md (counts, checks, SHA-256 of every file).
"""
from __future__ import annotations

import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.chdir(ROOT)                                    # relative paths only from here on
sys.path.insert(0, str(Path("revision/tools")))
import demandlib as dl  # noqa: E402

SRC = Path("revision/incoming/2026-11-02/answers_20261101/1_turn_counts_edges_0938.xml")
CANDIDATE = Path("sumo/candidate.rou.xml")
OUT = Path("revision/twin/E14")
SHIFT = 87
SEEDS = range(1401, 1411)
LOAD, VARIANT = "x10", "real0938"


def shifted(intervals: list[dl.Interval]) -> list[dl.Interval]:
    out = []
    for iv in intervals:
        b, e = int(iv.begin) - SHIFT, int(iv.end) - SHIFT
        if e - b == 300:
            out.append(dl.Interval(f"i{b}", str(b), str(e), [list(r) for r in iv.relations]))
    assert [iv.b for iv in out] == [0, 300, 600, 900]
    return out


def depart_table(route: Path, counts: list[dl.Interval]) -> dict:
    n = {}
    for v in dl.read_routes(route):
        b = next((iv.begin for iv in counts if iv.b <= v.depart < iv.e), None)
        if b is not None:
            fr, to = v.edges.split()
            n[(b, fr, to)] = n.get((b, fr, to), 0) + 1
    return n


def main() -> int:
    src = dl.read_counts(SRC)
    counts = shifted(src)
    cpath = OUT / "counts_0938_shifted.xml"
    dl.write_counts(counts, cpath, comment=f"E14: {SRC.as_posix()} shifted by -{SHIFT} s (common clock 87 s = 0 s); "
                                          "the four complete 300-s intervals, counts unchanged")
    sumo_home = dl.find_sumo_home(None)
    version = dl.sumo_version(sumo_home)
    outs = [OUT / "demand" / LOAD / VARIANT / f"e14_{VARIANT}_{LOAD}_s{s}.rou.xml" for s in SEEDS]
    cmds = [dl.routesampler_cmd(sys.executable, sumo_home, CANDIDATE, cpath, o, s) for o, s in zip(outs, SEEDS)]
    with ThreadPoolExecutor(4) as ex:
        list(ex.map(lambda job: dl.run_routesampler(job[0], sumo_home, job[1]), zip(cmds, outs)))
    want, total = dl.counts_table(counts), dl.counts_total(counts)
    log, checks = {}, []
    for o, s, cmd in zip(outs, SEEDS, cmds):
        got = depart_table(o, counts)
        bad = sum(got.get(k, 0) != v for k, v in want.items()) + sum(k not in want for k in got)
        nveh = len(dl.read_routes(o))
        checks.append((o, nveh, bad))
        log[dl.posix(o)] = dict(purpose="E14 exploratory test, second real window (09:38)", seeds=[s],
                                counts_file=dl.posix(cpath), counts_source=dl.posix(SRC), expected_total=total,
                                vehicles=nveh, cells_differing=bad, sumo_version=version,
                                command=dl.display_cmd(cmd, sumo_home), created_utc=dl.utc_now())
    dl.save_log(log, OUT / "generation_log.json")
    nbad = sum(b > 0 or n != total for _, n, b in checks)
    files = [SRC, cpath, *outs]
    readme = ["# E14 demand: second real window (09:38), 31 Mar 2025", "",
              f"Made by `revision/tools/e14_demand.py` on {dl.utc_now()} with SUMO {version}. Source: Ryzhanskyi's "
              f"pipeline counts `{SRC.as_posix()}` (not hand-checked), shifted by -{SHIFT} s, the incomplete last "
              f"interval (158 s, 132 vehicles) left out; {total} vehicles (U-turns left out), intervals {', '.join(f'{iv.begin}-{iv.end}' for iv in counts)} s with "
              f"{', '.join(str(x) for x in dl.interval_totals(counts))} vehicles.", "",
              f"Route files: routeSampler seeds {SEEDS[0]}-{SEEDS[-1]}, candidate `{CANDIDATE.as_posix()}`, default "
              f"options; {len(outs) - nbad} of {len(outs)} pass the count check (vehicles per relation and "
              "planned-departure interval equal the counts).", "",
              "## Files and SHA-256", "", "| File | SHA-256 |", "|---|---|",
              *(f"| `{dl.posix(p)}` | `{dl.sha256(p)}` |" for p in files)]
    (OUT / "README.md").write_text("\n".join(readme) + "\n", encoding="utf-8")
    print(f"{len(outs)} route files, {nbad} failing the count check; {total} vehicles each; SUMO {version}")
    return 1 if nbad else 0


if __name__ == "__main__":
    sys.exit(main())
