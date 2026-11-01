"""Сравнение агентов RESCO на перекрёстке prybuzka: IDQN vs baselines.

Разбирает results/<AGENT>-...prybuzka.../metrics_<ep>.csv (формат RESCO:
время, {'nC': reward}, {'nC': max_queue}, {'nC': queue_length}) и сводит по эпизодам:
средняя/пиковая суммарная очередь и средний reward. Строит кривую обучения IDQN
и сравнивает с эвристиками (MAXPRESSURE/STOCHASTIC).

Запуск:  python src/rl_compare.py [--results RESCO/results]
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

VAL = re.compile(r"nC':\s*([-\d.]+)")


def parse_metrics(csv_path):
    """-> (mean_queue, peak_queue, mean_reward) за эпизод (по строкам-шагам)."""
    q, r = [], []
    for line in open(csv_path, encoding="utf-8"):
        m = VAL.findall(line)
        if len(m) >= 3:
            rew, _maxq, qlen = float(m[0]), float(m[1]), float(m[2])
            q.append(qlen); r.append(rew)
    if not q:
        return None
    return float(np.mean(q)), float(np.max(q)), float(np.mean(r))


def agent_of(dirname):
    return dirname.split("-")[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=os.environ.get("RESCO_RESULTS", "RESCO/results"))
    args = ap.parse_args()
    root = Path(args.results)

    dirs = [d for d in root.glob("*prybuzka*") if d.is_dir()]
    if not dirs:
        raise SystemExit(f"нет результатов prybuzka в {root}")

    # для каждого агента — самый свежий каталог
    latest = {}
    for d in dirs:
        a = agent_of(d.name)
        if a not in latest or d.stat().st_mtime > latest[a].stat().st_mtime:
            latest[a] = d

    series = {}   # agent -> list[(ep, mean_q, peak_q, mean_r)]
    for a, d in latest.items():
        rows = []
        eps = sorted(d.glob("metrics_*.csv"),
                     key=lambda p: int(re.search(r"metrics_(\d+)", p.name).group(1)))
        for p in eps:
            e = int(re.search(r"metrics_(\d+)", p.name).group(1))
            res = parse_metrics(p)
            if res:
                rows.append((e, *res))
        series[a] = rows

    print("=== Сводка по агентам (перекрёсток prybuzka) ===")
    print(f"{'агент':13s} {'эпиз.':>5s} {'ср.очередь(посл.)':>17s} {'лучшая ср.оч.':>13s} {'ср.reward(посл.)':>16s}")
    summary = {}
    for a, rows in series.items():
        if not rows:
            continue
        n = len(rows)
        tail = rows[-max(1, n // 5):]                 # последние ~20% эпизодов
        mq_tail = np.mean([r[1] for r in tail])
        best = min(r[1] for r in rows)
        rew_tail = np.mean([r[3] for r in tail])
        summary[a] = mq_tail
        print(f"{a:13s} {n:5d} {mq_tail:17.1f} {best:13.1f} {rew_tail:16.2f}")

    # относительное улучшение IDQN vs baselines по средней очереди
    if "IDQN" in summary:
        print("\n=== IDQN vs baseline (по средней очереди, меньше = лучше) ===")
        for a, v in summary.items():
            if a == "IDQN":
                continue
            impr = (v - summary["IDQN"]) / v * 100 if v else 0
            print(f"  IDQN vs {a}: {summary['IDQN']:.1f} vs {v:.1f}  -> {impr:+.1f}% очереди")

    # график обучения IDQN
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        plt.figure(figsize=(9, 5))
        for a, rows in series.items():
            if not rows:
                continue
            xs = [r[0] for r in rows]; ys = [r[1] for r in rows]
            if len(rows) > 5:
                plt.plot(xs, ys, label=a, linewidth=1.8)
            else:
                plt.axhline(np.mean(ys), linestyle="--", label=f"{a} (avg)")
        plt.xlabel("эпизод"); plt.ylabel("средняя суммарная очередь (маш.)")
        plt.title("Обучение IDQN vs baseline — перекрёсток Прибузька-Свободи")
        plt.legend(); plt.grid(alpha=0.3)
        out = Path(__file__).resolve().parents[1] / "data" / "rl_learning_curve.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(out, dpi=120, bbox_inches="tight")
        print(f"\n[plot] кривая обучения -> {out}")
    except Exception as e:
        print(f"[plot] пропущено: {e}")


if __name__ == "__main__":
    main()
