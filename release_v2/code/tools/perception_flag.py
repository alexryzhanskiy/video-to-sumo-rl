"""Tracking review for Comment 1.3: candidate ID switches, track fragments, missed and double counts, cross-camera
duplicates, and a blind check of the exits inferred from the heading. The reviewer only confirms or rejects events.

    revision/.venv/Scripts/python.exe revision/tools/perception_flag.py build --interval i300
    revision/.venv/Scripts/python.exe revision/tools/perception_flag.py review --clip center_i300
    revision/.venv/Scripts/python.exe revision/tools/perception_flag.py status

`build` reads the tracker output (tracks_<camera>_undist.csv), the pipeline's movements, the gates and, if the blind
counts of the clip are final (manual_counts/FINAL.json lists it), the hand-count events; it writes, per clip,
revision/perception/tracking_review/<clip>/candidates.csv. Candidate rules (all thresholds are constants below):

  break   track A ends and track B starts 1-12 tracker frames (<= 1.44 s) later, B's first box centre within
          max(40 px, 0.6 x A's box diagonal) of A's position extrapolated with A's last velocity, box areas within
          x0.4-2.5; A or B is a counted track (a movement of this camera); greedy one-to-one.
          Question: same vehicle? (yes = a new ID for the same vehicle: fragment or ID switch).
  jump    inside one relevant track, a step longer than max(25 px, half the box diagonal, 3 x the track's median step)
          with the box area changing by more than x1.6: the ID moved to another object (ID switch).
  uncounted  a track that entered through an owned stop gate but ended inside the junction box (not counted by the
          pipeline), or a track first seen within 200 px past an owned stop gate that moves > 150 px into the junction
          without an entry crossing: was this vehicle counted (under another ID)?
  manual_only / pipeline_only   (only after FINAL.json) hand-count events with no pipeline count of the same approach
          within -2..+6 s, and pipeline counts with no hand count (optimal one-to-one matching). For a pipeline-only
          count the reviewer says whether it is a double count (same camera, or a vehicle the other camera counted:
          the cross-camera duplicates), a false count, or a real vehicle the hand count missed.
  movement  every counted movement with a heading-fallback exit, plus 10 gate-exit movements per clip (seeded
          control sample): the reviewer says on the RAW clip which way the highlighted vehicle went, without seeing
          the pipeline's answer.
  vehicle   8 counted vehicles per clip whose tracks have no candidate (seeded sample): the reviewer follows each one
          from entry to exit, to estimate the ID changes and double counts the rules miss.

`review` shows the candidates one by one: movement checks first on the raw clip (blind), then the overlay clip for the
other events and the vehicle sample. Answers are saved after every key to <clip>/review.csv.
Keys (shown on screen): break/jump 1 yes 2 no 3 cannot tell; movement 1 left 2 through 3 right 4 U-turn 5 cannot tell;
uncounted 1 missed 2 counted under another ID 3 cannot tell 4 not a vehicle of this approach; manual_only 1 pipeline
missed it 2 no vehicle 3 cannot tell 4 pipeline counted it; pipeline_only 1 double count (same camera) 2 real vehicle
3 cannot tell 4 false count 5 double count (other camera); vehicle 1 ID changed 2 no problem 3 cannot tell 4 counted
twice. Boxes: A magenta, B cyan; dashed = the track is not present at this moment (nearest box shown). Space pause/play, Left/Right one step, R replay,
- = speed, PageUp/PageDown previous/next candidate, Esc save and quit.
"""
from __future__ import annotations

import argparse
import random
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import perception_common as pc  # noqa: E402

OUTDIR = pc.OUT / "tracking_review"
MANUAL_DIR = pc.OUT / "manual_counts"
SEED = 20261101
BREAK_MAX_GAP, BREAK_MIN_D, BREAK_DIAG = 12, 40.0, 0.6
AREA_LO, AREA_HI = 0.4, 2.5
NEAR_GATE = 250.0
JUMP_MIN, JUMP_AREA = 25.0, 1.6
START_PAST, START_MOVE = 200.0, 150.0
MATCH_LO, MATCH_HI = -2.0, 6.0
N_CONTROL, N_SAMPLE = 10, 8
MAX_SEG = 12.0                     # longest segment shown for one candidate (s)
CACHE = 160                        # decoded display frames kept per candidate (about 0.5 GB at 1350 px)
FIELDS = ["cand_id", "clip", "type", "t_clip", "t_end", "t_common", "track_a", "track_b", "approach", "detail",
          "question", "pipeline_movement", "method"]


# ---------------------------------------------------------------- geometry helpers
def seg_dist(p, a, b):
    ab = b - a
    t = np.clip(((p - a) @ ab) / (ab @ ab + 1e-9), 0, 1)
    return np.linalg.norm(p - (a + t[..., None] * ab), axis=-1) if p.ndim > 1 else float(np.linalg.norm(p - (a + t * ab)))


def centre(box):
    return np.stack([(box[:, 0] + box[:, 2]) / 2, (box[:, 1] + box[:, 3]) / 2], axis=1)


def area(b):
    return max(1.0, (b[2] - b[0]) * (b[3] - b[1]))


def diag(b):
    return float(np.hypot(b[2] - b[0], b[3] - b[1]))


def match_manual(manual: list[dict], pipe: list[dict], lo=MATCH_LO, hi=MATCH_HI):
    """Optimal one-to-one matching per approach of hand-count events (press time) to pipeline counts (stop-line
    crossing time, t_common): allowed lag press - crossing in [lo, hi] s, cost |lag - 1 s|. Returns (pairs,
    unmatched manual, unmatched pipeline)."""
    from scipy.optimize import linear_sum_assignment
    pairs, um, up = [], [], []
    for a in sorted({m["approach"] for m in manual} | {p["entry"] for p in pipe}):
        M = [m for m in manual if m["approach"] == a]
        P = [p for p in pipe if p["entry"] == a]
        if not M or not P:
            um += M
            up += P
            continue
        lag = np.array([[float(m["t_common_s"]) - p["t_common"] for p in P] for m in M])
        cost = np.where((lag >= lo) & (lag <= hi), np.abs(lag - 1.0), 1e6)
        r, c = linear_sum_assignment(cost)
        ok = {(i, j) for i, j in zip(r, c) if cost[i, j] < 1e6}
        pairs += [(M[i], P[j]) for i, j in ok]
        um += [M[i] for i in range(len(M)) if i not in {x for x, _ in ok}]
        up += [P[j] for j in range(len(P)) if j not in {y for _, y in ok}]
    return pairs, um, up


# ---------------------------------------------------------------- build
def build_clip(clip: pc.Clip, manual: list[dict] | None):
    cam = clip.camera
    gates = pc.load_gates(cam)
    tracks = pc.load_tracks(cam)
    _, status = pc.classify(tracks, gates)
    moves = pc.load_movements(cam)
    k0, k1 = clip.k_at(0), clip.k_at(pc.CLIP_LEN)
    win = {t: tr for t, tr in tracks.items() if tr["k"][-1] >= k0 - 5 and tr["k"][0] <= k1 + 5}
    allpts = np.array([p for g in gates for p in g["points"]], float)
    box_c = allpts.mean(axis=0)
    owned_stops = [(g["label"], np.array(g["points"], float)) for g in gates if g["role"] == "stop" and g["label"] in pc.OWNED[cam]]
    counted = {m["track_id"]: m for m in moves}

    def near_gate(tr):
        d = min(seg_dist(tr["cu"], p[0], p[1]).min() for _, p in owned_stops)
        return d < NEAR_GATE

    relevant = {t for t, tr in win.items() if t in counted or (len(tr["k"]) >= 3 and near_gate(tr))}
    tc = lambda k: clip.t_clip_of_k(k)                                    # noqa: E731
    inside = lambda k: 0 <= tc(k) < pc.CLIP_LEN                          # noqa: E731
    cands = []

    def add(typ, k_a, k_b, a=None, b=None, appr="", detail="", q="", mv="", method=""):
        cands.append(dict(clip=clip.name, type=typ, t_clip=round(tc(k_a), 2), t_end=round(tc(k_b), 2),
                          t_common=round(clip.t0 + tc(k_a), 2), track_a=a if a is not None else "",
                          track_b=b if b is not None else "", approach=appr, detail=detail, question=q,
                          pipeline_movement=mv, method=method))

    # break: A ends, B starts shortly after nearby
    ends = sorted(((tr["k"][-1], t) for t, tr in win.items() if len(tr["k"]) >= 2), key=lambda x: x[0])
    starts = {}
    for t, tr in win.items():
        starts.setdefault(int(tr["k"][0]), []).append(t)
    pairs = []
    for ke, ta in ends:
        A = win[ta]
        c = centre(A["box"][-3:])
        v = (c[-1] - c[0]) / max(1, A["k"][-1] - A["k"][-min(3, len(A["k"]))]) if len(c) > 1 else np.zeros(2)
        for g in range(1, BREAK_MAX_GAP + 1):
            for tb in starts.get(int(ke) + g, []):
                if tb == ta or (ta not in counted and tb not in counted):
                    continue
                B = win[tb]
                pred = c[-1] + v * g
                d = float(np.linalg.norm(centre(B["box"][:1])[0] - pred))
                ar = area(B["box"][0]) / area(A["box"][-1])
                if d < max(BREAK_MIN_D, BREAK_DIAG * diag(A["box"][-1])) and AREA_LO <= ar <= AREA_HI:
                    pairs.append((d, ta, tb, ke, B["k"][0]))
    used_a, used_b = set(), set()
    for d, ta, tb, ke, ks in sorted(pairs):
        if ta in used_a or tb in used_b or not (inside(ke) or inside(ks)):
            continue
        used_a.add(ta)
        used_b.add(tb)
        both = ta in counted and tb in counted
        typ = "break_double" if both else "break"
        info = "; ".join(f"{x}: {counted[x]['entry']}->{counted[x]['exit']}" for x in (ta, tb) if x in counted) or "neither counted"
        add(typ, ke - 8, ks + 8, ta, tb, detail=f"gap {ks - ke} frames, {d:.0f} px; {info}",
            q=("Are A and B the same vehicle? Both were counted (double count?)" if both else
               "Are A and B the same vehicle (a new ID for one vehicle)?"))
    # jump inside a track
    for t in relevant:
        tr = win[t]
        if len(tr["k"]) < 4:
            continue
        c = centre(tr["box"])
        step = np.linalg.norm(np.diff(c, axis=0), axis=1)
        dk = np.diff(tr["k"])
        med = float(np.median(step))
        for i in np.where(dk <= 2)[0]:
            ar = area(tr["box"][i + 1]) / area(tr["box"][i])
            if step[i] > max(JUMP_MIN, 0.5 * diag(tr["box"][i]), 3 * med) and (ar > JUMP_AREA or ar < 1 / JUMP_AREA) \
                    and inside(tr["k"][i]):
                add("jump", tr["k"][i] - 12, tr["k"][i] + 12, t, detail=f"step {step[i]:.0f} px, area x{ar:.2f}",
                    q="Does track A jump from one vehicle to another here (ID switch)?")
                break
    # uncounted vehicles near owned stop gates
    for t, tr in win.items():
        if t in counted or len(tr["k"]) < 3:
            continue
        p0 = tr["cu"][0]
        why = None
        if status.get(t) == "in_box":
            why = "entered through an owned stop gate but ended inside the junction"
        elif status.get(t) == "no_entry" and len(tr["k"]) >= 8:
            for lab, g in owned_stops:
                mid = g.mean(axis=0)
                if seg_dist(p0, g[0], g[1]) < START_PAST and (p0 - mid) @ (box_c - mid) > 0 \
                        and np.linalg.norm(tr["cu"][-1] - p0) > START_MOVE:
                    why = f"first seen just past the {lab} stop line"
                    break
        if why and inside(tr["k"][0]):
            add("uncounted", tr["k"][0] - 16, min(tr["k"][-1], tr["k"][0] + 40), t, detail=why,
                q="Box A was not counted. Was this vehicle counted under another ID (coloured label), or missed?")
    # hand count vs pipeline (only after the blind phase is closed)
    if manual is not None:
        mine = [dict(m, t_common=m["t_common"]) for m in moves if 0 <= m["t_common"] - clip.t0 < pc.CLIP_LEN]
        _, um, up = match_manual([e for e in manual if e["clip"] == clip.name], mine)
        for e in um:
            k = clip.k_at(float(e["t_clip_s"]))
            add("manual_only", k - 40, k + 16, appr=e["approach"],
                detail=f"hand count {e['approach']} {e['movement']} at {float(e['t_clip_s']):.1f} s (press time)",
                q="Your hand count here has no pipeline count nearby. Did the pipeline miss this vehicle?")
        for m in up:
            add("pipeline_only", m["k"] - 16, m["k"] + 24, m["track_id"], appr=m["entry"],
                detail=f"pipeline {m['entry']}->{m['exit']} ({m['method']})",
                q="Pipeline count (box A) with no hand count: double count, false count, or a real vehicle?")
    # movement checks (blind, raw clip): all heading exits + a control sample of gate exits
    rng = random.Random(f"{SEED}-{clip.name}")
    inwin = [m for m in moves if 0 <= m["t_common"] - clip.t0 < pc.CLIP_LEN and m["entry"] in pc.OWNED[cam]]
    head = [m for m in inwin if m["method"] == "heading"]
    gate = [m for m in inwin if m["method"] == "gate"]
    for m in head + rng.sample(gate, min(N_CONTROL, len(gate))):
        tr = tracks[m["track_id"]]
        add("movement", m["k"] - 8, tr["k"][-1] + 25, m["track_id"], appr=m["entry"],
            detail=f"exit by {m['method']}", q=f"Which way did the vehicle in box A (from {m['entry']}) go?",
            mv=pc.MOV_EN[m["movement"]], method=m["method"])
    # random sample of counted vehicles without any candidate (estimates what the rules miss)
    flagged = {int(c[x]) for c in cands if c["type"] != "movement" for x in ("track_a", "track_b") if c[x] != ""}
    clean = [m for m in inwin if m["track_id"] not in flagged]
    for m in sorted(rng.sample(clean, min(N_SAMPLE, len(clean))), key=lambda x: x["k"]):
        tr = tracks[m["track_id"]]
        add("vehicle", max(tr["k"][0], m["k"] - 50), min(tr["k"][-1], m["k"] + 50) + 8, m["track_id"], appr=m["entry"],
            detail=f"sampled counted vehicle ({len(clean)} unflagged of {len(inwin)})",
            q="Follow vehicle A. Did its ID change, or was it counted twice?")
    order = {"movement": 0, "break": 1, "break_double": 1, "jump": 1, "uncounted": 1, "manual_only": 1,
             "pipeline_only": 1, "vehicle": 2}
    cands.sort(key=lambda c: (order[c["type"]], c["t_clip"]))
    for i, c in enumerate(cands, 1):
        c["cand_id"] = i
    return cands, dict(counted_in_clip=len(inwin), relevant_tracks=len(relevant), window_tracks=len(win))


def cmd_build(a):
    clips = [pc.Clip(c, a.interval) for c in ("center", "zarich")] if a.interval else [pc.clip_by_name(x) for x in a.clip]
    manual, fin = None, pc.final_clips(MANUAL_DIR)
    if fin is not None:
        manual = [e for e in pc.read_csv(MANUAL_DIR / "1.3_manual_counts_events.csv") if e["deleted"] != "1"]
    elif not a.allow_unblind:
        print("NOTE: blind counts are not final (manual_counts/FINAL.json missing): no manual_only/pipeline_only "
              "candidates. Do the blind counts of these clips before reviewing their overlay clips.")
    for clip in clips:
        if fin is not None and clip.name not in fin:
            print(f"NOTE: {clip.name} is not closed by FINAL.json (closed: {sorted(fin)}): no manual_only/pipeline_only "
                  "candidates for it, and review needs --allow-unblind.")
        mine = manual if fin is not None and clip.name in fin else None
        cands, info = build_clip(clip, mine)
        d = OUTDIR / clip.name
        d.mkdir(parents=True, exist_ok=True)
        old = pc.read_csv(d / "review.csv")
        if old and not a.force:
            raise SystemExit(f"{d / 'review.csv'} exists (answers would no longer match); use --force to rebuild")
        pc.write_csv(d / "candidates.csv", cands, FIELDS)
        pc.write_json(d / "build_meta.json", dict(created=pc.now_iso(), seed=SEED, manual_final=mine is not None,
                                                  **info, constants=dict(
            BREAK_MAX_GAP=BREAK_MAX_GAP, BREAK_MIN_D=BREAK_MIN_D, BREAK_DIAG=BREAK_DIAG, AREA=[AREA_LO, AREA_HI],
            NEAR_GATE=NEAR_GATE, JUMP=[JUMP_MIN, JUMP_AREA], START=[START_PAST, START_MOVE],
            MATCH=[MATCH_LO, MATCH_HI], N_CONTROL=N_CONTROL, N_SAMPLE=N_SAMPLE)))
        from collections import Counter
        print(f"{clip.name}: {len(cands)} candidates {dict(Counter(c['type'] for c in cands))}; {info}")


# ---------------------------------------------------------------- review
REV_FIELDS = ["cand_id", "type", "answer", "seconds", "answered"]
ANS = {"movement": {ord("1"): "left", ord("2"): "through", ord("3"): "right", ord("4"): "U-turn", ord("5"): "cannot tell"},
       "pipeline_only": {ord("1"): "double count (same camera)", ord("2"): "real vehicle", ord("3"): "cannot tell",
                         ord("4"): "false count", ord("5"): "double count (other camera)"},
       "uncounted": {ord("1"): "missed (never counted)", ord("2"): "counted under another ID", ord("3"): "cannot tell",
                     ord("4"): "not a vehicle of this approach"},
       "manual_only": {ord("1"): "pipeline missed it", ord("2"): "no vehicle (my mistake)", ord("3"): "cannot tell",
                       ord("4"): "pipeline counted it (time off)"},
       "vehicle": {ord("1"): "ID changed or fragment", ord("2"): "no problem", ord("3"): "cannot tell",
                   ord("4"): "counted twice"},
       "default": {ord("1"): "yes", ord("2"): "no", ord("3"): "cannot tell"}}
KEYTXT = {t: "   ".join(f"{chr(k)} {v}" for k, v in m.items()) for t, m in ANS.items()}


class Reviewer:
    def __init__(self, clip: pc.Clip, max_w, max_h, ui, test=False):
        self.clip = clip
        self.d = OUTDIR / clip.name
        self.cands = pc.read_csv(self.d / "candidates.csv")
        if not self.cands:
            raise SystemExit(f"no candidates for {clip.name}: run build first")
        self.ans = {r["cand_id"]: r for r in pc.read_csv(self.d / "review.csv")}
        self.tracks = pc.load_tracks(clip.camera, clip.k_at(-5), clip.k_at(pc.CLIP_LEN + 5))
        self.players = {}
        self.max_w, self.max_h, self.fs = max_w, max_h, max(0.45, 0.4 * ui)
        self.lh = int(43 * self.fs)
        self.strip = self.lh * 5 + 8
        self.speed, self.win, self.test = 1.0, f"Tracking review - {clip.name}", test
        self.i = next((j for j, c in enumerate(self.cands) if c["cand_id"] not in self.ans), len(self.cands) - 1)
        self.load()

    def player(self, kind):
        if kind not in self.players:
            self.players[kind] = pc.Player(self.clip.raw_path() if kind == "raw" else self.clip.overlay_path(), cache=0)
        return self.players[kind]

    def load(self):
        c = self.cands[self.i]
        self.kind = "raw" if c["type"] == "movement" else "overlay"
        pl = self.player(self.kind)
        t0 = max(0.0, float(c["t_clip"]) - (1.0 if c["type"] == "movement" else 0.0))
        t1 = min(pc.CLIP_LEN - 0.01, float(c["t_end"]), t0 + MAX_SEG)
        f0, f1 = int(t0 * pl.fps), max(int(t0 * pl.fps) + 1, int(t1 * pl.fps))
        if self.kind == "raw":
            f0, f1 = f0 + pc.FRAME_OFFSET[self.clip.camera], f1 + pc.FRAME_OFFSET[self.clip.camera]
        w, h = int(pl.cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(pl.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.disp = pc.fit_size(w, h, self.max_w, self.max_h - self.strip)
        # frames are decoded lazily while playing and cached (at most CACHE frames), so a candidate opens at once
        self.pl, self.nfr, self.cache = pl, f1 - f0 + 1, {}
        self.f0, self.fps = f0, pl.fps
        self.j, self.playing, self.t_in = 0, True, time.time()

    def boxes(self, f):
        """Boxes of the candidate's tracks at display frame f (tracker frame nearest to that video frame)."""
        c = self.cands[self.i]
        t = (f - (pc.FRAME_OFFSET[self.clip.camera] if self.kind == "raw" else 0)) / self.fps
        k = self.clip.k_at(t)
        out = []
        for lab, tid, col in (("A", c["track_a"], (255, 0, 255)), ("B", c["track_b"], (255, 255, 0))):
            if not tid:
                continue
            tr = self.tracks.get(int(tid))
            if tr is None:
                continue
            j = int(np.argmin(np.abs(tr["k"] - k)))
            gone = abs(tr["k"][j] - k) > 1.5                   # not tracked now: dashed nearest box
            out.append((lab, tid, tr["box"][j], col, gone))
        return out

    def render(self):
        c = self.cands[self.i]
        W, H = self.disp
        can = np.zeros((H + self.strip, W, 3), np.uint8)
        if self.j not in self.cache:
            if len(self.cache) >= CACHE:
                del self.cache[max(self.cache, key=lambda x: abs(x - self.j))]
            self.cache[self.j] = cv2.resize(self.pl.read(self.f0 + self.j), self.disp, interpolation=cv2.INTER_AREA)
        can[:H] = self.cache[self.j]
        s = W / pc.RAW_W
        for lab, tid, b, col, gone in self.boxes(self.f0 + self.j):
            x1, y1, x2, y2 = (b * s).astype(int)
            if gone:                                           # track ended: dashed last box
                for x in range(x1, x2, 12):
                    cv2.line(can, (x, y1 - 4), (min(x + 6, x2), y1 - 4), col, 2)
                    cv2.line(can, (x, y2 + 4), (min(x + 6, x2), y2 + 4), col, 2)
            else:
                cv2.rectangle(can, (x1 - 4, y1 - 4), (x2 + 4, y2 + 4), (0, 0, 0), 4)
                cv2.rectangle(can, (x1 - 4, y1 - 4), (x2 + 4, y2 + 4), col, 2)
            txt = lab if c["type"] == "movement" else f"{lab} {tid}"
            cv2.putText(can, txt, (x1, max(14, y1 - 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 4, cv2.LINE_AA)
            cv2.putText(can, txt, (x1, max(14, y1 - 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, col, 2, cv2.LINE_AA)
        done = sum(x["cand_id"] in self.ans for x in self.cands)
        prev = self.ans.get(c["cand_id"], {}).get("answer", "")
        t = (self.f0 + self.j) / self.fps
        keys = KEYTXT.get(c["type"], KEYTXT["default"])
        info = (f"vehicle A from {c['approach']} (raw clip; the pipeline's answer is hidden)" if c["type"] == "movement"
                else c["detail"])
        lines = [(f"{self.clip.name}  candidate {self.i + 1}/{len(self.cands)} ({c['type']})   answered {done}   "
                  f"t_clip {t:.1f} s   {'PLAY' if self.playing else 'PAUSED'} {self.speed:g}x"
                  + (f"   your answer: {prev}" if prev else ""), (255, 255, 255)),
                 (c["question"], (0, 255, 255)), (info, (200, 200, 200)), (keys, (80, 255, 80)),
                 ("Space pause | Left/Right step | R replay | - = speed | PgUp/PgDn previous/next | Esc quit",
                  (180, 180, 180))]
        pc.put_lines(can, lines, (0, H + 2), scale=self.fs, alpha=0.0, lh=self.lh)
        cv2.rectangle(can, (0, H - 6), (int(W * (self.j + 1) / self.nfr), H), (255, 255, 255), -1)
        return can

    def answer(self, text):
        c = self.cands[self.i]
        self.ans[c["cand_id"]] = dict(cand_id=c["cand_id"], type=c["type"], answer=text,
                                      seconds=round(time.time() - self.t_in, 1), answered=pc.now_iso())
        pc.write_csv(self.d / "review.csv", [self.ans[x["cand_id"]] for x in self.cands if x["cand_id"] in self.ans],
                     REV_FIELDS)

    def step(self, k) -> bool:
        c = self.cands[self.i]
        if k == pc.K_ESC:
            return False
        nxt = False
        amap = ANS.get(c["type"], ANS["default"])
        if k in amap:
            self.answer(amap[k])
            nxt = True
        if k == pc.K_SPACE:
            self.playing = not self.playing
        elif k == pc.K_LEFT:
            self.playing, self.j = False, max(0, self.j - 1)
        elif k == pc.K_RIGHT:
            self.playing, self.j = False, min(self.nfr - 1, self.j + 1)
        elif k == ord("r"):
            self.j, self.playing = 0, True
        elif k in (ord("-"), ord("_")):
            self.speed = 0.5 if self.speed > 0.5 else 0.25
        elif k in (ord("="), ord("+")):
            self.speed = 1.0 if self.speed >= 0.5 else 0.5
        elif k == pc.K_PGUP:
            self.i = max(0, self.i - 1)
            self.load()
        elif k == pc.K_PGDN:
            nxt = True
        if nxt:
            if self.i < len(self.cands) - 1:
                self.i += 1
                self.load()
            else:
                print("last candidate reached")
        return True

    def run(self, script=None):
        if not self.test:
            cv2.namedWindow(self.win, cv2.WINDOW_AUTOSIZE)
        last = time.time()
        while True:
            img = self.render()
            if self.test:
                if not script:
                    break
                k = script.pop(0)
                if k == "snap":
                    cv2.imwrite(str(self.d / f"snap_{self.i}.jpg"), img)
                    continue
            else:
                cv2.imshow(self.win, img)
                k = pc.read_key(max(1, int(1000 / (self.fps * self.speed) - (time.time() - last) * 1000)))
                last = time.time()
                if pc.window_closed(self.win):
                    break
            if self.playing:
                self.j += 1
                if self.j >= self.nfr:
                    self.j = 0                                 # loop the candidate
            if not self.step(k):
                break
        if not self.test:
            cv2.destroyAllWindows()
        print(f"{len(self.ans)} of {len(self.cands)} answered -> {self.d / 'review.csv'}")


def cmd_review(a):
    global OUTDIR
    clip = pc.clip_by_name(a.clip)
    fin = pc.final_clips(MANUAL_DIR)
    if (fin is None or clip.name not in fin) and not a.allow_unblind:
        raise SystemExit(f"The blind count of {clip.name} is not final yet (manual_counts/FINAL.json"
                         f"{'' if fin is None else ' closes only ' + ', '.join(sorted(fin))}). The overlay clip shows "
                         "the pipeline's labels, so review only after counting. Override with --allow-unblind.")
    if a.test_out:
        import shutil
        shutil.copytree(OUTDIR / clip.name, a.test_out / clip.name, dirs_exist_ok=True)
        OUTDIR = a.test_out
        r = Reviewer(clip, 1900, 948, 1.5, test=True)
        names = {"enter": pc.K_ENTER, "back": pc.K_BACK, "pgdn": pc.K_PGDN, "pgup": pc.K_PGUP, "space": pc.K_SPACE,
                 "none": -1, "snap": "snap"}
        r.run([names.get(t, ord(t) if len(t) == 1 else -1) for t in a.test_script.split(",")])
        return
    sw, sh, ui = pc.screen_size()
    Reviewer(clip, a.max_width or sw - 20, sh, ui).run()


def cmd_status(_):
    for clip in pc.CLIPS:
        d = OUTDIR / clip.name
        c, r = pc.read_csv(d / "candidates.csv"), pc.read_csv(d / "review.csv")
        if c:
            mins = sum(float(x["seconds"]) for x in r) / 60
            print(f"{clip.name}: {len(r)}/{len(c)} answered, {mins:.0f} min of answering time")


def main():
    global OUTDIR, MANUAL_DIR
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out-dir", type=Path, default=OUTDIR, help="(testing) output folder")
    ap.add_argument("--manual-dir", type=Path, default=MANUAL_DIR, help="(testing) folder of the blind counts")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    g = b.add_mutually_exclusive_group(required=True)
    g.add_argument("--interval", choices=["i300", "i900"], help="both cameras of one interval (enables cross-camera)")
    g.add_argument("--clip", nargs="+")
    b.add_argument("--allow-unblind", action="store_true")
    b.add_argument("--force", action="store_true")
    r = sub.add_parser("review")
    r.add_argument("--clip", required=True)
    r.add_argument("--allow-unblind", action="store_true")
    r.add_argument("--max-width", type=int, default=0)
    r.add_argument("--test-out", type=Path)
    r.add_argument("--test-script", default="")
    sub.add_parser("status")
    a = ap.parse_args()
    OUTDIR, MANUAL_DIR = a.out_dir, a.manual_dir
    {"build": cmd_build, "review": cmd_review, "status": cmd_status}[a.cmd](a)


if __name__ == "__main__":
    main()
