"""Статистична оцінка за кількома сідами: mean±std для RL vs Фікс + крива навчання з тінню.

RL: для кожного (винагорода × навантаження) беремо 5 трайлів (tr1..tr5), із фінального
епізоду кожного — метрики (throughput/очік/дорога/timeLoss/CO2), рахуємо mean±std.
Фікс: 5 сідів SUMO (sumo/seeds/fix_*).
Крива навчання: 5 сідів IDQN-wait ×1.0, mean±std по епізодах, з заливкою ±σ.

Запуск:  python src/seed_stats.py
"""
from __future__ import annotations
import glob, os, re, sys
import xml.etree.ElementTree as ET
from pathlib import Path
import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
R = Path(os.environ.get("RESCO_RESULTS", ROOT / "RESCO" / "results"))
S = ROOT / "sumo"
DATA = ROOT / "data"
LOADS = {"prybuzka": ("×1.0", "10"), "prybuzka_12": ("×1.2", "12"), "prybuzka_15": ("×1.5", "15")}
VAL = re.compile(r"nC':\s*([-\d.]+)")


def trip_metrics(tp):
    try:
        ts = ET.parse(tp).getroot().findall("tripinfo")
    except Exception:
        return None                     # обрізаний/битий файл — пропустити
    n = len(ts)
    if not n:
        return None
    dur = np.mean([float(t.get("duration")) for t in ts])
    wait = np.mean([float(t.get("waitingTime")) for t in ts])
    tl = np.mean([float(t.get("timeLoss")) for t in ts])
    co2 = sum(float(t.find("emissions").get("CO2_abs")) for t in ts
              if t.find("emissions") is not None) / 1e6
    return np.array([n, wait, dur, tl, co2])


def rl_seed_dir(mapn, reward, tr):
    ds = [d for d in R.glob(f"IDQN-tr{tr}-{mapn}-*{reward}*") if d.is_dir()]
    return max(ds, key=lambda p: p.stat().st_mtime) if ds else None


def rl_stats(mapn, reward, seeds=(1, 2, 3, 4, 5)):
    rows = []
    for tr in seeds:
        d = rl_seed_dir(mapn, reward, tr)
        if d is None:
            continue
        tps = glob.glob(str(d / "tripinfo_*.xml"))
        if not tps:
            continue
        nmax = max(int(Path(f).stem.split("_")[-1]) for f in tps)
        if nmax < 90:                   # незавершений прогон (обірвався до 100 еп.) — пропустити
            continue
        m = trip_metrics(d / f"tripinfo_{nmax}.xml")
        if m is not None:
            rows.append(m)
    if not rows:
        return None
    a = np.array(rows)
    # відкинути лише прогони, ЯВНО пошкоджені контенцією TraCI (одинокі провали
    # серед ідентичних сідів: throughput <0.8×median, напр. 718 при 1352).
    # Реальний розкид політики (напр. ×1.5-wait 0.83–0.84×median) зберігаємо —
    # це справжня нестабільність wait-винагороди під перегрузом, наш висновок.
    med = np.median(a[:, 0])
    keep = a[a[:, 0] >= 0.8 * med]
    a = keep if len(keep) >= 1 else a
    return a.mean(0), a.std(0, ddof=1) if len(a) > 1 else np.zeros(a.shape[1]), len(a)


def fix_stats(load):
    rows = [trip_metrics(f) for f in sorted(glob.glob(str(S / f"seeds/fix_{load}_s*.xml")))]
    rows = [r for r in rows if r is not None]
    if not rows:
        return None
    a = np.array(rows)
    return a.mean(0), a.std(0, ddof=1), len(rows)


def fmt(mean, std):  # "throughput / очік / дорога / timeLoss / CO2"
    return (f"{mean[0]:.0f}±{std[0]:.0f} | {mean[1]:.1f}±{std[1]:.1f} | {mean[2]:.1f}±{std[2]:.1f} | "
            f"{mean[3]:.1f}±{std[3]:.1f} | {mean[4]:.0f}±{std[4]:.0f}")


def main():
    print("Метрики: throughput | очікування,с | дорога,с | timeLoss,с | CO2,кг  (mean±std, 5 сідів)\n")
    for mapn, (lab, ld) in LOADS.items():
        print(f"— навантаження {lab} —")
        f = fix_stats(ld)
        if f: print(f"  Фікс       : {fmt(f[0], f[1])}  (n={f[2]})")
        for rew, name in [("wait_norm", "IDQN-wait"), ("pressure_norm", "IDQN-press")]:
            r = rl_stats(mapn, rew)
            if r: print(f"  {name:11s}: {fmt(r[0], r[1])}  (n={r[2]})")
            else: print(f"  {name:11s}: (ще нема даних)")
        print()

    # крива навчання з тінню: IDQN-wait ×1.0, 5 сідів
    curves = []
    for tr in (1, 2, 3, 4, 5):
        d = rl_seed_dir("prybuzka", "wait_norm", tr)
        if d is None:
            continue
        eps = sorted(d.glob("metrics_*.csv"), key=lambda p: int(re.search(r"metrics_(\d+)", p.name).group(1)))
        ys = []
        for p in eps:
            q = [float(VAL.findall(l)[2]) for l in open(p, encoding="utf-8") if len(VAL.findall(l)) >= 3]
            ys.append(np.mean(q) if q else np.nan)
        curves.append(ys)
    if curves:
        L = min(len(c) for c in curves)
        arr = np.array([c[:L] for c in curves])
        mean = np.nanmean(arr, 0); std = np.nanstd(arr, 0, ddof=1)
        import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
        x = np.arange(1, L + 1)
        plt.figure(figsize=(9, 4.8))
        plt.fill_between(x, mean - std, mean + std, color="#1f77b4", alpha=0.25, label="±σ (5 сідів)")
        plt.plot(x, mean, color="#1f77b4", lw=1.8, label="IDQN (середнє)")
        plt.xlabel("епізод"); plt.ylabel("середня сумарна черга (ТЗ)")
        plt.title("Навчання агента IDQN — перехрестя Прибузька–Свободи (5 сідів)")
        plt.legend(); plt.grid(alpha=0.3)
        plt.savefig(DATA / "rl_learning_curve.png", dpi=140, bbox_inches="tight")
        print(f"[fig] крива навчання з тінню ±σ ({len(curves)} сідів) -> rl_learning_curve.png")


if __name__ == "__main__":
    main()
