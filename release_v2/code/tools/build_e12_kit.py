"""Build the RESCO part of the E12 compute kit (revision/e12_kit/).

Copies the eval kit's patched RESCO (revision/resco_eval/resco) and adds, all marked `E12`:
  - training maps prybuzka_tr10 / _tr12 / _tr15: same network, 20 routeSampler realizations each
    (revision/demand/train, seeds 3001-3020; gen_1.rou.xml is the first seed, as in the held-out maps);
  - reward `pressure_inout` and agent `IDQN_pressure_inout` (genuine pressure: vehicles on the outgoing
    lanes minus vehicles on the incoming lanes, per incoming lane);
  - `--seed` in main.py (seeds random, numpy and torch for a training run); no beep when RESCO_NO_BEEP is set.
Also copies the original checkpoint used by `e12.py verify`. The driver, scripts and README of the kit are
written separately and are not touched here.

From the repository root:
  python revision/tools/build_e12_kit.py --out revision/e12_kit [--force]
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

SRC = Path("revision/resco_eval/resco")
TRAIN = Path("revision/demand/train")
VERIFY_CKPT = sorted(Path("revision/incoming/2026-10-28/answers/step_0/a_resco_results").glob(
    "IDQN-tr4-prybuzka-1-drq_norm1-pressure_norm==7c226dc666ef433598fcafd821c283a8/agent_nC.pt"))
MAPS = {"prybuzka_tr10": ("x10", 1500), "prybuzka_tr12": ("x12", 1800), "prybuzka_tr15": ("x15", 1800)}

REWARD = '''

def pressure_inout(signals):
    # E12: genuine pressure for an isolated junction (as in sumo-rl): vehicles on the outgoing lanes minus
    # vehicles on the incoming lanes, divided by the number of incoming lanes like pressure_norm. `pressure`
    # subtracts outgoing queues only where a downstream signal exists, so on one junction it is the inbound queue.
    rewards = dict()
    for signal_id in signals:
        signal = signals[signal_id]
        out_lanes = {link[0][1] for link in signal.links if link}
        n_in = sum(signal.sumo.lane.getLastStepVehicleNumber(lane) for lane in signal.lanes)
        n_out = sum(signal.sumo.lane.getLastStepVehicleNumber(lane) for lane in out_lanes)
        rewards[signal_id] = (n_out - n_in) / max(1, len(signal.lanes))
    return rewards
'''

AGENT = """    'IDQN_pressure_inout': {                # E12: same IDQN, genuine pressure reward
        'agent': IDQN,
        'state': states.drq_norm1,
        'reward': rewards.pressure_inout,
        'max_distance': 200,
        'BATCH_SIZE': 64,
        'GAMMA': 0.99,
        'EPS_START': 1.0,
        'EPS_END': 0.0,
        'EPS_DECAY': 640,
        'TARGET_UPDATE': 500
    },
    'IPPO': {
"""

S4_END = """        'route': 'environments/prybuzka_s4/routes/gen',
        'step_length': 5, 'yellow_length': 3, 'step_ratio': 1,
        'start_time': 0, 'end_time': 1800, 'warmup': 0
    },
"""


def map_entry(name: str, load: str, end: int) -> str:
    return (f"    '{name}': {{                   # E12 training {load}, 20 route files (seeds 3001-3020)\n"
            f"        'lights': ['nC'],\n"
            f"        'net': 'environments/{name}/intersection.net.xml',\n"
            f"        'route': 'environments/{name}/routes/gen',\n"
            f"        'step_length': 5, 'yellow_length': 3, 'step_ratio': 1,\n"
            f"        'start_time': 0, 'end_time': {end}, 'warmup': 0\n"
            f"    }},\n")


def patch(path: Path, pairs: list[tuple[str, str]]) -> None:
    text = path.read_text(encoding="utf-8")
    for old, new in pairs:
        if text.count(old) != 1:
            sys.exit(f"{path}: expected one match of {old[:60]!r}, found {text.count(old)}")
        text = text.replace(old, new)
    path.write_text(text, encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--force", action="store_true", help="replace an existing resco/ copy")
    args = ap.parse_args()
    resco = args.out / "resco"
    if resco.exists():
        if not args.force:
            sys.exit(f"{resco} exists (use --force)")
        shutil.rmtree(resco)
    shutil.copytree(SRC, resco, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    bench = resco / "resco_benchmark"

    for name, (load, _) in MAPS.items():
        files = sorted((TRAIN / load).glob(f"train_{load}_s*.rou.xml"),
                       key=lambda p: int(re.search(r"_s(\d+)\.rou\.xml$", p.name).group(1)))
        if len(files) != 20:
            sys.exit(f"{TRAIN / load}: {len(files)} training files, expected 20")
        env = bench / "environments" / name
        (env / "routes").mkdir(parents=True)
        shutil.copy2(bench / "environments" / "prybuzka" / "intersection.net.xml", env)
        for i, f in enumerate(files, 1):
            seed = re.search(r"_s(\d+)\.rou\.xml$", f.name).group(1)
            dest = "gen_1.rou.xml" if i == 1 else f"gen_1_r{i:02d}_s{seed}.rou.xml"
            shutil.copy2(f, env / "routes" / dest)

    maps = "".join(map_entry(n, load, end) for n, (load, end) in MAPS.items())
    patch(bench / "config" / "map_config.py", [(S4_END, S4_END + "    # E12: training maps\n" + maps)])
    patch(bench / "config" / "signal_config.py", [
        ("'prybuzka_s1', 'prybuzka_s2', 'prybuzka_s3', 'prybuzka_s4']:",
         "'prybuzka_s1', 'prybuzka_s2', 'prybuzka_s3', 'prybuzka_s4',\n"
         "           'prybuzka_tr10', 'prybuzka_tr12', 'prybuzka_tr15']:    # E12 training maps")])
    patch(bench / "config" / "agent_config.py", [("    'IPPO': {\n", AGENT)])
    rewards = bench / "rewards.py"
    rewards.write_text(rewards.read_text(encoding="utf-8").rstrip("\n") + "\n" + REWARD, encoding="utf-8")
    patch(bench / "main.py", [
        ("'IDQN_start_stop',", "'IDQN_start_stop', 'IDQN_pressure_inout',"),
        ("'prybuzka_s1', 'prybuzka_s2', 'prybuzka_s3', 'prybuzka_s4'\n",
         "'prybuzka_s1', 'prybuzka_s2', 'prybuzka_s3', 'prybuzka_s4',\n"
         "                                'prybuzka_tr10', 'prybuzka_tr12', 'prybuzka_tr15'    # E12\n"),
        ('        ap.add_argument("--allred", type=int, default=0)\n',
         '        ap.add_argument("--allred", type=int, default=0)\n'
         '        # E12: seed random, numpy and torch for this run; None = original behaviour\n'
         '        ap.add_argument("--seed", type=int, default=None)\n'),
        ("def run_trial(args, trial):\n",
         "def run_trial(args, trial):\n"
         "    if args.seed is not None:    # E12\n"
         "        import torch\n"
         "        set_random_seeds(args.seed)\n"
         "        torch.manual_seed(args.seed)\n"),
        ("    pretty_beep_sequence()\n\n\nif __name__",
         "    if not os.environ.get('RESCO_NO_BEEP'):    # E12: parallel runs\n"
         "        pretty_beep_sequence()\n\n\nif __name__"),
    ])

    if len(VERIFY_CKPT) != 1:
        sys.exit("original IDQN-queue x1.0 run 4 checkpoint not found")
    (args.out / "verify").mkdir(parents=True, exist_ok=True)
    shutil.copy2(VERIFY_CKPT[0], args.out / "verify" / "idqn_queue_x10_run4.pt")
    print(f"built {resco} and {args.out / 'verify'}")


if __name__ == "__main__":
    main()
