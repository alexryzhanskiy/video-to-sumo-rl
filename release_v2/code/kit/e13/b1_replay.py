#!/usr/bin/env python3
"""B1 replay (pre-registration section 9): run RESCO's main.py unchanged and record, for the chosen episodes,

  seconds_e<E>.csv    every simulated second: signal state, green phase (0-3, empty during yellow/all-red) and
                      the halting vehicles on every incoming lane;
  decisions_e<E>.csv  every 5-s decision: time, current green phase, elapsed green, the action, the Q-values
                      and the state vector the policy saw.

Recording only reads from SUMO and from the policy's own forward pass (pfrl DQN), so the episodes are identical to
an unrecorded run; e13.py replay checks this against the E12 tripinfo files.

  python b1_replay.py --out DIR --record 3,7 -- <main.py arguments>
Run with cwd = resco/resco_benchmark and PYTHONPATH = resco (e13.py replay does both).
"""
import argparse
import csv
import json
import os
import sys
from pathlib import Path

GREENS = {"GGGrsrrrGGGrsrrr": 0, "srrGsrrrsrrGsrrr": 1, "srrrGGGrsrrrGGGr": 2, "srrrsrrGsrrrsrrG": 3}
TLS = "nC"


def main() -> None:
    argv = sys.argv[1:]
    cut = argv.index("--")
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--record", required=True, help="episode numbers, comma-separated")
    args = ap.parse_args(argv[:cut])
    record = {int(x) for x in args.record.split(",")}
    args.out.mkdir(parents=True, exist_ok=True)
    bench = Path(__file__).resolve().parent / "resco" / "resco_benchmark"
    sys.path.insert(0, str(bench))
    os.chdir(bench)

    import numpy as np
    import multi_signal
    import pfrl.agents.dqn as pdqn

    traci = multi_signal.traci
    cur = {"obs": None, "q": None, "lanes": None, "sec": None, "dec": None, "files": []}

    def close_files():
        for f in cur["files"]:
            f.close()
        cur.update(files=[], sec=None, dec=None)

    orig_sim = traci.simulationStep

    def sim_step(*a, **k):
        r = orig_sim(*a, **k)
        if cur["sec"] is not None:
            state = traci.trafficlight.getRedYellowGreenState(TLS)
            cur["sec"].writerow([traci.simulation.getTime(), state, GREENS.get(state, "")]
                                + [traci.lane.getLastStepHaltingNumber(lane) for lane in cur["lanes"]])
        return r

    traci.simulationStep = sim_step

    orig_reset = multi_signal.MultiSignal.reset

    def reset(self):
        close_files()
        obs = orig_reset(self)
        cur["obs"] = obs
        if cur["lanes"] is None:
            cur["lanes"] = list(dict.fromkeys(traci.trafficlight.getControlledLanes(TLS)))
        if self.run in record:
            fs = open(args.out / f"seconds_e{self.run}.csv", "w", newline="", encoding="utf-8")
            fd = open(args.out / f"decisions_e{self.run}.csv", "w", newline="", encoding="utf-8")
            cur["files"] = [fs, fd]
            cur["sec"], cur["dec"] = csv.writer(fs), csv.writer(fd)
            cur["sec"].writerow(["time", "tls_state", "green_phase"] + [f"halting_{lane}" for lane in cur["lanes"]])
            cur["dec"].writerow(["time", "green_phase", "green_elapsed_s", "action", "q_values", "state"])
        return obs

    multi_signal.MultiSignal.reset = reset

    orig_step = multi_signal.MultiSignal.step

    def step(self, act):
        if cur["dec"] is not None:
            sig = self.signals[TLS]
            o = np.asarray(cur["obs"][TLS], dtype=float)
            cur["dec"].writerow([traci.simulation.getTime(), sig.green_phase, round(sig.green_elapsed(), 1),
                                 int(act[TLS]), json.dumps(cur["q"]), json.dumps(np.round(o, 5).ravel().tolist())])
        out = orig_step(self, act)
        cur["obs"] = out[0]
        return out

    multi_signal.MultiSignal.step = step

    orig_eval = pdqn.DQN._evaluate_model_and_update_recurrent_states

    def evaluate(self, batch_obs):
        av = orig_eval(self, batch_obs)
        try:
            cur["q"] = [round(float(x), 5) for x in av.q_values[0].detach().cpu().numpy().ravel()]
        except (AttributeError, IndexError, TypeError):
            cur["q"] = None
        return av

    pdqn.DQN._evaluate_model_and_update_recurrent_states = evaluate

    sys.argv = ["main.py"] + argv[cut + 1:]
    import main as resco_main
    resco_main.main()
    close_files()


if __name__ == "__main__":
    main()
