"""Shared helpers for the perception tools (Comment 1.3 / 2.1 / 2.2): clip catalogue, gates and camera model,
track loading, a replica of src/classify.py, a small OpenCV video player and keyboard handling.

Nothing here writes outside revision/; the repository's calib/ and src/ files are only read.
"""
from __future__ import annotations

import csv
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
REV = ROOT / "revision"
INC26 = REV / "incoming" / "2026-10-26" / "manual-counting"
INC28 = REV / "incoming" / "2026-10-28" / "answers"
MC28 = INC28 / "step_1.2_1.3" / "manual_counting"
TRACKS = INC28 / "step_0" / "c_tracks"
OUT = REV / "perception"
CLIP_DIR: Path | None = None       # folder with the raw clips, if not the incoming folders (--clip-dir)

RAW_W, RAW_H = 2688, 1520          # camera frames (tracks and gates live here)
TRACK_DT = 0.12                    # tracker step: every 3rd frame of 25 fps
SYNC = {"center": 19.0, "zarich": 0.0}   # config.yaml sync_offset_sec (t_common = t_local + SYNC)
# The raw center clips start one video frame early relative to t_local = t_common - 19 (found by matching raw and
# overlay frames at 5 times per clip); zarich clips match exactly. Add this to a computed raw-clip frame index.
FRAME_OFFSET = {"center": 1, "zarich": 0}
OWNED = {"center": ["SVB_N", "PRB_E"], "zarich": ["SVB_S", "PRB_W"]}
INTERVALS = {"i300": 300.0, "i900": 900.0}
CLIP_LEN = 300.0
MOV_EN = {"пряمо": "through", "прямо": "through", "налево": "left", "направо": "right", "разворот": "U-turn"}
MOV_CODE = {"through": "T", "left": "L", "right": "R", "U-turn": "U"}
LEG_VEC = {"SVB_N": (0, 1), "SVB_S": (0, -1), "PRB_E": (1, 0), "PRB_W": (-1, 0)}


@dataclass(frozen=True)
class Clip:
    camera: str
    interval: str

    @property
    def name(self) -> str:
        return f"{self.camera}_{self.interval}"

    @property
    def t0(self) -> float:                       # t_common of the first frame
        return INTERVALS[self.interval]

    @property
    def stem(self) -> str:
        a = int(self.t0)
        return f"{self.camera}_{self.interval}_common{a}-{a + 300}s"

    def raw_path(self) -> Path:
        """Raw clip. The 26 Oct copies seek ~20x faster than the 28 Oct re-encodes (same content)."""
        if CLIP_DIR is not None:
            return Path(CLIP_DIR) / f"{self.stem}.mp4"
        p = INC26 / "clips" / f"{self.stem}.mp4"
        return p if p.exists() else MC28 / "clips" / f"{self.stem}.mp4"

    def overlay_path(self) -> Path:
        return MC28 / "clips_tracks" / f"{self.stem}_tracks.mp4"

    def k_at(self, t_clip: float) -> float:
        """Tracker frame index (fractional) at clip time t_clip (s)."""
        return (self.t0 + t_clip - SYNC[self.camera]) / TRACK_DT

    def t_clip_of_k(self, k: float) -> float:
        return k * TRACK_DT + SYNC[self.camera] - self.t0


CLIPS = [Clip(c, i) for c in ("center", "zarich") for i in ("i300", "i900")]


def clip_by_name(name: str) -> Clip:
    for c in CLIPS:
        if c.name == name:
            return c
    raise SystemExit(f"unknown clip {name!r}; use one of {[c.name for c in CLIPS]}")


# the blind-count sample: one clip per camera, all four approaches (decision C-3, 1 Nov 2026). Since 3 Nov 2026
# (decision C-13) the two i300 clips: the i900 counts were made by an AI frame review, not by hand, and are archived
# under perception/archive/codex_i900_20261103/
COUNT_CLIPS = [clip_by_name("center_i300"), clip_by_name("zarich_i300")]


def final_clips(manual_dir: Path) -> set[str] | None:
    """Clips whose blind count is closed by <manual_dir>/FINAL.json (perception_count.py export --final); None if the
    blind phase is not closed. A FINAL.json without a clip list (older format) closes all four clips."""
    p = Path(manual_dir) / "FINAL.json"
    if not p.exists():
        return None
    return set(read_json(p).get("clips") or [c.name for c in CLIPS])


def true_common(camera: str, t_local):
    """Corrected common time for cross-camera comparisons: the center clock runs 4 s fast over t_local 425-459 s
    (Ryzhanskyi, README_1_2: +19 s before 425 s, +15 s after 459 s, linear in between)."""
    t = np.asarray(t_local, float)
    if camera != "center":
        return t
    return t + np.interp(t, [425.0, 459.0], [19.0, 15.0])


# ---------------------------------------------------------------- gates and camera model
def load_gates(camera: str) -> list[dict]:
    with open(ROOT / "calib" / f"gates_{camera}.json", encoding="utf-8") as fh:
        return json.load(fh)["gates"]


def load_camera(camera: str):
    c = ROOT / "calib"
    return np.load(c / f"{camera}_K.npy"), np.load(c / f"{camera}_D.npy"), np.load(c / f"{camera}_Kout.npy")


def distort(pts_u, camera: str) -> np.ndarray:
    """Undistorted (Kout) pixels -> raw camera pixels (inverse of src/undistort.py)."""
    K, D, Kout = load_camera(camera)
    p = np.asarray(pts_u, float).reshape(-1, 2)
    xn = (p - Kout[:2, 2]) / np.diag(Kout)[:2]
    obj = np.hstack([xn, np.ones((len(xn), 1))]).reshape(-1, 1, 3)
    img, _ = cv2.projectPoints(obj, np.zeros(3), np.zeros(3), K, D)
    return img.reshape(-1, 2)


def gate_polyline_raw(gate: dict, camera: str, n: int = 24) -> np.ndarray:
    """A gate (straight in the undistorted frame) as a curve in raw camera pixels."""
    a, b = np.asarray(gate["points"], float)
    return distort(a + np.linspace(0, 1, n)[:, None] * (b - a), camera)


def undistort_image(img: np.ndarray, camera: str) -> np.ndarray:
    """Raw frame of any width -> undistorted frame in the same pixel scale (Kout scaled with the width)."""
    K, D, Kout = load_camera(camera)
    s = img.shape[1] / RAW_W
    S = np.diag([s, s, 1.0])
    return cv2.undistort(img, S @ K, D, None, S @ Kout)


# ---------------------------------------------------------------- tracks and classification
def load_tracks(camera: str, k_lo: float = -1e18, k_hi: float = 1e18) -> dict:
    """tracks_<camera>_undist.csv -> {track_id: dict(k, box(x1,y1,x2,y2), cu(x,y), cls)} (sorted by k)."""
    rows = {}
    with open(TRACKS / f"tracks_{camera}_undist.csv", encoding="utf-8", newline="") as fh:
        r = csv.reader(fh)
        head = next(r)
        ix = {h: i for i, h in enumerate(head)}
        for row in r:
            k = int(row[ix["k"]])
            if k < k_lo or k > k_hi:
                continue
            rows.setdefault(int(row[ix["track_id"]]), []).append(
                (k, *(float(row[ix[c]]) for c in ("x1", "y1", "x2", "y2", "cx_u", "cy_u")), row[ix["cls"]]))
    out = {}
    for tid, rs in rows.items():
        rs.sort(key=lambda x: x[0])
        out[tid] = dict(k=np.array([x[0] for x in rs]), box=np.array([x[1:5] for x in rs]),
                        cu=np.array([x[5:7] for x in rs]), cls=max(set(x[7] for x in rs), key=[x[7] for x in rs].count))
    return out


def load_movements(camera: str) -> list[dict]:
    with open(MC28 / f"movements_{camera}.csv", encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        r["track_id"], r["k"], r["t_sec"], r["t_common"] = int(r["track_id"]), int(r["k"]), float(r["t_sec"]), float(r["t_common"])
    return rows


def seg_intersect(p1, p2, p3, p4):
    d1, d2 = p2 - p1, p4 - p3
    den = d1[0] * d2[1] - d1[1] * d2[0]
    if abs(den) < 1e-9:
        return None
    t = ((p3[0] - p1[0]) * d2[1] - (p3[1] - p1[1]) * d2[0]) / den
    u = ((p3[0] - p1[0]) * d1[1] - (p3[1] - p1[1]) * d1[0]) / den
    return p1 + t * d1 if 0 <= t <= 1 and 0 <= u <= 1 else None


def movement_of(entry: str, exit_: str) -> str:
    h = -np.array(LEG_VEC[entry], float)
    e = np.array(LEG_VEC[exit_], float)
    dot, cross = float(h @ e), h[0] * e[1] - h[1] * e[0]
    if dot > 0.7:
        return "through"
    if dot < -0.7:
        return "U-turn"
    return "left" if cross > 0 else "right"


def classify(tracks: dict, gates: list[dict]) -> tuple[list[dict], dict]:
    """Replica of src/classify.py (entry = first inward crossing of a stop gate, exit = first outward crossing of an
    exit gate after it, else the heading fallback; tracks ending inside the box are not counted).
    Returns (movements, per-track status) where status in {counted, no_entry, in_box, short}."""
    allpts = np.array([p for g in gates for p in g["points"]], float)
    box_c = allpts.mean(axis=0)
    stops = [(g["label"], np.array(g["points"][0], float), np.array(g["points"][1], float)) for g in gates if g["role"] == "stop"]
    exits = [(g["label"], np.array(g["points"][0], float), np.array(g["points"][1], float)) for g in gates if g["role"] == "exit"]
    leg = {}
    for lab, a, b in exits:
        v = (a + b) / 2 - box_c
        leg[lab] = v / (np.linalg.norm(v) + 1e-9)
    ref = np.mean([np.linalg.norm((a + b) / 2 - box_c) for _, a, b in exits])
    moves, status = [], {}
    for tid in sorted(tracks):
        tr = tracks[tid]
        pts = tr["cu"]
        if len(pts) < 3:
            status[tid] = "short"
            continue
        entry = exit_ = method = None
        for i in range(len(pts) - 1):
            a, b = pts[i], pts[i + 1]
            mv = b - a
            if entry is None:
                for lab, p, q in stops:
                    X = seg_intersect(a, b, p, q)
                    if X is not None and mv @ (box_c - X) > 0:
                        entry = (i, lab)
                        break
            else:
                for lab, p, q in exits:
                    X = seg_intersect(a, b, p, q)
                    if X is not None and mv @ (box_c - X) < 0:
                        exit_, method = (i, lab), "gate"
                        break
            if exit_ is not None:
                break
        if entry is None:
            status[tid] = "no_entry"
            continue
        if exit_ is None:
            ev = pts[-1] - box_c
            if np.linalg.norm(ev) < 0.5 * ref:
                status[tid] = "in_box"
                continue
            eu = ev / (np.linalg.norm(ev) + 1e-9)
            exit_, method = (len(pts) - 1, max(leg, key=lambda k: float(eu @ leg[k]))), "heading"
        status[tid] = "counted"
        moves.append(dict(track_id=tid, entry=entry[1], exit=exit_[1], movement=movement_of(entry[1], exit_[1]),
                          method=method, k=int(tr["k"][entry[0]]), k_exit=int(tr["k"][exit_[0]]), cls=tr["cls"]))
    return moves, status


# ---------------------------------------------------------------- keyboard
# Ukrainian/Russian layouts send Cyrillic letters for the same physical keys; map them to Latin.
_CYR = "йцукенгшщзхїфівапролджєячсмитьбюыэъё"
_LAT = "qwertyuiop[]asdfghjkl;'zxcvbnm,.s']`"
CYR2LAT = {}
for _c, _l in zip(_CYR + _CYR.upper(), _LAT + _LAT):
    CYR2LAT[ord(_c)] = ord(_l)                    # Unicode window messages
    CYR2LAT[_c.encode("cp1251")[0]] = ord(_l)     # ANSI window messages (cp1251 system locale)
K_LEFT, K_UP, K_RIGHT, K_DOWN = 2424832, 2490368, 2555904, 2621440
K_PGUP, K_PGDN, K_HOME, K_END, K_DEL = 2162688, 2228224, 2359296, 2293760, 3014656
K_ESC, K_ENTER, K_BACK, K_SPACE, K_TAB = 27, 13, 8, 32, 9


_SMOKE = {"t0": None}


def read_key(delay_ms: int) -> int:
    """waitKeyEx with Cyrillic letters mapped to Latin and letters lower-cased; -1 if no key.
    (Testing: with the environment variable PERCEPTION_SMOKE=N the window receives Esc after N seconds.)"""
    k = cv2.waitKeyEx(max(1, int(delay_ms)))
    if os.environ.get("PERCEPTION_SMOKE"):
        _SMOKE["t0"] = _SMOKE["t0"] or time.time()
        if time.time() - _SMOKE["t0"] > float(os.environ["PERCEPTION_SMOKE"]):
            return K_ESC
    if k == -1:
        return -1
    if k in CYR2LAT:
        return CYR2LAT[k]
    if 65 <= k <= 90:
        return k + 32
    if k in (10, 13):
        return K_ENTER
    return k


def window_closed(win: str) -> bool:
    try:
        return cv2.getWindowProperty(win, cv2.WND_PROP_VISIBLE) < 1
    except cv2.error:
        return True


# ---------------------------------------------------------------- video
class Player:
    """Sequential reader with seeking and a small cache of recent frames for stepping back."""

    def __init__(self, path: Path, cache: int = 40):
        self.path = Path(path)
        self.cap = cv2.VideoCapture(str(path))
        if not self.cap.isOpened():
            raise SystemExit(f"cannot open {path}")
        self.fps = self.cap.get(cv2.CAP_PROP_FPS)
        self.n = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.pos = -1                 # index of the frame in self.frame
        self.frame = None
        self._next = 0                # index the capture will return next
        self.cache, self.cache_n = {}, cache

    def _keep(self, i, fr):
        self.cache[i] = fr
        if len(self.cache) > self.cache_n:
            del self.cache[min(self.cache)]

    def read(self, i: int) -> np.ndarray:
        i = int(min(max(i, 0), self.n - 1))
        if i == self.pos:
            return self.frame
        if i in self.cache:
            self.pos, self.frame = i, self.cache[i]
            return self.frame
        if i < self._next or i > self._next + 50:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, i)
            self._next = i
        while self._next < i:
            self.cap.grab()
            self._next += 1
        ok, fr = self.cap.read()
        if not ok:
            fr = self.frame if self.frame is not None else np.zeros((1086, 1920, 3), np.uint8)
        self._next = i + 1
        self.pos, self.frame = i, fr
        self._keep(i, fr)
        return fr


def put_lines(img, lines, org=(10, 10), scale=0.55, color=(255, 255, 255), bg=(0, 0, 0), alpha=0.6, lh=None):
    """Text block with a translucent background; lines may be (text, colour) tuples."""
    lh = lh or int(26 * scale / 0.55)
    w = max((cv2.getTextSize(t if isinstance(t, str) else t[0], cv2.FONT_HERSHEY_SIMPLEX, scale, 1)[0][0] for t in lines), default=0)
    x, y = org
    h = lh * len(lines) + 8
    sub = img[y:y + h, x:x + w + 16]
    if sub.size:
        img[y:y + h, x:x + w + 16] = (sub * (1 - alpha) + np.array(bg) * alpha).astype(np.uint8)
    for j, t in enumerate(lines):
        txt, col = (t, color) if isinstance(t, str) else t
        cv2.putText(img, txt, (x + 8, y + lh * (j + 1) - 6), cv2.FONT_HERSHEY_SIMPLEX, scale, col, 1, cv2.LINE_AA)


def fit_size(w: int, h: int, max_w: int, max_h: int) -> tuple[int, int]:
    s = min(max_w / w, max_h / h, 1.0)
    return int(w * s), int(h * s)


def screen_size() -> tuple[int, int, float]:
    """Usable screen area in physical pixels (work area minus the taskbar and a window title) and the UI scale.
    Makes the process DPI-aware first, so OpenCV windows are not blurred by Windows' display scaling."""
    try:
        import ctypes
        from ctypes import wintypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
        rect = wintypes.RECT()
        ctypes.windll.user32.SystemParametersInfoW(0x30, 0, ctypes.byref(rect), 0)   # SPI_GETWORKAREA
        dpi = ctypes.windll.user32.GetDpiForSystem() / 96.0
        return rect.right - rect.left, rect.bottom - rect.top - int(40 * dpi), dpi
    except Exception:
        return 1600, 860, 1.0


# ---------------------------------------------------------------- files
def write_csv(path: Path, rows: list[dict], fields: list[str] | None = None):
    """Atomic CSV write (temporary file + replace), so a crash never leaves a half-written file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = fields or (list(rows[0]) if rows else [])
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, path)


def read_csv(path: Path) -> list[dict]:
    if not Path(path).exists():
        return []
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def write_json(path: Path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def read_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def posix(path: Path) -> str:
    """Path relative to the repository root, with forward slashes."""
    p = Path(path).resolve()
    try:
        return p.relative_to(ROOT).as_posix()
    except ValueError:
        return p.as_posix()


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def sha256(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()
