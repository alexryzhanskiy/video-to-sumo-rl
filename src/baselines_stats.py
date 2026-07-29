"""Статистика сильніших базових рівнів (Actuated, MaxPressure) + оновлення Рис. 5.

Actuated: нативний SUMO, gap-based tlLogic (sumo/intersection_act.net.xml), 5 сідів
          -> sumo/seeds/act_{10,12,15}_s{1..5}.xml
MaxPressure: аналітичний агент RESCO -> results/MAXPRESSURE-tr{1..5}-{map}-*mplight*
Фікс / IDQN: як у seed_stats.

Друкує mean±std по всіх контролерах і перемальовує data/throughput_compare.png (Рис. 5)
з лініями для Фікс, Actuated, MaxPressure, IDQN-wait, IDQN-press (планки ±σ).

Запуск:  python src/baselines_stats.py
"""
from __future__ import annotations
import glob, sys
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import seed_stats as S

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

R = Path("C:/Work/RESCO/results")
SU = Path("C:/Work/TrafficVideos_RL2/sumo")
DATA = Path("C:/Work/TrafficVideos_RL2/data")
LOADS = [("×1.0", "10", "prybuzka"), ("×1.2", "12", "prybuzka_12"), ("×1.5", "15", "prybuzka_15")]


def _stats(rows):
    a = np.array([r for r in rows if r is not None])
    return a.mean(0), (a.std(0, ddof=1) if len(a) > 1 else np.zeros(a.shape[1])), len(a)


def fixed(ld):
    return _stats([S.trip_metrics(f) for f in sorted(glob.glob(str(SU / f"seeds/fix_{ld}_s*.xml")))])


def actuated(ld):
    return _stats([S.trip_metrics(f) for f in sorted(glob.glob(str(SU / f"seeds/act_{ld}_s*.xml")))])


def maxpressure(mapn):
    rows = []
    for tr in range(1, 6):
        ds = [d for d in R.glob(f"MAXPRESSURE-tr{tr}-{mapn}-*mplight*") if d.is_dir()]
        if not ds:
            continue
        d = max(ds, key=lambda p: p.stat().st_mtime)
        tps = glob.glob(str(d / "tripinfo_*.xml"))
        if not tps:
            continue
        nmax = max(int(Path(f).stem.split("_")[-1]) for f in tps)
        rows.append(S.trip_metrics(d / f"tripinfo_{nmax}.xml"))
    return _stats(rows)


def mplight(mapn):
    """MPLight (FRAP-DQN на винагороді pressure), навчений 100 еп. × 5 сідів.
    На tr створюються дві теки (службова порожня + робоча) — беремо ту, що має tripinfo.
    Фільтруємо явні збої контенції (<0.8×median), як і для IDQN."""
    import numpy as _np
    rows = []
    for tr in range(1, 6):
        cand = [d for d in R.glob(f"MPLight-tr{tr}-{mapn}-*mplight-pressure*")
                if d.is_dir() and glob.glob(str(d / "tripinfo_*.xml"))]
        if not cand:
            continue
        d = max(cand, key=lambda p: p.stat().st_mtime)
        tps = glob.glob(str(d / "tripinfo_*.xml"))
        nmax = max(int(Path(f).stem.split("_")[-1]) for f in tps)
        if nmax < 90:
            continue
        m = S.trip_metrics(d / f"tripinfo_{nmax}.xml")
        if m is not None:
            rows.append(m)
    a = _np.array(rows)
    med = _np.median(a[:, 0])
    a = a[a[:, 0] >= 0.8 * med]
    return a.mean(0), (a.std(0, ddof=1) if len(a) > 1 else _np.zeros(a.shape[1])), len(a)


def idqn(mapn, rew):
    m, s, n = S.rl_stats(mapn, rew)
    return m, s, n


def _fmt(r):
    m, s, n = r
    return (f"{m[0]:.0f}±{s[0]:.0f} | {m[1]:.1f}±{s[1]:.1f} | {m[2]:.1f}±{s[2]:.1f} | "
            f"{m[3]:.1f}±{s[3]:.1f} | {m[4]:.0f}±{s[4]:.0f}  (n={n})")


def main():
    print("thru | wait,s | travel,s | timeLoss,s | CO2,kg  (mean±std)\n")
    for lab, ld, mp in LOADS:
        print(f"—— {lab} ——")
        print("  Фіксований :", _fmt(fixed(ld)))
        print("  Actuated   :", _fmt(actuated(ld)))
        print("  MaxPressure:", _fmt(maxpressure(mp)))
        print("  MPLight    :", _fmt(mplight(mp)))
        print("  IDQN-wait  :", _fmt(idqn(mp, "wait_norm")))
        print("  IDQN-press :", _fmt(idqn(mp, "pressure_norm")))
        print()

    # ---- Рис. 5: пропускна vs навантаження, усі контролери ----
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from PIL import Image
    x = np.arange(3)
    dem = [1355, 1626, 2036]

    def thr(fn):
        ms = [fn(k) for k in ("10", "12", "15")]
        return [m[0][0] for m in ms], [m[1][0] for m in ms]

    def thr_rl(rew):
        ms = [idqn(mp, rew) for _, _, mp in LOADS]
        return [m[0][0] for m in ms], [m[1][0] for m in ms]

    fxm, fxe = thr(fixed)
    acm, ace = thr(actuated)
    mpm, mpe = [maxpressure(mp)[0][0] for _, _, mp in LOADS], [maxpressure(mp)[1][0] for _, _, mp in LOADS]
    mlm, mle = [mplight(mp)[0][0] for _, _, mp in LOADS], [mplight(mp)[1][0] for _, _, mp in LOADS]
    wm, we = thr_rl("wait_norm")
    pm, pe = thr_rl("pressure_norm")

    plt.figure(figsize=(8, 5.587))
    plt.plot(x, dem, "k--", alpha=.5, label="попит")
    plt.errorbar(x, fxm, yerr=fxe, fmt="o-", color="#8a8a8a", capsize=4, label="Фіксований (відео)")
    plt.errorbar(x, acm, yerr=ace, fmt="s-", color="#e8820c", capsize=4, label="Actuated (індуктивне)")
    plt.errorbar(x, mpm, yerr=mpe, fmt="^-", color="#d62728", capsize=4, label="MaxPressure (аналітичний)")
    plt.errorbar(x, mlm, yerr=mle, fmt="D-", color="#9467bd", capsize=4, label="MPLight (навчений)")
    plt.errorbar(x, wm, yerr=we, fmt="o-", color="#2a9d3f", capsize=4, label="IDQN (винагорода wait)")
    plt.errorbar(x, pm, yerr=pe, fmt="o-", color="#1f6feb", capsize=4, label="IDQN (винагорода pressure)")
    plt.xticks(x, [l for l, _, _ in LOADS])
    plt.ylabel("пропускна здатність (проїхало ТЗ)"); plt.xlabel("навантаження")
    plt.title("Пропускна здатність за зростання навантаження\n(планки — ±σ за 5 сідів)")
    plt.legend(fontsize=8.5); plt.grid(alpha=.3)
    out = DATA / "throughput_compare.png"
    plt.savefig(out, dpi=120, bbox_inches="tight"); plt.close()

    # доповнити до співвідношення 984/687 (щоб заміна в docx не спотворювала)
    im = Image.open(out).convert("RGB"); w, h = im.size; target = 984 / 687
    if w / h < target:
        nw = int(round(h * target)); c = Image.new("RGB", (nw, h), (255, 255, 255)); c.paste(im, ((nw - w) // 2, 0)); c.save(out)
    print(f"[fig5] -> {out}")


if __name__ == "__main__":
    main()
