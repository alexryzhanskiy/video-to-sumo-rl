"""Apply this work's RESCO integration to an upstream RESCO checkout.

RESCO is not bundled with this repository (it has its own, non-MIT licence). Clone it
yourself, then point this script at the clone: it adds the `prybuzka` maps, the signal
configuration, the `pressure_norm` reward and the `IDQN_pressure` agent, copies the SUMO
network and the reconstructed demand into `environments/`, and makes the few one-line edits
that the published runs need: the argparse choices, the SUMO flag that keeps unfinished trips
in tripinfo, and the two that make a run reproducible (fixed seed, fixed demand file).

Every change is idempotent: running the script twice leaves the checkout unchanged.

Usage:
    python resco_integration/apply_to_resco.py --resco /path/to/RESCO
    python resco_integration/apply_to_resco.py --resco /path/to/RESCO --dry-run
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
MARKER = "# >>> video-to-sumo-rl"

# patch file -> (target relative to <resco>/resco_benchmark/, text that means "already there").
# The probe is what the patch defines, not our marker: a checkout that already carries these
# entries inline (for instance the authors' own working copy) must not get them twice.
APPENDS = {
    "map_config.append.py": ("config/map_config.py", "'prybuzka'"),
    "signal_config.append.py": ("config/signal_config.py", "'prybuzka'"),
    "agent_config.append.py": ("config/agent_config.py", "'IDQN_pressure'"),
    "rewards.append.py": ("rewards.py", "def pressure_norm"),
}

# our SUMO files -> environments/<map>/
MAPS = {
    "prybuzka": "sumo/demand.rou.xml",
    "prybuzka_12": "sumo/demand_12.rou.xml",
    "prybuzka_15": "sumo/demand_15.rou.xml",
}

CHOICES = {"--agent": ["IDQN_pressure"], "--map": ["prybuzka", "prybuzka_12", "prybuzka_15"]}

# Reproducibility of the published runs, in multi_signal.py. Upstream RESCO seeds SUMO with
# `--random` and loads a separate route file per trial; the numbers reported for this work come
# from seeded runs that all share one demand file, so both have to be pinned here. Each entry is
# (upstream text, replacement, what it does) and is skipped when the upstream text is absent —
# which is also the case for a checkout that already carries the change.
SEED = 42   # SUMO gets SEED + tr, so trials 1..5 are seeds 43..47
DETERMINISM = (
    ("'--random'", f"'--seed', str({SEED} + self.run)", f"SUMO seed = {SEED} + tr"),
    ("self.route + '_'+str(self.run)+'.rou.xml'", "self.route + '_1.rou.xml'",
     "one demand file for every trial"),
)


class Patcher:
    def __init__(self, dry_run: bool) -> None:
        self.dry_run = dry_run
        self.changed = 0
        self.skipped = 0
        self.failed = 0

    def say(self, status: str, msg: str) -> None:
        print(f"[{status}] {msg}")
        if status == "patched":
            self.changed += 1
        elif status == "present":
            self.skipped += 1
        elif status == "FAILED":
            self.failed += 1

    def write(self, path: Path, text: str) -> None:
        if not self.dry_run:
            path.write_text(text, encoding="utf-8")

    def copy(self, src: Path, dst: Path) -> None:
        if not self.dry_run:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)


def add_choices(text: str, option: str, values: list[str]) -> tuple[str, str]:
    """Add missing values to the `choices=[...]` list of one argparse option."""
    opt = text.find(f'"{option}"')
    if opt < 0:
        opt = text.find(f"'{option}'")
    if opt < 0:
        return text, f"option {option} not found"
    start = text.find("choices=[", opt)
    if start < 0:
        return text, f"choices=[ not found for {option}"
    end = text.find("]", start)
    if end < 0:
        return text, f"unterminated choices list for {option}"
    body = text[start:end]
    missing = [v for v in values if f"'{v}'" not in body and f'"{v}"' not in body]
    if not missing:
        return text, "present"
    insert = ", " + ", ".join(f"'{v}'" for v in missing)
    return text[:end].rstrip().rstrip(",") + insert + text[end:], "patched"


def main() -> None:
    ap = argparse.ArgumentParser(description="Apply the RESCO integration of this work")
    ap.add_argument("--resco", required=True, help="path to an upstream RESCO checkout")
    ap.add_argument("--dry-run", action="store_true", help="report what would change, write nothing")
    args = ap.parse_args()

    resco = Path(args.resco).resolve()
    bench = resco / "resco_benchmark"
    if not (bench / "config" / "map_config.py").exists():
        raise SystemExit(f"Not a RESCO checkout (no resco_benchmark/config/map_config.py): {resco}")

    p = Patcher(args.dry_run)
    if args.dry_run:
        print("--- dry run: nothing will be written ---")

    # 1. append our configuration blocks
    for patch_name, (target_rel, probe) in APPENDS.items():
        target = bench / target_rel
        patch = HERE / "patches" / patch_name
        if not target.exists():
            p.say("FAILED", f"{target_rel}: file not found in the checkout")
            continue
        text = target.read_text(encoding="utf-8")
        if MARKER in text or probe in text:
            p.say("present", f"{target_rel}: already defines {probe}")
            continue
        p.write(target, text.rstrip("\n") + "\n\n\n" + patch.read_text(encoding="utf-8"))
        p.say("patched", f"{target_rel}: appended {patch_name}")

    # 2. network + reconstructed demand
    net_src = REPO / "sumo" / "intersection.net.xml"
    for map_name, demand_rel in MAPS.items():
        env = bench / "environments" / map_name
        route_dst = env / "routes" / "gen_1.rou.xml"   # RESCO loads <prefix>_1.rou.xml
        net_dst = env / "intersection.net.xml"
        demand_src = REPO / demand_rel
        for src, dst in ((net_src, net_dst), (demand_src, route_dst)):
            if not src.exists():
                p.say("FAILED", f"{map_name}: missing source {src}")
                continue
            if dst.exists() and dst.read_bytes() == src.read_bytes():
                p.say("present", f"environments/{map_name}/{dst.name}: identical")
                continue
            p.copy(src, dst)
            p.say("patched", f"environments/{map_name}/{dst.name}: copied from {src.name}")

    # 3. argparse choices in main.py
    main_py = bench / "main.py"
    if main_py.exists():
        text = main_py.read_text(encoding="utf-8")
        for option, values in CHOICES.items():
            text, status = add_choices(text, option, values)
            if status == "patched":
                p.say("patched", f"main.py: {option} choices += {values}")
            elif status == "present":
                p.say("present", f"main.py: {option} choices already complete")
            else:
                p.say("FAILED", f"main.py: {status} — add {values} to the {option} choices by hand")
        p.write(main_py, text)
    else:
        p.say("FAILED", "main.py not found in the checkout")

    # 4. keep unfinished trips in tripinfo (vehicles still in the network at the end).
    #    Without this flag the throughput of a congested episode is silently overstated.
    ms = bench / "multi_signal.py"
    flag = "--tripinfo-output.write-unfinished"
    if not ms.exists():
        p.say("FAILED", "multi_signal.py not found in the checkout")
    else:
        text = ms.read_text(encoding="utf-8")
        if flag in text:
            p.say("present", "multi_signal.py: write-unfinished already set")
        else:
            lines = text.splitlines(keepends=True)
            at = next((i for i, l in enumerate(lines) if "'tripinfo_' + str(self.run)" in l), None)
            if at is None:
                p.say("FAILED", f"multi_signal.py: anchor not found — add '{flag}' to sumo_cmd by hand")
            else:
                indent = " " * (len(lines[at]) - len(lines[at].lstrip()))
                lines.insert(at + 1, f"{indent}'{flag}',\n")
                p.write(ms, "".join(lines))
                p.say("patched", f"multi_signal.py: added {flag}")

    # 5. make a run reproducible: fixed SUMO seed, and the same demand file for every trial.
    #    Without these, a reproduction is non-deterministic and dies on --tr 2, because each
    #    map ships exactly one demand file (routes/gen_1.rou.xml).
    if ms.exists():
        text = ms.read_text(encoding="utf-8")
        patched = text
        for old, new, what in DETERMINISM:
            if old not in patched:
                p.say("present", f"multi_signal.py: {what} already in place")
                continue
            patched = patched.replace(old, new)
            p.say("patched", f"multi_signal.py: {what}")
        if patched != text:
            p.write(ms, patched)

    print(f"\n{p.changed} changed, {p.skipped} already in place, {p.failed} need manual work")
    if p.failed:
        raise SystemExit("some steps failed — see resco_integration/README.md for the manual edits")


if __name__ == "__main__":
    main()
