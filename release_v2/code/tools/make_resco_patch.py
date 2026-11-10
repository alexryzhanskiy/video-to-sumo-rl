#!/usr/bin/env python3
"""Write a unified diff of the evaluation-kit changes to RESCO (code files only).

Compares every *.py file under <original>/resco_benchmark with the same file under <patched>/resco_benchmark and
writes one patch whose paths are relative to the RESCO root (a/resco_benchmark/..., b/resco_benchmark/...), so it
applies with `git apply` from any RESCO copy, e.g. C:/Work/RESCO. New .py files are included; map data are not.

  python revision/tools/make_resco_patch.py --original resco --patched revision/resco_eval/resco \
      --out revision/resco_eval/resco_eval.patch
"""
import argparse
import difflib
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--original", required=True, help="unmodified RESCO root (contains resco_benchmark/)")
    ap.add_argument("--patched", required=True, help="patched RESCO root")
    ap.add_argument("--out", required=True, help="patch file to write")
    args = ap.parse_args()
    orig, new = Path(args.original), Path(args.patched)
    rels = sorted({p.relative_to(new).as_posix() for p in (new / "resco_benchmark").rglob("*.py")
                   if "__pycache__" not in p.parts})
    def lines(path: Path) -> list[str]:    # keep CRLF line endings as they are in the files
        with path.open(encoding="utf-8", newline="") as f:
            return f.read().splitlines(keepends=True)

    chunks, changed = [], []
    for rel in rels:
        a = orig / rel
        a_lines = lines(a) if a.is_file() else []
        b_lines = lines(new / rel)
        if a_lines == b_lines:
            continue
        diff = list(difflib.unified_diff(a_lines, b_lines, fromfile=f"a/{rel}" if a_lines else "/dev/null",
                                         tofile=f"b/{rel}", n=3))
        diff = [d if d.endswith("\n") else d + "\n\\ No newline at end of file\n" for d in diff]
        chunks.append(f"diff --git a/{rel} b/{rel}\n" + "".join(diff))
        changed.append(rel)
    Path(args.out).write_text("".join(chunks), encoding="utf-8", newline="")
    print(f"{len(changed)} files changed -> {args.out}")
    for rel in changed:
        print("  " + rel)
    return 0


if __name__ == "__main__":
    sys.exit(main())
