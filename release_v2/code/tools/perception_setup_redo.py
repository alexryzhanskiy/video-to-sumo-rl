"""Timed redo of one camera's manual set-up (Comment 2.2: how much manual pre-annotation the method needs, and
whether it must be redone when the camera moves).

The pipeline's per-camera set-up is the gate picking of src/zones_pick.py: on the rectified frame, one stop line per
approach the camera owns (2) and one exit line per leg (4), two clicks each, plus naming each line. This tool repeats
that step on a rectified frame of the same camera, without showing the original gates, and times it; then it re-runs
the pipeline's classification (a verified replica of src/classify.py) with the new gates on all tracks of that
camera and compares the movement counts with the published ones. The fisheye calibration (src/calib_pick.py) is not
redone here.

    revision/.venv/Scripts/python.exe revision/tools/perception_setup_redo.py prepare --camera center
    revision/.venv/Scripts/python.exe revision/tools/perception_setup_redo.py pick --camera center
    revision/.venv/Scripts/python.exe revision/tools/perception_setup_redo.py compare --camera center

Pick keys: left click = point (2 points = 1 line); after each line press its approach: 1 SVB_N, 2 SVB_S, 3 PRB_E,
4 PRB_W; Tab = switch stop line / exit line; Backspace = undo; Space = pause the clock; Enter = finished (saves; refused,
with a message, until there is one stop line per owned approach and one exit line per leg); Esc = save and quit without
finishing. Output: revision/perception/setup_redo/<camera>_gates_redo.json (same layout as calib/gates_<camera>.json)
with the click log and the active time. `compare` prints the pipeline's counts, so it runs only after FINAL.json closes
the camera's counting clip (decision C-10); it refuses an incomplete redo file; --out sets its output folder.
A second person picks into their own folder (`pick --out <folder>`, the reference frame stays shared) and is
compared with `compare --gates <folder>/<camera>_gates_redo.json --out <folder>`.
"""
from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import perception_common as pc  # noqa: E402

OUT = pc.OUT / "setup_redo"
LABELS = {ord("1"): "SVB_N", ord("2"): "SVB_S", ord("3"): "PRB_E", ord("4"): "PRB_W"}
COL = {"stop": (0, 0, 255), "exit": (255, 200, 0)}


def missing_lines(gates: list[dict], cam: str) -> str:
    """'' if the set-up is complete: one stop line for each approach the camera owns and one exit line for each of the
    four legs, each named once; otherwise what is missing or wrong."""
    stop = sorted(g.get("label", "?") for g in gates if g["role"] == "stop")
    exit_ = sorted(g.get("label", "?") for g in gates if g["role"] == "exit")
    msg = []
    if stop != sorted(pc.OWNED[cam]):
        msg.append(f"stop lines {', '.join(stop) or 'none'} (need {' and '.join(pc.OWNED[cam])})")
    if exit_ != sorted(LABELS.values()):
        msg.append(f"exit lines {', '.join(exit_) or 'none'} (need one each for {', '.join(LABELS.values())})")
    return "; ".join(msg)


def ref_path(cam):
    return OUT / f"{cam}_undistorted_ref.jpg"


def cmd_prepare(a):
    OUT.mkdir(parents=True, exist_ok=True)
    clip = pc.Clip(a.camera, "i300")
    fr = pc.Player(clip.raw_path(), cache=0).read(int(a.t * 25))
    fr = cv2.resize(fr, (pc.RAW_W, pc.RAW_H), interpolation=cv2.INTER_CUBIC)
    cv2.imwrite(str(ref_path(a.camera)), pc.undistort_image(fr, a.camera), [cv2.IMWRITE_JPEG_QUALITY, 95])
    print("wrote", ref_path(a.camera))


class Picker:
    def __init__(self, cam, max_w, max_h, ui, out=OUT):
        self.cam = cam
        self.img = cv2.imread(str(ref_path(cam)))
        if self.img is None:
            raise SystemExit("run `prepare` first")
        self.fs = max(0.45, 0.4 * ui)
        self.lh = int(43 * self.fs)
        self.strip = self.lh * 4 + 8
        self.disp = pc.fit_size(self.img.shape[1], self.img.shape[0], max_w, max_h - self.strip)
        self.sc = self.disp[0] / self.img.shape[1]
        self.path = Path(out) / f"{cam}_gates_redo.json"
        old = pc.read_json(self.path) if self.path.exists() else {}
        self.gates, self.log = old.get("gates", []), old.get("log", [])
        self.active = float(old.get("active_seconds", 0))
        self.finished = old.get("finished")
        self.role, self.pending, self.need_label = "stop", None, None
        self.paused, self.t_mark = False, time.time()
        self.flash, self.flash_until = "", 0.0

    def tick(self):
        if not self.paused:
            self.active += time.time() - self.t_mark
        self.t_mark = time.time()

    def ev(self, what, **kw):
        self.tick()
        self.log.append(dict(t=round(self.active, 2), wall=pc.now_iso(), what=what, **kw))

    def save(self, finished=None):
        self.tick()
        if finished:
            self.finished = pc.now_iso()
        pc.write_json(self.path, dict(camera=self.cam, image_size=[pc.RAW_W, pc.RAW_H], gates=self.gates,
                                      active_seconds=round(self.active, 1), finished=self.finished,
                                      reference=pc.posix(ref_path(self.cam)), log=self.log))

    def mouse(self, e, x, y, *_):
        if e != cv2.EVENT_LBUTTONDOWN or self.paused or self.need_label is not None or y >= self.disp[1]:
            return
        pt = [round(x / self.sc, 1), round(y / self.sc, 1)]
        if self.pending is None:
            self.pending = pt
            self.ev("point", role=self.role, p=pt)
        else:
            self.need_label = dict(id=f"{self.role}{sum(g['role'] == self.role for g in self.gates)}", role=self.role,
                                   points=[self.pending, pt])
            self.pending = None
            self.ev("line", role=self.role, p=pt)

    def render(self):
        W, H = self.disp
        can = np.zeros((H + self.strip, W, 3), np.uint8)
        can[:H] = cv2.resize(self.img, self.disp, interpolation=cv2.INTER_AREA)
        for g in self.gates + ([self.need_label] if self.need_label else []):
            (x1, y1), (x2, y2) = (np.array(g["points"]) * self.sc).astype(int)
            cv2.line(can, (x1, y1), (x2, y2), COL[g["role"]], 3, cv2.LINE_AA)
            cv2.putText(can, g.get("label", "?"), ((x1 + x2) // 2 + 5, (y1 + y2) // 2 - 6), cv2.FONT_HERSHEY_SIMPLEX,
                        0.6, COL[g["role"]], 2, cv2.LINE_AA)
        if self.pending:
            cv2.circle(can, tuple((np.array(self.pending) * self.sc).astype(int)), 5, COL[self.role], -1)
        n = Counter(g["role"] for g in self.gates)
        self.tick()
        state = ("PAUSED" if self.paused else f"clock {self.active / 60:4.1f} min") + (" (finished)" if self.finished else "")
        ask = ("which approach is this line? 1 SVB_N  2 SVB_S  3 PRB_E  4 PRB_W" if self.need_label else
               self.flash if time.time() < self.flash_until else f"drawing: {self.role} lines (Tab switches)")
        pc.put_lines(can, [(f"{self.cam}: stop lines {n['stop']} (need {len(pc.OWNED[self.cam])}: "
                            f"{', '.join(pc.OWNED[self.cam])}), exit lines {n['exit']} (need 4)   {state}", (255, 255, 255)),
                           (ask, (0, 255, 255)),
                           "Stop line: across the approach lanes at the stop line. Exit line: across the leaving lanes "
                           "of a leg, where vehicles leave the junction.",
                           "Click 2 points per line | 1-4 name it | Tab stop/exit | Backspace undo | Space pause clock "
                           "| Enter finished | Esc quit"], (0, H + 2), scale=self.fs, alpha=0.0, lh=self.lh)
        return can

    def run(self):
        win = f"Set-up redo - {self.cam}"
        cv2.namedWindow(win, cv2.WINDOW_AUTOSIZE)
        cv2.setMouseCallback(win, self.mouse)
        self.ev("open")
        while True:
            cv2.imshow(win, self.render())
            k = pc.read_key(30)
            if self.need_label is not None and k in LABELS:
                self.need_label["label"] = LABELS[k]
                self.gates.append(self.need_label)
                self.ev("label", id=self.need_label["id"], label=LABELS[k])
                self.need_label = None
                self.save()
            elif k == pc.K_TAB:
                self.role, self.pending = ("exit" if self.role == "stop" else "stop"), None
            elif k == pc.K_BACK:
                if self.need_label is not None or self.pending is not None:
                    self.need_label = self.pending = None
                elif self.gates:
                    self.gates.pop()
                self.ev("undo")
                self.save()
            elif k == pc.K_SPACE:
                self.tick()
                self.paused = not self.paused
                self.ev("pause" if self.paused else "resume")
            elif k == pc.K_ENTER:
                miss = missing_lines(self.gates, self.cam)
                if miss:                                  # not finished: say what is missing, keep the window open
                    self.flash, self.flash_until = f"NOT FINISHED: {miss} (Backspace undoes the last line)", time.time() + 6
                    self.ev("finish refused", missing=miss)
                    continue
                self.ev("finished")
                self.save(finished=True)
                break
            elif k == pc.K_ESC or pc.window_closed(win):
                self.ev("quit")
                self.save()
                break
        cv2.destroyAllWindows()
        print(f"saved {len(self.gates)} lines, active time {self.active / 60:.1f} min -> {self.path}")


def cmd_pick(a):
    sw, sh, ui = pc.screen_size()
    Picker(a.camera, sw - 20, sh, ui, a.out).run()


def cmd_compare(a):
    cam = a.camera
    # blind rule (C-10): the comparison prints the pipeline's counts per approach and movement
    need = [c.name for c in pc.COUNT_CLIPS if c.camera == cam]
    fin = pc.final_clips(a.manual_dir)
    if fin is None or not set(need) <= fin:
        raise SystemExit(f"compare shows the pipeline's counts of the {cam} camera: run it after the blind count of "
                         f"{', '.join(need)} is closed (perception_count.py export --final; decision C-10)")
    gpath = Path(a.gates) if a.gates else OUT / f"{cam}_gates_redo.json"
    redo = pc.read_json(gpath)
    orig = pc.load_gates(cam)
    new = redo["gates"]
    miss = missing_lines(new, cam)
    if miss:
        raise SystemExit(f"{gpath} is incomplete: {miss}. Run `pick --camera {cam}` again and finish with Enter.")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    lines = [f"# Set-up redo, {cam} camera", "",
             f"Redo file: `{pc.posix(gpath)}`; finished: {redo.get('finished') or 'no (quit with Esc)'}; "
             f"active time **{redo.get('active_seconds', 0) / 60:.1f} min** for {len(new)} lines "
             f"({sum(e['what'] == 'undo' for e in redo.get('log', []))} undos).", "",
             "## Line positions (rectified frame, pixels of the 2688-px image)", "",
             "| Line | Original midpoint | Redo midpoint | Midpoint shift (px) | Endpoint shifts (px) | Length orig / redo |",
             "|---|---|---|---|---|---|"]
    for g in orig:
        m = [x for x in new if x["role"] == g["role"] and x.get("label") == g["label"]]
        if not m:
            lines.append(f"| {g['role']} {g['label']} | – | missing | | | |")
            continue
        p, q = np.array(g["points"]), np.array(m[0]["points"])
        if np.linalg.norm(p[0] - q[0]) + np.linalg.norm(p[1] - q[1]) > np.linalg.norm(p[0] - q[1]) + np.linalg.norm(p[1] - q[0]):
            q = q[::-1]
        lines.append(f"| {g['role']} {g['label']} | {p.mean(0).round(0).tolist()} | {q.mean(0).round(0).tolist()} | "
                     f"{np.linalg.norm(p.mean(0) - q.mean(0)):.0f} | {np.linalg.norm(p[0] - q[0]):.0f}, "
                     f"{np.linalg.norm(p[1] - q[1]):.0f} | {np.linalg.norm(p[1] - p[0]):.0f} / {np.linalg.norm(q[1] - q[0]):.0f} |")
    tracks = pc.load_tracks(cam)
    mo, _ = pc.classify(tracks, orig)
    mn, _ = pc.classify(tracks, [dict(g, label=g.get("label", "?")) for g in new])
    ref = {m["track_id"]: m for m in pc.load_movements(cam)}
    assert {m["track_id"] for m in mo} == set(ref), "replica differs from the published movements"
    O, N = {m["track_id"]: m for m in mo}, {m["track_id"]: m for m in mn}
    same = sum(t in N and (N[t]["entry"], N[t]["exit"]) == (O[t]["entry"], O[t]["exit"]) for t in O)
    lines += ["", "## Effect on the counts (all tracks of the 24-min recording)", "",
              f"- Movements counted: original {len(O)}, with the redo gates {len(N)} ({len(N) - len(O):+d}, "
              f"{100 * (len(N) - len(O)) / len(O):+.1f}%).",
              f"- Original movements counted again with the same entry and exit: {same} of {len(O)} "
              f"({100 * same / len(O):.1f}%); lost {sum(t not in N for t in O)}; new {sum(t not in O for t in N)}.",
              f"- Heading-fallback exits: original {sum(m['method'] == 'heading' for m in mo)}, redo "
              f"{sum(m['method'] == 'heading' for m in mn)}.", "",
              "| Approach | Movement | Original | Redo | Difference |", "|---|---|---|---|---|"]
    rows = []
    for ap in pc.OWNED[cam]:
        for mv in ("left", "through", "right", "U-turn"):
            o = sum(m["entry"] == ap and m["movement"] == mv for m in mo)
            n = sum(m["entry"] == ap and m["movement"] == mv for m in mn)
            lines.append(f"| {ap} | {mv} | {o} | {n} | {n - o:+d} |")
            rows.append(dict(camera=cam, approach=ap, movement=mv, original=o, redo=n, diff=n - o))
    # 5-min bins as in the demand (t_common = t_sec + sync)
    bins = Counter((int((m["k"] * pc.TRACK_DT + pc.SYNC[cam]) // 300), m["entry"], m["movement"]) for m in mn
                   if m["movement"] != "U-turn")
    obins = Counter((int((m["k"] * pc.TRACK_DT + pc.SYNC[cam]) // 300), m["entry"], m["movement"]) for m in mo
                    if m["movement"] != "U-turn")
    keys = sorted(set(bins) | set(obins))
    diffs = [abs(bins[k] - obins[k]) for k in keys if k[0] < 5]
    lines += ["", f"Demand cells (5-min interval x approach x movement, U-turns excluded, 0-1500 s): {len(diffs)}; "
              f"mean absolute difference {np.mean(diffs):.2f} vehicles; cells changed {sum(d > 0 for d in diffs)}."]
    pc.write_csv(out / f"{cam}_compare_counts.csv", rows)
    (out / f"{cam}_compare.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--camera", choices=["center", "zarich"], default="center")
    p.add_argument("--t", type=float, default=2.0, help="clip time of the reference frame (i300 clip)")
    k = sub.add_parser("pick")
    k.add_argument("--camera", choices=["center", "zarich"], default="center")
    k.add_argument("--out", type=Path, default=OUT, help="folder for <camera>_gates_redo.json "
                                                        "(default revision/perception/setup_redo)")
    c = sub.add_parser("compare")
    c.add_argument("--camera", choices=["center", "zarich"], default="center")
    c.add_argument("--gates", help="(testing) another redo file")
    c.add_argument("--out", type=Path, default=OUT, help="folder for <camera>_compare.md and _compare_counts.csv "
                                                         "(default revision/perception/setup_redo)")
    c.add_argument("--manual-dir", type=Path, default=pc.OUT / "manual_counts",
                   help="(testing) folder of the blind counts whose FINAL.json must close the camera's clip")
    a = ap.parse_args()
    {"prepare": cmd_prepare, "pick": cmd_pick, "compare": cmd_compare}[a.cmd](a)


if __name__ == "__main__":
    main()
