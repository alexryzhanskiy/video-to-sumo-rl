"""Blind manual counting of 5-min clips (Comment 1.3): one key per approach x movement. The sample is one clip per
camera, all four approaches (decision C-3, 1 Nov 2026); since 3 Nov 2026 (decision C-13) the two i300 clips,
center_i300 and zarich_i300 (pc.COUNT_CLIPS); status and export use these two clips unless --clips names others.

The app never reads or shows the pipeline's counts. It shows the raw clip, the pipeline's stop lines of the counted
approaches (for orientation: count a vehicle when it crosses this line), and the counter's own counts.

    revision/.venv/Scripts/python.exe revision/tools/perception_count.py count --clip center_i300
    revision/.venv/Scripts/python.exe revision/tools/perception_count.py count --clip center_i300 --approach SVB_N
    revision/.venv/Scripts/python.exe revision/tools/perception_count.py status
    revision/.venv/Scripts/python.exe revision/tools/perception_count.py export [--final]

Keys (window must have focus; digits, arrows, Space, Backspace, Delete and Esc work in any keyboard layout):
    a pass of one approach (--approach X)   1 left  2 through  3 right  4 U-turn, for either approach
                                            (since 3 Nov 2026; 7-0 still work for the camera's second approach)
    both approaches at once                 first approach 1-4 as above, second approach 7 left  8 through
                                            9 right  0 U-turn
    Space play/pause, Left/Right -/+ 2 s, Down/Up -/+ 10 s, Home start, comma/period one frame (paused),
    minus/equals speed 0.5x/1x/2x, Backspace undo last key, Delete delete the last event before the playhead,
    Tab mark the last event unsure, G (or End) jump to 2 s before the next unwatched second, H help on/off,
    Esc save and quit. Backspace, Delete and Tab act only on the approaches of the current pass (since 3 Nov 2026:
    before that they could remove or mark a count of the other approach of the same clip).

Every key press is saved at once to revision/perception/manual_counts/<clip>/events.csv (one row per event, with
clip time, t_common and frame), so the app can be closed and reopened at any time; it resumes where it stopped.
`export` writes revision/perception/manual_counts/1.3_manual_counts.csv in the layout of the 1.3 template
(manual_count filled, pipeline_count left empty) plus all events; `--final` also writes FINAL.json, which closes the
blind phase for the exported clips only: their names, the watched share per approach and the SHA-256 of their event
files and of both export files. It refuses if an approach of these clips was watched less than 99% (--force
overrides; the warning is then kept in FINAL.json).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import perception_common as pc  # noqa: E402

OUTDIR = pc.OUT / "manual_counts"
MOVES = ["L", "T", "R", "U"]
MOVE_NAME = {"L": "left", "T": "through", "R": "right", "U": "U-turn"}
KEYS = {0: {ord("1"): "L", ord("2"): "T", ord("3"): "R", ord("4"): "U"},
        1: {ord("7"): "L", ord("8"): "T", ord("9"): "R", ord("0"): "U"}}
KEYLAB = {0: "1 left  2 through  3 right  4 U-turn", 1: "7 left  8 through  9 right  0 U-turn"}
COL = {0: (0, 200, 255), 1: (255, 160, 0)}          # BGR: orange-yellow, blue
SPEEDS = [0.5, 1.0, 2.0]
FIELDS = ["event_id", "clip", "camera", "interval", "approach", "movement", "t_clip_s", "t_common_s", "frame",
          "speed", "unsure", "deleted", "created", "deleted_at", "session"]


class Counter:
    def __init__(self, clip: pc.Clip, approaches: list[str], speed: float, max_w: int, max_h: int, ui: float = 1.0,
                 script: list | None = None, snapshot: Path | None = None):
        self.clip, self.appr = clip, approaches
        self.cam_appr = pc.OWNED[clip.camera]
        self.active = [self.cam_appr.index(a) for a in approaches]
        # a pass of one approach counts with 1-4 whichever approach it is (7-0 still work for the second one)
        self.solo = len(self.active) == 1
        self.keys = {ai: ({**KEYS[ai], **KEYS[0]} if self.solo else KEYS[ai]) for ai in self.active}
        self.dir = OUTDIR / clip.name
        self.dir.mkdir(parents=True, exist_ok=True)
        self.ev_path, self.st_path = self.dir / "events.csv", self.dir / "state.json"
        self.events = pc.read_csv(self.ev_path)
        self.state = json.loads(self.st_path.read_text(encoding="utf-8")) if self.st_path.exists() else {}
        self.state.setdefault("clip", clip.name)
        self.state["video"] = pc.posix(clip.raw_path())
        self.state.setdefault("sessions", [])
        self.state.setdefault("coverage", {})            # approach -> list of watched 1-s bins
        self.cov = {a: set(self.state["coverage"].get(a, [])) for a in self.cam_appr}
        self.player = pc.Player(clip.raw_path(), cache=25)
        self.fps = self.player.fps
        self.pos = int(self.state.get("position", 0))
        self.speed = speed
        self.playing = False
        self.help = True
        self.flash, self.flash_until = "", 0.0
        self.session = time.strftime("%Y%m%d-%H%M%S")
        self.sess_start = time.time()
        self.script, self.snapshot = script, snapshot
        s = clip.raw_path()
        cap = cv2.VideoCapture(str(s))
        w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()
        self.fs = max(0.45, 0.4 * ui)                     # font scale and line height of the text strip
        self.lh = int(43 * self.fs)
        self.strip = self.lh * (4 + len(self.active)) + 34
        self.disp = pc.fit_size(w, h, max_w, max_h - self.strip)
        self.scale = self.disp[0] / pc.RAW_W
        self.gates = [(g["label"], (pc.gate_polyline_raw(g, clip.camera) * self.scale).astype(np.int32))
                      for g in pc.load_gates(clip.camera) if g["role"] == "stop" and g["label"] in approaches]
        self.win = f"Blind count - {clip.name} - {' + '.join(approaches)}"

    # ---------------------------------------------------------------- events
    def live(self):
        return [e for e in self.events if e["deleted"] != "1"]

    def mine(self):
        """Live events of the approaches counted in this pass; undo, delete, unsure and the playhead line use these."""
        names = {self.cam_appr[ai] for ai in self.active}
        return [e for e in self.live() if e["approach"] in names]

    def save(self):
        pc.write_csv(self.ev_path, self.events, FIELDS)

    def save_state(self):
        self.state["position"] = self.pos
        self.state["coverage"] = {a: sorted(v) for a, v in self.cov.items()}
        pc.write_json(self.st_path, self.state)

    def add(self, ai: int, mv: str):
        a = self.cam_appr[ai]
        t = self.pos / self.fps
        eid = 1 + max((int(e["event_id"]) for e in self.events), default=0)
        self.events.append(dict(event_id=eid, clip=self.clip.name, camera=self.clip.camera,
                                interval=self.clip.interval, approach=a, movement=mv, t_clip_s=f"{t:.3f}",
                                t_common_s=f"{self.clip.t0 + t:.3f}", frame=self.pos, speed=self.speed, unsure=0,
                                deleted=0, created=pc.now_iso(), deleted_at="", session=self.session))
        self.save()
        self.say(f"+ #{eid} {a} {MOVE_NAME[mv]} at {t:.1f} s")

    def undo(self):
        lv = self.mine()
        if not lv:
            return self.say("nothing to undo")
        e = max(lv, key=lambda x: (x["created"], int(x["event_id"])))
        self._delete(e)

    def delete_before(self):
        t = self.pos / self.fps
        lv = [e for e in self.mine() if float(e["t_clip_s"]) <= t + 1e-6 and t - float(e["t_clip_s"]) <= 10]
        if not lv:
            return self.say("no event in the last 10 s before the playhead")
        self._delete(max(lv, key=lambda x: float(x["t_clip_s"])))

    def _delete(self, e):
        e["deleted"], e["deleted_at"] = "1", pc.now_iso()
        self.save()
        self.say(f"deleted #{e['event_id']} {e['approach']} {MOVE_NAME[e['movement']]} at {float(e['t_clip_s']):.1f} s")

    def mark_unsure(self):
        lv = self.mine()
        if not lv:
            return
        e = max(lv, key=lambda x: (x["created"], int(x["event_id"])))
        e["unsure"] = "0" if str(e["unsure"]) == "1" else "1"
        self.save()
        self.say(f"#{e['event_id']} unsure = {e['unsure']}")

    def next_gap(self):
        """Jump to 2 s before the next second that an approach of this pass has not watched (paused)."""
        t = int(self.pos / self.fps)
        miss = sorted(b for b in range(300) if any(b not in self.cov[self.cam_appr[ai]] for ai in self.active))
        if not miss:
            return self.say("every second of this pass is watched")
        b = next((x for x in miss if x > t), miss[0])
        self.playing = False
        self.seek(max(0, b - 2) * self.fps)
        self.say(f"unwatched second at {b} s ({len(miss)} left): press Space to play through it")

    def say(self, msg):
        self.flash, self.flash_until = msg, time.time() + 2.5
        print(msg, flush=True)

    # ---------------------------------------------------------------- drawing
    def render(self):
        W, H = self.disp
        canvas = np.zeros((H + self.strip, W, 3), np.uint8)
        canvas[:H] = cv2.resize(self.player.read(self.pos), self.disp, interpolation=cv2.INTER_AREA)
        for lab, poly in self.gates:
            cv2.polylines(canvas, [poly], False, (0, 0, 255), 2, cv2.LINE_AA)
            p = poly[len(poly) // 2]
            for col, th in (((0, 0, 0), 3), ((80, 80, 255), 1)):
                cv2.putText(canvas, f"{lab} stop line", (int(p[0]) - 40, int(p[1]) - 10), cv2.FONT_HERSHEY_SIMPLEX,
                            self.fs, col, th, cv2.LINE_AA)
        t = self.pos / self.fps
        lv = self.live()
        lines = [(f"{self.clip.name}   t_clip {t:6.1f} s   t_common {self.clip.t0 + t:7.1f} s   "
                  f"{'PLAY' if self.playing else 'PAUSED'} {self.speed:g}x", (255, 255, 255))]
        for ai in self.active:
            a = self.cam_appr[ai]
            n = {m: sum(e["approach"] == a and e["movement"] == m for e in lv) for m in MOVES}
            lines.append((f"{a}   keys {KEYLAB[0 if self.solo else ai]}      counted: " + "  ".join(f"{MOVE_NAME[m]} {n[m]}" for m in MOVES)
                          + f"   (watched {len(self.cov[a]) / 3:.0f}%)", COL[ai]))
        if self.help:
            lines += ["Count when the vehicle crosses its stop line (red) and its movement is clear.   Space play/pause"
                      "   Left/Right 2 s   Down/Up 10 s   , . one frame   - = speed",
                      "Backspace undo last   Delete last event before playhead   Tab mark unsure   G next unwatched   "
                      "H hide help   Esc save + quit"]
        else:
            lines += ["", ""]
        near = [e for e in sorted(self.mine(), key=lambda x: float(x["t_clip_s"])) if abs(float(e["t_clip_s"]) - t) <= 6]
        msg = "  ".join(f"{e['approach']} {MOVE_NAME[e['movement']]} {float(e['t_clip_s']):.1f}s"
                        + ("?" if str(e["unsure"]) == "1" else "") for e in near[-5:])
        lines.append((("last: " + self.flash) if time.time() < self.flash_until else
                      (("near playhead: " + msg) if msg else ""), (80, 255, 80)))
        pc.put_lines(canvas, lines, (0, H + 2), scale=self.fs, alpha=0.0, lh=self.lh)
        # timeline: grey = watched, ticks = own events, white = playhead
        y0 = H + self.strip - 26
        cv2.rectangle(canvas, (0, y0), (W, H + self.strip), (40, 40, 40), -1)
        for ai in self.active:
            a = self.cam_appr[ai]
            yy = y0 + 4 + 12 * self.active.index(ai)
            for b in self.cov[a]:
                x = int(b / 300 * W)
                cv2.line(canvas, (x, yy), (x + max(1, W // 300), yy), (110, 110, 110), 3)
        for e in lv:
            ai = self.cam_appr.index(e["approach"])
            if ai in self.active:
                x = int(float(e["t_clip_s"]) / 300 * W)
                yy = y0 + 8 + 12 * self.active.index(ai)
                cv2.line(canvas, (x, yy), (x, yy + 8), COL[ai], 1)
        x = int(t / 300 * W)
        cv2.line(canvas, (x, y0), (x, H + self.strip), (255, 255, 255), 2)
        return canvas

    # ---------------------------------------------------------------- loop
    def seek(self, frame):
        self.pos = int(min(max(frame, 0), self.player.n - 1))
        self.t_start, self.f_start = time.time(), self.pos
        self.sim_reset = True

    def handle(self, k) -> bool:
        if k == -1:
            return True
        for ai in self.active:
            if k in self.keys[ai]:
                self.add(ai, self.keys[ai][k])
                return True
        for ai in (0, 1):
            if ai not in self.active and k in KEYS[ai]:
                self.say(f"{self.cam_appr[ai]} is not counted in this pass")
                return True
        if k == pc.K_ESC or k == ord("q"):
            return False
        if k == pc.K_SPACE:
            self.playing = not self.playing
            self.seek(self.pos)
        elif k == pc.K_LEFT:
            self.seek(self.pos - 2 * self.fps)
        elif k == pc.K_RIGHT:
            self.seek(self.pos + 2 * self.fps)
        elif k == pc.K_DOWN or k == pc.K_PGDN:
            self.seek(self.pos - 10 * self.fps)
        elif k == pc.K_UP or k == pc.K_PGUP:
            self.seek(self.pos + 10 * self.fps)
        elif k == pc.K_HOME:
            self.seek(0)
        elif k == ord(","):
            self.playing = False
            self.seek(self.pos - 1)
        elif k == ord("."):
            self.playing = False
            self.seek(self.pos + 1)
            self.watch(self.pos)
        elif k in (ord("-"), ord("_")):
            self.speed = SPEEDS[max(0, SPEEDS.index(self.speed) - 1)]
            self.seek(self.pos)
            self.say(f"speed {self.speed:g}x")
        elif k in (ord("="), ord("+")):
            self.speed = SPEEDS[min(len(SPEEDS) - 1, SPEEDS.index(self.speed) + 1)]
            self.seek(self.pos)
            self.say(f"speed {self.speed:g}x")
        elif k == pc.K_BACK or k == ord("z"):
            self.undo()
        elif k == pc.K_DEL or k == ord("x"):
            self.delete_before()
        elif k == pc.K_TAB or k == ord("u"):
            self.mark_unsure()
        elif k == ord("g") or k == pc.K_END:
            self.next_gap()
        elif k == ord("h"):
            self.help = not self.help
        elif k == ord("?") or k == 63:
            self.say("letter keys may not work in this keyboard layout: use digits, arrows, Space, Tab, Esc")
        return True

    def watch(self, frame):
        b = int(frame / self.fps)
        for ai in self.active:
            self.cov[self.cam_appr[ai]].add(min(b, 299))

    def run(self):
        headless = self.script is not None
        if not headless:
            cv2.namedWindow(self.win, cv2.WINDOW_AUTOSIZE)
        self.seek(self.pos)
        smoke = getattr(self, "smoke", 0)
        if smoke:
            self.playing, t_smoke, f_smoke = True, time.time(), self.pos
        last_save = time.time()
        sim_t = 0.0
        step = 0
        while True:
            if getattr(self, "sim_reset", False):
                sim_t, self.sim_reset = 0.0, False
            if self.playing:
                if headless:                  # one loop step = 1/fps of simulated time
                    sim_t += 1 / self.fps
                    due = self.f_start + int(sim_t * self.fps * self.speed + 1e-9)
                else:
                    due = self.f_start + int((time.time() - self.t_start) * self.fps * self.speed)
                if due > self.pos:
                    for f in range(self.pos + 1, due + 1):
                        self.watch(f)
                    self.pos = min(due, self.player.n - 1)
                    if self.pos >= self.player.n - 1:
                        self.playing = False
                        self.say("end of clip")
            img = self.render()
            if headless:
                if step >= len(self.script):
                    break
                k = self.script[step]
                step += 1
                if k == "snap" and self.snapshot:
                    cv2.imwrite(str(self.snapshot), img)
                    continue
                if not self.handle(k):
                    break
            else:
                cv2.imshow(self.win, img)
                k = pc.read_key(int(1000 / (self.fps * self.speed)) if self.playing else 30)
                if not self.handle(k) or pc.window_closed(self.win):
                    break
            if smoke and time.time() - t_smoke > smoke:
                el = time.time() - t_smoke
                print(f"smoke test: {self.pos - f_smoke} frames in {el:.1f} s = {(self.pos - f_smoke) / el:.1f} "
                      f"video frames/s at {self.speed:g}x (target {self.fps * self.speed:.0f}); window {self.disp}")
                break
            if time.time() - last_save > 5:
                self.save_state()
                last_save = time.time()
        self.state["sessions"].append(dict(session=self.session, approaches=self.appr, start=time.strftime(
            "%Y-%m-%dT%H:%M:%S", time.localtime(self.sess_start)), end=pc.now_iso(),
            seconds=round(time.time() - self.sess_start, 1), headless=headless))
        self.save_state()
        if not headless:
            cv2.destroyAllWindows()
        print(f"saved {len(self.live())} events to {self.ev_path}")


# ---------------------------------------------------------------- status and export
def summary(clips=None):
    rows = []
    for clip in clips or pc.COUNT_CLIPS:
        d = OUTDIR / clip.name
        ev = [e for e in pc.read_csv(d / "events.csv") if e["deleted"] != "1"]
        st = json.loads((d / "state.json").read_text(encoding="utf-8")) if (d / "state.json").exists() else {}
        for a in pc.OWNED[clip.camera]:
            cov = len(st.get("coverage", {}).get(a, []))
            n = {m: sum(e["approach"] == a and e["movement"] == m for e in ev) for m in MOVES}
            rows.append(dict(clip=clip.name, approach=a, coverage_pct=round(cov / 3, 1), events=sum(n.values()),
                             unsure=sum(e["approach"] == a and str(e["unsure"]) == "1" for e in ev),
                             minutes=round(sum(s["seconds"] for s in st.get("sessions", []) if not s.get("headless")
                                               and a in s["approaches"]) / 60, 1), **n))
    return rows


def cmd_status(_):
    # the counting sample, plus any other clip that already has events (nothing is hidden)
    extra = [c for c in pc.CLIPS if c not in pc.COUNT_CLIPS and (OUTDIR / c.name / "events.csv").exists()]
    for r in summary(pc.COUNT_CLIPS + extra):
        print(f"{r['clip']:12} {r['approach']}: watched {r['coverage_pct']:5.1f}%  events {r['events']:3d} "
              f"(L {r['L']} T {r['T']} R {r['R']} U {r['U']}; unsure {r['unsure']})  time in app {r['minutes']} min")
        st = OUTDIR / r["clip"] / "state.json"
        cov = set(json.loads(st.read_text(encoding="utf-8")).get("coverage", {}).get(r["approach"], [])) \
            if st.exists() else set()
        miss = [b for b in range(300) if b not in cov]
        if cov and miss:
            print(f"{'':12} {'':5}  not watched yet (s): {', '.join(map(str, miss[:30]))}"
                  f"{' ...' if len(miss) > 30 else ''}  -> open the pass and press G")
    if extra:
        print(f"note: {[c.name for c in extra]} are not in the counting sample; export --final closes "
              f"{[c.name for c in pc.COUNT_CLIPS]} unless --clips says otherwise")
    fin = pc.final_clips(OUTDIR)
    print(f"blind phase: closed for {sorted(fin)}" if fin else "blind phase: open (no FINAL.json)")


def cmd_export(a):
    rows, allev, warn = [], [], []
    clips = [pc.clip_by_name(n) for n in a.clips] if a.clips else pc.COUNT_CLIPS
    summ = {(r["clip"], r["approach"]): r for r in summary(clips)}
    for clip in clips:
        ev = pc.read_csv(OUTDIR / clip.name / "events.csv")
        allev += ev
        for ap in pc.OWNED[clip.camera]:
            s = summ[(clip.name, ap)]
            if s["coverage_pct"] < 99:
                warn.append(f"{clip.name} {ap}: only {s['coverage_pct']}% of the clip watched")
            for m in MOVES:
                rows.append(dict(camera=clip.camera, interval_start_video_s=f"{clip.t0:.1f}",
                                 interval_end_video_s=f"{clip.t0 + pc.CLIP_LEN:.1f}", approach=ap, movement=m,
                                 manual_count=s[m] if s["coverage_pct"] > 0 else "", pipeline_count="",
                                 note=f"blind manual count ({a.counter}) with perception_count.py on clip "
                                      f"{clip.stem}.mp4; window t_common [{clip.t0:.0f},{clip.t0 + 300:.0f}) s "
                                      f"(times are t_common, not camera-local); unsure {s['unsure']}; "
                                      f"watched {s['coverage_pct']}%"))
    head = ["camera", "interval_start_video_s", "interval_end_video_s", "approach", "movement", "manual_count",
            "pipeline_count", "note"]
    pc.write_csv(OUTDIR / "1.3_manual_counts.csv", rows, head)
    pc.write_csv(OUTDIR / "1.3_manual_counts_events.csv", allev, FIELDS)
    print(f"wrote {OUTDIR / '1.3_manual_counts.csv'} and 1.3_manual_counts_events.csv ({len(allev)} rows)")
    for w in warn:
        print("WARNING:", w)
    if a.final:
        if warn and not a.force:
            raise SystemExit("not final: some approaches are not fully watched (use --force to override)")
        if (OUTDIR / "FINAL.json").exists():
            print("NOTE: FINAL.json existed and is replaced:", pc.read_json(OUTDIR / "FINAL.json").get("finalized"))
        fin = dict(finalized=pc.now_iso(), counter=a.counter, clips=[c.name for c in clips],
                   clip_set="decision C-3 (1 Nov 2026)" if clips == pc.COUNT_CLIPS else "given with --clips",
                   watched_pct={f"{c} {ap}": s["coverage_pct"] for (c, ap), s in summ.items()}, warnings=warn, files={
            p.relative_to(OUTDIR).as_posix(): pc.sha256(p)
            for p in [OUTDIR / c.name / "events.csv" for c in clips if (OUTDIR / c.name / "events.csv").exists()]
            + [OUTDIR / "1.3_manual_counts.csv", OUTDIR / "1.3_manual_counts_events.csv"]})
        pc.write_json(OUTDIR / "FINAL.json", fin)
        print(f"blind phase closed for {fin['clips']}:", OUTDIR / "FINAL.json")


def main():
    global OUTDIR
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out-dir", type=Path, default=OUTDIR, help="output folder (default revision/perception/manual_counts)")
    ap.add_argument("--clip-dir", type=Path, help="folder with the raw clips <camera>_<interval>_common<a>-<b>s.mp4 "
                                                  "(default: the incoming folders of this repository)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("count", help="count one clip")
    c.add_argument("--clip", required=True, help="center_i300 or zarich_i300 (the counting sample since 3 Nov, C-13)")
    c.add_argument("--approach", nargs="+", help="approaches to count in this pass (default: both of the camera)")
    c.add_argument("--speed", type=float, default=1.0, choices=SPEEDS)
    c.add_argument("--max-width", type=int, default=0, help="window width limit in pixels (default: screen)")
    c.add_argument("--test-script", help="(testing) comma-separated keys, run without a window")
    c.add_argument("--snapshot", type=Path, help="(testing) write the rendered frame at the 'snap' step")
    c.add_argument("--smoke", type=float, default=0, help="(testing) play N seconds in a real window, then quit")
    sub.add_parser("status", help="progress per clip and approach")
    e = sub.add_parser("export", help="write 1.3_manual_counts.csv")
    e.add_argument("--final", action="store_true", help="close the blind phase (writes FINAL.json)")
    e.add_argument("--force", action="store_true")
    e.add_argument("--clips", nargs="+", help="export these clips (default: center_i300 zarich_i300)")
    e.add_argument("--counter", default="A1", help="name or initials of the counter, written into the notes")
    a = ap.parse_args()
    OUTDIR = a.out_dir
    pc.CLIP_DIR = a.clip_dir
    if a.cmd == "status":
        return cmd_status(a)
    if a.cmd == "export":
        return cmd_export(a)
    clip = pc.clip_by_name(a.clip)
    appr = a.approach or pc.OWNED[clip.camera]
    bad = [x for x in appr if x not in pc.OWNED[clip.camera]]
    if bad:
        raise SystemExit(f"{bad} not owned by {clip.camera}; owned: {pc.OWNED[clip.camera]}")
    if (OUTDIR / "FINAL.json").exists():
        print("NOTE: the blind phase was closed (FINAL.json); new events are still saved but not in the final export")
    if clip not in pc.COUNT_CLIPS:
        print(f"NOTE: {clip.name} is not in the counting sample {[c.name for c in pc.COUNT_CLIPS]} (decision C-3)")
    sw, sh, ui = pc.screen_size()
    max_w = a.max_width or sw - 20
    script = None
    if a.test_script:
        names = {"space": pc.K_SPACE, "left": pc.K_LEFT, "right": pc.K_RIGHT, "up": pc.K_UP, "down": pc.K_DOWN,
                 "back": pc.K_BACK, "del": pc.K_DEL, "tab": pc.K_TAB, "esc": pc.K_ESC, "none": -1, "snap": "snap"}
        script = []
        for tok in a.test_script.split(","):
            tok = tok.strip()
            if tok.startswith("wait"):                    # waitN = N idle loop steps
                script += [-1] * int(tok[4:])
            else:
                script.append(names.get(tok, ord(tok) if len(tok) == 1 else -1))
    app = Counter(clip, appr, a.speed, max_w, sh, ui, script, a.snapshot)
    app.smoke = a.smoke
    app.run()


if __name__ == "__main__":
    main()
