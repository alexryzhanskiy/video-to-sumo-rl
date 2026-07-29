"""Перегенерація рисунків для статті українською: лише Фікс vs IDQN.

- rl_comparison.png  — затримки (очікування/час у дорозі/втрати часу) + пропускна.
- rl_learning_curve.png — крива навчання лише IDQN (wait, ×1.0) з результатів RESCO.

Запуск:  python src/article_figs.py
"""
from __future__ import annotations
import re, sys
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

DATA = Path("C:/Work/TrafficVideos_RL2/data")
RESULTS = Path("C:/Work/RESCO/results")
VAL = re.compile(r"nC':\s*([-\d.]+)")

# Показники за навантаження ×1.0, однакове вікно оцінювання (з прогонів RESCO/SUMO)
FIX = {"through": 1283, "travel": 62.1, "wait": 33.7, "timeloss": 44.6}
IDQN = {"through": 1352, "travel": 40.8, "wait": 13.0, "timeloss": 23.8}
DEMAND = 1355

BLUE, GREEN, GREY = "#1f77b4", "#2ca02c", "#8a8a8a"


def bar_chart():
    fig, (axL, axR) = plt.subplots(1, 2, figsize=(11, 4.6))
    agents = ["Фікс\n(відео)", "IDQN"]
    metrics = [("Очікування, с", "wait"), ("Час у дорозі, с", "travel"), ("Втрати часу, с", "timeloss")]
    x = np.arange(len(agents)); w = 0.26
    for i, (lab, key) in enumerate(metrics):
        vals = [FIX[key], IDQN[key]]
        axL.bar(x + (i - 1) * w, vals, w, label=lab)
        for xi, v in zip(x + (i - 1) * w, vals):
            axL.text(xi, v + 0.8, f"{v:.1f}", ha="center", va="bottom", fontsize=8)
    axL.set_xticks(x); axL.set_xticklabels(agents)
    axL.set_title("Затримки (менше = краще)"); axL.legend(fontsize=9); axL.grid(axis="y", alpha=0.3)

    thr = [FIX["through"], IDQN["through"]]
    axR.bar(x, thr, 0.5, color=[GREY, GREEN])
    for xi, v in zip(x, thr):
        axR.text(xi, v + 3, str(v), ha="center", va="bottom", fontsize=9)
    axR.axhline(DEMAND, ls="--", color="#444", lw=1, label=f"попит {DEMAND}")
    axR.set_xticks(x); axR.set_xticklabels(agents)
    axR.set_ylim(min(thr) - 40, DEMAND + 30)
    axR.set_title("Пропускна здатність (проїхало ТЗ)"); axR.legend(fontsize=9); axR.grid(axis="y", alpha=0.3)

    fig.suptitle("Прибузька–Свободи: фіксований світлофор (відео) проти RL-агента IDQN", fontsize=12)
    fig.tight_layout()
    fig.savefig(DATA / "rl_comparison.png", dpi=140, bbox_inches="tight")
    print("[fig] rl_comparison.png")


def parse_queue(csv_path):
    q = []
    for line in open(csv_path, encoding="utf-8"):
        m = VAL.findall(line)
        if len(m) >= 3:
            q.append(float(m[2]))
    return float(np.mean(q)) if q else None


def learning_curve():
    # каталог саме IDQN, ×1.0 (prybuzka-1-), винагорода wait_norm
    cand = [d for d in RESULTS.glob("IDQN-*prybuzka-1-*wait_norm*") if d.is_dir()]
    if not cand:
        print("[fig] не знайдено IDQN wait ×1.0"); return
    d = max(cand, key=lambda p: p.stat().st_mtime)
    eps = sorted(d.glob("metrics_*.csv"), key=lambda p: int(re.search(r"metrics_(\d+)", p.name).group(1)))
    xs, ys = [], []
    for p in eps:
        e = int(re.search(r"metrics_(\d+)", p.name).group(1))
        v = parse_queue(p)
        if v is not None:
            xs.append(e); ys.append(v)
    plt.figure(figsize=(9, 4.8))
    plt.plot(xs, ys, color=BLUE, lw=1.8, label="IDQN")
    plt.xlabel("епізод"); plt.ylabel("середня сумарна черга (ТЗ)")
    plt.title("Навчання агента IDQN — перехрестя Прибузька–Свободи")
    plt.legend(); plt.grid(alpha=0.3)
    plt.savefig(DATA / "rl_learning_curve.png", dpi=140, bbox_inches="tight")
    print(f"[fig] rl_learning_curve.png  (з {d.name}, {len(xs)} епізодів)")


if __name__ == "__main__":
    bar_chart()
    learning_curve()
