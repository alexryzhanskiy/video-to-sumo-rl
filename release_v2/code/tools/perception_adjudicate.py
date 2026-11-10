"""Adjudication of the unmatched events by the tracking review: who was right where hand and pipeline disagree."""
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

R = Path(r"D:\GitHub\video-to-sumo-rl\revision\perception\tracking_review")
A = Path(r"D:\GitHub\video-to-sumo-rl\revision\analysis\perception")
ans = Counter()
per_ap = defaultdict(Counter)
types = defaultdict(Counter)
for clip in ("center_i300", "zarich_i300"):
    cand = {r["cand_id"]: r for r in csv.DictReader(open(R / clip / "candidates.csv", encoding="utf-8"))}
    for r in csv.DictReader(open(R / clip / "review.csv", encoding="utf-8")):
        c = cand[r["cand_id"]]
        types[c["type"]][r["answer"]] += 1
        if c["type"] in ("manual_only", "pipeline_only"):
            per_ap[c["approach"]][(c["type"], r["answer"])] += 1
print("== answers by type")
for t, cnt in types.items():
    print(f"  {t:14} {dict(cnt)}")
cells = list(csv.DictReader(open(A / "counting_cells.csv", encoding="utf-8")))
hand = Counter()
pipe = Counter()
for c in cells:
    if c["movement"] != "U":
        hand[c["approach"]] += int(c["manual"])
        pipe[c["approach"]] += int(c["pipeline"])
print("\n== per approach (no U-turns in hand/pipeline totals; unmatched answers include all movements)")
tot = Counter()
for ap in ("SVB_N", "PRB_E", "SVB_S", "PRB_W"):
    a = per_ap[ap]
    false_press = sum(v for (t, x), v in a.items() if t == "manual_only" and x.startswith("no vehicle"))
    pipe_missed = sum(v for (t, x), v in a.items() if t == "manual_only" and x.startswith("pipeline missed"))
    time_off = sum(v for (t, x), v in a.items() if t == "manual_only" and x.startswith("pipeline counted"))
    mo_ct = sum(v for (t, x), v in a.items() if t == "manual_only" and x.startswith("cannot"))
    real = sum(v for (t, x), v in a.items() if t == "pipeline_only" and x.startswith("real"))
    dbl = sum(v for (t, x), v in a.items() if t == "pipeline_only" and x.startswith("double"))
    fals = sum(v for (t, x), v in a.items() if t == "pipeline_only" and x.startswith("false"))
    po_ct = sum(v for (t, x), v in a.items() if t == "pipeline_only" and x.startswith("cannot"))
    adj = hand[ap] - false_press + real
    row = dict(hand=hand[ap], pipeline=pipe[ap], hand_false_press=false_press, hand_missed=real,
               pipeline_missed=pipe_missed, time_off=time_off, manual_only_cannot=mo_ct,
               pipeline_double=dbl, pipeline_false=fals, pipeline_only_cannot=po_ct, adjudicated=adj)
    tot.update(row)
    print(f"  {ap}: {row}  pipeline vs adjudicated {pipe[ap] - adj:+d}")
print(f"  ALL: {dict(tot)}  pipeline vs adjudicated {tot['pipeline'] - tot['adjudicated']:+d} "
      f"({100 * (tot['pipeline'] - tot['adjudicated']) / tot['adjudicated']:+.1f}%); hand vs adjudicated "
      f"{tot['hand'] - tot['adjudicated']:+d} ({100 * (tot['hand'] - tot['adjudicated']) / tot['adjudicated']:+.1f}%)")

# Independent check (added 4 Nov 2026): did the second counter (blind, counter2) also count the vehicle behind each
# unmatched event? Hand-only event: A1's press is paired with a second-counter press in the B2 matching (same
# approach, lag within +-3 s). Pipeline-only event: the pipeline crossing is paired with a second-counter press in the B1
# matching (lag press - crossing in [-2, +6] s). Same one-to-one matching as perception_metrics.py, so in a platoon a
# press can pair with a neighbouring vehicle.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import perception_common as pc  # noqa: E402
import perception_metrics as pm  # noqa: E402

f1 = pm.final_events(pc.OUT / "manual_counts", "hand counts")
f2 = pm.final_events(pc.OUT / "counter2" / "manual_counts", "second counter")
if f1 is None or f2 is None:
    print("\n== second counter on the unmatched events: not available (a FINAL.json is missing)")
    sys.exit(0)
tc = lambda e: float(e["t_common_s"])  # noqa: E731
chk = defaultdict(Counter)
odd = []
for clip in pc.COUNT_CLIPS:
    e1 = [e for e in f1["events"] if e["clip"] == clip.name]
    e2 = [e for e in f2["events"] if e["clip"] == clip.name]
    pipe_ev = pm.pipeline_events(clip)
    by_a1 = {id(y) for _, y in pm.match(e2, e1, tc, tc, -3.0, 3.0, 0.0)[0]}
    by_pipe = {id(p) for _, p in pm.match(e2, pipe_ev, tc, lambda p: p["t_common"], -2.0, 6.0, 1.0)[0]}
    cand = {r["cand_id"]: r for r in csv.DictReader(open(R / clip.name / "candidates.csv", encoding="utf-8"))}
    for r in csv.DictReader(open(R / clip.name / "review.csv", encoding="utf-8")):
        c = cand[r["cand_id"]]
        if c["type"] == "manual_only":
            t_press = float(re.search(r"at ([0-9.]+) s \(press time\)", c["detail"]).group(1))
            hit = [e for e in e1 if e["approach"] == c["approach"] and abs(float(e["t_clip_s"]) - t_press) < 0.051]
            seen = by_a1
        elif c["type"] == "pipeline_only":
            hit = [p for p in pipe_ev if str(p["track_id"]) == c["track_a"] and p["approach"] == c["approach"]]
            seen = by_pipe
        else:
            continue
        if len(hit) != 1:
            raise SystemExit(f"cannot join candidate {clip.name} {c['cand_id']} to one event ({len(hit)} found)")
        also = id(hit[0]) in seen
        chk[(c["type"], r["answer"])]["second counter also counted" if also else "second counter did not"] += 1
        if also != (c["type"] == "manual_only" or r["answer"] == "real vehicle"):
            odd.append(f"{clip.name} {c['type']} {c['approach']} t_common {float(c['t_common']):.1f} s: review '{r['answer']}', "
                       f"second counter {'counted' if also else 'did not count'}")
print(f"\n== second counter ({f2['counter']}, blind, closed {f2['finalized']}) on the unmatched events")
for k in sorted(chk):
    print(f"  {k[0]:14} {k[1]:32} {dict(chk[k])}")
print("  not in line with the review answer:")
for o in odd:
    print("   ", o)
