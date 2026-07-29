"""Полное сравнение baseline (фикс. светофор из видео) vs RL-агенты по tripinfo.

Метрики (по последнему эпизоду каждого агента): throughput (прибыло), ср. время в пути,
ср. ожидание, ср. timeLoss, суммарный CO2. Throughput ключевой — очередь одна обманчива
(гридлок даёт низкую очередь, т.к. машины не доезжают).

Запуск:  python src/rl_metrics.py
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
RL2 = Path("C:/Work/TrafficVideos_RL2")


def latest_dir(pattern):
    ds = sorted(glob.glob(str(RESULTS / pattern)), key=lambda p: Path(p).stat().st_mtime)
    return Path(ds[-1]) if ds else None


def last_tripinfo(d: Path):
    files = glob.glob(str(d / "tripinfo_*.xml"))
    n = max(int(Path(f).stem.split("_")[-1]) for f in files)
    return d / f"tripinfo_{n}.xml", n


def trip_metrics(path: Path):
    dur, wait, tloss, co2 = [], [], [], 0.0
    for tp in ET.parse(path).getroot().findall("tripinfo"):
        dur.append(float(tp.get("duration")))
        wait.append(float(tp.get("waitingTime")))
        tloss.append(float(tp.get("timeLoss")))
        em = tp.find("emissions")
        if em is not None and em.get("CO2_abs"):
            co2 += float(em.get("CO2_abs"))
    return {"throughput": len(dur), "travel": float(np.mean(dur)), "wait": float(np.mean(wait)),
            "timeloss": float(np.mean(tloss)), "co2_kg": co2 / 1e6}


def main():
    sources = {"Фикс (видео)": RL2 / "sumo" / "fixed_tripinfo.xml"}
    for name, pat in [("IDQN", "IDQN-*prybuzka*"),
                      ("MAXPRESSURE", "MAXPRESSURE-*prybuzka*"),
                      ("STOCHASTIC", "STOCHASTIC-*prybuzka*")]:
        d = latest_dir(pat)
        if d:
            tp, _ = last_tripinfo(d)
            sources[name] = tp

    rows = {name: trip_metrics(p) for name, p in sources.items() if p.exists()}

    print(f"{'агент':14s} {'throughput':>10s} {'travel,с':>9s} {'wait,с':>8s} "
          f"{'timeLoss,с':>10s} {'CO2,кг':>8s}")
    for name, m in rows.items():
        print(f"{name:14s} {m['throughput']:>10d} {m['travel']:>9.1f} {m['wait']:>8.1f} "
              f"{m['timeloss']:>10.1f} {m['co2_kg']:>8.1f}")

    base, idqn = rows.get("Фикс (видео)"), rows.get("IDQN")
    if base and idqn:
        pct = lambda a, b: (a - b) / b * 100 if b else 0.0
        print("\nIDQN vs Фикс-сигнал (видео):")
        print(f"  throughput:   {pct(idqn['throughput'], base['throughput']):+.1f}%")
        print(f"  время в пути: {pct(idqn['travel'], base['travel']):+.1f}%")
        print(f"  ожидание:     {pct(idqn['wait'], base['wait']):+.1f}%")
        print(f"  timeLoss:     {pct(idqn['timeloss'], base['timeloss']):+.1f}%")
        print(f"  CO2:          {pct(idqn['co2_kg'], base['co2_kg']):+.1f}%")


if __name__ == "__main__":
    main()
