# Emission-Aware Reinforcement Learning for Traffic Signal Control (RESCO-CO₂)

![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)
![SUMO](https://img.shields.io/badge/SUMO-Traffic%20Simulator-green)
![Status:
Research](https://img.shields.io/badge/Status-Active%20Research-orange)

*A multi-objective reinforcement learning framework for CO₂-aware
traffic control in uphill scenarios.*

------------------------------------------------------------------------

**RESCO-CO₂** extends the RESCO benchmark with emission-aware reward
engineering, uphill dynamics modeling, and statistically rigorous
multi-seed evaluation.

> **Key Insight:** Classical traffic RL optimizes waiting time or
> pressure.\
> **RESCO-CO₂ introduces physically grounded emission penalties and
> uphill start/stop dynamics**, enabling policies that are both
> efficient and environmentally sustainable.

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

We model traffic signal control as a Markov Decision Process:

$$
\mathcal{M} = (\mathcal{S}, \mathcal{A}, P, R)
$$

Where:

-   $\mathcal{S}$ --- traffic state (queues, waiting times, CO₂,
    lane-level metrics)
-   $\mathcal{A}$ --- signal phase selection
-   $P$ --- SUMO transition dynamics
-   $R$ --- multi-objective emission-aware reward

Unlike classical RESCO baselines, we explicitly integrate:

-   Lane-normalized CO₂ emissions\
-   Uphill start/stop penalties\
-   Multi-seed statistical aggregation\
-   Reward weight sensitivity analysis

------------------------------------------------------------------------

# Reward Formulation

## Base Multi-Objective Reward

The base reward combines emission and waiting time penalties, normalized
per lane to ensure scale invariance across maps.

### Reference Implementation

``` python
rvalue = (
    -0.5 * total_co2 / num_lanes / 10e4
    -0.1 * total_wait / num_lanes / 10e2
)
```

------------------------------------------------------------------------

## Extended Uphill-Aware Reward

The extended formulation additionally penalizes queue buildup and uphill
start/stop oscillations to improve physical realism in sloped
environments.

### Reference Implementation

``` python
rvalue = (
    -0.5 * queue_length / num_lanes / 10e1 
    -1.5 * total_wait / num_lanes / 10e1 
    -0.7 * uphill_started_count / num_lanes 
    -0.7 * uphill_stopped_count / num_lanes 
)
```

------------------------------------------------------------------------

## Design Principles

-   Lane normalization for scale invariance\
-   Magnitude balancing via scaling factors\
-   Penalizing oscillatory behavior in uphill traffic\
-   Explicit CO2-aware optimization 

------------------------------------------------------------------------

# Repository Structure

``` plaintext
.
├── environments/           # SUMO maps (1way_single_uphill, etc.)
├── resco_benchmark/        # Modified RESCO core
├── utils/
│   ├── readXMLCombine.py   # Metric aggregation
│   ├── plotting.py         # Statistical visualization
├── configs/                # Experiment configs
└── main.py                 # Main training entry point
```

------------------------------------------------------------------------

# Installation

## Requirements

-   Python 3.9+
-   SUMO
-   PyTorch
-   NumPy
-   Pandas
-   Matplotlib
-   Seaborn

Install dependencies:

``` bash
pip install -r requirements.txt
```

Verify SUMO:

``` bash
echo $SUMO_HOME
```

------------------------------------------------------------------------

# Usage

## Experiment 1

``` bash
python main.py --agent IDQNCO2Multiple --eps 200 --map 1way_single --procs 1
```

## Experiment 2

``` bash
python main.py --agent IDQNCO2Multiple --eps 200 --map 1way_single_uphill --procs 1
```

## Experiment 3

``` bash
python main.py --agent IDQN_start_stop --eps 200 --map 1way_single_uphill --procs 1
```

Available agents:

-   idqn
-   mplight
-   maxpressure

------------------------------------------------------------------------

## Results Aggregation & Statistical Visualization

After training, aggregate metrics and generate comparison plots:

```bash
python utils/readXML_Chart_SummarizeData.py
```

Generates:

-   Mean curves
-   ± Standard deviation shading
-   Multi-seed comparison plots

------------------------------------------------------------------------

# Experimental Results

## CO₂ vs Waiting Time Trade-off

By varying $w_{CO₂}$:

-   CO₂ emissions decrease significantly
-   Waiting time increases marginally
-   Policy stability preserved across seeds

## Uphill Start/Stop Penalization

Explicit penalization reduces:

-   Acceleration-induced emission spikes
-   Stop-and-go oscillations
-   Policy instability

------------------------------------------------------------------------

# Statistical Evaluation

Mean:

$$
\mu = \frac{1}{n} \sum x_i
$$

Standard deviation:

$$
\sigma = \sqrt{\frac{1}{n-1} \sum (x_i - \mu)^2}
$$

Implementation:

``` python
mean = np.mean(results, axis=0)
std = np.std(results, axis=0, ddof=1)
```

------------------------------------------------------------------------

# Conclusion

1.  Emission-aware reward significantly reduces CO₂.
2.  Waiting time remains competitive.
3.  Uphill modeling improves physical realism.
4.  Multi-seed evaluation confirms robustness.

RESCO-CO₂ provides a physically grounded extension of RL traffic control
toward sustainable optimization.
