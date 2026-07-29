import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import pandas as pd
import os
import glob
import xml.etree.ElementTree as ET
from resco_benchmark.config.map_config import map_configs
from collections import deque, defaultdict

# =========================
# Config
# =========================
sns.set_theme(style="whitegrid")

files_len = 200

log_dir = os.path.join(os.path.dirname(os.path.dirname(os.getcwd())), "results" + os.sep)
env_base = ".." + os.sep + "environments" + os.sep


'''

# Experiment 1: single 

names = [
    "MAXPRESSURE-tr0-1way_single-0-mplight-wait",
    "MPLight-tr0-1way_single-0-mplight_Co2Multiple-pressure_CO2Multiple",
    "IDQN-tr0-1way_single-0-drq_norm1-wait_norm",
    "IDQN-tr0-1way_single-0-idqn_Co2Multiple-pressure_CO2MultipleNorm"
]
'''

'''

Experiment 2: single uphill 

names = [
    "MAXPRESSURE-tr0-1way_single_uphill-0-mplight-wait",
    "MPLight-tr0-1way_single_uphill-0-mplight_Co2Multiple-pressure_CO2Multiple",
    "11IDQN-tr0-1way_single_uphill-0-drq_norm1-wait_norm",
    "IDQN-tr0-1way_single_uphill-0-idqn_Co2Multiple-pressure_CO2MultipleNorm"
]
'''

# Experiment 3: single uphill start stop

names = [
    "MAXPRESSURE-tr0-1way_single_uphill-0-mplight-wait",
    "MPLight-tr0-1way_single_uphill-0-mplight_Co2Multiple-pressure_CO2Multiple",
    "11IDQN-tr0-1way_single_uphill-0-drq_norm1-wait_norm",
    "IDQN-tr0-1way_single_uphill-0-drq_norm_start_stop-pressure_CO2StartStop"
]

metrics = ["duration", "waitingTime", "CO2_abs", "waitingCount"]

SMOOTH_WINDOW = 20
STAT_BAND = "std"  # "std" or "minmax"

OUT_ROOT = os.path.join(log_dir, "2") 

import winsound

def beep(frequency=440, duration=500):
    winsound.Beep(frequency, duration)

def pretty_beep_sequence():
    frequencies = [500, 440, 660, 990]
    durations = [750, 250, 250, 500]
    for freq, dur in zip(frequencies, durations):
        winsound.Beep(freq, dur)

# =========================
# Helpers
# =========================
def format_mean_std(mean, std, threshold=1000):
    if abs(mean) >= threshold:
        exp = int(np.floor(np.log10(abs(mean))))
        base = 10 ** exp
        m = mean / base
        s = std / base
        return f"({m:.2f}±{s:.2f})⋅10^{exp}"
    else:
        return f"({mean:.2f}±{std:.2f})"


def pick_every_k_points(df: pd.DataFrame, k: int = 50, start_x: int = 1,
                        keep_cols: list[str] | None = None) -> pd.DataFrame:  
    if keep_cols is None:
        keep_cols = ["map", "metric", "legend", "x", "y", "z", "a", "b", "y_low", "y_high"]

    df2 = df.copy()
    df2 = df2.sort_values(["legend", "x"])
    df2 = df2[(((df2["x"] - start_x) % k) == 0) | (df2["x"] == 200)]

    keep_cols = [c for c in keep_cols if c in df2.columns]
    return df2[keep_cols].reset_index(drop=True)


def export_every50_for_map(df_stats: pd.DataFrame, map_name: str, metric: str,
                           stat_band: str, k: int = 50) -> pd.DataFrame:
    df_map = df_stats[(df_stats["map"] == map_name) & (df_stats["metric"] == metric)].copy()
    
    if stat_band == "minmax":
        df_map["y_low"] = df_map["a"]
        df_map["y_high"] = df_map["b"]
    else:  # "std"
        df_map["y_low"] = df_map["y"] - df_map["z"]
        df_map["y_high"] = df_map["y"] + df_map["z"]

    return pick_every_k_points(df_map, k=k, start_x=1)


def save_as_png(fig, out_root, map_name, metric, demand, smoothing, suffix=""):
    img_dir = os.path.join(out_root)
    os.makedirs(img_dir, exist_ok=True)

    safe_map = map_name.replace("-", "").replace(" ", "_")
    file_name = f"{metric.replace(' ', '_').lower()}{safe_map}{suffix}.png"

    match metric:
        case 'duration':
            file_name = 'Average Duration Comparison.png'
        case 'waitingTime':
            file_name = 'Average Waiting Time Comparison'
        case 'waitingCount':
            file_name = 'Average Queue Length Comparison'
        case 'CO2_abs':
            file_name = 'CO2 Emissions Comparison'
        case _:
            pass

    fig.set_constrained_layout(True)
    fig.savefig(os.path.join(img_dir, file_name), dpi=600)


def set_axis_labels(ax, map_name, metric, max_x, max_y):
    if "peak" in map_name.lower():
        demand = "peak"
        points = np.asarray([0, 20, 40, 60, 80, 100, 110])
        labels = ("0", "20", "40", "60", "80", "100", ".." + str(max_x))
        ax.set_xticks(points)
        ax.set_xticklabels(labels)
        ax.set_xlabel("Episode")
    else:
        demand = "year"
        ax.set_xlabel("Hour")

    ax.set_ylabel(metric)
    ax.set_title(f"{map_name}")
    return demand


def moving_average_filter(data, window):
    windowed = []
    queue = deque(maxlen=window)
    for i in range(len(data)):
        queue.append(data[i])
        windowed.append(np.mean(queue))
    return np.asarray(windowed)


def average_over_trials(stack, smoothing=None):
    exp_avg = np.mean(stack, axis=0)
    exp_std = np.std(stack, axis=0, ddof=1)
    exp_min = np.min(stack, axis=0)
    exp_max = np.max(stack, axis=0)

    if smoothing is not None and stack.shape[1] >= smoothing:
        exp_avg = moving_average_filter(exp_avg, smoothing)
        exp_std = moving_average_filter(exp_std, smoothing)
        exp_min = moving_average_filter(exp_min, smoothing)
        exp_max = moving_average_filter(exp_max, smoothing)

    return exp_avg, exp_std, exp_min, exp_max


def make_legend_label(name):
    name_lower = name

    if "IDQN-tr0-1way_single_uphill-0-drq_norm_start_stop-pressure_CO2StartStop" in name_lower:
        return "OUR"
    if "IDQN-tr0-1way_single_uphill-0-idqn_Co2Multiple-pressure_CO2MultipleNorm" in name_lower:
        return "OUR"  
    if "IDQN-tr0-1way_single-0-idqn_Co2Multiple-pressure_CO2MultipleNorm" in name_lower:
        return "OUR"  
    if "MAXPRESSURE-tr0" in name_lower:
        return "MaxPressure"
    if "MPLight-tr0" in name_lower:
        return "MPLight"
    if "IDQN-tr0-1way_single-0-drq_norm1-wait_norm" in name_lower:
        return "DQN Standart"
    if "IDQN-tr0-1way_single_uphill-0-drq_norm1-wait_norm" in name_lower:
        return "DQN Standart"

    return "OUR"


color_map = {
    "OUR": "green",   
    "MaxPressure": "purple",
    "MPLight": "orange",
    "DQN Standart": "blue",
}


def plot_map_metric_seaborn_from_stats(df_plot, map_name, metric, stat="std"):
    fig, ax = plt.subplots(figsize=(16, 8))
    print("Hue values:", sorted(df_plot["legend"].astype(str).unique()))

    sns.lineplot(
        data=df_plot,
        x="x",
        y="y",
        hue="legend",
        ax=ax,
        linewidth=2,
        palette=color_map
    )
    
    lines = ax.get_lines()
    hue_values = df_plot["legend"].unique()

    for line, nm in zip(lines, hue_values):
        g = df_plot[df_plot["legend"] == nm].sort_values("x")
        x = g["x"].to_numpy()
        y = g["y"].to_numpy()
        color = line.get_color()

        if stat == "minmax":
            a = g["a"].to_numpy()
            b = g["b"].to_numpy()
            ax.fill_between(
                x,
                a,
                b,
                color=color,
                alpha=0.25,
                linewidth=0
            )
        else:
            z = g["z"].to_numpy()
            ax.fill_between(
                x,
                y - z,
                y + z,
                color=color,
                alpha=0.25,
                linewidth=0
            )

    max_x = int(df_plot["x"].max())
    max_y = float(df_plot["y"].max())
    demand = set_axis_labels(ax, map_name, metric, max_x, max_y)

    ax.legend(title="Run", loc="best")

    axis_label_fontsize = 20
    axis_ticks_fontsize = 20
    legend_fontsize = 20
    title_fontsize = 26

    match metric:
        case 'duration':
            plt.title('Average Duration Comparison', fontsize=title_fontsize, pad=20)
            plt.xlabel("Training Cycles", fontsize=axis_label_fontsize, labelpad=10)
            plt.ylabel("Average Duration, (sec)", fontsize=axis_label_fontsize, labelpad=10)
        case 'waitingTime':
            plt.title('Average Waiting Time Comparison', fontsize=title_fontsize, pad=20)
            plt.xlabel("Training Cycles", fontsize=axis_label_fontsize, labelpad=10)
            plt.ylabel("Average Waiting Time, (sec)", fontsize=axis_label_fontsize, labelpad=10)
        case 'waitingCount':
            plt.title('Average Queue Length Comparison', fontsize=title_fontsize, pad=20)
            plt.xlabel("Training Cycles", fontsize=axis_label_fontsize, labelpad=10)
            plt.ylabel("Average Queue Length, (vehs)", fontsize=axis_label_fontsize, labelpad=10)
        case 'CO2_abs':
            plt.title('CO2 Emissions Comparison', fontsize=title_fontsize, pad=20)
            plt.xlabel("Training Cycles", fontsize=axis_label_fontsize, labelpad=10)
            plt.ylabel("CO2 (mg)", fontsize=axis_label_fontsize, labelpad=10)
        case _:
            pass

    plt.xticks(fontsize=axis_ticks_fontsize)
    plt.yticks(fontsize=axis_ticks_fontsize)
    plt.ticklabel_format(style='plain', axis='y')
    plt.legend(fontsize=legend_fontsize)

    pretty_beep_sequence()
    plt.grid(True, which='both', linestyle='--', linewidth=0.5)
    plt.show()

    return fig, demand


def format_mean_pm_std(mean: float, std: float, threshold: float = 1000.0) -> str:
    if mean is None or std is None:
        return "(nan±nan)"

    mean = float(mean)
    std = float(std)

    if mean == 0.0:
        return f"({mean:.2f}±{std:.2f})"

    if abs(mean) >= threshold:
        exp = int(np.floor(np.log10(abs(mean)) / 3) * 3)
        base = 10.0 ** exp
        m = mean / base
        s = std / base
        return f"({m:.2f}±{s:.2f})⋅10^{exp}"
    else:
        return f"({mean:.2f}±{std:.2f})"


def format_mean_pm_std_plain(mean: float, std: float, threshold: float = 1000.0) -> str:
    mean = float(mean)
    std = float(std)

    if mean == 0:
        return f"{mean:.2f}±{std:.2f}"

    if abs(mean) >= threshold:
        exp = int(np.floor(np.log10(abs(mean)) / 3) * 3)
        base = 10.0 ** exp
        m = mean / base
        s = std / base
        return f"{m:.2f}±{s:.2f}⋅10^{exp}"
    else:
        return f"{mean:.2f}±{std:.2f}"


# =========================
# Main
# =========================
for metric in metrics:
    rows_stats = []

    for name in names:
        split_name = name.split("-")
        map_name = split_name[2]
        name_mask = name + "=="

        runs = [
            d for d in os.listdir(log_dir)
            if d.startswith(name_mask) and os.path.isdir(os.path.join(log_dir, d))
        ]

        run_avg = []

        for run in runs:
            print(run)
            split_run_name = run.split("==")
            run_name = split_run_name[1] if len(split_run_name) > 1 else run

            average_per_run = []
            files = glob.glob(os.path.join(log_dir, run, "tripinfo_*.xml"))
            count = min(len(files), files_len)
            begins_from = 1

            for i in range(begins_from, count + 1):
                trip_file_name = os.path.join(log_dir, run, f"tripinfo_{i}.xml")
                if not os.path.exists(trip_file_name):
                    break

                try:
                    tree = ET.parse(trip_file_name)
                    root = tree.getroot()

                    num_trips, total = 0, 0.0
                    last_departure_time = 0
                    last_depart_id = ""

                    for child in root:
                        try:
                            num_trips += 1
                            if metric == "CO2_abs":
                                for emission in child:
                                    total += float(emission.attrib[metric])
                            else:
                                total += float(child.attrib[metric])

                            if metric == "timeLoss":
                                total += float(child.attrib["departDelay"])
                                depart_time = float(child.attrib["depart"])
                                if depart_time > last_departure_time:
                                    last_departure_time = depart_time
                                    last_depart_id = child.attrib["id"]
                        except Exception:
                            break

                    if metric == "timeLoss":
                        route_file_name = os.path.join(env_base, map_name, f"{map_name}_{i}.rou.xml")
                        try:
                            tree = ET.parse(route_file_name)
                        except FileNotFoundError:
                            route_file_name = os.path.join(env_base, map_name, f"{map_name}.rou.xml")
                            tree = ET.parse(route_file_name)

                        rroot = tree.getroot()
                        expected_depart = None
                        for child in rroot:
                            if child.attrib.get("id") == last_depart_id:
                                expected_depart = float(child.attrib["depart"])
                                break
                        if expected_depart is None:
                            raise Exception("Wrong trip file / can't find last depart id in route")

                        never_departed = []
                        for child in rroot:
                            if child.tag != "vehicle":
                                continue
                            depart_time = float(child.attrib["depart"])
                            if depart_time > expected_depart:
                                never_departed.append(depart_time)

                        never_departed = np.asarray(never_departed)
                        end_time = float(map_configs[map_name]["end_time"])
                        never_departed_delay = np.sum(end_time - never_departed)
                        total += never_departed_delay
                        num_trips += len(never_departed)

                    if num_trips == 0:
                        break

                    average = total if metric == "CO2_abs" else (total / num_trips)
                    average_per_run.append(average)

                except ET.ParseError:
                    break

            average_per_run = np.asarray(average_per_run, dtype=float)
            if average_per_run.size > 0:
                run_avg.append(average_per_run)

        if len(run_avg) == 0:
            continue

        min_len = min(arr.shape[0] for arr in run_avg)
        run_avg = [arr[:min_len] for arr in run_avg]

        stack = np.vstack(run_avg)
        exp_avg, exp_std, exp_min, exp_max = average_over_trials(stack, SMOOTH_WINDOW)
        x = np.arange(1, len(exp_avg) + 1)

        for xi, yi, zi, ai, bi in zip(x, exp_avg, exp_std, exp_min, exp_max):
            rows_stats.append({
                "map": map_name,
                "metric": metric,
                "name": make_legend_label(name),
                "legend": make_legend_label(name),
                "x": int(xi),
                "y": float(yi),
                "z": float(zi),
                "a": float(ai),
                "b": float(bi),
            })

    if not rows_stats:
        continue

    df_stats = pd.DataFrame(rows_stats)

    for map_name in df_stats["map"].unique():
        df_every50 = export_every50_for_map(
            df_stats=df_stats,
            map_name=map_name,
            metric=metric,
            stat_band=STAT_BAND,
            k=50
        )

        print(f"\nBand every 50 points (no scale): map={map_name}, metric={metric}")

        df_print = df_every50.copy()

        if STAT_BAND == "minmax":
            std_for_print = (df_print["b"] - df_print["a"]) / 2.0
        else:
            std_for_print = df_print["z"]

        df_print["mean±std"] = [
            format_mean_pm_std(m, s, threshold=1000.0)
            for m, s in zip(df_print["y"].to_numpy(), std_for_print.to_numpy())
        ]
        df_print["mean±std_plain"] = [
            format_mean_pm_std_plain(m, s)
            for m, s in zip(df_print["y"].to_numpy(), std_for_print.to_numpy())
        ]

        print("\nTAB separated by legend:")
        for legend_name, g in df_print.sort_values("x").groupby("legend"):
            tab_line = "\t".join(g["mean±std_plain"].tolist())
            print(f"{legend_name}\t{tab_line}")

        df_print["band2"] = (
            df_print["legend"]
            + "  "
            + df_print["x"].astype(int).astype(str)
            + "  "
            + df_print["mean±std"]
        )

        pd.set_option("display.max_colwidth", None)
        pd.set_option("display.width", None)
        print(df_print["band2"].to_string(index=False))

    for map_name in df_stats["map"].unique():
        df_map = df_stats[df_stats["map"] == map_name].copy()
        fig, demand = plot_map_metric_seaborn_from_stats(df_map, map_name, metric, stat=STAT_BAND)
        # save_as_png(fig, OUT_ROOT, map_name, metric, demand, str(SMOOTH_WINDOW), suffix=f"_{STAT_BAND}")
