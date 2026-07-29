"""Этап 2c — применение калибровки к координатам треков (а не к видео).

Undistort точек контакта (cx,cy) из CSV Этапа 1. Делаем по координатам: быстрее и
точнее для счёта, чем перегонять всё видео. Система координат — Kout (та же, что у
кадра через cv2.undistort(frame,K,D,None,Kout)), поэтому треки и зоны совпадают.

Запуск:
    python src/undistort.py --camera center
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


def load_calib(camera: str):
    cdir = ROOT / "calib"
    K = np.load(cdir / f"{camera}_K.npy")
    D = np.load(cdir / f"{camera}_D.npy")
    Kout = np.load(cdir / f"{camera}_Kout.npy")
    return K, D, Kout


def undistort_points(pts, K, D, Kout):
    """Nx2 пикселей искажённого кадра -> Nx2 спрямлённого (в системе Kout)."""
    p = np.asarray(pts, dtype=np.float64).reshape(-1, 1, 2)
    return cv2.undistortPoints(p, K, D, P=Kout).reshape(-1, 2)


def main() -> None:
    ap = argparse.ArgumentParser(description="Undistort координат треков")
    ap.add_argument("--camera", required=True)
    ap.add_argument("--in", dest="inp", default=None, help="входной CSV (по умолч. tracks_<cam>.csv)")
    args = ap.parse_args()

    import yaml
    cfg = yaml.safe_load(open(ROOT / "config.yaml", encoding="utf-8"))
    tracks_dir = Path(cfg["paths"]["out_dir"]) / "tracks"
    inp = Path(args.inp) if args.inp else tracks_dir / f"tracks_{args.camera}.csv"
    if not inp.exists():
        raise SystemExit(f"Нет треков: {inp}. Сначала Этап 1: python src/stage1_track.py --camera {args.camera}")
    cal = ROOT / "calib" / f"{args.camera}_K.npy"
    if not cal.exists():
        raise SystemExit(f"Нет калибровки для {args.camera}. Сначала Этап 2: python src/calib_fisheye.py --camera {args.camera}")

    K, D, Kout = load_calib(args.camera)
    df = pd.read_csv(inp)
    uv = undistort_points(df[["cx", "cy"]].to_numpy(), K, D, Kout)
    df["cx_u"] = np.round(uv[:, 0], 1)
    df["cy_u"] = np.round(uv[:, 1], 1)

    out = tracks_dir / f"tracks_{args.camera}_undist.csv"
    df.to_csv(out, index=False)
    print(f"[undistort] {len(df)} точек спрямлено -> {out}")


if __name__ == "__main__":
    main()
