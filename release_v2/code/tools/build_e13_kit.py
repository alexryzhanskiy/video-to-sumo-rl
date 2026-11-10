"""Build the E13 kit (option B) from the E12 kit: copy RESCO and apply the E13 changes (pre-registration v1).

Every change is an exact text replacement that must match once; every new line is marked '# E13'.
With the default flags (--mode e12 --allred_mode every --mplight_phase legacy, no --vtype, no --undeparted)
the patched code behaves exactly like the E12 code; the tests check this against E12 episodes.

E13 changes:
  - green-time tracking per signal (green phase, start time, elapsed);
  - all-red only when the green changes street (--allred_mode street; map_config 'phase_street');
  - green limits and phase order by action masking (--mode free|field, --min_green, --max_green);
  - IDQN state drq_norm1_pt = drq_norm1 + one row with elapsed green / 60 s and the green-phase one-hot;
  - MPLight phase input fixed to the green phase index 0-3 (--mplight_phase fixed; K32);
  - extra SUMO options: --vtype (calibrated DEFAULT_VEHTYPE) and --undeparted (tripinfo write-undeparted);
  - metrics log: the green phase after each decision (switch counts);
  - e13/baselines/intersection_act.net.xml (E6 actuated network) and e13/locked_test_hashes.txt (copies);
  - new maps for the E13 demand sets (validation, locked test, L4 mix), filled from revision/demand/e13.

  revision/.venv/Scripts/python.exe revision/tools/build_e13_kit.py --e12-kit revision/e12_kit \
      --out revision/e12_kit/e13 [--demand revision/demand/e13]
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

NEW_MAPS = {    # map -> (demand subfolder, end time)
    "prybuzka_va10": ("validation/x10", 1800), "prybuzka_va12": ("validation/x12", 1800),
    "prybuzka_va15": ("validation/x15", 1800),
    "prybuzka_vas1": ("validation/scenarios/S1", 1800), "prybuzka_vas2": ("validation/scenarios/S2", 1800),
    "prybuzka_vas3": ("validation/scenarios/S3", 1800), "prybuzka_vas4": ("validation/scenarios/S4", 1800),
    "prybuzka_lt10": ("locked_test/x10", 1800), "prybuzka_lt12": ("locked_test/x12", 1800),
    "prybuzka_lt15": ("locked_test/x15", 1800),
    "prybuzka_lts1": ("locked_test/scenarios/S1", 1800), "prybuzka_lts2": ("locked_test/scenarios/S2", 1800),
    "prybuzka_lts3": ("locked_test/scenarios/S3", 1800), "prybuzka_lts4": ("locked_test/scenarios/S4", 1800),
    "prybuzka_mix": ("mix", 1800),
}


def patch(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert text.count(old) == 1, f"{path.name}: expected 1 match, found {text.count(old)}:\n{old[:200]}"
    path.write_text(text.replace(old, new), encoding="utf-8")


def patch_resco(bench: Path) -> None:
    # ---------- traffic_signal.py: green-time tracking ----------
    ts = bench / "traffic_signal.py"
    patch(ts, "        self.sumo.trafficlight.setProgramLogic(self.id, logic)\n",
          "        self.sumo.trafficlight.setProgramLogic(self.id, logic)\n"
          "        self.green_phase = self.sumo.trafficlight.getPhase(self.id)    # E13: green-time tracking\n"
          "        self.green_start = self.sumo.simulation.getTime()    # E13\n")
    patch(ts, "    def set_phase(self):\n        self.sumo.trafficlight.setPhase(self.id, int(self.next_phase))\n",
          "    def set_phase(self):\n"
          "        if int(self.next_phase) != self.green_phase:    # E13: a new green starts now\n"
          "            self.green_phase = int(self.next_phase)    # E13\n"
          "            self.green_start = self.sumo.simulation.getTime()    # E13\n"
          "        self.sumo.trafficlight.setPhase(self.id, int(self.next_phase))\n\n"
          "    def green_elapsed(self):    # E13: seconds since the current green started\n"
          "        return self.sumo.simulation.getTime() - self.green_start    # E13\n")

    # ---------- multi_signal.py: clearance mode, legal actions, extra SUMO options ----------
    ms = bench / "multi_signal.py"
    patch(ms, "warmup=0, gymma=False, seed:int=GLOBAL_SEED, allred_length=0):\n",
          "warmup=0, gymma=False, seed:int=GLOBAL_SEED, allred_length=0,\n"
          "                 allred_mode='every', green_limits=None, order='free', phase_street=None, sumo_extra=()):    # E13\n"
          "        self.allred_mode = allred_mode    # E13: 'every' change (E12) or only when the green changes 'street'\n"
          "        self.green_limits = green_limits    # E13: (min, max) green in s, or None = no limits (E12)\n"
          "        self.order = order    # E13: 'free' = any phase, 'field' = current or next in the field order\n"
          "        self.phase_street = phase_street    # E13: street of each green phase\n"
          "        self.sumo_extra = list(sumo_extra)    # E13: extra SUMO options for every episode\n"
          "        if allred_mode == 'street' and phase_street is None:    # E13\n"
          "            raise Exception('allred_mode street needs phase_street in map_config')    # E13\n")
    patch(ms, "                          '--no-warnings', 'True']\n        if self.libsumo:\n            traci.start(self.sumo_cmd)\n",
          "                          '--no-warnings', 'True']\n"
          "        self.sumo_cmd += self.sumo_extra    # E13\n"
          "        if self.libsumo:\n            traci.start(self.sumo_cmd)\n")
    patch(ms, "        # Send actions to their signals\n        for signal in self.signals:\n",
          "        # Send actions to their signals\n"
          "        prev_green = {signal: self.signals[signal].green_phase for signal in self.signals}    # E13\n"
          "        for signal in self.signals:\n")
    patch(ms, "            changing = [signal for signal in self.signal_ids if self.signals[signal].changing]\n",
          "            changing = [signal for signal in self.signal_ids if self.signals[signal].changing\n"
          "                        and (self.allred_mode == 'every'    # E13: else all-red only at a street change\n"
          "                             or self.phase_street[prev_green[signal]]\n"
          "                             != self.phase_street[int(self.signals[signal].next_phase)])]\n")
    patch(ms, "    def calc_metrics(self, rewards):\n",
          "    def legal_actions(self):    # E13: actions allowed by the green limits and the phase order\n"
          "        if self.green_limits is None:    # E13: no limits (E12)\n"
          "            return None\n"
          "        g_min, g_max = self.green_limits\n"
          "        legal = dict()\n"
          "        for ts in self.signal_ids:\n"
          "            sig = self.signals[ts]\n"
          "            cur, n = sig.green_phase, len(self.phases[ts])\n"
          "            nxt = (cur + 1) % n\n"
          "            elapsed = sig.green_elapsed()\n"
          "            if elapsed < g_min:    # minimum green not reached: keep the green\n"
          "                legal[ts] = [cur]\n"
          "            elif elapsed + self.step_length > g_max:    # holding would exceed the maximum green: change\n"
          "                legal[ts] = [nxt] if self.order == 'field' else [a for a in range(n) if a != cur]\n"
          "            else:\n"
          "                legal[ts] = sorted({cur, nxt}) if self.order == 'field' else list(range(n))\n"
          "        return legal\n\n"
          "    def calc_metrics(self, rewards):\n")
    # metrics log: the green phase after each decision (switch counts; no effect on the simulation)
    patch(ms, "            'queue_lengths': queue_lengths\n        })\n",
          "            'queue_lengths': queue_lengths,\n"
          "            'green': {s: self.signals[s].green_phase for s in self.signals}    # E13: switch counts\n"
          "        })\n")
    patch(ms, "                for metric in ['step', 'reward', 'max_queues', 'queue_lengths']:\n",
          "                for metric in ['step', 'reward', 'max_queues', 'queue_lengths', 'green']:    # E13\n")

    # ---------- states.py: MPLight phase fix (K32) and the E13 IDQN state ----------
    st = bench / "states.py"
    text = st.read_text(encoding="utf-8")
    a, b = text.index("def mplight(signals):"), text.index("def mplightCO2(signals):")
    old = "        mplight_phase = raw_phase // 2    # 0 or 1\n"
    assert text[a:b].count(old) == 1
    text = text[:a] + text[a:b].replace(old, "        mplight_phase = raw_phase if MPLIGHT_PHASE_FIX else raw_phase // 2"
                                         "    # E13: fixed = green phase index 0-3 (K32)\n") + text[b:]
    first_def = text.index("\ndef ")
    text = (text[:first_def] + "\n\nMPLIGHT_PHASE_FIX = False    # E13: set by main.py --mplight_phase fixed\n" + text[first_def:]
            + "\n\ndef drq_norm1_pt(signals):    # E13: drq_norm1 + one row: elapsed green / 60 s and green-phase one-hot\n"
              "    observations = drq_norm1(signals)\n"
              "    for signal_id in observations:\n"
              "        signal = signals[signal_id]\n"
              "        obs = observations[signal_id]\n"
              "        row = np.zeros(obs.shape[-1])\n"
              "        assert 2 + signal.green_phase < len(row)\n"
              "        row[1] = signal.green_elapsed() / 60.0\n"
              "        row[2 + signal.green_phase] = 1.0\n"
              "        observations[signal_id] = np.concatenate([obs, row[None, None, :]], axis=1)\n"
              "    return observations\n")
    st.write_text(text, encoding="utf-8")

    # ---------- agents: action masking ----------
    dq = bench / "agents" / "pfrl_dqn.py"
    patch(dq, "    def act(self, observation, valid_acts=None, reverse_valid=None):\n        if isinstance(self.agent, SharedDQN):\n",
          "    def act(self, observation, valid_acts=None, reverse_valid=None, legal=None):\n"
          "        if legal is not None:    # E13: action masking (green limits, phase order)\n"
          "            if isinstance(self.agent, SharedDQN):\n"
          "                return masked_batch_act(self.agent, observation, legal)\n"
          "            return masked_batch_act(self.agent, [observation], [legal])[0]\n"
          "        if isinstance(self.agent, SharedDQN):\n")
    dq.write_text(dq.read_text(encoding="utf-8")
                  + "\n\ndef masked_batch_act(dqn, batch_obs, batch_legal):    # E13: greedy or epsilon-random among legal actions\n"
                    "    with torch.no_grad(), evaluating(dqn.model):\n"
                    "        batch_av = dqn._evaluate_model_and_update_recurrent_states(batch_obs)\n"
                    "        q = batch_av.q_values.detach().cpu().numpy()\n"
                    "    acts = []\n"
                    "    for i, legal in enumerate(batch_legal):\n"
                    "        act = max(legal, key=lambda a: q[i][a])    # ties: first legal action\n"
                    "        if dqn.training:\n"
                    "            dqn.explorer.epsilon = dqn.explorer.compute_epsilon(dqn.t)\n"
                    "            if np.random.rand() < dqn.explorer.epsilon:\n"
                    "                act = legal[np.random.randint(len(legal))]\n"
                    "        acts.append(int(act))\n"
                    "    if dqn.training:\n"
                    "        dqn.batch_last_obs = list(batch_obs)\n"
                    "        dqn.batch_last_action = list(acts)\n"
                    "    return acts\n", encoding="utf-8")
    ag = bench / "agents" / "agent.py"
    patch(ag, "    def act(self, observation):\n        acts = dict()\n        for agent_id in observation.keys():\n"
              "            acts[agent_id] = self.agents[agent_id].act(observation[agent_id])\n",
          "    def act(self, observation, legal=None):\n        acts = dict()\n        for agent_id in observation.keys():\n"
          "            if legal is None:\n"
          "                acts[agent_id] = self.agents[agent_id].act(observation[agent_id])\n"
          "            else:    # E13\n"
          "                acts[agent_id] = self.agents[agent_id].act(observation[agent_id], legal=legal[agent_id])\n")
    patch(ag, "    def act(self, observation):\n        if self.reverse_valid is None",
          "    def act(self, observation, legal=None):\n"
          "        if legal is not None:    # E13: action masking, one batch item per signal\n"
          "            batch_acts = self.agent.act([observation[a] for a in observation.keys()],\n"
          "                                        legal=[legal[a] for a in observation.keys()])\n"
          "            return {a: batch_acts[i] for i, a in enumerate(observation.keys())}\n"
          "        if self.reverse_valid is None")

    # ---------- main.py: options, state, environment, masked loop ----------
    mn = bench / "main.py"
    patch(mn, "        ap.add_argument(\"--seed\", type=int, default=None)\n",
          "        ap.add_argument(\"--seed\", type=int, default=None)\n"
          "        # E13: green limits and phase order (action masking), clearance mode, MPLight phase, SUMO extras\n"
          "        ap.add_argument(\"--mode\", type=str, default='e12', choices=['e12', 'free', 'field'])\n"
          "        ap.add_argument(\"--min_green\", type=int, default=12)\n"
          "        ap.add_argument(\"--max_green\", type=int, default=60)\n"
          "        ap.add_argument(\"--allred_mode\", type=str, default='every', choices=['every', 'street'])\n"
          "        ap.add_argument(\"--mplight_phase\", type=str, default='legacy', choices=['legacy', 'fixed'])\n"
          "        ap.add_argument(\"--vtype\", type=str, default=None)    # additional file overriding DEFAULT_VEHTYPE\n"
          "        ap.add_argument(\"--undeparted\", action='store_true')    # tripinfo write-undeparted\n")
    patch(mn, "                                'prybuzka_tr10', 'prybuzka_tr12', 'prybuzka_tr15'    # E12\n",
          "                                'prybuzka_tr10', 'prybuzka_tr12', 'prybuzka_tr15',    # E12\n"
          + "".join(f"                                '{m}',    # E13\n" for m in NEW_MAPS))
    patch(mn, "    map_config = map_configs[args.map]\n",
          "    import resco_benchmark.states as e13_states    # E13\n"
          "    e13_states.MPLIGHT_PHASE_FIX = (args.mplight_phase == 'fixed')    # E13\n"
          "    if args.mode != 'e12' and agt_config['state'] is e13_states.drq_norm1:    # E13: + phase and elapsed green\n"
          "        agt_config['state'] = e13_states.drq_norm1_pt\n"
          "    sumo_extra = (['--tripinfo-output.write-undeparted'] if args.undeparted else [])    # E13\n"
          "    if args.vtype:    # E13\n"
          "        if not os.path.isfile(args.vtype): raise FileNotFoundError(args.vtype)\n"
          "        sumo_extra += ['-a', os.path.abspath(args.vtype)]\n"
          "    map_config = map_configs[args.map]\n")
    patch(mn, "                      seed=GLOBAL_SEED + trial, allred_length=args.allred)\n",
          "                      seed=GLOBAL_SEED + trial, allred_length=args.allred,\n"
          "                      allred_mode=args.allred_mode, order=args.mode, sumo_extra=sumo_extra,    # E13\n"
          "                      green_limits=None if args.mode == 'e12' else (args.min_green, args.max_green),\n"
          "                      phase_street=map_config.get('phase_street'))\n")
    patch(mn, "            act = agent.act(obs)\n",
          "            legal = env.legal_actions()    # E13: None without green limits\n"
          "            act = agent.act(obs) if legal is None else agent.act(obs, legal=legal)\n")

    # ---------- configs: maps and phase streets ----------
    mc = bench / "config" / "map_config.py"
    mc.write_text(mc.read_text(encoding="utf-8")
                  + "\n# E13: maps for the E13 demand sets (validation, locked test, L4 mix)\n"
                  + "".join(f"map_configs['{m}'] = {{'lights': ['nC'], 'net': 'environments/{m}/intersection.net.xml', "
                            f"'route': 'environments/{m}/routes/gen', 'step_length': 5, 'yellow_length': 3, "
                            f"'step_ratio': 1, 'start_time': 0, 'end_time': {end}, 'warmup': 0}}    # E13\n"
                            for m, (_, end) in NEW_MAPS.items())
                  + "# E13: street of each green phase (0, 1 = Svobody; 2, 3 = Prybuzka), for all-red at street changes\n"
                  "for _m in list(map_configs):\n"
                  "    if _m.startswith('prybuzka'):\n"
                  "        map_configs[_m]['phase_street'] = [0, 0, 1, 1]\n", encoding="utf-8")
    sc = bench / "config" / "signal_config.py"
    sc.write_text(sc.read_text(encoding="utf-8")
                  + "# E13: the E13 maps use the same network and signal\n"
                  + "".join(f"signal_configs['{m}'] = signal_configs['prybuzka']    # E13\n" for m in NEW_MAPS),
                  encoding="utf-8")


def fill_maps(bench: Path, demand: Path) -> dict:
    """Map folders: the E12 network and the route files, the first named gen_1.rou.xml (RESCO's init file)."""
    net = bench / "environments" / "prybuzka_ho10" / "intersection.net.xml"
    counts = {}
    for m, (sub, _) in NEW_MAPS.items():
        files = sorted((demand / sub).glob("*.rou.xml"))
        if m == "prybuzka_mix":    # E13 L4: all 60 mix files, in one fixed seeded order (RESCO cycles them)
            import numpy as np
            files = sorted((demand / sub).rglob("*.rou.xml"), key=lambda f: int(f.stem.split("_s")[-1].split(".")[0]))
            files = [files[i] for i in np.random.default_rng(6100).permutation(len(files))]
        if not files:
            counts[m] = 0
            continue
        routes = bench / "environments" / m / "routes"
        routes.mkdir(parents=True, exist_ok=True)
        shutil.copy2(net, routes.parent / "intersection.net.xml")
        for i, f in enumerate(files, 1):
            seed = f.stem.split("_s")[-1].split(".")[0]
            shutil.copy2(f, routes / ("gen_1.rou.xml" if i == 1 else f"gen_1_r{i:02d}_s{seed}.rou.xml"))
        (routes.parent / "route_order.txt").write_text(    # E13: which demand file each route file is
            "".join(f"{i:02d} {f.relative_to(demand).as_posix()}\n" for i, f in enumerate(files, 1)), encoding="utf-8")
        counts[m] = len(files)
    return counts


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--e12-kit", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--demand", type=Path, default=None, help="revision/demand/e13 (maps are filled if given)")
    args = ap.parse_args()
    dst = args.out / "resco"
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(args.e12_kit / "resco", dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    bench = dst / "resco_benchmark"
    patch_resco(bench)
    print("patched:", bench)
    # baselines (pre-registration 6.1): the actuated network of E6, unchanged; locked-test hash list (section 3)
    repo = Path(__file__).resolve().parents[2]
    (args.out / "baselines").mkdir(parents=True, exist_ok=True)
    shutil.copy2(repo / "sumo" / "intersection_act.net.xml", args.out / "baselines" / "intersection_act.net.xml")
    shutil.copy2(repo / "revision" / "prereg" / "locked_test_hashes.txt", args.out / "locked_test_hashes.txt")
    if args.demand:
        for m, n in fill_maps(bench, args.demand).items():
            print(f"{m:16s} {n} route files")


if __name__ == "__main__":
    main()
