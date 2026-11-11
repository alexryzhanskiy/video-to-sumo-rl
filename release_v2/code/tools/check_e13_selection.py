"""Independent recomputation of the E13 selection (pre-registration 5.1/5.2, steps 1-3) from the published episode tables.

Usage: python check_e13_selection.py <e13/results>
"""
import csv
import statistics as st
import sys
from pathlib import Path

res = Path(sys.argv[1])
ev = list(csv.DictReader(open(res / "eval_episodes.csv", encoding="utf-8")))
bl = list(csv.DictReader(open(res / "baseline_episodes.csv", encoding="utf-8")))
MAPS = {"x1.0": "prybuzka_va10", "x1.2": "prybuzka_va12"}
fixed = {(r["map"], r["route_file"], r["sumo_seed"]): r for r in bl
         if r["policy"] == "Fixed plan" and r["eval_set"] == "validation"}
cands = sorted({(r["rung"], r["policy"]) for r in ev if r["rung"] in ("L1", "L2", "L3", "L4")})

rows = []
for rung, pol in cands:
    per, dl, delays, ok = {}, 0, [], True
    for load, m in MAPS.items():
        # per-load models (L1-L3) are scored on their own load; the mixed-load model (L4) on each load
        tl = "mix" if rung == "L4" else load
        eps = [r for r in ev if r["rung"] == rung and r["policy"] == pol and r["eval_set"] == "validation"
               and r["train_load"] == tl and r["map"] == m]
        pairs = [(r, fixed.get((m, r["route_file"], r["sumo_seed"]))) for r in eps]
        if len(eps) != 50 or any(f is None for _, f in pairs):
            ok = False
        d = [float(r["arrived_1800"]) - float(f["arrived_1800"]) for r, f in pairs if f]
        dem = st.mean(float(r["demand"]) for r in eps)
        per[load] = 100 * st.mean(d) / dem
        dl += sum(1 for r in eps if r["deadlock"] in ("1", "True", "true"))
        delays.append(st.mean(float(r["mean_delay_s"]) for r in eps))
    rows.append({"rung": rung, "policy": pol, "x1.0": per["x1.0"], "x1.2": per["x1.2"],
                 "score": st.mean(per.values()), "deadlocks": dl, "delay": st.mean(delays), "complete": ok})


def rank(cand):
    cand = sorted(cand, key=lambda r: (r["deadlocks"] > 0, -r["score"]))
    # ties within 0.1 pp go to the lower delay (adjacent swaps, as D10)
    changed = True
    while changed:
        changed = False
        for i in range(len(cand) - 1):
            a, b = cand[i], cand[i + 1]
            if (a["deadlocks"] > 0) == (b["deadlocks"] > 0) and abs(a["score"] - b["score"]) <= 0.1 and b["delay"] < a["delay"]:
                cand[i], cand[i + 1] = b, a
                changed = True
    return cand


for rung in ("L1", "L2"):
    print(rung, "mean score over 4 rewards:", round(st.mean(r["score"] for r in rows if r["rung"] == rung), 4))
base = max(("L1", "L2"), key=lambda g: st.mean(r["score"] for r in rows if r["rung"] == g))
print("step 1-2: base", base, "| rewards", [r["policy"] for r in rank([r for r in rows if r["rung"] == base])[:2]])
print(f"{'#':>2} {'rung':4} {'policy':14} {'x1.0':>8} {'x1.2':>8} {'score':>8} {'dl':>3} {'delay':>7} complete")
final = rank(rows)
for i, r in enumerate(final, 1):
    print(f"{i:2d} {r['rung']:4} {r['policy']:14} {r['x1.0']:8.4f} {r['x1.2']:8.4f} {r['score']:8.4f} {r['deadlocks']:3d} {r['delay']:7.2f} {r['complete']}")
print("step 3: final design", final[0]["rung"], final[0]["policy"])
