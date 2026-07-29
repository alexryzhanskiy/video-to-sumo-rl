# Video-Driven Digital Twins for Reinforcement-Learning Traffic Signal Control (Video-to-SUMO-RL)

![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)
![SUMO](https://img.shields.io/badge/SUMO-Traffic%20Simulator-green)
![Framework: RESCO](https://img.shields.io/badge/Framework-RESCO-orange)
![Status: Research](https://img.shields.io/badge/Status-Active%20Research-orange)

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
│   ├── build_sumo_net.py, to_routesampler.py   # SUMO network + demand
│   ├── seed_stats.py       # multi-seed mean ± σ, learning curves
│   ├── baselines_stats.py  # Actuated / MaxPressure / MPLight stats + figures
│   └── run_actuated.sh, run_mplight.sh   # baseline runners
├── sumo/                   # network, signal, reconstructed demand (.rou.xml)
├── calib/                  # calibration matrices + gate/line definitions
├── resco/                  # bundled RESCO (prybuzka maps + modified config)
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

The RL code is bundled under `resco/` (see `resco/README.md` for setup of the RESCO environment `resco_env`).

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

## Stage 2 --- RL Training (from `resco/resco_benchmark/`, `--procs 1`)

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
| MPLight        | 1304±74    | 36.6±18.2  | 73.6±17.8 | 204±20  |
| IDQN-wait      | 1351±1     | 13.4±1.4   | 41.5±1.7  | 152±3   |
| **IDQN-press** | 1352±0     | **14.3±0.9** | 42.1±0.9 | 153±2   |

IDQN reduces **waiting −61%, travel −34%, CO₂ −17%** versus the fixed signal, at the same throughput.

## Robustness Under Overload (throughput / waiting, s)

| Controller     | ×1.2 thru / wait | ×1.5 thru / wait   |
|:--------------:|:----------------:|:------------------:|
| Fixed (video)  | 1607 / 52.2      | 1784 / 66.4        |
| Actuated       | 1394 / 47.0      | 1404 / 60.9        |
| MaxPressure    | 1012 / 156.1     | 799 / 234.0        |
| MPLight        | 1516 / 45.8      | 1512 / 60.0        |
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
4.  The learned agents outperform stronger baselines (Actuated, analytical MaxPressure, MPLight); multi-seed evaluation confirms robustness.

Video-to-SUMO-RL grounds RL traffic control in real, statistically validated demand, exposing reward-function limits that remain hidden under synthetic traffic.
