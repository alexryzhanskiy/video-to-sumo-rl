# Video-Driven Digital Twins for Reinforcement-Learning Traffic Signal Control (Video-to-SUMO-RL)

![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)
![SUMO](https://img.shields.io/badge/SUMO-Traffic%20Simulator-green)
![Framework: RESCO](https://img.shields.io/badge/Framework-RESCO-orange)
![Status: Research](https://img.shields.io/badge/Status-Active%20Research-orange)
![License: MIT](https://img.shields.io/badge/License-MIT-lightgrey.svg)

*An end-to-end pipeline that reconstructs real traffic demand from intersection video and learns adaptive signal control in a calibrated SUMO digital twin.*

------------------------------------------------------------------------

**Video-to-SUMO-RL** turns two fisheye camera streams of a signalized intersection into a GEH-validated SUMO digital twin, then trains IDQN agents (in the RESCO framework) whose reward is either **waiting-time** or **spatial max-pressure**, and benchmarks them against classical controllers.

> **Key Insight:** The waiting-time reward is optimal at design load but becomes **short-sighted and unstable under saturation**.\
> **The max-pressure (pressure) reward restores throughput and stabilizes queues**, outperforming the fixed plan and stronger baselines (Actuated, analytical MaxPressure, MPLight) under overload.

------------------------------------------------------------------------

## Table of Contents

-   [Methodology](#methodology)
-   [Reward Formulation](#reward-formulation)
-   [Repository Structure](#repository-structure)
-   [Installation](#installation)
-   [Usage](#usage)
-   [Experimental Results](#experimental-results)
-   [Statistical Evaluation](#statistical-evaluation)
-   [Conclusion](#conclusion)
-   [Citation](#citation)
-   [License](#license)

------------------------------------------------------------------------

# Methodology

We formulate adaptive traffic signal control as a Markov Decision Process:

$$
\mathcal{M} = (\mathcal{S}, \mathcal{A}, P, R)
$$

Where:

-   $\mathcal{S}$ --- per-lane normalized state (queue, waiting time, approach density, current phase, mean speed)
-   $\mathcal{A}$ --- selection of one of four green phases (through / left per axis)
-   $P$ --- SUMO transition dynamics accessed through the TraCI interface
-   $R$ --- waiting-time reward or spatial max-pressure reward

The demand that drives the MDP is **reconstructed from real video**, not synthesized. The end-to-end pipeline has five stages:

1.  **Computer vision** --- YOLO11x detection + ByteTrack tracking on two cameras; Brown--Conrady distortion correction applied to track coordinates.
2.  **Movement reconstruction** --- turning-movement matrix (approach × movement × vehicle type × 5-min interval).
3.  **Digital twin** --- SUMO network + `routeSampler` trip generation, validated with the GEH statistic (GEH < 5 for 100% of sections).
4.  **RL training** --- IDQN agents (RESCO) trained over multiple random seeds with the waiting or pressure reward.
5.  **Adaptive control** --- dynamic green-phase switching that measurably beats the real fixed signal.

------------------------------------------------------------------------

# Reward Formulation

Both rewards are computed over the controlled lanes $L$ of the signal, using the per-lane state exposed by the SUMO environment.

## Waiting-Time Reward (`r_wait`)

Penalizes the total accumulated waiting time at the intersection.

### Reference Implementation

``` python
total_wait = sum(obs[lane]['total_wait'] for lane in signal.lanes)
rvalue = np.clip(-total_wait / 224, -4, 4)
```

## Max-Pressure Reward (`r_press`)

Penalizes the mean queue length on the incoming lanes, acting as a spatial queue stabilizer (throughput-aware control).

### Reference Implementation

``` python
q = sum(obs[lane]['queue'] for lane in signal.lanes)
rvalue = -q / max(1, len(signal.lanes))
```

## Design Principles

-   Queue defined as vehicles with speed < 0.1 m/s within 200 m of the stop line\
-   Lane averaging in `r_press` for scale invariance across approaches\
-   `r_press` penalizes spatial queue accumulation, preventing turn-pocket starvation under saturation\
-   `r_wait` directly minimizes delay, which is optimal only at design load

------------------------------------------------------------------------

# Repository Structure

``` plaintext
.
├── src/                    # CV → SUMO → RL pipeline scripts
│   ├── preprocess.py       # HEVC → clean H.264
│   ├── stage1_track.py     # YOLO11x + ByteTrack detection/tracking
│   ├── calib_*.py, undistort.py   # fisheye calibration (plumb-line)
│   ├── classify.py, aggregate.py  # movement classification + demand matrix
│   ├── camera_shift.py     # did the camera move between recordings? (phase correlation)
│   ├── cmp_tracks.py       # sanity-check a new recording's tracks against a reference run
│   ├── build_sumo_net.py, to_routesampler.py   # SUMO network + demand
│   ├── seed_stats.py       # multi-seed mean ± σ, learning curves
│   ├── figures_pub.py      # publication figures, UA and EN
│   ├── baselines_stats.py  # Actuated / MaxPressure / MPLight stats + figures
│   └── run_actuated.sh, run_mplight.sh   # baseline runners
├── sumo/                   # network, signal, reconstructed demand (.rou.xml)
├── calib/                  # calibration matrices + gate/line definitions
├── resco_integration/      # our RESCO additions (maps, signal, reward, agent) + patcher
│   ├── apply_to_resco.py   # applies them to an upstream RESCO checkout (idempotent)
│   └── patches/            # the added config / reward blocks as plain text
├── config.yaml             # pipeline configuration
└── requirements.txt
```

------------------------------------------------------------------------

# Installation

## Requirements

-   Python 3.11
-   SUMO (with `SUMO_HOME` set)
-   PyTorch (CPU), pfrl
-   ultralytics, OpenCV, NumPy, SciPy, Matplotlib

Install pipeline dependencies:

``` bash
pip install -r requirements.txt
```

Verify SUMO:

``` bash
echo $SUMO_HOME
```

Run every script from the repository root: the paths in `config.yaml` are relative to it. Recordings
go to `videos/`, detector weights to `weights/`, and everything produced to `data/`. The analysis
scripts read the RL results from `RESCO/results`; set `RESCO_RESULTS` if they are elsewhere.

## RL framework

RESCO is not bundled here (it is distributed under CC BY-NC-SA 4.0). Clone it, then apply
this work's additions — the `prybuzka` maps, the signal configuration, the `pressure_norm`
reward and the `IDQN_pressure` agent:

``` bash
git clone -c core.longpaths=true https://github.com/Pi-Star-Lab/RESCO.git
git -C RESCO checkout fc65e91                               # the commit this was verified on
python resco_integration/apply_to_resco.py --resco RESCO    # add --dry-run to preview
```

Upstream has since moved on to RESCO v2.0, which the integration has not been tested on.
The script is idempotent and reports every change. Details, and the manual edits to fall
back on if the upstream layout moves: `resco_integration/README.md`.

------------------------------------------------------------------------

# Usage

## Stage 1 --- Video → Demand

``` bash
python src/preprocess.py                 # broken HEVC → clean H.264
python src/stage1_track.py --camera center --device 0   # YOLO11x + ByteTrack
python src/calib_pick.py   --camera center              # fisheye calibration
python src/undistort.py    --camera center
python src/classify.py     --camera center              # movement classification
python src/aggregate.py                                 # demand matrix + turn counts
python src/build_sumo_net.py                            # SUMO network
python src/to_routesampler.py                           # turn counts → routeSampler
python "%SUMO_HOME%/tools/routeSampler.py" -r sumo/candidate.rou.xml \
       -t sumo/turn_counts_edges.xml -o sumo/demand.rou.xml   # GEH-validated demand
```

### Checking a further recording of the same intersection

The gates and the lamp ROI are fixed pixel coordinates, and nothing downstream notices when
a camera has been nudged or when a recording decodes worse than the one the calibration was
built on: the pipeline still finishes and still produces plausible — but wrong — counts. Two
checks cover that, and both are cheap compared with the hours the detection itself takes.

``` bash
# Before detection: has the camera moved? (phase correlation against the reference frame)
python src/camera_shift.py --camera center --new data/video/center_new_clean.mp4

# After detection: do the new tracks look like the reference run's?
python src/cmp_tracks.py --camera center --new data/tracks/tracks_center_new.csv
```

`camera_shift.py` reports the shift in pixels: under 1 px the calibration and the gates can be
reused as they are, 1--3 px calls for overlaying the gates on a new frame and checking them by
eye, and more than that means the gates and the lamp ROI have to be marked again.

`cmp_tracks.py` compares only what does *not* depend on traffic — the lower tail of the detection
confidences (p10, the share below 0.3) and the distribution of detections over a 4×3 grid of the
frame. Those are properties of the image and the geometry, so with an unmoved camera they have to
match. Density, class mix and track lengths depend on when the recording was made, so they are
printed for reference and deliberately kept out of the verdict. Comparing on fewer frames than one
signal cycle is meaningless and the script says so.

One caveat the script encodes: on boxes below 80 px — the far part of the frame — the class is not
stable, with the same vehicle drifting between `car`, `truck` and `bus` and tracks breaking up.
This is a property of the detector at that distance, not a regression, so the class mix is reported
separately for small boxes and must not be read from that zone. Gate-based movement counts are
taken at the stop lines and are unaffected.

The scripts write to fixed names by default, so a second recording run without explicit paths
overwrites the reference tracks, movements and demand matrix. Name the outputs, and give
`aggregate.py` that recording's own clock offsets and common window: `sync_offset_sec` in
`config.yaml` belongs to the reference pair. The offsets and window below are examples.

``` bash
python src/stage1_track.py --camera center --video data/video/center_new_clean.mp4 \
       --out data/tracks/tracks_center_new.csv
python src/undistort.py --camera center --in data/tracks/tracks_center_new.csv \
       --out data/tracks/tracks_center_new_undist.csv
python src/classify.py  --camera center --in data/tracks/tracks_center_new_undist.csv \
       --out data/tracks/movements_center_new.csv
# the same for the second camera, then:
python src/aggregate.py --cameras center zarich \
       --movements data/tracks/movements_center_new.csv data/tracks/movements_zarich_new.csv \
       --offsets 87 0 --window 87:1445 \
       --out data/movements_matrix_new.csv --out-xml data/turn_counts_new.xml
python src/to_routesampler.py --in data/movements_matrix_new.csv \
       --out-dir data/sumo_new --end 1445
```

With `--window`, intervals start at the beginning of the common window, so both cameras fill the
first one. A shorter tail keeps its real length in the turn-counts file and has to be read as such.
Interval times stay in that recording's common time, so its first interval does not begin at zero;
shift them before using the demand in a simulation that starts at zero.

A 300 s interval holds 2.5 signal cycles of 120 s, so neighbouring intervals see a different number
of green phases. Compare recordings over a whole number of cycles, not interval by interval.

## Stage 2 --- RL Training (from the patched `RESCO/resco_benchmark/`, `--procs 1`)

``` bash
# Trained agents — 100 episodes, 5 seeds each (--tr 1..5) for mean ± σ
python main.py --agent IDQN    --map prybuzka --eps 100 --tr 1 --procs 1   # r_wait / r_press
python main.py --agent MPLight --map prybuzka --eps 100 --tr 1 --procs 1   # learned FRAP-DQN
# Analytical baseline — no training
python main.py --agent MAXPRESSURE --map prybuzka --eps 2 --tr 1 --procs 1
# Stress loads: --map prybuzka_12 / prybuzka_15
# Actuated baseline (native SUMO, gap-based): src/run_actuated.sh
```

## Stage 3 --- Statistics & Figures

``` bash
python src/seed_stats.py         # mean ± σ, learning curves with ±σ bands
python src/baselines_stats.py    # all controllers + throughput figure
```

Generates mean curves, ±σ shading, and multi-controller comparison plots.

------------------------------------------------------------------------

# Experimental Results

All values are **mean ± σ over 5 random seeds** (RL agents trained 5 times; fixed baseline over 5 SUMO seeds), computed in an identical evaluation window.

## Design Load (×1.0, demand 1355 vehicles)

| Controller     | throughput | waiting, s | travel, s | CO₂, kg |
|:--------------:|:----------:|:----------:|:---------:|:-------:|
| Fixed (video)  | 1285±1     | 34.2±0.4   | 62.6±0.4  | 184±1   |
| Actuated       | 1277±9     | 31.0±1.9   | 59.1±1.9  | 175±3   |
| MaxPressure    | 1335±11    | 33.6±2.7   | 72.3±3.5  | 208±5   |
| MPLight        | 1352±0     | 16.0±1.6   | 46.4±2.5  | 163±5   |
| IDQN-wait      | 1351±1     | 13.4±1.4   | 41.5±1.7  | 152±3   |
| **IDQN-press** | 1352±0     | **14.3±0.9** | 42.1±0.9 | 153±2   |

IDQN reduces **waiting −61%, travel −34%, CO₂ −17%** versus the fixed signal, at the same throughput.

## Robustness Under Overload (throughput / waiting, s)

| Controller     | ×1.2 thru / wait | ×1.5 thru / wait   |
|:--------------:|:----------------:|:------------------:|
| Fixed (video)  | 1607 / 52.2      | 1784 / 66.4        |
| Actuated       | 1394 / 47.0      | 1404 / 60.9        |
| MaxPressure    | 1012 / 156.1     | 799 / 234.0        |
| MPLight        | 1620 / 31.1      | 1718±140 / 44.0    |
| IDQN-wait      | 1626 / 26.6      | 1400±297 / 83.3±36 |
| **IDQN-press** | **1626 / 21.0**  | **1874 / 35.4**    |

Under saturation the **wait reward becomes unstable** (×1.5: 1400±297, large seed variance), while **IDQN-press stays robust** (1874, above the fixed 1784) and keeps waiting lowest. The **analytical MaxPressure gridlocks** the real intersection (799 at ×1.5) as its unbounded-storage assumption breaks on short turn pockets.

------------------------------------------------------------------------

# Statistical Evaluation

Every reported metric is aggregated across $n = 5$ seeds.

Mean:

$$
\mu = \frac{1}{n} \sum_{i} x_i
$$

Standard deviation:

$$
\sigma = \sqrt{\frac{1}{n-1} \sum_{i} (x_i - \mu)^2}
$$

Implementation (`src/seed_stats.py`, `src/baselines_stats.py`):

``` python
mean = a.mean(axis=0)
std  = a.std(axis=0, ddof=1)
```

Learning curves are drawn as the seed-mean with ±σ shaded bands; runs corrupted by TraCI contention (throughput < 0.8 × median) are excluded as technical artifacts, while genuine policy variance is retained.

------------------------------------------------------------------------

# Conclusion

1.  Traffic demand is reconstructed directly from video and validated (GEH < 5 for 100% of sections).
2.  IDQN cuts waiting by 61%, travel by 34% and CO₂ by 17% versus the real fixed signal at design load.
3.  Under overload the max-pressure reward restores throughput and halves waiting, remaining stable across seeds.
4.  On the last training episode IDQN-press outperforms the stronger baselines (Actuated, analytical MaxPressure, MPLight); MPLight comes close and beats IDQN-wait at ×1.5. Frozen on held-out demand, MPLight serves the full demand more reliably than either IDQN agent at ×1.0.

Video-to-SUMO-RL grounds RL traffic control in real, statistically validated demand, exposing reward-function limits that remain hidden under synthetic traffic.

------------------------------------------------------------------------

# Citation

``` bibtex
@misc{videotosumorl2026,
  title        = {Video-Driven Digital Twins for Reinforcement-Learning Traffic Signal Control from Real Traffic Demand},
  author       = {<AUTHORS — fill in before publishing>},
  year         = {2026},
  note         = {Submitted for publication}
}
```

------------------------------------------------------------------------

# License

This repository is released under the **MIT License** (see `LICENSE`).

[RESCO](https://github.com/Pi-Star-Lab/RESCO), the RL framework used for the experiments, is **not part of this repository**: it is distributed by its own authors under **CC BY-NC-SA 4.0** (attribution, non-commercial, share-alike) and has to be obtained from them. `resco_integration/` contains only the code written for this work and the script that applies it to a RESCO checkout, so nothing here inherits those terms.
