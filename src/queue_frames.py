"""Извлечение стоп-кадров «конец красного» для полуручного подсчёта очереди.

Для каждого подъезда (на камере-владельце) находит старты зелёного (первое пересечение
стоп-линии после паузы >50с = разрядка очереди) и сохраняет выпрямленный кадр за ~1с до —
там стоящая очередь видна целиком. Накладывает стоп-линию подъезда. Кадры пронумерованы,
очередь считаешь глазами и сверяешь с целями SUMO.

Запуск:  python src/queue_frames.py --cycles 3
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# подъезд -> камера-владелец
OWNER = {"SVB_N": "center", "PRB_E": "center", "SVB_S": "zarich", "PRB_W": "zarich"}
RU = {"SVB_N": "Svobodi-Sever", "PRB_E": "Prybuzka-Vostok",
      "SVB_S": "Svobodi-Yug", "PRB_W": "Prybuzka-Zapad"}
FPS = 25.0
LEAD = 1.0          # за сколько секунд до старта зелёного брать кадр
RED_GAP = 50.0      # пауза между пересечениями, считающаяся «был красный»


def burst_starts(times):
    times = np.sort(times)
    starts = []
    prev = -1e9
    for t in times:
        if t - prev > RED_GAP:
            starts.append(t)
        prev = t
    return starts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cycles", type=int, default=3)
    args = ap.parse_args()

    cfg = __import__("yaml").safe_load(open(ROOT / "config.yaml", encoding="utf-8"))
    out_dir = Path(cfg["paths"]["out_dir"]) / "queue_frames"
    out_dir.mkdir(parents=True, exist_ok=True)
    tracks_dir = Path(cfg["paths"]["out_dir"]) / "tracks"

    # калибровки, гейты, треки по камерам
    calib, gates, caps, trk = {}, {}, {}, {}
    for cam in set(OWNER.values()):
        calib[cam] = (np.load(ROOT / "calib" / f"{cam}_K.npy"),
                      np.load(ROOT / "calib" / f"{cam}_D.npy"),
                      np.load(ROOT / "calib" / f"{cam}_Kout.npy"))
        gates[cam] = json.load(open(ROOT / "calib" / f"gates_{cam}.json", encoding="utf-8"))["gates"]
        caps[cam] = cv2.VideoCapture(str(Path(cfg["paths"]["out_dir"]) / "video" / f"{cam}_clean.mp4"))
        trk[cam] = pd.read_csv(tracks_dir / f"tracks_{cam}_undist.csv")
    counts_by_appr = {}

    for appr, cam in OWNER.items():
        mv = pd.read_csv(tracks_dir / f"movements_{cam}.csv")
        times = mv[mv.entry == appr]["t_sec"].to_numpy()
        if len(times) == 0:
            print(f"[queue] {appr}: нет въездов"); continue
        starts = burst_starts(times)
        if len(starts) < args.cycles:
            picks = starts
        else:
            # равномерно из середины (без первого/последнего)
            mid = starts[1:-1] or starts
            idx = np.linspace(0, len(mid) - 1, args.cycles).round().astype(int)
            picks = [mid[i] for i in idx]

        K, D, Kout = calib[cam]
        stop_gate = next(g for g in gates[cam] if g["role"] == "stop" and g["label"] == appr)
        cap = caps[cam]
        for n, t_green in enumerate(picks, 1):
            t_frame = max(0.0, t_green - LEAD)
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(t_frame * FPS))
            ok, fr = cap.read()
            if not ok:
                print(f"[queue] {appr} c{n}: не прочёлся кадр t={t_frame:.1f}"); continue
            und = cv2.undistort(fr, K, D, None, Kout)
            pts = np.array(stop_gate["points"], float)
            (x1, y1), (x2, y2) = pts.astype(int)
            box_c = np.mean([p for g in gates[cam] for p in g["points"]], axis=0)
            mid = pts.mean(axis=0)
            up = mid - box_c; up = up / (np.linalg.norm(up) + 1e-9)   # наружу = к подъезду
            cv2.line(und, (x1, y1), (x2, y2), (0, 0, 255), 5, cv2.LINE_AA)
            tip = (mid + up * 230).astype(int)
            cv2.arrowedLine(und, mid.astype(int), tuple(tip), (0, 255, 255), 4, cv2.LINE_AA, tipLength=0.25)
            cv2.putText(und, "ochered' zdes'", (tip[0] - 60, tip[1] + 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 255), 2, cv2.LINE_AA)
            # пометить машины в коридоре подъезда (сторона стрелки, перед стоп-линией)
            along = pts[1] - pts[0]; along = along / (np.linalg.norm(along) + 1e-9)
            gate_len = np.linalg.norm(pts[1] - pts[0])
            tr = trk[cam]
            near = tr[(tr.t_sec - t_frame).abs() < 0.12]
            count = 0
            for _, v in near.iterrows():
                rel = np.array([v.cx_u - mid[0], v.cy_u - mid[1]])
                d_up = float(np.dot(rel, up))            # >0 = сторона подъезда
                d_lat = abs(float(np.dot(rel, along)))   # вдоль стоп-линии
                if 0 < d_up < 900 and d_lat < gate_len * 0.75:
                    count += 1
                    c = (int(v.cx_u), int(v.cy_u))
                    cv2.circle(und, c, 9, (0, 255, 0), 2, cv2.LINE_AA)
                    cv2.putText(und, str(count), (c[0] - 6, c[1] + 5),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2, cv2.LINE_AA)
            cv2.rectangle(und, (0, 0), (820, 44), (0, 0, 0), -1)
            cv2.putText(und, f"{RU[appr]}  cikl {n}/{len(picks)}  avto-schet ocheredi: {count}",
                        (12, 31), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2, cv2.LINE_AA)
            p = out_dir / f"queue_{appr}_c{n}.jpg"
            cv2.imwrite(str(p), und)
            counts_by_appr.setdefault(appr, []).append(count)
            print(f"[queue] {appr} c{n}: t_green~{t_green:.0f}s  авто-счёт={count}  -> {p.name}")

    for cap in caps.values():
        cap.release()
    SUMO = {"SVB_N": "25-31", "SVB_S": "21-30", "PRB_E": "11-18", "PRB_W": "19-26"}
    print("\n[queue] СВОДКА: авто-счёт очереди по видео vs цель SUMO")
    print(f"{'подъезд':9s} {'видео (циклы)':>20s}  {'видео ср.':>9s}  {'SUMO макс':>9s}")
    for appr in ["SVB_N", "SVB_S", "PRB_E", "PRB_W"]:
        c = counts_by_appr.get(appr, [])
        avg = f"{np.mean(c):.0f}" if c else "-"
        print(f"{appr:9s} {str(c):>20s}  {avg:>9s}  {SUMO[appr]:>9s}")
    print(f"\n[queue] кадры в {out_dir}")


if __name__ == "__main__":
    main()
