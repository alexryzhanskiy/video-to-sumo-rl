# From Urban Video to Adaptive Traffic Signals: data, code and models

Release package of the article *From Urban Video to Adaptive Traffic Signals: Digital Twin and Deep Reinforcement Learning under Real-World Demand* (O. Ryzhanskyi, O. Barmak, E. Manziuk, P. Radiuk, I. Krak; revised version, November 2026).

- Repository: https://github.com/alexryzhanskiy/video-to-sumo-rl, folder `release_v2` (everything except the trained models, which are in the Zenodo archive only)
- Archive: Zenodo, https://doi.org/10.5281/zenodo.24030604
- Original video-to-SUMO pipeline of the first version: https://github.com/alexryzhanskiy/video-to-sumo-rl (MIT, commit `27362e54d3c0e0088ff8407ef0756a713d6dd1df`)

The study turns urban video of one signalised intersection (Prybuzka–Svobody, Khmelnytskyi, Ukraine) into a SUMO digital twin with 5-min turning-movement counts, and trains and tests deep reinforcement learning (DRL) signal controllers on it against the field fixed plan, an actuated plan, tuned MaxPressure and Webster plans. This package holds everything needed to check and rerun the simulations and analyses. The raw videos are not included: they show licence plates and identifiable persons and were provided by Khmelnytskyi City Council for this study only.

**All simulations use SUMO 1.26.0** (the `eclipse-sumo`, `libsumo` and `sumolib` 1.26.0 wheels). Fixed-plan results differ between SUMO 1.26.0 and later versions such as 1.28.0, so use 1.26.0 when you compare numbers.

## Contents

| Folder | What | Licence |
|---|---|---|
| `network/` | SUMO network of the intersection with the field signal plan (`intersection.net.xml`), the actuated variant (`intersection_act.net.xml`), the plain-XML sources (`nodes`, `edges`, `conn`, `tls.tll.xml`), `intersection.sumocfg`, and the candidate routes for routeSampler (`candidate.rou.xml`) | CC BY 4.0 |
| `counts/` | 5-min turning-movement counts as routeSampler edge-relation files: ×1.0 (`turn_counts_edges.xml`), ×1.2, ×1.5, the training-mix loads ×0.8/×1.4/×1.6 (`mix/`), the second real window (`e14/`); all cells in one table, `turn_counts_5min.csv` | CC BY 4.0 |
| `demand/` | Every route file used, each folder with a `SHA256SUMS` list and the `generation_log.json` written when the files were made (command, counts, seed, SUMO version): `original/` (first version, seed 42), `train/` (E12 training, seeds 3001–3020), `heldout/` (1001–1010), `scenarios/` S1–S4, `e13/validation`, `e13/locked_test` (with the pre-registered hash list `locked_test_hashes.txt`), `e13/mix` (L4 training mix), `b7/` (perception-error variants: field of view ±10/±20%, measured field-of-view error, measured counting error), `e14/` (second real window); QA tables `check_report.csv`, `sanity_fixed.csv` | CC BY 4.0 |
| `code/tools/` | Demand generation, kit builders, analysis, twin calibration and validation, perception metrics (scripts of the revision) | MIT |
| `code/kit/` | The E12/E13 compute kit: drivers `e12.py`, `e13/e13.py` (pre-registered ladder L0–L4, selection, locked test), `e13/b7.py` (perception-error runs), `e13/b1_replay.py`, CO2 and queue extractors; RESCO modifications as patches in `resco_integration/` (RESCO is not redistributed) | MIT (patches: see `resco_integration/README.md`) |
| `code/s2c/` | Baselines: fixed plan, actuated, tuned MaxPressure, Webster (`s2c.py`; Webster plans and saturation flows in `plan/`; implementation readings of the pre-registration in `DEVIATIONS.md`) | MIT |
| `code/s2c_rt/` | Post hoc baseline added after peer review (not pre-registered; deviation D20 of the section-11 log): MaxPressure whose phase pressure also counts the right turns (`s2c_rt.py`, which imports `code/s2c/s2c.py`), its analysis (`mp_rt_analysis.py`) and the left-turn-phase check (`left_phase_share.py`) | MIT |
| `models/` | Trained models: the final checkpoint of all 220 DRL training runs (E13 rungs L1–L4, 160, incl. the 15 of the final design L2 MPLight; E12 = rung L0, 60), indexed with seeds, flags and SHA-256 in `MODELS.csv` (see `models/README.md`) | CC BY 4.0 |
| `results/` | Episode-level results and analysis tables: `e13/` (training, validation, locked test, selection, B7 and E14 episodes of the DRL designs), `e12/`, `s2c/` (baselines incl. tuning and B7), `s2c_rt/` (post hoc right-turn MaxPressure: tuning, regression and smoke checks, locked-test and second-window episodes, left-turn-phase shares, and its level and difference tables in `analysis/`), `e14_baselines/`, `e3/` (frozen re-evaluation of the first-version policies), `e6/`, `e7/`, `e8_validation/`, `twin/` (B6 calibration grid summary, GEH, lane capacity, SUMO unit tests, figure data), `analysis/` (derived tables) | CC BY 4.0 |
| `prereg/` | Pre-registration of E13 (frozen 29 Oct 2026, with its SHA-256), the section-11 log of deviations and decisions, the confirmatory result, the locked-test hash list, and the approved B6 twin-calibration protocol with its SHA-256 | CC BY 4.0 |
| `figures/` | Rectified camera frames of both cameras, the track renders over them, and Figure 2 of the article (PNG and PDF, with its segment data). License plates and faces were blurred. See `figures/README.md` | Frames and every image containing them: © Khmelnytskyi City Council, reproduced with permission, **not** under CC BY 4.0; `Figure_2_data.csv`: CC BY 4.0 |
| `perception/` | Pseudonymised event log of the blind hand counts of the first annotator (A1) and the answers of the tracking review, with the review candidates (see `perception/README.md`); the second annotator's (A2) event log is not released | CC BY 4.0 |

`MANIFEST.sha256` lists the SHA-256 of every file (`sha256sum -c MANIFEST.sha256` from the package root). In the Zenodo archive each top-level folder is one zip file (`code.zip`, `counts.zip`, …, `models.zip`); unzip them all into one folder first. The GitHub folder `release_v2` has no model files, so check it with `sha256sum -c --ignore-missing MANIFEST.sha256`.

## Experiments named in the files

| Label | What |
|---|---|
| E3 | Frozen (greedy, no learning) re-evaluation of the first-version policies on held-out and scenario demand |
| E6, E7 | Non-learning baselines on all demand files; recomputation of the first version's metrics |
| E8 | Validation of the twin against observed queue discharge (sim-to-real) |
| B6 | Pre-registered calibration of the twin's vehicle parameters (criterion not met, so the default SUMO vehicle is used) |
| E12 | Retraining of the four DRL policies with the field clearance and randomised training demand |
| E13 | Pre-registered design ladder L0–L4 with selection on validation files and one locked test; final design L2 MPLight |
| S2c | Fixed, actuated, tuned MaxPressure and Webster baselines on the E13 files |
| S2c-RT | Post hoc (8 Nov 2026, after peer review; not pre-registered, deviation D20): MaxPressure with the right turns in the phase pressure, re-tuned with the pre-registered grid and rule, run once on the locked test set and the second real window |
| B7 | Perception-error demand (field-of-view shifts, measured field-of-view and counting errors) with all controllers |
| E10 | Field-of-view sensitivity inputs (heading-exit shares) |
| E14 | Exploratory test on a second real demand window (31 Mar 2025, 09:38) |

## Reproduce

### Environment

Python 3.13 and the pinned packages of `code/kit/requirements.txt` (SUMO 1.26.0 with libsumo, torch CPU, pfrl 0.4.0, gym 0.22.0). With [uv](https://docs.astral.sh/uv/):

```bash
uv venv code/kit/.venv --python 3.13
uv pip install --python code/kit/.venv -r code/kit/requirements.txt
```

On Windows, `code/kit/setup.ps1` does the same and then runs `e12.py verify` and `e12.py bench`. `verify` compares against reference episodes of the first-version IDQN-queue model (`code/kit/verify/reference.json`), which needs that model's checkpoint in `code/kit/verify/`; that checkpoint is not part of this package.

### Demand files

Route files were generated with SUMO 1.26.0 routeSampler from `network/candidate.rou.xml` and the counts in `counts/`; every file's command and seed is in the `generation_log.json` of its folder, and its hash in `SHA256SUMS`. Check a folder with, for example, `cd demand/heldout && sha256sum -c SHA256SUMS`. The generators are `code/tools/make_heldout.py` (load factors), `make_scenarios.py` (S1–S4), `make_mix_e13.py` (L4 mix), `twin_b7_demand.py` (B7) and `e14_demand.py` (E14).

### DRL runs (E12, E13, B7, E14)

RESCO is not redistributed (CC BY-NC-SA 4.0). Rebuild the RESCO copy the runs used from upstream RESCO and this package:

```bash
git clone -c core.longpaths=true https://github.com/Pi-Star-Lab/RESCO.git code/kit/e13/resco
git -C code/kit/e13/resco checkout fc65e91
python code/kit/resco_integration/apply_to_resco.py --resco code/kit/e13/resco --variant e13 --kit code/kit
```

The patched code was checked to equal the kit's RESCO code file by file (line endings aside), and every map folder (network and route files) by SHA-256. Then, from `code/kit/e13/`, with the kit's Python: `python e13.py verify`, `python e13.py run L12` (or `L0`, `L34`), `python e13.py select`, and `python e13.py locked --go` for the locked test (it checks the 50 locked files against `locked_test_hashes.txt`). Seeds: training run k = 1..5 uses `--tr k --seed 42+k`; evaluation of run k uses SUMO seed 1042 + k + file index. `python e13.py --help` lists all commands; B7 runs with `python b7.py run --demand b7_demand` after `--kit` has filled `b7_demand/`. For the E12 driver, apply `--variant e12` to a second checkout at `code/kit/resco`.

### Baselines (S2c)

`code/s2c/s2c.py` runs the fixed, actuated, tuned MaxPressure and Webster controllers through SUMO (no RESCO): `python s2c.py --help`. `code/s2c_rt/s2c_rt.py` runs the post hoc right-turn MaxPressure with the same driver (it changes only the movements of each phase): `python s2c_rt.py --help`.

### Analyses

The scripts in `code/tools/` and `code/s2c/` were run from the root of the study's working copy and use its paths. Mirror the package into that layout, or edit the path constants at the top of each script:

| Package | Path used by the scripts |
|---|---|
| `network/*`, `counts/turn_counts_*.xml`, `demand/original/*` | `sumo/` |
| `demand/train`, `heldout`, `scenarios`, `e13` | `revision/demand/train`, `heldout`, `scenarios`, `e13` |
| `demand/b7`, `demand/e14` | `revision/twin/B7/demand`, `revision/twin/E14/demand` |
| `code/tools`, `code/s2c`, `code/s2c_rt` | `revision/tools`, `revision/s2c`, `revision/s2c_rt` |
| `code/kit`, `results/e12` | `revision/e12_kit`, `revision/e12_kit/results` |
| `results/e13` | `revision/e12_kit/e13/results` |
| `results/s2c`, `results/e14_baselines` | `revision/runs/s2c/out/results`, `revision/runs/e14/baselines/results` |
| `results/s2c_rt` (except `analysis/`) | `revision/runs/s2c_rt/out` (episode tables in its `results/`) |
| `results/analysis`, `results/twin` | `revision/analysis`, `revision/twin` |
| `prereg` | `revision/prereg` |
| `perception/hand_counts/A1` | `revision/perception/manual_counts` (original column layout; see `perception/README.md`) |

Comments and generation logs in the code refer to internal planning notes and to the review comments by number (for example "Comment 1.5"); those notes are not part of this package.

## Not included

- Raw videos (never shared), unblurred frames or crops, and the pipeline's track files. The camera frames shown in Figure 2 are in `figures/`, with license plates and faces blurred.
- Per-episode SUMO tripinfo files, training logs and metrics series of the DRL runs, and the per-point files of the B6 grid (858 JSON files; their SHA-256 list is `results/twin/B6/grid_sha256_colab.txt` and their summary `grid_results.csv`). They are available from the authors on request.
- The event log of the second hand counter (A2). The comparisons computed from it (agreement of A1 and A2, pipeline against A2) are in `results/analysis/perception/`.
- The first-version IDQN-queue checkpoint that `code/kit/verify/` compares against (a model of the first version, available from the first author on request).
- The intermediate per-axis routeSampler outputs of scenario S2 (`work/` folders); the merged S2 files are included.
- RESCO itself (patches only).

## Pseudonymisation

The two people who counted vehicles by hand appear as A1 (first counter) and A2 (second counter); only A1's annotation files are released, and a third count that is not released is A3. Names, initials, session ids and wall-clock times were removed from the annotation files; event times in the video, approach, movement and the unsure and deleted flags are kept. The perception tools in `code/tools/` and the perception tables in `results/analysis/perception/` use the same pseudonyms. The pre-registration in `prereg/` is published unchanged, because its SHA-256 was fixed before any run.

## Licences

Code (everything under `code/`, and every `*.py`, `*.ps1`, `*.ipy` and `*.ipynb` file): MIT, `LICENSE`. Data, results, models and documentation: CC BY 4.0, `LICENSE-DATA`. Copyright holders: the five authors. Two exceptions:

- **Camera frames.** The frames in `figures/` and every image that contains them belong to Khmelnytskyi City Council and are reproduced with its permission. They are not covered by CC BY 4.0 or any other licence of this package.
- **RESCO patches.** The patch files in `code/kit/resco_integration/` contain lines of RESCO (https://github.com/Pi-Star-Lab/RESCO), which is licensed CC BY-NC-SA 4.0, and are therefore distributed under CC BY-NC-SA 4.0; the lines added by the authors may also be used under MIT. RESCO itself is not part of this package.

## Use of generative AI

Under the authors' direction, the large language model Claude Opus 5.5 (Anthropic) drafted the pre-registered evaluation protocol and wrote the code of the revised simulation experiments, analyses and figures in this package. No image was generated or edited by a generative AI tool, and every result file was produced by running this code. The authors reviewed all code and take full responsibility for it.

## Funding

EU Horizon Europe grant agreement 101148374, U_CAN.

## How to cite

Cite the article and this package (`CITATION.cff`): Ryzhanskyi O., Barmak O., Manziuk E., Radiuk P., Krak I. (2026). *Code and data for “From Urban Video to Adaptive Traffic Signals: Digital Twin and Deep Reinforcement Learning under Real-World Demand”* (version 1.0.0). Zenodo. https://doi.org/10.5281/zenodo.24030604
