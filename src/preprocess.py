"""Предобработка — перекодировка битых HEVC-роликов в чистый H.264.

Исходные ролики имеют повреждённый HEVC-поток (PPS id out of range, broken RPS):
bundled-ffmpeg в OpenCV их НЕ декодирует (0 кадров), поэтому детекция падает.
Системный ffmpeg декодирует с error concealment — перегоняем в чистый H.264,
который читают и OpenCV, и ultralytics. Разрешение сохраняем (мелкие ТС вдаль).

Чистые файлы портативны: их можно скопировать на GPU-машину для финального прогона,
там возни с битым HEVC уже не будет.

Запуск:
    python src/preprocess.py            # обе камеры
    python src/preprocess.py --camera center
    python src/preprocess.py --force    # перекодировать даже если файл уже есть
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import yaml

# Windows-консоль по умолчанию cp1252 и падает на кириллице/юникоде в print
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent


def load_config(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def clean_path(out_dir: Path, cam_id: str) -> Path:
    """Детерминированный путь к чистому файлу — общий для preprocess и stage1."""
    return out_dir / "video" / f"{cam_id}_clean.mp4"


PACK_START = b"\x00\x00\x01\xba"   # заголовок pack MPEG-PS


def ps_payload_offset(src: Path, search_bytes: int = 4 << 20) -> int | None:
    """Смещение первого pack-заголовка MPEG-PS.

    Ролики выгружаются с фирменным заголовком IMKH впереди. У части файлов
    (выгрузка 30.10) мусор перед первым pack ломает PS-демуксер ffmpeg:
    'Error during demuxing: Invalid data found' на первом же пакете, 0 кадров.
    Пропуск этих байт полностью чинит чтение — поток внутри целый.
    """
    with open(src, "rb") as f:
        head = f.read(search_bytes)
    i = head.find(PACK_START)
    return i if i > 0 else None


def _ffmpeg_cmd(src: Path, dst: Path, crf: int, skip: int | None) -> list[str]:
    cmd = ["ffmpeg", "-v", "error", "-y"]
    if skip:
        cmd += ["-skip_initial_bytes", str(skip)]
    cmd += [
        "-i", str(src),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
        "-pix_fmt", "yuv420p", "-an",
        str(dst),
    ]
    return cmd


def transcode(src: Path, dst: Path, crf: int = 20) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    print(f"[preprocess] {src.name} -> {dst.name} (libx264 crf{crf}) ...")
    # ffmpeg сыплет варнингами битого HEVC в stderr — гасим, оставляем только фатальное
    proc = subprocess.run(_ffmpeg_cmd(src, dst, crf, None), capture_output=True, text=True)
    if proc.returncode != 0:
        skip = ps_payload_offset(src)
        if skip:
            print(f"[preprocess] демуксер споткнулся, пробую с -skip_initial_bytes {skip}")
            proc = subprocess.run(_ffmpeg_cmd(src, dst, crf, skip),
                                  capture_output=True, text=True)
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-5:])
        raise SystemExit(f"ffmpeg упал на {src.name}:\n{tail}")
    size_mb = dst.stat().st_size / 1e6
    print(f"[preprocess] готово: {dst}  ({size_mb:.0f} МБ)")


def main() -> None:
    ap = argparse.ArgumentParser(description="Перекодировка битых HEVC → чистый H.264")
    ap.add_argument("--camera", default=None, help="id камеры (по умолч. — все из config)")
    ap.add_argument("--config", default=str(ROOT / "config.yaml"))
    ap.add_argument("--crf", type=int, default=20)
    ap.add_argument("--force", action="store_true", help="перекодировать, даже если файл есть")
    args = ap.parse_args()

    cfg = load_config(Path(args.config))
    videos_dir = Path(cfg["paths"]["videos_dir"])
    out_dir = Path(cfg["paths"]["out_dir"])

    cams = cfg["cameras"]
    if args.camera:
        cams = [c for c in cams if c["id"] == args.camera]
        if not cams:
            raise SystemExit(f"Камера '{args.camera}' не найдена в config.yaml")

    for cam in cams:
        src = videos_dir / cam["video"]
        dst = clean_path(out_dir, cam["id"])
        if not src.exists():
            print(f"[preprocess] ПРОПУСК {cam['id']}: нет исходника {src}")
            continue
        if dst.exists() and not args.force:
            print(f"[preprocess] ПРОПУСК {cam['id']}: {dst.name} уже есть (--force чтобы пересоздать)")
            continue
        transcode(src, dst, crf=args.crf)


if __name__ == "__main__":
    main()
