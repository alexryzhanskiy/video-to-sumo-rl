# RESCO integration

RESCO is **not bundled** with this repository. It carries its own licence
(CC BY-NC-SA 4.0: attribution, non-commercial, share-alike), which cannot be re-released
under MIT, so this repository ships only the code written for this work and the steps that
reproduce the RL experiments on top of an upstream RESCO checkout.

## Reproduce

```bash
git clone -c core.longpaths=true https://github.com/Pi-Star-Lab/RESCO.git
git -C RESCO checkout fc65e91                                 # the commit this was verified on
python resco_integration/apply_to_resco.py --resco RESCO      # add our maps + reward + agent
cd RESCO/resco_benchmark
python main.py --agent IDQN --map prybuzka --eps 100 --tr 1 --procs 1
```

Upstream has since moved on to RESCO v2.0 (`f1ed9a1`); the integration has not been tested there,
so use the commit above. `core.longpaths` is needed only on Windows and is harmless elsewhere.

Add `--dry-run` to see what the script would change and write nothing. Every step is
idempotent: a second run reports `already in place` and leaves the checkout untouched.
The experiments in the paper were run on a RESCO-CO2 fork, which adds the emission
utilities; the integration itself does not depend on them.

## What the script does

| Target in `resco_benchmark/` | Change |
|---|---|
| `config/map_config.py` | adds `prybuzka`, `prybuzka_12`, `prybuzka_15` (step_length 5 s, yellow 3 s, end_time 1500 / 1800 / 1800 s) |
| `config/signal_config.py` | adds the signal entry: the four action phases and the lane sets of our network |
| `config/agent_config.py` | adds `IDQN_pressure` — stock IDQN hyper-parameters, `pressure_norm` reward |
| `rewards.py` | adds the `pressure_norm` reward |
| `environments/prybuzka*/` | copies `sumo/intersection.net.xml` and the reconstructed demand as `routes/gen_1.rou.xml` |
| `main.py` | adds the new names to the `--agent` and `--map` argparse choices |
| `multi_signal.py` | adds `--tripinfo-output.write-unfinished` to the SUMO command |
| `multi_signal.py` | replaces `--random` with `--seed 42 + tr`, so trials 1..5 are seeds 43..47 |
| `multi_signal.py` | loads `routes/gen_1.rou.xml` for every trial, not one file per trial |

On a fresh upstream checkout the script reports 14 changes and one step already in place
(`--tripinfo-output.write-unfinished`, which upstream already passes). On the working copy the
experiments were run on, it reports all 15 as already in place: the fork spells the last two
differently (`--seed self.seed_value + self.run` with `GLOBAL_SEED = 42`, and a glob over the
routes directory that finds the single demand file) but behaves identically.

**MPLight state.** The MPLight numbers in the main README come from runs that pass `signal.phase`
to FRAP, as upstream does, so a patched upstream checkout runs the same model. The first runs passed
`signal.phase // 2`, which fits a program of two green phases and hides the Prybuzka phases on this
four-phase signal; they were replaced.

The patch bodies are plain text in `patches/`, so they can also be pasted by hand if the
upstream layout changes and the script cannot find an anchor; it then says which edit to
make and exits non-zero.

## Two details that are easy to get wrong

**Route file naming, and one demand for every trial.** Upstream RESCO loads
`<prefix>_<trial>.rou.xml`, a separate demand per trial, which is why the script pins it to
`_1`: the demand of this work is one reconstructed matrix, and the five trials differ only in
the SUMO seed and the agent's initialisation. Left unpinned, `--tr 1` would run and `--tr 2`
would die on a missing `gen_2.rou.xml`. The demand must therefore land as
`environments/<map>/routes/gen_1.rou.xml`; a differently named file is ignored and the episode
runs empty.

**Unfinished trips.** Without `--tripinfo-output.write-unfinished`, SUMO omits vehicles
still in the network when the episode ends, and the throughput of a congested episode is
overstated — the metric then counts only the vehicles that made it. All numbers reported
for this work use the flag and count arrivals inside a common window.

**Phase indices come from the network.** RESCO takes the green phases straight from the
`tlLogic` of `intersection.net.xml` (a phase counts as green when its state string contains
`g` and no `y`) and inserts yellow itself. `netconvert` orders connections geometrically
(clockwise N, E, S, W) and ignores an explicit `linkIndex`, so the legs must be generated in
that order — otherwise the phase pairs in `signal_config` address the wrong movements.
`src/build_sumo_net.py` generates them in that order.
