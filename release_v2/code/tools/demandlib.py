"""Shared helpers for the revision demand tools (P01, Comments 1.5 and 1.9).

Not a command-line tool; imported by make_heldout.py, make_scenarios.py,
check_demand.py, sanity_fixed.py and package_handoff.py.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path

# Edge map of the Prybuzka-Svobody intersection (kb/02_REPOSITORY_GUIDE.md).
SVOBODY = ("nN_nC", "nS_nC")
PRYBUZKA = ("nE_nC", "nW_nC")
MOVEMENT = {
    ("nN_nC", "nC_nS"): "through", ("nN_nC", "nC_nE"): "left", ("nN_nC", "nC_nW"): "right",
    ("nS_nC", "nC_nN"): "through", ("nS_nC", "nC_nW"): "left", ("nS_nC", "nC_nE"): "right",
    ("nE_nC", "nC_nW"): "through", ("nE_nC", "nC_nS"): "left", ("nE_nC", "nC_nN"): "right",
    ("nW_nC", "nC_nE"): "through", ("nW_nC", "nC_nN"): "left", ("nW_nC", "nC_nS"): "right",
}
APPROACHES = ("nN_nC", "nS_nC", "nE_nC", "nW_nC")

# routeSampler stamps its output with the wall-clock time; it is removed so that the same
# seed gives a byte-identical file. The creation time goes to the generation log instead.
_STAMP_RE = re.compile(rb"<!-- generated on [^\r\n]*? by ")


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def posix(path: Path) -> str:
    """Path as written into command lines and logs (forward slashes, as in the originals)."""
    return Path(path).as_posix()


def round_half_up(x) -> int:
    """Conventional rounding (2.5 -> 3); Python's round() would give 2."""
    return math.floor(x + Fraction(1, 2))


def largest_remainder(values: list[Fraction], total: int) -> tuple[list[int], list[bool]]:
    """Round values to integers that sum to total; ties go to the earlier index.

    Values are exact fractions, so no float noise decides a tie. Returns the integers and,
    per value, whether it received the extra unit.
    """
    floors = [math.floor(v) for v in values]
    deficit = total - sum(floors)
    if deficit < 0 or deficit > len(values):
        raise ValueError(f"cannot distribute {deficit} units over {len(values)} values")
    order = sorted(range(len(values)), key=lambda i: (-(values[i] - floors[i]), i))
    bumped = [False] * len(values)
    for i in order[:deficit]:
        floors[i] += 1
        bumped[i] = True
    return floors, bumped


# --------------------------------------------------------------------------- turn counts

@dataclass
class Interval:
    id: str
    begin: str
    end: str
    relations: list[list] = field(default_factory=list)  # [from, to, count]

    @property
    def b(self) -> float:
        return float(self.begin)

    @property
    def e(self) -> float:
        return float(self.end)


def read_counts(path: Path) -> list[Interval]:
    root = ET.parse(path).getroot()
    out = []
    for iv in root.iter("interval"):
        rel = [[r.get("from"), r.get("to"), int(r.get("count"))] for r in iv.iter("edgeRelation")]
        out.append(Interval(iv.get("id"), iv.get("begin"), iv.get("end"), rel))
    return out


def write_counts(intervals: list[Interval], path: Path, comment: str | None = None) -> None:
    """Write turn counts in the layout of sumo/turn_counts_edges.xml (CRLF, 2-space indent).

    An optional comment is placed inside <data>, before the first interval.
    """
    lines = ["<data>"]
    if comment:
        lines.append(f"  <!-- {comment} -->")
    for iv in intervals:
        lines.append(f'  <interval id="{iv.id}" begin="{iv.begin}" end="{iv.end}">')
        for f, t, c in iv.relations:
            lines.append(f'    <edgeRelation from="{f}" to="{t}" count="{c}"/>')
        lines.append("  </interval>")
    lines.append("</data>")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="ascii", newline="\r\n") as f:
        f.write("\n".join(lines) + "\n")


def counts_table(intervals: list[Interval]) -> dict[tuple[str, str, str], int]:
    """(interval begin, from, to) -> count."""
    return {(iv.begin, f, t): c for iv in intervals for f, t, c in iv.relations}


def counts_total(intervals: list[Interval]) -> int:
    return sum(c for iv in intervals for _, _, c in iv.relations)


def interval_totals(intervals: list[Interval]) -> list[int]:
    return [sum(c for _, _, c in iv.relations) for iv in intervals]


def movement_totals(intervals: list[Interval]) -> dict[str, int]:
    tot = {"left": 0, "through": 0, "right": 0}
    for iv in intervals:
        for f, t, c in iv.relations:
            tot[MOVEMENT[(f, t)]] += c
    return tot


# --------------------------------------------------------------------------- route files

@dataclass
class Vehicle:
    id: str
    depart_str: str
    edges: str

    @property
    def depart(self) -> float:
        return float(self.depart_str)


def read_routes(path: Path) -> list[Vehicle]:
    """Vehicles of a routeSampler file (vehicle with inline <route edges=...>)."""
    root = ET.parse(path).getroot()
    out = []
    for v in root.iter("vehicle"):
        r = v.find("route")
        edges = v.get("route") if r is None else r.get("edges")
        out.append(Vehicle(v.get("id"), v.get("depart"), edges))
    return out


def vehicle_signature(vehicles: list[Vehicle]) -> str:
    h = hashlib.sha256()
    for v in vehicles:
        h.update(f"{v.id}|{v.depart_str}|{v.edges}\n".encode())
    return h.hexdigest()


def candidate_routes(path: Path) -> dict[str, str]:
    """edges -> route id of sumo/candidate.rou.xml."""
    return {r.get("edges"): r.get("id") for r in ET.parse(path).getroot().iter("route")}


# --------------------------------------------------------------------------- SUMO

def find_sumo_home(arg: str | None) -> Path:
    home = arg or os.environ.get("SUMO_HOME")
    if not home:
        try:
            import sumo  # eclipse-sumo wheel
            home = sumo.SUMO_HOME
        except ImportError:
            sys.exit("SUMO_HOME is not set; pass --sumo-home")
    home = Path(home)
    if not (home / "tools" / "routeSampler.py").is_file():
        sys.exit(f"routeSampler.py not found under {home}")
    return home


def sumo_binary(sumo_home: Path, name: str = "sumo") -> Path:
    for cand in (sumo_home / "bin" / f"{name}.exe", sumo_home / "bin" / name):
        if cand.is_file():
            return cand
    sys.exit(f"{name} binary not found under {sumo_home / 'bin'}")


def sumo_version(sumo_home: Path) -> str:
    out = subprocess.run([str(sumo_binary(sumo_home)), "--version"], capture_output=True, text=True).stdout
    first = out.splitlines()[0] if out else ""
    m = re.search(r"sumo\s+(\S+)", first)
    return m.group(1) if m else first.strip()


def sumo_env(sumo_home: Path) -> dict:
    env = dict(os.environ)
    env["SUMO_HOME"] = str(sumo_home)
    return env


def routesampler_cmd(python: str, sumo_home: Path, candidate: Path, counts: Path, out: Path,
                     seed: int | None = None, extra: list[str] | None = None) -> list[str]:
    cmd = [python, posix(sumo_home / "tools" / "routeSampler.py"),
           "-r", posix(candidate), "-t", posix(counts), "-o", posix(out)]
    if seed is not None:
        cmd += ["--seed", str(seed)]
    return cmd + list(extra or [])


def display_cmd(cmd: list[str], sumo_home: Path) -> str:
    """Command line for logs: interpreter as 'python', SUMO tools path as %SUMO_HOME%."""
    parts = ["python"] + cmd[1:]
    tools = posix(sumo_home / "tools")
    out = []
    for p in parts:
        p = p.replace(tools, "%SUMO_HOME%/tools")
        out.append(f'"{p}"' if (" " in p or "," in p) else p)
    return " ".join(out)


def run_routesampler(cmd: list[str], sumo_home: Path, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    res = subprocess.run(cmd, capture_output=True, text=True, env=sumo_env(sumo_home))
    if res.returncode != 0 or not out.is_file():
        sys.exit(f"routeSampler failed ({res.returncode}): {' '.join(cmd)}\n{res.stdout}\n{res.stderr}")
    strip_stamp(out)


def strip_stamp(path: Path) -> None:
    data = path.read_bytes()
    new = _STAMP_RE.sub(b"<!-- generated by ", data, count=1)
    if new != data:
        path.write_bytes(new)


# --------------------------------------------------------------------------- logs

def load_log(path: Path) -> dict:
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def save_log(log: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(log, indent=1, sort_keys=True) + "\n", encoding="utf-8")
