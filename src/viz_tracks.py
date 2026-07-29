"""Визуализация траекторий треков на выпрямленном кадре — для дизайна Этапов 3–4.

Рисует путь каждого трека (по спрямлённым точкам контакта cx_u,cy_u) поверх
undistorted-кадра. Видно: держит ли ByteTrack ID через коробку (длинные сплошные
траектории сквозь центр) и читаются ли повороты по кривизне (дуги налево/направо vs
прямые). От этого зависит, нужна ли межкамерная гомография и как классифицировать
движения.

Запуск:
    python src/viz_tracks.py --camera center --min-len 8
"""
from __future__ import annotations

import argparse
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


def color_for(tid: int):
    rng = np.random.default_rng(int(tid) * 9973 + 1)
    return tuple(int(c) for c in rng.integers(60, 256, size=3))


def main() -> None:
    ap = argparse.ArgumentParser(description="Визуализация траекторий")
    ap.add_argument("--camera", required=True)
    ap.add_argument("--min-len", type=int, default=8, help="мин. число точек в треке")
    args = ap.parse_args()

    import yaml
    cfg = yaml.safe_load(open(ROOT / "config.yaml", encoding="utf-8"))
    tracks_dir = Path(cfg["paths"]["out_dir"]) / "tracks"
    csv = tracks_dir / f"tracks_{args.camera}_undist.csv"
    if not csv.exists():
        raise SystemExit(f"Нет {csv}. Сначала: stage1_track -> undistort для камеры {args.camera}")
    df = pd.read_csv(csv)
    xcol, ycol = ("cx_u", "cy_u") if "cx_u" in df.columns else ("cx", "cy")

    bg_path = ROOT / "calib" / f"{args.camera}_undistorted_ref.jpg"
    bg = cv2.imread(str(bg_path)) if bg_path.exists() else None
    if bg is None:
        W, H = cfg_size = (int(df[xcol].max()) + 50, int(df[ycol].max()) + 50)
        bg = np.zeros((H, W, 3), np.uint8)
    canvas = (bg * 0.45).astype(np.uint8)  # притушить фон, чтобы траектории читались

    n_drawn = 0
    lens = []
    for tid, g in df.groupby("track_id"):
        g = g.sort_values("k")
        if len(g) < args.min_len:
            continue
        pts = g[[xcol, ycol]].to_numpy().astype(np.int32)
        col = color_for(tid)
        cv2.polylines(canvas, [pts], False, col, 2, cv2.LINE_AA)
        cv2.circle(canvas, tuple(pts[0]), 5, (0, 255, 0), -1)    # старт зелёный
        cv2.circle(canvas, tuple(pts[-1]), 5, (0, 0, 255), -1)   # конец красный
        n_drawn += 1
        lens.append(len(g))

    out = tracks_dir / f"trajectories_{args.camera}.jpg"
    cv2.imwrite(str(out), canvas)
    lens = np.array(lens) if lens else np.array([0])
    print(f"[viz] нарисовано {n_drawn} треков (>= {args.min_len} точек); "
          f"длина: медиана={np.median(lens):.0f} макс={lens.max()}")
    print(f"[viz] старт=зелёный конец=красный -> {out}")


if __name__ == "__main__":
    main()
