#!/usr/bin/env python3
"""CO2 per episode from SUMO tripinfo files (E13 decision D-9, 30 Oct 2026: exploratory, not pre-specified).

Reads the episodes CSV of a run (e13/results/eval_episodes.csv, baseline_episodes.csv, or the S2c eval_episodes.csv),
keeps the rows selected by the options, opens each row's tripinfo file (column 'tripinfo', relative to <root>; plain
or .gz) and sums CO2_abs (mg) over every <tripinfo> element. SUMO writes arrived, unfinished and undeparted vehicles
(--tripinfo-output.write-unfinished / write-undeparted, emissions device on every vehicle); a vehicle that never
entered the network emits nothing. Read-only on the run folders.

  python e13/extract_co2.py <episodes.csv> <root> <out.csv> [--set locked] [--maps prybuzka_lt10,prybuzka_lt12]
         [--policies "Fixed plan,Actuated"] [--rung L2 --policy MPLight --own-load]

  E13 on MyPC (root = e13/):
    python e13/extract_co2.py e13/results/eval_episodes.csv e13 e13/results/co2_final_locked.csv --rung L2 --policy MPLight --own-load
    python e13/extract_co2.py e13/results/baseline_episodes.csv e13 e13/results/co2_baselines_locked.csv --policies "Fixed plan,Actuated"

Output: one row per episode with the key fields, demand, tripinfo entries, entries with an <emissions> element,
CO2 in kg, and the SHA-256 of the tripinfo file.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

OWN_LOAD = {"prybuzka_lt10": "x1.0", "prybuzka_lt12": "x1.2", "prybuzka_lt15": "x1.5"}
KEYS = ["rung", "policy", "controller_config", "train_load", "training_run", "eval_set", "map", "episode",
        "route_file", "sumo_seed", "demand"]


def co2_of(path: Path) -> tuple[int, int, float, str]:
    """(tripinfo entries, entries with emissions, CO2 in mg, SHA-256 of the file)."""
    raw = path.read_bytes()
    data = gzip.decompress(raw) if path.suffix == ".gz" else raw
    entries = with_em = 0
    co2 = 0.0
    for el in ET.fromstring(data).iter("tripinfo"):
        entries += 1
        em = el.find("emissions")
        if em is not None:
            with_em += 1
            co2 += float(em.get("CO2_abs", "0"))
    return entries, with_em, co2, hashlib.sha256(raw).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("episodes")
    ap.add_argument("root")
    ap.add_argument("out")
    ap.add_argument("--set", default="locked")
    ap.add_argument("--maps", default="prybuzka_lt10,prybuzka_lt12")
    ap.add_argument("--policies", default="")
    ap.add_argument("--rung", default="")
    ap.add_argument("--policy", default="")
    ap.add_argument("--own-load", action="store_true", help="only the model trained at the map's load")
    a = ap.parse_args()
    maps, pols = a.maps.split(","), [p for p in a.policies.split(",") if p]
    with open(a.episodes, newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r["eval_set"] == a.set and r["map"] in maps
                and (not pols or r["policy"] in pols)
                and (not a.rung or (r.get("rung") == a.rung and r["policy"] == a.policy))
                and (not a.own_load or r.get("train_load") == OWN_LOAD.get(r["map"]))]
    if not rows:
        print("no rows selected", file=sys.stderr)
        return 1
    out, problems = [], []
    for r in rows:
        p = Path(a.root) / r["tripinfo"]
        if not p.is_file():
            problems.append(f"missing {p}")
            continue
        n, n_em, mg, sha = co2_of(p)
        if n != int(float(r["demand"])):
            problems.append(f"{p}: {n} tripinfo entries, demand {r['demand']}")
        out.append({k: r.get(k, "") for k in KEYS} | {"entries": n, "with_emissions": n_em,
                                                      "co2_kg": round(mg / 1e6, 4), "tripinfo": r["tripinfo"],
                                                      "tripinfo_sha256": sha})
    with open(a.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)
    print(f"{len(out)} episodes written to {a.out}; problems: {len(problems)}")
    for x in problems[:20]:
        print("  " + x)
    return 0 if not problems else 2


if __name__ == "__main__":
    sys.exit(main())
