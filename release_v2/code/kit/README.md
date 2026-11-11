# E12/E13 compute kit (drivers only)

The drivers that ran E12, E13, B7 and E14 on one CPU-only Windows 11 PC (16 threads, Python 3.13, SUMO 1.26.0 with libsumo). The RESCO copy they need is rebuilt from upstream RESCO with `resco_integration/` (see its README); the B7 and E14 route files are copied into `e13/b7_demand/` and `e13/e14_demand/` by the same script (`--kit`).

| File | What |
|---|---|
| `requirements.txt`, `setup.ps1` | Pinned environment (uv, Python 3.13) and the one-time set-up with checks |
| `e12.py`, `run_e12.ps1`, `start_e12.ps1` | E12 driver: retraining of four policies with the field clearance and randomised demand; frozen evaluation |
| `eval_frozen.py` | Frozen evaluation of trained policies (E3) |
| `verify/reference.json` | Reference hashes for `verify` (needs the first-version IDQN-queue checkpoint, which is not in this package; available from the first author on request) |
| `e13/e13.py` | E13 driver: verify, bench, baselines (fixed, actuated), ladder rungs L0–L4, selection rules 5.1/5.2, B1 replay, the locked test (once, hash-checked), status, pack |
| `e13/b1_replay.py` | B1 replay recorder (byte-identical replays) |
| `e13/b7.py` | The final design on the B7 perception-error demand (and E14) |
| `e13/repair.py` | Recovery of state files cut off by a power cut |
| `e13/extract_co2.py`, `e13/extract_queue_lt15.py` | CO2 per episode from tripinfo; queue series of the final design on the locked ×1.5 files |
| `e13/twin.json` | The twin used by every E13 run (`default`: SUMO's default vehicle, after B6) |
| `e13/locked_test_hashes.txt` | Pre-registered SHA-256 of the 50 locked route files |
| `e13/baselines/intersection_act.net.xml` | Actuated network for the actuated baseline (same as `network/intersection_act.net.xml`) |
| `e13/start_e13.ps1`, `e13/run_e13.ps1` | Windows wrappers that run `e13.py all` in their own window |

Operator messages in the drivers name the corresponding author, who decided when the locked test ran; the `publish` and `pack` commands uploaded results to the authors' private compute repository and do nothing useful outside it. Results of the runs are in `../../results/e13/` and `../../results/e12/`; the per-episode metric definitions are in section 4 of the pre-registration (`../../prereg/`).
