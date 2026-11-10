#!/usr/bin/env python3
"""Turn an upstream RESCO checkout into the RESCO copy that the E12 or E13 runs used.

RESCO (https://github.com/Pi-Star-Lab/RESCO, CC BY-NC-SA 4.0) is not redistributed here. This script
  1. checks the checkout (commit fc65e91 expected; a different commit is reported, not refused, with --force);
  2. applies resco_<variant>.patch with `git apply` (line endings of the touched files are first set to LF,
     so the patch applies to checkouts made with core.autocrlf=true as well);
  3. creates every map folder under resco_benchmark/environments/ from this package's network/ and demand/
     files, as listed in maps_<variant>.json, and checks each file's SHA-256;
  4. with --kit, copies the B7 and E14 route files into <kit>/e13/b7_demand and <kit>/e13/e14_demand.

Usage (from the package root):
  git clone -c core.longpaths=true https://github.com/Pi-Star-Lab/RESCO.git code/kit/e13/resco
  git -C code/kit/e13/resco checkout fc65e91
  python code/kit/resco_integration/apply_to_resco.py --resco code/kit/e13/resco --variant e13 --kit code/kit

For the E12 driver (code/kit/e12.py) use a second checkout at code/kit/resco with --variant e12.
Every step is idempotent; --dry-run reports what would change and writes nothing.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG = HERE.parents[2]          # package root (contains network/, demand/)
UPSTREAM = "fc65e91f6711d53296dee824e684b201a3e6808d"


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def check_checkout(resco: Path, force: bool) -> None:
    if not (resco / "resco_benchmark" / "main.py").is_file():
        sys.exit(f"{resco} is not a RESCO checkout (resco_benchmark/main.py missing)")
    r = git(["rev-parse", "HEAD"], resco)
    if r.returncode == 0:
        head = r.stdout.strip()
        if head != UPSTREAM:
            msg = f"RESCO checkout is at {head[:7]}, the patch was made against {UPSTREAM[:7]}"
            if not force:
                sys.exit(msg + " (git -C <resco> checkout fc65e91, or --force)")
            print("warning:", msg)
    else:
        print("note: not a git checkout; commit not checked")


def apply_patch(resco: Path, patch: Path, dry: bool) -> None:
    targets = re.findall(r"^\+\+\+ b/(\S+)", patch.read_text(encoding="utf-8"), re.M)
    if git(["apply", "--reverse", "--check", str(patch)], resco).returncode == 0:
        print(f"patch {patch.name}: already in place ({len(targets)} files)")
        return
    if not dry:
        for t in targets:    # LF line endings, as in the patch
            p = resco / t
            if p.is_file():
                b = p.read_bytes()
                if b"\r\n" in b:
                    p.write_bytes(b.replace(b"\r\n", b"\n"))
    r = git(["apply", "--check", str(patch)], resco)
    if r.returncode != 0:
        sys.exit(f"patch {patch.name} does not apply:\n{r.stderr}")
    if dry:
        print(f"patch {patch.name}: would change {len(targets)} files")
        return
    r = git(["apply", "--whitespace=nowarn", str(patch)], resco)
    if r.returncode != 0:
        sys.exit(f"git apply failed:\n{r.stderr}")
    print(f"patch {patch.name}: applied to {len(targets)} files")


def fill_maps(resco: Path, maps: dict, dry: bool) -> None:
    env = resco / "resco_benchmark" / "environments"
    made = same = 0
    for name, entry in maps.items():
        for f in entry["files"]:
            dst = env / name / f["target"]
            if dst.is_file() and sha256(dst) == f["sha256"]:
                same += 1
                continue
            made += 1
            if dry:
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            if "source" in f:
                src = PKG / f["source"]
                if sha256(src) != f["sha256"]:
                    sys.exit(f"{src} has the wrong SHA-256")
                shutil.copyfile(src, dst)
            else:
                dst.write_bytes(f["text"].encode("utf-8"))
            if sha256(dst) != f["sha256"]:
                sys.exit(f"{dst}: SHA-256 differs after writing")
    print(f"maps: {len(maps)} folders, {made} files {'to write' if dry else 'written'}, {same} already in place")


def fill_kit(kit: Path, dry: bool) -> None:
    n = 0
    for src_dir, dst_dir in [(PKG / "demand" / "b7", kit / "e13" / "b7_demand"),
                             (PKG / "demand" / "e14", kit / "e13" / "e14_demand")]:
        for f in sorted(src_dir.rglob("*.rou.xml")):
            dst = dst_dir / f.relative_to(src_dir)
            if dst.is_file() and sha256(dst) == sha256(f):
                continue
            n += 1
            if not dry:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(f, dst)
    print(f"kit demand: {n} route files {'to copy' if dry else 'copied'} (B7, E14)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--resco", type=Path, required=True, help="RESCO checkout (root, contains resco_benchmark/)")
    ap.add_argument("--variant", choices=["e12", "e13"], default="e13")
    ap.add_argument("--kit", type=Path, help="also fill <kit>/e13/b7_demand and e14_demand (e.g. code/kit)")
    ap.add_argument("--force", action="store_true", help="accept a checkout at another commit")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    resco = args.resco.resolve()
    check_checkout(resco, args.force)
    apply_patch(resco, HERE / f"resco_{args.variant}.patch", args.dry_run)
    maps = json.loads((HERE / f"maps_{args.variant}.json").read_text(encoding="utf-8"))["maps"]
    fill_maps(resco, maps, args.dry_run)
    if args.kit:
        fill_kit(args.kit.resolve(), args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
