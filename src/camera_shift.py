"""Проверка, не сдвинулась ли камера между записями.

Гейты и ROI лампы — фиксированные пиксельные координаты. Если камеру задели,
пайплайн всё равно досчитает и выдаст правдоподобные, но неверные числа
(см. ответ 3). Автоматически сдвиг нигде не ловится, но померить его дёшево:
фазовая корреляция кадра нового ролика с опорным кадром старого.

Сдвиг в доли пикселя — геометрия прежняя, калибровку и гейты можно переиспользовать.
Единицы пикселей — обязательна визуальная проверка `*_gates_check.jpg`.
Больше — гейты переразмечаются заново.

Запуск:
    python src/camera_shift.py --camera center --new data/video/center_new_clean.mp4
    python src/camera_shift.py --camera center --ref A.mp4 --new B.mp4 --frame 300
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np
import yaml

ROOT = Path(__file__).resolve().parent.parent
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")   # SystemExit печатается в stderr
except Exception:
    pass

# выше этого — считаем, что камеру двигали
WARN_PX = 1.0
MOVED_PX = 3.0


def grab(path: Path, idx: int):
    cap = cv2.VideoCapture(str(path))
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.set(cv2.CAP_PROP_POS_FRAMES, min(idx, max(n - 2, 0)))
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise SystemExit(f"Не читается кадр {idx} из {path}")
    return frame


def shift_px(ref, new):
    """(dx, dy, response) между двумя кадрами одного размера."""
    a = cv2.cvtColor(ref, cv2.COLOR_BGR2GRAY).astype(np.float32)
    b = cv2.cvtColor(new, cv2.COLOR_BGR2GRAY).astype(np.float32)
    win = cv2.createHanningWindow((a.shape[1], a.shape[0]), cv2.CV_32F)
    (dx, dy), resp = cv2.phaseCorrelate(a, b, win)
    return dx, dy, resp


def main() -> None:
    ap = argparse.ArgumentParser(description="Сдвиг камеры между записями, в пикселях")
    ap.add_argument("--camera", required=True)
    ap.add_argument("--new", required=True, help="новый ролик (уже перекодированный)")
    ap.add_argument("--ref", default=None, help="опорный ролик (по умолч. <cam>_clean.mp4)")
    ap.add_argument("--frame", type=int, default=5000, help="номер кадра в опорном ролике")
    ap.add_argument("--new-frame", type=int, default=300)
    args = ap.parse_args()

    cfg = yaml.safe_load(open(ROOT / "config.yaml", encoding="utf-8"))
    out_dir = Path(cfg["paths"]["out_dir"])
    ref_path = Path(args.ref) if args.ref else out_dir / "video" / f"{args.camera}_clean.mp4"
    new_path = Path(args.new)
    for p in (ref_path, new_path):
        if not p.exists():
            raise SystemExit(f"Нет файла: {p}")

    ref = grab(ref_path, args.frame)
    new = grab(new_path, args.new_frame)
    if ref.shape[:2] != new.shape[:2]:
        print(f"[shift] {args.camera}: разрешение изменилось "
              f"{ref.shape[1]}x{ref.shape[0]} -> {new.shape[1]}x{new.shape[0]}")
        print("[shift] ВЕРДИКТ: нужна полная калибровка заново (шаги а-е)")
        return

    dx, dy, resp = shift_px(ref, new)
    # верх кадра — статика (дома, столбы), низ — проезжая часть с потоком
    h = ref.shape[0] // 2
    dxt, dyt, respt = shift_px(ref[:h], new[:h])
    mag = max(abs(dx), abs(dy), abs(dxt), abs(dyt))

    print(f"[shift] {args.camera}: {ref_path.name} кадр {args.frame} -> "
          f"{new_path.name} кадр {args.new_frame}")
    print(f"[shift] весь кадр: dx={dx:+.2f} dy={dy:+.2f} (отклик {resp:.3f})")
    print(f"[shift] верх кадра: dx={dxt:+.2f} dy={dyt:+.2f} (отклик {respt:.3f})")
    if mag < WARN_PX:
        print(f"[shift] ВЕРДИКТ: {mag:.2f} px — камера не двигалась, "
              f"калибровка и гейты переиспользуются")
    elif mag < MOVED_PX:
        print(f"[shift] ВЕРДИКТ: {mag:.2f} px — обязательна визуальная проверка "
              f"calib/{args.camera}_gates_check.jpg")
    else:
        print(f"[shift] ВЕРДИКТ: {mag:.2f} px — камеру двигали, гейты и ROI лампы "
              f"размечаются заново (шаги в, г, е)")


if __name__ == "__main__":
    main()
