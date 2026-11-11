"""Compare two routeSampler files vehicle by vehicle (id, depart, route edges).

The generator comment is ignored. Exit code 0 if identical, 1 otherwise.

Example (Step 0 of P01, reproduction check):
  python revision/tools/compare_routes.py sumo/demand.rou.xml revision/demand/repro/demand.rou.xml
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from demandlib import read_routes


def compare(a: Path, b: Path, show: int = 5) -> tuple[bool, str]:
    va, vb = read_routes(a), read_routes(b)
    diffs = []
    for i in range(max(len(va), len(vb))):
        x = va[i] if i < len(va) else None
        y = vb[i] if i < len(vb) else None
        if x is None or y is None or (x.id, x.depart_str, x.edges) != (y.id, y.depart_str, y.edges):
            diffs.append((i, x, y))
    if not diffs:
        return True, f"identical: {len(va)} vehicles"
    lines = [f"DIFFERENT: {len(va)} vs {len(vb)} vehicles, {len(diffs)} differing positions"]
    for i, x, y in diffs[:show]:
        fmt = lambda v: "-" if v is None else f"{v.id} {v.depart_str} [{v.edges}]"
        lines.append(f"  #{i}: {fmt(x)}  <>  {fmt(y)}")
    return False, "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("reference", type=Path, help="reference route file (e.g. sumo/demand.rou.xml)")
    ap.add_argument("candidate", type=Path, help="regenerated route file")
    ap.add_argument("--show", type=int, default=5, help="number of differences to print (default 5)")
    args = ap.parse_args()
    ok, msg = compare(args.reference, args.candidate, args.show)
    print(f"{args.reference.as_posix()} vs {args.candidate.as_posix()}: {msg}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
