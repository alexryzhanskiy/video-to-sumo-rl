"""Сравнение throughput-aware награды: фикс vs IDQN(wait) vs IDQN_pressure по нагрузкам.

Отвечает на вопрос: чинит ли max-pressure награда провал throughput под перегрузом.
Различает RESCO-папки по суффиксу награды в имени (wait_norm / pressure_norm).

Запуск:  python src/throughput_compare.py
"""
from __future__ import annotations

import glob
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
RESULTS = Path(os.environ.get("RESCO_RESULTS", ROOT / "RESCO" / "results"))
SUMO = ROOT / "sumo"

# нагрузка -> (тег карты в имени папки, фикс-tripinfo, спрос)
LOADS = {
    "×1.0": ("prybuzka-1", SUMO / "fixed_tripinfo.xml", 1355),
    "×1.2": ("prybuzka_12-1", SUMO / "fixed_tripinfo_12.xml", 1626),
    "×1.5": ("prybuzka_15-1", SUMO / "fixed_tripinfo_15.xml", 2036),
}


def trip(path: Path):
    dur, wait = [], []
    for tp in ET.parse(path).getroot().findall("tripinfo"):
        dur.append(float(tp.get("duration")))
        wait.append(float(tp.get("waitingTime")))
    return {"thru": len(dur), "travel": float(np.mean(dur)), "wait": float(np.mean(wait))}


def latest_trip(map_tag, reward_tag):
    pat = f"IDQN-*{map_tag}-drq_norm1-{reward_tag}*"
    ds = sorted(glob.glob(str(RESULTS / pat)), key=lambda p: Path(p).stat().st_mtime)
    if not ds:
        return None
    d = Path(ds[-1])
    tps = glob.glob(str(d / "tripinfo_*.xml"))
    if not tps:
        return None
    n = max(int(Path(f).stem.split("_")[-1]) for f in tps)
    return trip(d / f"tripinfo_{n}.xml")


def main():
    print(f"{'нагрузка':8s} {'спрос':>6s} | {'фикс':>6s} {'IDQN-wait':>10s} {'IDQN-press':>11s}  (throughput)")
    data = {}
    for load, (tag, fixed, dem) in LOADS.items():
        fx = trip(fixed) if fixed.exists() else None
        w = latest_trip(tag, "wait_norm")
        p = latest_trip(tag, "pressure_norm")
        data[load] = (fx, w, p, dem)
        fxt = fx["thru"] if fx else "-"
        wt = w["thru"] if w else "нет"
        pt = p["thru"] if p else "нет(идёт?)"
        print(f"{load:8s} {dem:>6d} | {str(fxt):>6} {str(wt):>10} {str(pt):>11}")

    print(f"\n{'нагрузка':8s} | {'IDQN-wait':>10s} {'IDQN-press':>11s}  (ср. ожидание, с)")
    for load, (fx, w, p, dem) in data.items():
        wt = f"{w['wait']:.1f}" if w else "-"
        pt = f"{p['wait']:.1f}" if p else "-"
        print(f"{load:8s} | {wt:>10} {pt:>11}")

    # график throughput по нагрузкам
    if all(data[l][2] for l in data):     # все pressure готовы
        try:
            import matplotlib; matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            loads = list(data); x = np.arange(len(loads))
            fx = [data[l][0]["thru"] for l in loads]
            w = [data[l][1]["thru"] for l in loads]
            p = [data[l][2]["thru"] for l in loads]
            dem = [data[l][3] for l in loads]
            plt.figure(figsize=(8, 5))
            plt.plot(x, dem, "k--", alpha=.5, label="попит")
            plt.plot(x, fx, "o-", color="#888", label="Фікс (відео)")
            plt.plot(x, w, "o-", color="#2a9d3f", label="IDQN (винагорода wait)")
            plt.plot(x, p, "o-", color="#1f6feb", label="IDQN (винагорода pressure)")
            plt.xticks(x, loads); plt.ylabel("пропускна здатність (проїхало ТЗ)")
            plt.xlabel("навантаження")
            plt.title("Пропускна здатність за зростання навантаження:\nвинагорода pressure проти wait")
            plt.legend(); plt.grid(alpha=.3)
            out = ROOT / "data" / "throughput_compare.png"
            plt.savefig(out, dpi=120, bbox_inches="tight")
            print(f"\n[plot] -> {out}")
        except Exception as e:
            print(f"[plot] пропущено: {e}")


if __name__ == "__main__":
    main()
