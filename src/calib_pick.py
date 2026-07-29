"""Этап 2a — интерактивная разметка прямых линий для plumb-line калибровки.

Запускаешь локально (нужно окно OpenCV). На кадре кликаешь точки вдоль линий,
которые в РЕАЛЬНОСТИ прямые, но на fisheye-кадре выгнуты: бордюры, край пешеходного
перехода, кромка разделительной, столбы/мачты, длинные рёбра зданий, стоп-линии.

Чем длиннее линия через кадр и чем ближе к краям (где бочка сильнее) — тем лучше.
Нужно 5–8 линий по 4+ точки, желательно в разных частях кадра.

Управление:
    ЛКМ            — поставить точку на текущую линию
    n / Пробел     — завершить текущую линию, начать новую
    u              — убрать последнюю точку
    c              — очистить текущую линию
    s              — сохранить в calib/lines_<camera>.json
    q / Esc        — выход

Запуск:
    python src/calib_pick.py --camera center
    python src/calib_pick.py --camera center --frame 200   # другой кадр
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import yaml

ROOT = Path(__file__).resolve().parent.parent
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

COLORS = [(0, 0, 255), (0, 255, 0), (255, 0, 0), (0, 255, 255),
          (255, 0, 255), (255, 255, 0), (0, 128, 255), (128, 0, 255)]


def load_config(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def grab_frame(video: Path, frame_idx: int):
    cap = cv2.VideoCapture(str(video))
    if frame_idx > 0:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise SystemExit(f"Не удалось прочитать кадр {frame_idx} из {video}")
    return frame


def main() -> None:
    ap = argparse.ArgumentParser(description="Разметка прямых линий для калибровки")
    ap.add_argument("--camera", required=True)
    ap.add_argument("--config", default=str(ROOT / "config.yaml"))
    ap.add_argument("--frame", type=int, default=0)
    ap.add_argument("--video", default=None, help="переопределить путь к видео")
    ap.add_argument("--display-width", type=int, default=1500,
                    help="ширина окна; клики пересчитываются в полное разрешение")
    args = ap.parse_args()

    cfg = load_config(Path(args.config))
    out_dir = Path(cfg["paths"]["out_dir"])
    if args.video:
        video = Path(args.video)
    else:
        from preprocess import clean_path
        video = clean_path(out_dir, args.camera)
        if not video.exists():
            video = Path(cfg["paths"]["videos_dir"]) / next(
                c["video"] for c in cfg["cameras"] if c["id"] == args.camera)
    if not video.exists():
        raise SystemExit(f"Видео не найдено: {video}")

    frame = grab_frame(video, args.frame)
    H, W = frame.shape[:2]
    scale = args.display_width / W
    disp_size = (args.display_width, int(H * scale))

    lines: list[list[list[float]]] = []   # завершённые линии (в полном разрешении)
    current: list[list[float]] = []        # текущая линия

    out_path = ROOT / "calib" / f"lines_{args.camera}.json"

    def on_mouse(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            current.append([x / scale, y / scale])

    win = f"calib: {args.camera}  (n=след.линия u=undo c=очистить s=save q=выход)"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(win, *disp_size)
    cv2.setMouseCallback(win, on_mouse)

    print(f"[pick] {video.name} кадр={args.frame}  {W}x{H}")
    print("[pick] кликай точки вдоль прямых; n — следующая линия; s — сохранить; q — выход")

    while True:
        vis = cv2.resize(frame, disp_size)

        def draw_line(pts, color):
            for i, (px, py) in enumerate(pts):
                dp = (int(px * scale), int(py * scale))
                cv2.circle(vis, dp, 4, color, -1)
                if i > 0:
                    pp = (int(pts[i - 1][0] * scale), int(pts[i - 1][1] * scale))
                    cv2.line(vis, pp, dp, color, 1)

        for li, ln in enumerate(lines):
            draw_line(ln, COLORS[li % len(COLORS)])
        draw_line(current, COLORS[len(lines) % len(COLORS)])

        cv2.putText(vis, f"lines={len(lines)} cur_pts={len(current)}",
                    (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
        cv2.imshow(win, vis)
        k = cv2.waitKey(20) & 0xFF
        if k in (ord('q'), 27):
            break
        elif k in (ord('n'), ord(' ')):
            if len(current) >= 2:
                lines.append(current.copy())
                current.clear()
                print(f"[pick] линия #{len(lines)} зафиксирована")
            else:
                print("[pick] нужно >=2 точки на линию")
        elif k == ord('u'):
            if current:
                current.pop()
            elif lines:
                current[:] = lines.pop()
        elif k == ord('c'):
            current.clear()
        elif k == ord('s'):
            if current and len(current) >= 2:
                lines.append(current.copy())
                current.clear()
            data = {"camera": args.camera, "frame": args.frame,
                    "image_size": [W, H], "lines": lines}
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            npts = sum(len(l) for l in lines)
            print(f"[pick] сохранено {len(lines)} линий / {npts} точек -> {out_path}")

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
