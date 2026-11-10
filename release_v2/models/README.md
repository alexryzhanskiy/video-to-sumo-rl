# Trained models

The checkpoints are in the Zenodo archive, https://doi.org/10.5281/zenodo.24030604, as `models.zip`. The GitHub folder `release_v2` holds only this README and `MODELS.csv`.

220 checkpoints, 548 MB: the final checkpoint of every DRL training run of E13 (160) and E12 (60). `MODELS.csv` lists each one with its experiment, rung, policy, RESCO agent, training load and map, training run, seeds, number of episodes, design flags, the `final_design` mark, file, size and SHA-256.

| Folder | Models | Count |
|---|---|---|
| `e13/L2/MPLight/` | **Final design** (`final_design` = 1): L2 MPLight, green 12–60 s by action masking, field phase order, all-red only after a change of street; selected by the pre-registered rules on the validation files only (`results/e13/selection_final.json`); one model per training load ×1.0, ×1.2, ×1.5 | 3 loads × 5 runs = 15 |
| `e13/L1/`, `e13/L2/` | Rungs L1 (free phase order) and L2 (field order) for the rewards IDQN-wait, IDQN-queue, MPLight, IDQN-pressure, per training load | 2 × 4 × 3 × 5 = 120 (incl. the final design) |
| `e13/L3/` | Longer training (300 episodes) for the two rewards selected after L1/L2 (MPLight, IDQN-queue), per load | 2 × 3 × 5 = 30 |
| `e13/L4/` | One model for all loads, trained on the 60-file mix (`demand/e13/mix`) | 2 × 5 = 10 |
| `e12/` | E12 policies (field clearance after every change, randomised training demand); these are also rung L0 of E13 | 4 × 3 × 5 = 60 |

Paths are `<experiment>/<rung>/<policy>/<load>/run<k>/` (E12 without the rung). File names are those RESCO saved: `agent_nC.pt` for the IDQN agents (one agent at node `nC`, 3.3–3.6 MB) and `agent.pt` for MPLight (0.04 MB). Training run k used `--tr k --seed 42+k` and SUMO seeds 42 + k + episode; the full RESCO flags of each run are in the `flags` column.

**Loading.** The checkpoints belong to the patched RESCO of `code/kit/resco_integration/` (`--variant e13` for `e13/`, `e12` for `e12/`), with the state, reward and design flags of their row in `MODELS.csv`. Frozen (greedy, no learning) evaluation: `code/kit/e13/e13.py` for E13, `code/kit/e12.py` and `code/kit/eval_frozen.py` (`--ckpt <file>`) for E12. The files are PyTorch pickles, as written by `torch.save`; load them only with code you trust.

**Source and checks.** Taken from the compute packs of the runs (`e13_pack_MyPC_20261030_0717.zip`, SHA-256 `92a6a8f327fcb537a650e741b3bcb373104d4de5ac377932b9048b0868f38805`; `e12_pack_MyPC_20261028_2247.zip`, SHA-256 `ff77573645f243a4a4b370d8d471c3f6f16756189256b652d8ac6b0422d594e5`). Each extracted file's SHA-256 equals the one the training driver recorded in `results/e13/train_runs.csv` or `results/e12/train_runs.csv`. The packs' other contents (tripinfo files, training logs, metric series) are not included.

Not included: the first-version policies re-evaluated in E3 (trained by a co-author for the first version of the article).
