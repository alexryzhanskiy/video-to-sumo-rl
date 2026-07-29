"""Stress-сравнение: IDQN vs фикс-сигнал при нагрузке ×1.0 / ×1.2 / ×1.5.

Показывает, держит ли RL преимущество при росте спроса. По каждой нагрузке берёт
throughput, ожидание, время в пути, CO2 (из tripinfo последнего эпизода IDQN и фикс-baseline).

Запуск:  python src/stress_compare.py
"""
from __future__ import annotations

import glob
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

RESULTS = Path("C:/Work/RESCO/results")
SUMO = Path("C:/Work/TrafficVideos_RL2/sumo")

# нагрузка -> (glob IDQN-папки, фикс-tripinfo, спрос)
SCALES = {
    "×1.0": ("IDQN-*prybuzka-1-*", SUMO / "fixed_tripinfo.xml", 1355),
    "×1.2": ("IDQN-*prybuzka_12-*", SUMO / "fixed_tripinfo_12.xml", 1626),
    "×1.5": ("IDQN-*prybuzka_15-*", SUMO / "fixed_tripinfo_15.xml", 2036),
}


def trip_metrics(path: Path):
    dur, wait, co2 = [], [], 0.0
    for tp in ET.parse(path).getroot().findall("tripinfo"):
        dur.append(float(tp.get("duration")))
        wait.append(float(tp.get("waitingTime")))
        em = tp.find("emissions")
        if em is not None and em.get("CO2_abs"):
            co2 += float(em.get("CO2_abs"))
    return {"thru": len(dur), "travel": float(np.mean(dur)), "wait": float(np.mean(wait)),
            "co2": co2 / 1e6}


def latest_idqn(pattern):
    ds = sorted(glob.glob(str(RESULTS / pattern)), key=lambda p: Path(p).stat().st_mtime)
    if not ds:
        return None
    d = Path(ds[-1])
    tps = glob.glob(str(d / "tripinfo_*.xml"))
    n = max(int(Path(f).stem.split("_")[-1]) for f in tps)
    return d / f"tripinfo_{n}.xml"


def main():
    print(f"{'нагрузка':9s} {'спрос':>6s} | {'IDQN thru':>9s} {'фикс thru':>9s} | "
          f"{'IDQN wait':>9s} {'фикс wait':>9s} {'Δwait':>7s} | {'Δtravel':>8s} {'ΔCO2':>7s}")
    plot = {}
    for scale, (pat, fixed_tp, demand) in SCALES.items():
        idqn_tp = latest_idqn(pat)
        if idqn_tp is None or not fixed_tp.exists():
            print(f"{scale:9s}  (нет данных — прогон ещё идёт?)")
            continue
        q = trip_metrics(idqn_tp)
        b = trip_metrics(fixed_tp)
        dwait = (q["wait"] - b["wait"]) / b["wait"] * 100 if b["wait"] else 0
        dtrav = (q["travel"] - b["travel"]) / b["travel"] * 100 if b["travel"] else 0
        dco2 = (q["co2"] - b["co2"]) / b["co2"] * 100 if b["co2"] else 0
        plot[scale] = (b, q, dwait, dtrav, dco2)
        print(f"{scale:9s} {demand:>6d} | {q['thru']:>9d} {b['thru']:>9d} | "
              f"{q['wait']:>8.1f}с {b['wait']:>8.1f}с {dwait:>6.0f}% | {dtrav:>7.0f}% {dco2:>6.0f}%")

    if len(plot) >= 2:
        try:
            import matplotlib; matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            scales = list(plot)
            fig, ax = plt.subplots(1, 2, figsize=(12, 5))
            xw_b = [plot[s][0]["wait"] for s in scales]
            xw_q = [plot[s][1]["wait"] for s in scales]
            x = np.arange(len(scales))
            ax[0].plot(x, xw_b, "o-", label="Фикс (видео)", color="#888")
            ax[0].plot(x, xw_q, "o-", label="IDQN", color="#2a9d3f")
            ax[0].set_xticks(x); ax[0].set_xticklabels(scales)
            ax[0].set_ylabel("ср. ожидание, с"); ax[0].set_title("Ожидание vs нагрузка")
            ax[0].legend(); ax[0].grid(alpha=.3)
            tb = [plot[s][0]["thru"] for s in scales]; tq = [plot[s][1]["thru"] for s in scales]
            dem = [SCALES[s][2] for s in scales]
            ax[1].plot(x, tb, "o-", label="Фикс", color="#888")
            ax[1].plot(x, tq, "o-", label="IDQN", color="#2a9d3f")
            ax[1].plot(x, dem, "k--", alpha=.5, label="спрос")
            ax[1].set_xticks(x); ax[1].set_xticklabels(scales)
            ax[1].set_ylabel("throughput"); ax[1].set_title("Throughput vs нагрузка")
            ax[1].legend(); ax[1].grid(alpha=.3)
            fig.suptitle("Stress-тест: IDQN vs фикс-сигнал при росте спроса")
            plt.tight_layout()
            out = Path("C:/Work/TrafficVideos_RL2/data/stress_compare.png")
            plt.savefig(out, dpi=120, bbox_inches="tight")
            print(f"\n[plot] -> {out}")
        except Exception as e:
            print(f"[plot] пропущено: {e}")


if __name__ == "__main__":
    main()
