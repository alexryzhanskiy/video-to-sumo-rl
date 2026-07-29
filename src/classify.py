"""Этап 4 — классификация движений по пересечению гейтов.

Для каждого трека: находит ВЪЕЗД (пересечение стоп-линии внутрь коробки) и затем
ВЫЕЗД (пересечение выездного гейта наружу). Движение = (подъезд въезда -> нога выезда),
раскладывается в прямо/налево/направо/разворот по взаимной ориентации направлений.

Подписи гейтов (label) — компасные: SVB_N/SVB_S (Свободи) и PRB_E/PRB_W (Прибузька).
Если перекрёсток — нормальный крест, доминирующее движение каждого подъезда — «прямо»
на противоположную ногу; перекос в матрице сигналит о неверных подписях/геометрии.

Запуск:
    python src/classify.py --camera center
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
import json

ROOT = Path(__file__).resolve().parent.parent
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# Компасные единичные векторы ног (мир: x — восток, y — север)
LEG_VEC = {"SVB_N": (0, 1), "SVB_S": (0, -1), "PRB_E": (1, 0), "PRB_W": (-1, 0)}


def seg_intersect(p1, p2, p3, p4):
    """Пересекаются ли отрезки p1p2 и p3p4. Возвращает точку или None."""
    p1, p2, p3, p4 = map(np.asarray, (p1, p2, p3, p4))
    d1, d2 = p2 - p1, p4 - p3
    denom = d1[0] * d2[1] - d1[1] * d2[0]
    if abs(denom) < 1e-9:
        return None
    t = ((p3[0] - p1[0]) * d2[1] - (p3[1] - p1[1]) * d2[0]) / denom
    u = ((p3[0] - p1[0]) * d1[1] - (p3[1] - p1[1]) * d1[0]) / denom
    if 0 <= t <= 1 and 0 <= u <= 1:
        return p1 + t * d1
    return None


def movement_of(entry_label, exit_label):
    """прямо/налево/направо/разворот по компасным меткам подъезда и ноги выезда."""
    # подъезд: едет ПРОТИВОПОЛОЖНО своему направлению (въезд с севера -> едет на юг)
    h = np.array(LEG_VEC[entry_label], float)
    heading = -h
    e = np.array(LEG_VEC[exit_label], float)
    dot = float(np.dot(heading, e))
    cross = heading[0] * e[1] - heading[1] * e[0]
    if dot > 0.7:
        return "пряمо"
    if dot < -0.7:
        return "разворот"
    return "налево" if cross > 0 else "направо"


def main() -> None:
    ap = argparse.ArgumentParser(description="Классификация движений по гейтам")
    ap.add_argument("--camera", required=True)
    args = ap.parse_args()

    import yaml
    cfg = yaml.safe_load(open(ROOT / "config.yaml", encoding="utf-8"))
    tracks_dir = Path(cfg["paths"]["out_dir"]) / "tracks"
    gates = json.load(open(ROOT / "calib" / f"gates_{args.camera}.json", encoding="utf-8"))["gates"]
    df = pd.read_csv(tracks_dir / f"tracks_{args.camera}_undist.csv")
    xcol, ycol = ("cx_u", "cy_u") if "cx_u" in df.columns else ("cx", "cy")

    # центр коробки = центроид концов всех гейтов
    allpts = np.array([pt for g in gates for pt in g["points"]], float)
    box_c = allpts.mean(axis=0)

    stops = [g for g in gates if g["role"] == "stop"]
    exits = [g for g in gates if g["role"] == "exit"]

    # направления ног (от центра коробки к середине выездного гейта) — для запасного
    # определения выезда по траектории, когда трек оборвался до дальнего гейта
    leg_dir = {}
    for g in exits:
        mid = np.mean(g["points"], axis=0)
        v = mid - box_c
        leg_dir[g["label"]] = v / (np.linalg.norm(v) + 1e-9)
    ref_dist = np.mean([np.linalg.norm(np.mean(g["points"], axis=0) - box_c) for g in exits])

    rows = []          # классифицированные треки
    no_entry = 0       # не пересёк ни одной своей стоп-линии (чужой подъезд/шум)
    in_box = 0         # въехал, но оборвался в коробке (не определить ногу)
    for tid, g in df.groupby("track_id"):
        g = g.sort_values("k")
        pts = g[[xcol, ycol]].to_numpy()
        cls = g["cls"].mode().iloc[0]
        if len(pts) < 3:
            continue
        # 1) въезд = первое пересечение стоп-линии внутрь коробки
        entry = None
        exit_ = None
        method = None
        for i in range(len(pts) - 1):
            a, b = pts[i], pts[i + 1]
            mv = b - a
            if entry is None:
                for gate in stops:
                    X = seg_intersect(a, b, gate["points"][0], gate["points"][1])
                    if X is not None and np.dot(mv, box_c - X) > 0:
                        entry = (i, gate["label"]); break
            else:
                for gate in exits:                       # 2) выезд по гейту
                    X = seg_intersect(a, b, gate["points"][0], gate["points"][1])
                    if X is not None and np.dot(mv, box_c - X) < 0:
                        exit_ = (i, gate["label"]); method = "gate"; break
            if exit_ is not None:
                break
        if entry is None:
            no_entry += 1
            continue
        # 3) запасной выезд по направлению, если гейт не пересечён, но трек ушёл из коробки
        if exit_ is None:
            end_v = pts[-1] - box_c
            if np.linalg.norm(end_v) < 0.5 * ref_dist:
                in_box += 1
                continue
            end_u = end_v / (np.linalg.norm(end_v) + 1e-9)
            label = max(leg_dir, key=lambda k: float(np.dot(end_u, leg_dir[k])))
            exit_ = (len(pts) - 1, label); method = "heading"
        mvt = movement_of(entry[1], exit_[1])
        rows.append(dict(track_id=int(tid), cls=cls, entry=entry[1], exit=exit_[1],
                         movement=mvt, method=method,
                         k=int(g["k"].iloc[entry[0]]), t_sec=float(g["t_sec"].iloc[entry[0]])))

    res = pd.DataFrame(rows)
    out = tracks_dir / f"movements_{args.camera}.csv"
    res.to_csv(out, index=False)

    print(f"[classify] камера={args.camera}  треков всего={df.track_id.nunique()}  "
          f"классифицировано={len(res)}  (чужой подъезд/шум={no_entry}, оборвались в коробке={in_box})")
    if res.empty:
        print("[classify] ни одного движения не классифицировано — проверь гейты"); return
    if "method" in res:
        print(f"[classify] способ выезда: по гейту={(res.method=='gate').sum()}, "
              f"по направлению={(res.method=='heading').sum()}")

    print("\n[classify] МАТРИЦА въезд -> выезд (число ТС):")
    mat = pd.crosstab(res["entry"], res["exit"])
    print(mat.to_string())
    print("\n[classify] по подъездам и движениям:")
    summ = res.groupby(["entry", "movement"]).size().unstack(fill_value=0)
    print(summ.to_string())
    print(f"\n[classify] -> {out}")


if __name__ == "__main__":
    main()
