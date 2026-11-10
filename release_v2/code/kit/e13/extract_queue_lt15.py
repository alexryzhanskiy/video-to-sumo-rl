#!/usr/bin/env python3
"""Figure 8 data: the queue series of the E13 final design (L2 MPLight, the x1.5 model) on the locked x1.5 files
(map prybuzka_lt15), 5 training runs x 10 episodes, from the RESCO metrics logs of the locked evaluation.

Read-only on runs/. Writes to results/:

  queue_final_lt15_locked.csv      one row per episode; q_5 ... q_1800 = queue at the most recent logged decision
                                   with time <= t (step function, no interpolation; empty before the first decision)
  queue_final_lt15_locked_raw.csv  training_run, episode, time_s, queue: one row per logged decision
  queue_final_lt15_locked.json     sha256 of every source file, decisions per episode, decision spacing, and the
                                   check of the 50 (training_run, episode, route_file, sumo_seed) against
                                   results/eval_episodes.csv

The metrics_<e>.csv logs have no header row. RESCO's save_metrics (resco/resco_benchmark/multi_signal.py) writes the
fields in the order of its list ['step', 'reward', 'max_queues', 'queue_lengths', 'green'], each field after 'step' a
dict per signal; this file reads that list from the source and takes the field named 'queue_lengths' (the sum of the
queues over the signal's incoming lanes).

  python e13/extract_queue_lt15.py
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import ast  # noqa: E402
import bisect  # noqa: E402
import csv  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import re  # noqa: E402
import socket  # noqa: E402
import statistics  # noqa: E402
from collections import Counter  # noqa: E402
from datetime import datetime  # noqa: E402
from pathlib import Path  # noqa: E402

E13 = Path(__file__).resolve().parent
RESULTS = E13 / "results"
SELECT = {"eval_set": "locked", "rung": "L2", "policy": "MPLight", "train_load": "x1.5", "map": "prybuzka_lt15"}
MODEL = "L2_MPLight_x1.5_run{k}"
GRID = list(range(5, 1801, 5))
OUT = "queue_final_lt15_locked"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def metric_fields() -> list[str]:
    src = (E13 / "resco" / "resco_benchmark" / "multi_signal.py").read_text(encoding="utf-8")
    m = re.search(r"for metric in (\[[^\]]*\]):", src)
    if not m:
        sys.exit("cannot find the field list of save_metrics in resco/resco_benchmark/multi_signal.py")
    return ast.literal_eval(m.group(1))


def read_metrics(path: Path, fields: list[str]) -> list[tuple[float, int]]:
    """(time, queue) per logged decision; every row is checked against the field list."""
    out = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        step, rest = line.split(",", 1)
        dicts = [ast.literal_eval(d) for d in re.findall(r"\{[^{}]*\}", rest)]
        if len(dicts) != len(fields) - 1:
            sys.exit(f"{path}:{n}: {len(dicts) + 1} fields, expected {len(fields)} ({fields})")
        row = dict(zip(fields[1:], dicts))
        q, mq = row["queue_lengths"], row["max_queues"]
        if len(q) != 1 or set(q) != set(mq):
            sys.exit(f"{path}:{n}: expected one signal, got {q}")
        (sig, queue), = q.items()
        if not isinstance(queue, int) or queue < 0 or mq[sig] > queue:
            sys.exit(f"{path}:{n}: queue_lengths {queue} is not a total queue (max_queues {mq[sig]})")
        out.append((float(step), queue))
    times = [t for t, _ in out]
    if times != sorted(times) or len(set(times)) != len(times):
        sys.exit(f"{path}: decision times are not strictly increasing")
    return out


def main() -> int:
    fields = metric_fields()
    if "queue_lengths" not in fields or fields[0] != "step":
        sys.exit(f"unexpected metrics fields {fields}")
    with (RESULTS / "eval_episodes.csv").open(newline="", encoding="utf-8") as f:
        want = [r for r in csv.DictReader(f) if all(r[k] == v for k, v in SELECT.items())]
    want.sort(key=lambda r: (int(r["training_run"]), int(r["episode"])))

    source, episodes, wide, raw, gaps = [], [], [], [], []
    for k in sorted({int(r["training_run"]) for r in want} | set(range(1, 6))):
        base = E13 / "runs" / "eval" / MODEL.format(k=k) / SELECT["map"]
        info = json.loads((base / "eval.json").read_text(encoding="utf-8")) if (base / "eval.json").is_file() else {}
        if info.get("status") != "done":
            gaps.append(f"{base}: eval.json missing or not done")
        source += [(str(e["training_run"]), str(e["episode"]), e["route_file"], str(e["sumo_seed"]))
                   for e in info.get("episodes", [])]
    check_rows = [(r["training_run"], r["episode"], r["route_file"], r["sumo_seed"]) for r in want]

    for r in want:
        trip = E13 / r["tripinfo"]
        path = trip.parent / f"metrics_{r['episode']}.csv"
        if not path.is_file():
            gaps.append(f"training_run {r['training_run']} episode {r['episode']}: no {path}")
            continue
        series = read_metrics(path, fields)
        times = [t for t, _ in series]
        steps = [b - a for a, b in zip(times, times[1:])]
        grid = {}
        for t in GRID:
            i = bisect.bisect_right(times, t)
            grid[f"q_{t}"] = series[i - 1][1] if i else ""
        wide.append({"policy": "L2 MPLight", "controller_config": "", "eval_set": r["eval_set"], "map": r["map"],
                     "label": r["label"], "episode": r["episode"], "training_run": r["training_run"],
                     "sumo_seed": r["sumo_seed"], "route_file": r["route_file"]} | grid)
        raw += [{"training_run": r["training_run"], "episode": r["episode"], "time_s": t, "queue": q} for t, q in series]
        episodes.append({"training_run": int(r["training_run"]), "episode": int(r["episode"]),
                         "route_file": r["route_file"], "sumo_seed": int(r["sumo_seed"]),
                         "metrics_file": path.relative_to(E13).as_posix(), "sha256": sha256(path),
                         "decisions": len(series), "first_s": times[0], "last_s": times[-1],
                         "spacing_s": dict(sorted(Counter(steps).items())), "_steps": steps})
        if times[-1] < GRID[-1]:
            gaps.append(f"training_run {r['training_run']} episode {r['episode']}: last decision at {times[-1]} s")

    all_steps = [s for e in episodes for s in e.pop("_steps")]
    for name, rows in ((f"{OUT}.csv", wide), (f"{OUT}_raw.csv", raw)):
        with (RESULTS / name).open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    report = {
        "what": "queue series of the E13 final design L2 MPLight (x1.5 model) on the locked x1.5 files",
        "selection": SELECT, "source_fields": fields, "queue_field": "queue_lengths",
        "grid": "q_t for t = 5, 10, ..., 1800 s: queue at the most recent logged decision with time <= t; "
                "empty before the first decision",
        "host": socket.gethostname(), "created": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "rows": {f"{OUT}.csv": len(wide), f"{OUT}_raw.csv": len(raw)},
        "decision_spacing_s": {"min": min(all_steps), "median": statistics.median(all_steps), "max": max(all_steps),
                               "counts": dict(sorted(Counter(all_steps).items()))},
        "decisions_per_episode": {"min": min(e["decisions"] for e in episodes),
                                  "max": max(e["decisions"] for e in episodes)},
        "check_eval_episodes": {"eval_episodes_rows": len(check_rows), "source_episodes": len(source),
                                "match": sorted(check_rows) == sorted(source) and len(check_rows) == 50,
                                "only_in_eval_episodes": sorted(set(check_rows) - set(source)),
                                "only_in_source": sorted(set(source) - set(check_rows))},
        "missing_or_gaps": gaps,
        "outputs_sha256": {n: sha256(RESULTS / n) for n in (f"{OUT}.csv", f"{OUT}_raw.csv")},
        "episodes": episodes,
    }
    (RESULTS / f"{OUT}.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("rows", "decision_spacing_s", "decisions_per_episode",
                                             "check_eval_episodes", "missing_or_gaps", "outputs_sha256")}, indent=1))
    return 1 if gaps or not report["check_eval_episodes"]["match"] else 0


if __name__ == "__main__":
    sys.exit(main())
