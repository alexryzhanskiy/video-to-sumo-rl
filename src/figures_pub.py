"""Публікаційні рисунки (300 dpi, PNG, узгоджена типографіка, БЕЗ title), UA + EN.

Вихід: figures/ (імена без префікса fig#_; англ. версія має суфікс _en):
  network_x300[_en].png          — модель перехрестя у SUMO
  metrics_x10[_en].png           — показники руху ×1.0, 5 контролерів (mean ± σ)
  learning_idqn_x10[_en].png     — крива навчання IDQN (wait, ×1.0), ±σ
  throughput_vs_load[_en].png    — пропускна vs навантаження, 6 контролерів (mean ± σ)
  learning_wait_vs_press[_en].png— криві навчання wait vs press (×1.0), ±σ
  queue_dynamics_x15[_en].png    — динаміка черги у часі, ×1.5, 24 хв

Заголовків (title) на рисунках немає — опис виноситься у підписи статті.
Запуск:  python src/figures_pub.py
"""
from __future__ import annotations
import os, re, glob, sys
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import seed_stats as S
import baselines_stats as B

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import matplotlib
matplotlib.use("Agg")
import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

mpl.rcParams.update({
    "figure.dpi": 300, "savefig.dpi": 300,
    "font.family": "DejaVu Sans", "font.size": 13,
    "axes.labelsize": 13, "xtick.labelsize": 11.5, "ytick.labelsize": 11.5,
    "legend.fontsize": 11, "legend.framealpha": 0.9,
    "axes.grid": True, "grid.alpha": 0.30, "grid.linewidth": 0.6,
    "lines.linewidth": 2.4, "lines.markersize": 7,
    "axes.axisbelow": True, "savefig.bbox": "tight", "savefig.pad_inches": 0.08,
})

OUT = Path("C:/Work/TrafficVideos_RL2/figures"); OUT.mkdir(exist_ok=True)
R = Path("C:/Work/RESCO/results")
COL = {"fix": "#7f7f7f", "act": "#e8820c", "mp": "#d62728",
       "ml": "#9467bd", "wait": "#2ca02c", "press": "#1f77b4"}
Q = re.compile(r"'nC':\s*([-\d.]+)")

# ------------------------- переклади -------------------------
TR = {
 "ua": dict(time_s="час, с", thr="пропускна здатність, ТЗ", metric="Показник",
            wait="Очікування", travel="Час у дорозі", tloss="Втрати часу", dem1355="попит = 1355 ТЗ",
            ep="епізод навчання", queue="середня сумарна черга, ТЗ",
            sigma5="±σ (5 сідів)", idqn_mean="IDQN (середнє за 5 сідами)",
            load="коефіцієнт навантаження", demand="попит",
            fixed="Фіксований (відео)", act="Actuated (індуктивне)", mp="MaxPressure (аналітичний)",
            ml="MPLight (навчений)", iw="IDQN (винагорода wait)", ip="IDQN (винагорода pressure)",
            iwm="IDQN-wait (середнє)", ipm="IDQN-press (середнє)",
            simtime="час симуляції, хв", qint="сумарна черга на перехресті, ТЗ", fixedS="Фіксований",
            ctrl5=["Фікс.\n(відео)", "Actuated", "MaxPressure", "MPLight", "IDQN"]),
 "en": dict(time_s="time, s", thr="throughput, veh", metric="Metric",
            wait="Waiting", travel="Travel time", tloss="Time loss", dem1355="demand = 1355 veh",
            ep="training episode", queue="mean total queue, veh",
            sigma5="±σ (5 seeds)", idqn_mean="IDQN (mean over 5 seeds)",
            load="load factor", demand="demand",
            fixed="Fixed (video)", act="Actuated (gap-based)", mp="MaxPressure (analytical)",
            ml="MPLight (learned)", iw="IDQN (wait reward)", ip="IDQN (pressure reward)",
            iwm="IDQN-wait (mean)", ipm="IDQN-press (mean)",
            simtime="simulation time, min", qint="total intersection queue, veh", fixedS="Fixed",
            ctrl5=["Fixed\n(video)", "Actuated", "MaxPressure", "MPLight", "IDQN"]),
}


def ep_series(mapn, rew, tr, ep):
    ds = [d for d in R.glob(f"IDQN-tr{tr}-{mapn}-*{rew}*") if d.is_dir()]
    if not ds:
        return None
    d = max(ds, key=lambda p: p.stat().st_mtime)
    f = d / f"metrics_{ep}.csv"
    if not f.exists():
        return None
    return np.array([float(Q.findall(l)[2]) for l in open(f, encoding="utf-8") if len(Q.findall(l)) >= 3])


def learning(mapn, rew, eps=100):
    curves = []
    for tr in range(1, 6):
        ys = [np.mean(s) if (s := ep_series(mapn, rew, tr, ep)) is not None and len(s) else np.nan
              for ep in range(1, eps + 1)]
        if not all(np.isnan(ys)):
            curves.append(ys)
    L = min(len(c) for c in curves)
    a = np.array([c[:L] for c in curves])
    return np.nanmean(a, 0), np.nanstd(a, 0, ddof=1)


def save(fig, base, lang):
    name = base + (".png" if lang == "ua" else "_en.png")
    fig.savefig(OUT / name); plt.close(fig)
    print("[fig]", name)


# ===================== мережа SUMO =====================
def fig_network(lang="ua"):
    os.environ.setdefault("SUMO_HOME", r"C:/Program Files (x86)/Eclipse/Sumo")
    sys.path.append(os.path.join(os.environ["SUMO_HOME"], "tools"))
    import sumolib
    from matplotlib.patches import Rectangle, FancyBboxPatch, Circle, FancyArrowPatch
    from matplotlib.legend_handler import HandlerPatch
    ROAD, EDGE, CENTER, DASH, ARROW, TXT = "#e6e9ed", "#3a3f45", "#3a3f45", "#8b9096", "#2c3e50", "#20262e"
    C, HALF, LEG_LEN = 120.0, 9.6, 52
    NPOS, NNEG = C + HALF, C - HALF
    LAB = {"ua": {"N": "вул. Свободи – північ", "S": "вул. Свободи – південь",
                  "E": "вул. Прибузька – схід", "W": "вул. Прибузька – захід",
                  "leg": ["напрям в’їзду", "осьова лінія", "межі смуг"]},
           "en": {"N": "Svobody St. – north", "S": "Svobody St. – south",
                  "E": "Prybuzka St. – east", "W": "Prybuzka St. – west",
                  "leg": ["inbound direction", "centre line", "lane borders"]}}[lang]
    net = sumolib.net.readNet("C:/Work/TrafficVideos_RL2/sumo/intersection.net.xml")
    fig, ax = plt.subplots(figsize=(7.2, 6.4))
    legs = {"N": dict(v=True, near=NPOS, far=NPOS + LEG_LEN),
            "S": dict(v=True, near=NNEG, far=NNEG - LEG_LEN),
            "E": dict(v=False, near=NPOS, far=NPOS + LEG_LEN),
            "W": dict(v=False, near=NNEG, far=NNEG - LEG_LEN)}
    for L, cfg in legs.items():
        vert, near, far = cfg["v"], cfg["near"], cfg["far"]
        perp = 0 if vert else 1
        in_c = sorted(ln.getShape()[0][perp] for ln in net.getEdge(f"n{L}_nC").getLanes())
        out_c = sorted(ln.getShape()[0][perp] for ln in net.getEdge(f"nC_n{L}").getLanes())
        lo, hi = min(near, far), max(near, far)

        def seg(pc, a, b, **kw):
            ax.plot([pc, pc], [a, b], **kw) if vert else ax.plot([a, b], [pc, pc], **kw)

        if vert:
            ax.add_patch(Rectangle((C - HALF, lo), 2 * HALF, hi - lo, fc=ROAD, ec="none", zorder=1))
        else:
            ax.add_patch(Rectangle((lo, C - HALF), hi - lo, 2 * HALF, fc=ROAD, ec="none", zorder=1))
        seg(C - HALF, lo, hi, color=EDGE, lw=1.6, zorder=3)
        seg(C + HALF, lo, hi, color=EDGE, lw=1.6, zorder=3)
        seg(C, lo, hi, color=CENTER, lw=1.4, zorder=4)
        for grp in (in_c, out_c):
            for a, b in zip(grp[:-1], grp[1:]):
                seg((a + b) / 2, lo + 2, hi - 2, color=DASH, lw=0.9, ls=(0, (9, 8)), zorder=4)
        mc = in_c[len(in_c) // 2]; sgn = 1 if near < far else -1
        s0, s1 = far - sgn * LEG_LEN * 0.28, far - sgn * LEG_LEN * 0.55
        xy, xt = ((mc, s1), (mc, s0)) if vert else ((s1, mc), (s0, mc))
        ax.annotate("", xy=xy, xytext=xt,
                    arrowprops=dict(arrowstyle="-|>,head_width=0.4,head_length=0.8", color=ARROW, lw=2.2), zorder=6)
    ax.add_patch(Rectangle((C - HALF, C - HALF), 2 * HALF, 2 * HALF, fc=ROAD, ec="none", zorder=2))
    ax.add_patch(Circle((C, C), 6.6, fc="white", ec=EDGE, lw=1.0, zorder=8))
    ax.add_patch(FancyBboxPatch((C - 1.9, C - 4.6), 3.8, 9.2, boxstyle="round,pad=0.4,rounding_size=1.1",
                 fc="#2b2f36", ec="#14171b", lw=0.8, zorder=9))
    for dy, col in [(2.8, "#d64545"), (0.0, "#e0b83a"), (-2.8, "#3f9d54")]:
        ax.add_patch(Circle((C, C + dy), 1.0, color=col, zorder=10))

    def txt(x, y, s, ha, va):
        ax.annotate(s, (x, y), ha=ha, va=va, fontsize=11.5, fontweight="bold", color=TXT,
                    bbox=dict(boxstyle="round,pad=0.28", fc="white", ec="#8b9096", lw=0.8), zorder=11)
    txt(C, NPOS + LEG_LEN + 4, LAB["N"], "center", "bottom")
    txt(C, NNEG - LEG_LEN - 4, LAB["S"], "center", "top")
    # Сх — у білому куті вгорі-праворуч (правіше півн. дороги, вище сх. дороги);
    # Зх — у білому куті внизу-ліворуч (лівіше півд. дороги, нижче зх. дороги) → без накладання на полотно
    txt(NPOS + 4, NPOS + 6, LAB["E"], "left", "bottom")
    txt(NNEG - 4, NNEG - 6, LAB["W"], "right", "top")
    ax.set_aspect("equal"); ax.axis("off"); ax.margins(0.06)

    class _HA(HandlerPatch):
        def create_artists(self, legend, orig, xd, yd, w, h, fs, trans):
            p = FancyArrowPatch((0, h / 2), (w, h / 2), arrowstyle="-|>", mutation_scale=13,
                                color=ARROW, lw=2.2, shrinkA=0, shrinkB=0)
            p.set_transform(trans); return [p]
    arr = FancyArrowPatch((0, 0), (1, 0), color=ARROW)
    ax.legend(handles=[arr, Line2D([0], [0], color=CENTER, lw=1.4),
                       Line2D([0], [0], color=DASH, lw=0.9, ls="--")],
              labels=LAB["leg"], handler_map={arr: _HA()},
              loc="lower right", fontsize=10, framealpha=0.96, edgecolor="#8b9096")
    fig.tight_layout()
    save(fig, "network_x300", lang)


# ===================== показники ×1.0 =====================
def fig_metrics_x10(lang="ua"):
    t = TR[lang]
    fx, ac, mp, ml, iq = B.fixed("10"), B.actuated("10"), B.maxpressure("prybuzka"), \
        B.mplight("prybuzka"), B.idqn("prybuzka", "wait_norm")
    M = [fx, ac, mp, ml, iq]
    bar_c = [COL["fix"], COL["act"], COL["mp"], COL["ml"], COL["wait"]]
    x = np.arange(5); w = 0.26
    fig, (axL, axR) = plt.subplots(1, 2, figsize=(13, 5.0))
    for i, (lab, k) in enumerate([(t["wait"], 1), (t["travel"], 2), (t["tloss"], 3)]):
        axL.bar(x + (i - 1) * w, [m[0][k] for m in M], w, yerr=[m[1][k] for m in M],
                capsize=3, label=lab, error_kw=dict(lw=1, ecolor="#333"))
    axL.set_xticks(x); axL.set_xticklabels(t["ctrl5"])
    axL.set_ylabel(t["time_s"]); axL.legend(title=t["metric"])
    thr = [m[0][0] for m in M]; errs = [m[1][0] for m in M]
    axR.bar(x, thr, 0.6, color=bar_c, yerr=errs, capsize=4, error_kw=dict(lw=1, ecolor="#333", zorder=1))
    for xi, v, e in zip(x, thr, errs):
        axR.text(xi, v + e + 3, f"{v:.0f}", ha="center", va="bottom", fontsize=10, zorder=6,
                 bbox=dict(boxstyle="round,pad=0.18", fc="white", ec="0.7", lw=0.4, alpha=0.95))
    axR.axhline(1355, ls="--", color="#444", lw=1.4, label=t["dem1355"])
    axR.set_xticks(x); axR.set_xticklabels(t["ctrl5"]); axR.set_ylim(min(thr) - 45, 1355 + 55)
    axR.set_ylabel(t["thr"]); axR.legend()
    fig.tight_layout()
    save(fig, "metrics_x10", lang)


# ===================== крива навчання IDQN =====================
def fig_learning_idqn(lang="ua"):
    t = TR[lang]
    m, s = learning("prybuzka", "wait_norm")
    x = np.arange(1, len(m) + 1)
    fig, ax = plt.subplots(figsize=(9.2, 5.0))
    ax.fill_between(x, m - s, m + s, color=COL["wait"], alpha=0.22, label=t["sigma5"])
    ax.plot(x, m, color=COL["wait"], label=t["idqn_mean"])
    ax.set_xlabel(t["ep"]); ax.set_ylabel(t["queue"]); ax.set_xlim(1, len(m)); ax.legend()
    fig.tight_layout()
    save(fig, "learning_idqn_x10", lang)


# ===================== пропускна vs навантаження =====================
def fig_throughput_vs_load(lang="ua"):
    t = TR[lang]
    x = np.arange(3); loads = ["×1.0", "×1.2", "×1.5"]; dem = [1355, 1626, 2036]
    maps = ["prybuzka", "prybuzka_12", "prybuzka_15"]; lds = ["10", "12", "15"]

    def thr(fn):
        ms = [fn(l) for l in lds]
        return [m[0][0] for m in ms], [m[1][0] for m in ms]
    fxm, fxe = thr(B.fixed); acm, ace = thr(B.actuated)
    mpm, mpe = [B.maxpressure(m)[0][0] for m in maps], [B.maxpressure(m)[1][0] for m in maps]
    mlm, mle = [B.mplight(m)[0][0] for m in maps], [B.mplight(m)[1][0] for m in maps]
    wm, we = [B.idqn(m, "wait_norm")[0][0] for m in maps], [B.idqn(m, "wait_norm")[1][0] for m in maps]
    pm, pe = [B.idqn(m, "pressure_norm")[0][0] for m in maps], [B.idqn(m, "pressure_norm")[1][0] for m in maps]
    fig, ax = plt.subplots(figsize=(9.2, 5.7))
    ax.plot(x, dem, "k--", alpha=.55, lw=1.6, label=t["demand"])
    for m, e, c, mk, lab in [(fxm, fxe, COL["fix"], "o", t["fixed"]),
                             (acm, ace, COL["act"], "s", t["act"]),
                             (mpm, mpe, COL["mp"], "^", t["mp"]),
                             (mlm, mle, COL["ml"], "D", t["ml"]),
                             (wm, we, COL["wait"], "o", t["iw"]),
                             (pm, pe, COL["press"], "o", t["ip"])]:
        ax.errorbar(x, m, yerr=e, fmt=mk + "-", color=c, capsize=4, capthick=1.2, label=lab)
    ax.set_xticks(x); ax.set_xticklabels(loads)
    ax.set_xlabel(t["load"]); ax.set_ylabel(t["thr"]); ax.legend(fontsize=10)
    fig.tight_layout()
    save(fig, "throughput_vs_load", lang)


# ===================== навчання wait vs press =====================
def fig_learning_wp(lang="ua"):
    t = TR[lang]
    fig, ax = plt.subplots(figsize=(9.2, 5.0))
    for rew, c, lab in [("wait_norm", COL["wait"], t["iwm"]), ("pressure_norm", COL["press"], t["ipm"])]:
        m, s = learning("prybuzka", rew); x = np.arange(1, len(m) + 1)
        ax.fill_between(x, m - s, m + s, color=c, alpha=0.18)
        ax.plot(x, m, color=c, label=lab)
    ax.set_xlabel(t["ep"]); ax.set_ylabel(t["queue"]); ax.set_xlim(1, 100); ax.legend()
    fig.tight_layout()
    save(fig, "learning_wait_vs_press", lang)


# ===================== динаміка черги ×1.5 =====================
def fig_queue_dynamics(lang="ua"):
    t = TR[lang]

    def smooth(y, k=5):
        return np.convolve(y, np.ones(k) / k, mode="same") if len(y) >= k else y
    npz = np.load("C:/Work/TrafficVideos_RL2/data/queue_fixed_act_x15.npz")
    tm = npz["t"]; fixed = npz["fixed"].mean(0); TMAX = 1440
    mask = tm <= TMAX
    wait = ep_series("prybuzka_15", "wait_norm", 1, 100)
    press = ep_series("prybuzka_15", "pressure_norm", 3, 100)
    tt = np.arange(5, 5 * len(wait) + 1, 5); m2 = tt <= TMAX
    fig, ax = plt.subplots(figsize=(9.6, 5.0))
    ax.plot(tm[mask] / 60, smooth(fixed)[mask], color=COL["fix"], label=t["fixedS"])
    ax.plot(tt[m2] / 60, smooth(wait)[m2], color=COL["wait"], label="IDQN-wait")
    ax.plot(tt[m2] / 60, smooth(press)[m2], color=COL["press"], label="IDQN-press")
    ax.set_xlim(0, 24); ax.set_xlabel(t["simtime"]); ax.set_ylabel(t["qint"]); ax.legend()
    fig.tight_layout()
    save(fig, "queue_dynamics_x15", lang)


if __name__ == "__main__":
    for lang in ("ua", "en"):
        fig_network(lang)
        fig_metrics_x10(lang)
        fig_learning_idqn(lang)
        fig_throughput_vs_load(lang)
        fig_learning_wp(lang)
        fig_queue_dynamics(lang)
    print("\nусі рисунки -> figures/  (UA + EN, 300 dpi, PNG, без title)")
