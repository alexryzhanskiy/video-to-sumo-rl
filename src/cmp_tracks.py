"""Сверка треков нового ролика с опорным прогоном той же камеры.

Зачем. Этап 1 на новой записи идёт часами и молча: битое декодирование, более
тёмная или мягкая картинка, сбитый кроп дадут правдоподобный CSV, в котором
просто меньше дальних ТЗ. Проверяется это сравнением с опорным прогоном —
камеру между записями не двигали (см. camera_shift.py), значит геометрия дороги
лежит на тех же пикселях, и распределение детекций по кадру обязано совпасть.

Что здесь признак поломки, а что нет:

  поломка        нижний хвост конфиденций (p10, доля conf<0.3) и распределение
                 детекций по кадру — от трафика почти не зависят;
  НЕ поломка     плотность потока, состав по классам, длины треков — зависят от
                 времени записи. Печатаются для справки, в вердикт не входят.

Сравнение честно только на целом числе циклов: на коротком окне и плотность, и
состав — шум. Скрипт сам предупредит, если кадров меньше цикла.

Классы на мелких боксах (дальняя часть кадра) не держатся: один и тот же ТЗ
кочует между car/truck/bus, треки рвутся. Это свойство опорного конвейера, не
регрессия, поэтому мелкие боксы считаются отдельной строкой — состав потока по
ним брать нельзя, подсчёт маневров через гейты на стоп-линиях это не затрагивает.

Новый CSV можно подавать недописанным: последний кадр отбрасывается.

Запуск:
    python src/cmp_tracks.py --camera center --new data/tracks/tracks_center_new.csv
    python src/cmp_tracks.py --camera center --new A.csv --ref B.csv --csv out.csv
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")   # SystemExit печатается в stderr
except Exception:
    pass

# Признаки ухудшения картинки: насколько новому прогону позволено просесть.
CONF_P10_DROP = 0.05     # p10 конфиденций ниже опорного на столько — тревога
JUNK_RISE_PP = 3.0       # доля conf<0.3 выше опорной на столько п.п. — тревога
# Геометрия: расхождение по «горячим» клеткам сетки кадра.
GRID_WARN_PP = 10.0
GRID_BAD_PP = 20.0
# Клетка считается горячей, если в опорном прогоне в ней не меньше этого.
HOT_CELL_PCT = 2.0
# Бокс ниже этой высоты — дальняя часть кадра, класс ненадёжен.
SMALL_H_PX = 80
NX, NY = 4, 3            # сетка по кадру


def load(path: Path, k_max: int | None = None) -> pd.DataFrame:
    df = pd.read_csv(path, on_bad_lines="skip")
    if df.empty:
        raise SystemExit(f"Пустой файл треков: {path}")
    df = df[df.k < df.k.max()]          # последний кадр может быть недописан
    if k_max is not None:
        df = df[df.k <= k_max]
    df["h"] = df.y2 - df.y1
    df["area"] = (df.x2 - df.x1) * df.h
    return df


def profile(df: pd.DataFrame, name: str) -> pd.Series:
    span = df.k.max() + 1
    lens = df.groupby("track_id").size()
    small = df.h < SMALL_H_PX
    mix = df.loc[~small, "cls"].value_counts(normalize=True) * 100
    return pd.Series({
        "кадров": span,
        "детекций": len(df),
        "детекций на кадр": len(df) / span,
        "треков": df.track_id.nunique(),
        "треков на 100 кадров": df.track_id.nunique() / span * 100,
        "длина трека, медиана": lens.median(),
        "доля треков <5 кадров, %": (lens < 5).mean() * 100,
        "conf, медиана": df.conf.median(),
        "conf, p10": df.conf.quantile(0.10),
        "доля conf<0.3, %": (df.conf < 0.30).mean() * 100,
        "площадь бокса, медиана px2": df.area.median(),
        f"доля боксов <{SMALL_H_PX} px, %": small.mean() * 100,
        "car, % (крупные боксы)": mix.get("car", 0.0),
        "truck, %": mix.get("truck", 0.0),
        "bus, %": mix.get("bus", 0.0),
        "motorcycle, %": mix.get("motorcycle", 0.0),
    }, name=name)


def grid(df: pd.DataFrame, w: int, h: int) -> pd.DataFrame:
    """Доля детекций по клеткам сетки NYxNX, % от всех."""
    gx = np.clip((df.cx / w * NX).astype(int), 0, NX - 1)
    gy = np.clip((df.cy / h * NY).astype(int), 0, NY - 1)
    t = pd.crosstab(gy, gx, normalize=True) * 100
    return t.reindex(index=range(NY), columns=range(NX), fill_value=0.0)


def main() -> None:
    ap = argparse.ArgumentParser(description="Сверка треков нового ролика с опорным прогоном")
    ap.add_argument("--camera", required=True, help="id камеры из config.yaml")
    ap.add_argument("--new", required=True, help="CSV треков нового ролика")
    ap.add_argument("--ref", default=None,
                    help="CSV опорного прогона (по умолч. data/tracks/tracks_<cam>.csv)")
    ap.add_argument("--csv", default=None, help="записать таблицу сравнения в файл")
    args = ap.parse_args()

    cfg = yaml.safe_load(open(ROOT / "config.yaml", encoding="utf-8"))
    tracks_dir = Path(cfg["paths"]["out_dir"]) / "tracks"
    new_path = Path(args.new)
    ref_path = Path(args.ref) if args.ref else tracks_dir / f"tracks_{args.camera}.csv"
    for p in (new_path, ref_path):
        if not p.exists():
            raise SystemExit(f"Нет файла: {p}")
    if new_path.resolve() == ref_path.resolve():
        raise SystemExit("--new и --ref — один файл")

    new = load(new_path)
    k_max = int(new.k.max())
    ref_pref = load(ref_path, k_max=k_max)
    ref_full = load(ref_path)

    stride = int(cfg["tracking"]["frame_stride"])
    cycle_frames = int(cfg["aggregation"]["cycle_sec"] * 25.0 / stride)
    cycles = (k_max + 1) / cycle_frames

    print(f"[cmp] {args.camera}: {new_path.name} ({k_max + 1} кадров, {cycles:.1f} цикла) "
          f"против {ref_path.name}")
    if cycles < 1.0:
        print(f"[cmp] ВНИМАНИЕ: меньше одного цикла ({cycle_frames} кадров) — "
              f"плотность и состав читать нельзя, только нижний хвост conf и геометрию")

    table = pd.concat([
        profile(new, "новый"),
        profile(ref_pref, f"опорный, те же {k_max + 1}"),
        profile(ref_full, "опорный, весь"),
    ], axis=1)
    pd.set_option("display.width", 200)
    print()
    print(table.round(2).to_string())

    # Геометрия. Кадр берём из разрешения, зашитого в калибровку камеры.
    calib = ROOT / "calib" / f"{args.camera}_calib.json"
    w, h = 2688, 1520
    if calib.exists():
        import json
        size = json.loads(calib.read_text(encoding="utf-8")).get("image_size")
        if size:
            w, h = int(size[0]), int(size[1])

    g_new, g_ref = grid(new, w, h), grid(ref_full, w, h)
    print(f"\n[cmp] доля детекций по клеткам кадра {w}x{h}, % "
          f"(строки — сверху вниз): новый / опорный")
    for iy in range(NY):
        cells = "  ".join(f"{g_new.iat[iy, ix]:5.1f}/{g_ref.iat[iy, ix]:5.1f}"
                          for ix in range(NX))
        print(f"  {cells}")

    hot = g_ref >= HOT_CELL_PCT
    delta = (g_new - g_ref).abs().where(hot)
    max_d = float(np.nanmax(delta.values))
    print(f"[cmp] по {int(hot.values.sum())} клеткам с >={HOT_CELL_PCT:.0f} % детекций опорного: "
          f"макс |Δ| = {max_d:.1f} п.п., среднее {float(np.nanmean(delta.values)):.1f} п.п.")

    # Вердикт — только по тому, что не зависит от трафика.
    p10_drop = float(ref_full.conf.quantile(0.10) - new.conf.quantile(0.10))
    junk_rise = float((new.conf < 0.30).mean() - (ref_full.conf < 0.30).mean()) * 100
    bad = []
    if p10_drop > CONF_P10_DROP:
        bad.append(f"p10 конфиденций просел на {p10_drop:.2f}")
    if junk_rise > JUNK_RISE_PP:
        bad.append(f"доля conf<0.3 выросла на {junk_rise:.1f} п.п.")
    if max_d > GRID_BAD_PP:
        bad.append(f"геометрия разошлась на {max_d:.1f} п.п.")

    print()
    if bad:
        print(f"[cmp] ВЕРДИКТ: детекция хуже опорной — {'; '.join(bad)}. "
              f"Проверить перекодировку и кадр глазами до того, как считать маневры")
    elif max_d > GRID_WARN_PP:
        print(f"[cmp] ВЕРДИКТ: картинка в норме, но детекции легли по кадру иначе "
              f"({max_d:.1f} п.п.) — сверить calib/{args.camera}_gates_check.jpg "
              f"и прогнать camera_shift.py")
    else:
        print(f"[cmp] ВЕРДИКТ: детекция эквивалентна опорной "
              f"(p10 {-p10_drop:+.2f}, conf<0.3 {junk_rise:+.1f} п.п., "
              f"геометрия {max_d:.1f} п.п.). Расхождения по плотности и составу — трафик")

    if args.csv:
        table.to_csv(args.csv, encoding="utf-8")
        print(f"[cmp] таблица → {args.csv}")


if __name__ == "__main__":
    main()
