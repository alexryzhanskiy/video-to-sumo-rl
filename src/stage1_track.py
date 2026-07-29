"""Этап 1 — детекция + трекинг по одной камере.

YOLO (v8/v11) + ByteTrack (встроенный в ultralytics). На выходе — треки в пикселях
ИСХОДНОГО, ещё искажённого fisheye кадра. Undistort и зоны — на следующих этапах.

Точка трека для геометрии — нижний центр бокса (cx, y2): контакт с землёй, корректно
ложится в гомографию/зоны. Пешеходы и велосипеды исключены через vehicle_classes.

Запуск:
    python src/stage1_track.py --camera center
    python src/stage1_track.py --camera center --max-seconds 60 --preview   # быстрый QA
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import yaml
from ultralytics import YOLO

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent


def load_config(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_camera(cfg: dict, cam_id: str) -> dict:
    for cam in cfg["cameras"]:
        if cam["id"] == cam_id:
            return cam
    raise SystemExit(f"Камера '{cam_id}' не найдена в config.yaml")


def main() -> None:
    ap = argparse.ArgumentParser(description="Этап 1: детекция + трекинг по камере")
    ap.add_argument("--camera", required=True, help="id камеры из config.yaml (center/zarich)")
    ap.add_argument("--config", default=str(ROOT / "config.yaml"))
    ap.add_argument("--video", default=None,
                    help="переопределить путь к видео (напр. перекодированный клип)")
    ap.add_argument("--model", default=None, help="переопределить веса (быстрый QA на лёгкой модели)")
    ap.add_argument("--imgsz", type=int, default=None, help="переопределить imgsz")
    ap.add_argument("--stride", type=int, default=None, help="переопределить frame_stride")
    ap.add_argument("--device", default=None, help="cpu / 0 / 0,1 — устройство ultralytics (по умолч. авто)")
    ap.add_argument("--max-seconds", type=float, default=None,
                    help="обработать только первые N секунд видео (для QA)")
    ap.add_argument("--preview", action="store_true",
                    help="сохранить аннотированное превью-видео обработанного отрезка")
    args = ap.parse_args()

    cfg = load_config(Path(args.config))
    det = cfg["detector"]
    trk = cfg["tracking"]
    cam = get_camera(cfg, args.camera)

    videos_dir = Path(cfg["paths"]["videos_dir"])
    weights_dir = Path(cfg["paths"]["weights_dir"])
    out_dir = Path(cfg["paths"]["out_dir"]) / "tracks"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Приоритет: явный --video > чистый перекодированный файл > исходный (битый HEVC)
    if args.video:
        video_path = Path(args.video)
    else:
        from preprocess import clean_path
        clean = clean_path(Path(cfg["paths"]["out_dir"]), args.camera)
        video_path = clean if clean.exists() else videos_dir / cam["video"]
        if not clean.exists():
            print(f"[stage1] ВНИМАНИЕ: чистого {clean.name} нет — беру исходный HEVC "
                  f"(OpenCV может не декодировать). Сначала: python src/preprocess.py --camera {args.camera}")
    if not video_path.exists():
        raise SystemExit(f"Видео не найдено: {video_path}")
    model_name = args.model or det["model"]
    imgsz = args.imgsz or det["imgsz"]
    model_path = weights_dir / model_name
    if not model_path.exists():
        raise SystemExit(f"Веса не найдены: {model_path}")

    class_ids = sorted(det["vehicle_classes"].values())
    id2name = {cid: name for name, cid in det["vehicle_classes"].items()}

    stride = int(args.stride or trk["frame_stride"])
    fps_src = 25.0  # все ролики 25 fps; уточняется ffprobe при необходимости
    # шаг между обрабатываемыми кадрами в секундах
    dt = stride / fps_src
    max_processed = None
    if args.max_seconds is not None:
        max_processed = int(args.max_seconds / dt)

    print(f"[stage1] камера={args.camera}  видео={video_path.name}")
    print(f"[stage1] модель={model_name} conf={det['conf']} imgsz={imgsz} "
          f"stride={stride} (~{fps_src/stride:.1f} Гц)")
    print(f"[stage1] классы={[id2name[c] for c in class_ids]}")

    model = YOLO(str(model_path))

    results = model.track(
        source=str(video_path),
        stream=True,
        persist=True,
        tracker=det["tracker_cfg"],
        classes=class_ids,
        conf=det["conf"],
        iou=det["iou"],
        imgsz=imgsz,
        vid_stride=stride,
        device=args.device,
        verbose=False,
    )

    out_csv = out_dir / f"tracks_{args.camera}.csv"
    writer = None
    fcsv = open(out_csv, "w", newline="", encoding="utf-8")
    writer = csv.writer(fcsv)
    writer.writerow(["k", "t_sec", "track_id", "cls", "conf",
                     "x1", "y1", "x2", "y2", "cx", "cy"])

    preview_writer = None
    n_rows = 0
    k = 0
    for k, res in enumerate(results):
        if max_processed is not None and k >= max_processed:
            break
        t_sec = round(k * dt, 3)

        boxes = res.boxes
        if boxes is not None and boxes.id is not None:
            xyxy = boxes.xyxy.cpu().numpy()
            ids = boxes.id.int().cpu().numpy()
            clss = boxes.cls.int().cpu().numpy()
            confs = boxes.conf.cpu().numpy()
            for (x1, y1, x2, y2), tid, c, cf in zip(xyxy, ids, clss, confs):
                cx = (x1 + x2) / 2.0
                cy = y2  # нижний центр — контакт с землёй
                writer.writerow([k, t_sec, int(tid), id2name.get(int(c), int(c)),
                                 round(float(cf), 3),
                                 round(float(x1), 1), round(float(y1), 1),
                                 round(float(x2), 1), round(float(y2), 1),
                                 round(float(cx), 1), round(float(cy), 1)])
                n_rows += 1

        if args.preview:
            import cv2
            frame = res.plot()
            if preview_writer is None:
                h, w = frame.shape[:2]
                prev_path = out_dir / f"preview_{args.camera}.mp4"
                preview_writer = cv2.VideoWriter(
                    str(prev_path), cv2.VideoWriter_fourcc(*"mp4v"),
                    fps_src / stride, (w, h))
            preview_writer.write(frame)

        if k % 100 == 0:
            print(f"  кадр k={k}  t={t_sec:.1f}s  строк={n_rows}", end="\r")

    fcsv.close()
    if preview_writer is not None:
        preview_writer.release()

    print(f"\n[stage1] готово: обработано {k} кадров, {n_rows} детекций")
    print(f"[stage1] треки → {out_csv}")
    if args.preview:
        print(f"[stage1] превью → {out_dir / f'preview_{args.camera}.mp4'}")


if __name__ == "__main__":
    main()
