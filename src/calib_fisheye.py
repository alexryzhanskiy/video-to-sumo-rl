"""Этап 2b — plumb-line калибровка дисторсии по размеченным линиям.

Подбираем радиальные коэффициенты k1,k2 (модель pinhole OpenCV) так, чтобы линии,
размеченные в calib_pick.py, после undistort стали прямыми. Ключевые приёмы, без
которых задача вырождается:

  * Фокус ФИКСИРОВАН (f = ширина кадра), оптимизируем только дисторсию. Иначе f и k1
    обмениваются (одна прямизна задаёт семейство (f,k)), оптимизатор уходит в границы.
  * Остаток МАСШТАБНО-ИНВАРИАНТЕН (перп. отклонение / протяжённость линии). Иначе
    оптимизатор «жульничает», сжимая весь кадр к центру: пиксельные отклонения падают,
    линии не выпрямляются.
  * Итеративная ОТБРАКОВКА ВЫБРОСОВ: линия, которая в реальности не прямая (провис
    провода, кривой бордюр), даёт огромный остаток и портит фит — выкидываем по порогу.

Сохраняет:
    calib/<camera>_K.npy, _D.npy, _Kout.npy   — для пайплайна (cv2-модель)
    calib/<camera>_calib.json                  — человекочитаемо + остаточная ошибка
    calib/<camera>_undistort_check.jpg         — кадр до/после + размеченные линии

Запуск:
    python src/calib_fisheye.py --camera center
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np
from scipy.optimize import least_squares

ROOT = Path(__file__).resolve().parent.parent
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def line_residuals(pts_u):
    """Масштабно-инвариантная прямизна: перп. отклонение от TLS-прямой / протяжённость."""
    pts_u = np.asarray(pts_u)
    d = pts_u - pts_u.mean(axis=0)
    _, _, vt = np.linalg.svd(d)
    along = d @ vt[0]
    perp = d @ vt[1]
    return perp / (np.sqrt(np.mean(along ** 2)) + 1e-6)


def undistort_pts(pts, K, D):
    p = np.asarray(pts, dtype=np.float64).reshape(-1, 1, 2)
    return cv2.undistortPoints(p, K, D, P=K).reshape(-1, 2)


def main() -> None:
    ap = argparse.ArgumentParser(description="Plumb-line калибровка дисторсии (pinhole k1,k2)")
    ap.add_argument("--camera", required=True)
    ap.add_argument("--drop-factor", type=float, default=3.0,
                    help="порог отбраковки линии: rms > factor*median (или > 0.05)")
    ap.add_argument("--balance", type=float, default=0.0,
                    help="getOptimalNewCameraMatrix alpha: 0=обрезать чёрные поля, 1=сохранить всё")
    args = ap.parse_args()

    lines_path = ROOT / "calib" / f"lines_{args.camera}.json"
    if not lines_path.exists():
        raise SystemExit(f"Нет разметки: {lines_path}. Сначала: python src/calib_pick.py --camera {args.camera}")
    data = json.load(open(lines_path, encoding="utf-8"))
    lines = [np.array(l, dtype=np.float64) for l in data["lines"]]
    W, H = data["image_size"]
    npts = sum(len(l) for l in lines)
    if len(lines) < 3 or npts < 12:
        print(f"[calib] ВНИМАНИЕ: {len(lines)} линий / {npts} точек — маловато (>=5 линий по 4+ точки)")

    f = float(W)                                  # фокус фиксирован
    K = np.array([[f, 0, W / 2.0], [0, f, H / 2.0], [0, 0, 1]], dtype=np.float64)

    def fit(idx):
        def res(x):
            D = np.array([x[0], x[1], 0, 0, 0], dtype=np.float64)
            return np.concatenate([line_residuals(undistort_pts(lines[i], K, D)) for i in idx])
        sol = least_squares(res, [0.0, 0.0], bounds=([-2, -2], [2, 2]),
                            loss="soft_l1", f_scale=0.02, max_nfev=8000)
        return sol.x

    def per_line_rms(D, idx):
        return np.array([float(np.sqrt(np.mean(line_residuals(undistort_pts(lines[i], K, D)) ** 2)))
                         for i in idx])

    idx = list(range(len(lines)))
    dropped_all = []
    rms0 = float(np.sqrt(np.mean(np.concatenate(
        [line_residuals(undistort_pts(l, K, np.zeros(5))) for l in lines]) ** 2)))
    for _ in range(6):
        k1, k2 = fit(idx)
        D = np.array([k1, k2, 0, 0, 0], dtype=np.float64)
        pl = per_line_rms(D, idx)
        med = float(np.median(pl))
        thr = max(args.drop_factor * med, 0.05)
        keep = [idx[j] for j in range(len(idx)) if pl[j] <= thr]
        dropped = [i for i in idx if i not in keep]
        if not dropped:
            break
        dropped_all += dropped
        idx = keep

    k1, k2 = fit(idx)
    D = np.array([k1, k2, 0, 0, 0], dtype=np.float64)
    rms1 = float(np.sqrt(np.mean(np.concatenate(
        [line_residuals(undistort_pts(lines[i], K, D)) for i in idx]) ** 2)))
    Kout, _ = cv2.getOptimalNewCameraMatrix(K, D, (W, H), args.balance)

    out = ROOT / "calib"
    np.save(out / f"{args.camera}_K.npy", K)
    np.save(out / f"{args.camera}_D.npy", D)
    np.save(out / f"{args.camera}_Kout.npy", Kout)
    json.dump({
        "camera": args.camera, "model": "pinhole_radial(k1,k2), f=W fixed",
        "image_size": [W, H], "K": K.tolist(), "D": D.tolist(), "Kout": Kout.tolist(),
        "rms_straightness_before": rms0, "rms_straightness_after": rms1,
        "n_lines": len(lines), "inliers": idx, "dropped_lines": dropped_all,
    }, open(out / f"{args.camera}_calib.json", "w", encoding="utf-8"), indent=2)

    print(f"[calib] k1={k1:+.4f} k2={k2:+.4f}  (f={f:.0f} фикс., центр кадра)")
    print(f"[calib] RMS прямизны (безразм.): {rms0:.4f} -> {rms1:.4f}  на {len(idx)} линиях")
    if dropped_all:
        print(f"[calib] отброшены как непрямые: линии {dropped_all}")
    print(f"[calib] сохранено -> {out / (args.camera + '_K.npy')}, _D.npy, _Kout.npy, _calib.json")

    # Визуальная проверка
    import yaml
    from preprocess import clean_path
    cfg = yaml.safe_load(open(ROOT / "config.yaml", encoding="utf-8"))
    video = clean_path(Path(cfg["paths"]["out_dir"]), args.camera)
    if not video.exists():
        return
    cap = cv2.VideoCapture(str(video))
    if data["frame"] > 0:
        cap.set(cv2.CAP_PROP_POS_FRAMES, data["frame"])
    ok, frame = cap.read()
    cap.release()
    if not ok:
        return
    und = cv2.undistort(frame, K, D, None, Kout)
    before = frame.copy()
    for ln in lines:
        for j in range(1, len(ln)):
            cv2.line(before, tuple(ln[j - 1].astype(int)), tuple(ln[j].astype(int)), (0, 0, 255), 2)
    after = und.copy()
    for i in idx:
        pu = cv2.undistortPoints(lines[i].reshape(-1, 1, 2), K, D, P=Kout).reshape(-1, 2)
        for j in range(1, len(pu)):
            cv2.line(after, tuple(pu[j - 1].astype(int)), tuple(pu[j].astype(int)), (0, 255, 0), 2)
    combo = cv2.resize(np.vstack([before, after]), (W // 2, H))
    cv2.imwrite(str(out / f"{args.camera}_undistort_check.jpg"), combo)
    print(f"[calib] проверка (верх=до красным, низ=после зелёным) -> {out / (args.camera + '_undistort_check.jpg')}")


if __name__ == "__main__":
    main()
