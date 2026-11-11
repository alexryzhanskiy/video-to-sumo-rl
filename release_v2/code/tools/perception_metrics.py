"""Comment 1.3 metrics from A1's manual video work (and the second counter), written to revision/analysis/perception/.

  A. Counting: hand counts against the pipeline per clip x approach x movement (5-min clips, owned approaches, U-turns
     reported separately; approaches watched below 99%, closed with --force, are left out): error = pipeline - manual,
     mean absolute error per cell, weighted absolute percentage error
     (sum |error| / sum manual), total error. Event level: optimal one-to-one matching of key presses to pipeline
     stop-line crossings (perception_flag.match_manual: lag press - crossing in [-2, +6] s, cost |lag - 1 s|), the
     movement confusion on matched pairs (by the pipeline's exit method, gate or heading), and the unmatched events per
     100 hand-counted vehicles. Annotation time from the app's session log.
  B. Second counter (default revision/perception/counter2/manual_counts, a second person counting A1's clips on
     this laptop; a third counter (A3, not released) is in revision/perception/second_counter): B1 its own clips against the pipeline,
     as in A; B2 the same cells against A1's counts where both counted the same clip and approach, and event
     matching between the two counters (lag in [-3, +3] s, cost |lag|). Approaches watched below 99% are left out.
  C. Tracking review (perception_flag.py review): per clip, the confirmed ID switches and fragments (break,
     break_double and jump "yes"), double counts (break_double "yes" plus pipeline-only "double count (same camera)"
     not already in a confirmed break_double pair; "other camera" = cross-camera duplicates), false counts, the two
     sources of pipeline misses (reported separately: they can describe the same vehicle), and the unflagged-vehicle
     sample. Pooled over the reviewed clips (tracking_rates.json), per 100 pipeline-counted vehicles: census of the
     confirmed flagged candidates + the sample share (answers other than "cannot tell") extrapolated to all unflagged
     counted vehicles, with a conservative 95% CI = Garwood (Poisson) bounds of the census + Clopper-Pearson bounds of
     the sample share x unflagged vehicles, "cannot tell" and unanswered candidates added to the upper bound; the same
     for double counts (sample answer "counted twice"). The accuracy of heading-fallback exits against the reviewer's
     blind answer, with gate exits as the control.
  D. Queue recount (perception_queue_click.py) against Ryzhanskyi's end-of-red queues (28 Oct): difference per frame.
  E. Set-up redo (perception_setup_redo.py): active time and the count difference with the redrawn lines, for A1 and
     the second person (revision/perception/counter2/setup_redo).

Blind rule: A, B and C compare with the pipeline, so they use only the clips that <manual-dir>/FINAL.json closes and
the hand-count events frozen by it (1.3_manual_counts_events.csv, or the per-clip event files of an older export,
after their SHA-256 is checked against FINAL.json); B also needs the second counter's FINAL.json and is held back until
A1's FINAL.json exists, so no count reaches him during his blind phase. --allow-unblind is
for synthetic tests only (live event files of the counting clips). Missing inputs are reported as not yet available;
a section that fails is reported as failed, and the script exits with status 1 after writing the report.

    revision/.venv/Scripts/python.exe revision/tools/perception_metrics.py --out revision/analysis/perception
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np
from scipy.optimize import linear_sum_assignment
from scipy.stats import beta, chi2

sys.path.insert(0, str(Path(__file__).resolve().parent))
import perception_common as pc  # noqa: E402

MOVES = ["L", "T", "R", "U"]
QUEUES28 = pc.INC28 / "step_1.2_1.3" / "1.2_observed_queues.csv"
ID_TYPES = ("break", "break_double", "jump")
FAILED: list[str] = []


def match(A, B, ta, tb, lo, hi, centre, by="approach"):
    """Optimal one-to-one matching per approach: lag = ta(a) - tb(b) in [lo, hi], cost |lag - centre|."""
    pairs, ua, ub = [], [], []
    for ap in sorted({a[by] for a in A} | {b[by] for b in B}):
        X, Y = [a for a in A if a[by] == ap], [b for b in B if b[by] == ap]
        if not X or not Y:
            ua, ub = ua + X, ub + Y
            continue
        lag = np.array([[ta(x) - tb(y) for y in Y] for x in X])
        cost = np.where((lag >= lo) & (lag <= hi), np.abs(lag - centre), 1e6)
        r, c = linear_sum_assignment(cost)
        ok = {(i, j) for i, j in zip(r, c) if cost[i, j] < 1e6}
        pairs += [(X[i], Y[j]) for i, j in ok]
        ua += [X[i] for i in range(len(X)) if i not in {p for p, _ in ok}]
        ub += [Y[j] for j in range(len(Y)) if j not in {q for _, q in ok}]
    return pairs, ua, ub


def final_events(d: Path, who: str) -> dict | None:
    """The blind count closed by <d>/FINAL.json (perception_count.py export --final): the closed clips, their live
    (not deleted) events, the watched shares and the warnings of the close; None if the blind phase is not closed.
    The events come from 1.3_manual_counts_events.csv, or from the per-clip event files (older export), after their
    SHA-256 is checked against FINAL.json, so nothing saved after the close enters the metrics."""
    p = Path(d) / "FINAL.json"
    if not p.exists():
        return None
    fin = pc.read_json(p)
    clips = set(fin.get("clips") or [c.name for c in pc.CLIPS])
    files = fin.get("files", {})
    srcs = (["1.3_manual_counts_events.csv"] if "1.3_manual_counts_events.csv" in files
            else [s for s in files if s.endswith("/events.csv") and s.split("/")[0] in clips])
    if not srcs:
        raise RuntimeError(f"{who}: FINAL.json in {pc.posix(d)} lists no event file")
    ev = []
    for s in srcs:
        f = Path(d) / s
        if not f.exists() or pc.sha256(f) != files[s]:
            raise RuntimeError(f"{who}: {pc.posix(f)} is missing or differs from its SHA-256 in FINAL.json "
                               "(changed after the blind phase was closed?)")
        ev += pc.read_csv(f)
    return dict(clips=clips, events=[e for e in ev if e["deleted"] != "1" and e["clip"] in clips],
                watched=fin.get("watched_pct", {}), warnings=fin.get("warnings", []), finalized=fin.get("finalized"),
                counter=fin.get("counter", ""))


def manual_events(d: Path, clip: pc.Clip, fin: dict | None):
    """Hand-count events of a clip (frozen by FINAL.json; the live event file only without one, --allow-unblind), the
    watched share per approach and the minutes in the app."""
    if fin is not None:
        ev = [e for e in fin["events"] if e["clip"] == clip.name]
    else:
        ev = [e for e in pc.read_csv(d / clip.name / "events.csv") if e["deleted"] != "1"]
    st = pc.read_json(d / clip.name / "state.json") if (d / clip.name / "state.json").exists() else {}
    watched = (fin or {}).get("watched", {})
    cov = {a: watched.get(f"{clip.name} {a}", round(len(st.get("coverage", {}).get(a, [])) / 3, 1))
           for a in pc.OWNED[clip.camera]}
    mins = round(sum(s["seconds"] for s in st.get("sessions", []) if not s.get("headless")) / 60, 1)
    return ev, cov, mins


def pipeline_events(clip: pc.Clip):
    rows = [m for m in pc.load_movements(clip.camera)
            if m["entry"] in pc.OWNED[clip.camera] and clip.t0 <= m["t_common"] < clip.t0 + pc.CLIP_LEN]
    for m in rows:
        m["approach"], m["mcode"] = m["entry"], pc.MOV_CODE[m["movement_en"]]
    return rows


def cell_stats(cells, key_ref="manual", key_x="pipeline"):
    d = [c[key_x] - c[key_ref] for c in cells]
    ref = sum(c[key_ref] for c in cells)
    return dict(cells=len(cells), reference_total=ref, other_total=sum(c[key_x] for c in cells),
                total_error=sum(d), total_error_pct=round(100 * sum(d) / ref, 2) if ref else None,
                mae_per_cell=round(float(np.mean(np.abs(d))), 3) if d else None,
                wape_pct=round(100 * sum(abs(x) for x in d) / ref, 2) if ref else None)


def counting(a, out, rep):
    fin = final_events(a.manual_dir, "hand counts")
    if fin is None and not a.allow_unblind:
        rep.append("## A. Counting\n\nNot yet available: the blind phase is not closed (no FINAL.json).\n")
        return None
    clips = [c for c in pc.CLIPS if c.name in fin["clips"]] if fin else pc.COUNT_CLIPS
    cells, conf, unm, meta, allpairs = [], {}, [], [], []
    for clip in clips:
        ev, cov, mins = manual_events(a.manual_dir, clip, fin)
        aps = [ap for ap in pc.OWNED[clip.camera] if cov.get(ap, 0) >= 99]   # --force can close a partly watched approach
        ev = [e for e in ev if e["approach"] in aps]
        if not ev:
            continue
        pipe = [p for p in pipeline_events(clip) if p["approach"] in aps]
        for ap in aps:
            for m in MOVES:
                cells.append(dict(clip=clip.name, approach=ap, movement=m,
                                  manual=sum(e["approach"] == ap and e["movement"] == m for e in ev),
                                  pipeline=sum(p["approach"] == ap and p["mcode"] == m for p in pipe),
                                  unsure=sum(e["approach"] == ap and e["movement"] == m and str(e["unsure"]) == "1" for e in ev)))
        pairs, um, up = match(ev, pipe, lambda e: float(e["t_common_s"]), lambda p: p["t_common"], -2.0, 6.0, 1.0)
        allpairs += [(clip.name, e, p) for e, p in pairs]
        for e, p in pairs:
            k = (p["method"], e["movement"], p["mcode"])
            conf[k] = conf.get(k, 0) + 1
        unm += [dict(clip=clip.name, side="manual only", approach=e["approach"], movement=e["movement"], t_common=e["t_common_s"],
                     track_id="") for e in um]
        unm += [dict(clip=clip.name, side="pipeline only", approach=p["approach"], movement=p["mcode"], t_common=p["t_common"],
                     track_id=p["track_id"]) for p in up]
        meta.append(dict(clip=clip.name, manual=len(ev), pipeline=len(pipe), matched=len(pairs), manual_only=len(um),
                         pipeline_only=len(up), minutes_in_app=mins, **{f"watched_{k}": v for k, v in cov.items()}))
    if not cells:
        rep.append("## A. Counting\n\nNot yet available: no hand-count events.\n")
        return None
    for c in cells:
        c["error"] = c["pipeline"] - c["manual"]
        c["error_pct"] = round(100 * c["error"] / c["manual"], 1) if c["manual"] else ""
    pc.write_csv(out / "counting_cells.csv", cells)
    pc.write_csv(out / "counting_clips.csv", meta, list(dict.fromkeys(k for m in meta for k in m)))
    pc.write_csv(out / "counting_unmatched_events.csv", unm, ["clip", "side", "approach", "movement", "t_common", "track_id"])
    conf_rows = [dict(pipeline_exit_method=k[0], manual_movement=k[1], pipeline_movement=k[2], n=v) for k, v in sorted(conf.items())]
    pc.write_csv(out / "movement_confusion_matched.csv", conf_rows)
    noU = [c for c in cells if c["movement"] != "U"]
    summ = dict(all_movements=cell_stats(cells), without_uturns=cell_stats(noU),
                by_movement={m: cell_stats([c for c in cells if c["movement"] == m]) for m in MOVES},
                by_approach={ap: cell_stats([c for c in noU if c["approach"] == ap]) for ap in sorted({c["approach"] for c in cells})})
    n_man = sum(m["manual"] for m in meta)
    agree = {meth: (sum(v for k, v in conf.items() if k[0] == meth and k[1] == k[2]), sum(v for k, v in conf.items() if k[0] == meth))
             for meth in ("gate", "heading")}
    summ["events"] = dict(manual=n_man, pipeline=sum(m["pipeline"] for m in meta), matched=sum(m["matched"] for m in meta),
                          manual_only_per_100=round(100 * sum(m["manual_only"] for m in meta) / n_man, 2),
                          pipeline_only_per_100=round(100 * sum(m["pipeline_only"] for m in meta) / n_man, 2),
                          movement_agreement={k: dict(agree=v[0], matched=v[1], pct=round(100 * v[0] / v[1], 1) if v[1] else None)
                                              for k, v in agree.items()},
                          minutes_in_app=round(sum(m["minutes_in_app"] for m in meta), 1))
    summ["blind_phase"] = (dict(finalized=fin["finalized"], clips=sorted(fin["clips"]), warnings=fin["warnings"]) if fin
                           else "unblind test run (--allow-unblind)")
    pc.write_json(out / "counting_summary.json", summ)
    s, w = summ["without_uturns"], summ["events"]
    L = ["## A. Counting (hand counts against the pipeline)", "",
         (f"Blind phase closed {fin['finalized']} for {', '.join(sorted(fin['clips']))}; hand counts from the frozen export."
          if fin else "UNBLIND TEST RUN (--allow-unblind): live event files, no FINAL.json."), ""]
    if fin and fin["warnings"]:
        L += ["FINAL.json warnings (closed with --force): " + "; ".join(fin["warnings"]) + ".", ""]
    L += [f"{len(meta)} clips, {n_man} hand-counted vehicles, {w['pipeline']} pipeline counts, {w['minutes_in_app']} min in the app. "
          f"Without U-turns (the demand excludes them): total error {s['total_error']:+d} ({s['total_error_pct']:+.1f}%), "
          f"mean absolute error {s['mae_per_cell']:.2f} vehicles per 5-min cell ({s['cells']} cells), "
          f"weighted absolute percentage error {s['wape_pct']:.1f}%.", "",
          "| Movement | Hand | Pipeline | Error | Error % | Mean abs. error per cell | Weighted abs. % error |", "|---|---|---|---|---|---|---|"]
    for m in MOVES:
        b = summ["by_movement"][m]
        L.append(f"| {m} | {b['reference_total']} | {b['other_total']} | {b['total_error']:+d} | "
                 f"{b['total_error_pct'] if b['total_error_pct'] is not None else '–'} | {b['mae_per_cell']} | {b['wape_pct'] if b['wape_pct'] is not None else '–'} |")
    L += ["", "| Approach (no U-turns) | Hand | Pipeline | Error | Error % | Weighted abs. % error |", "|---|---|---|---|---|---|"]
    for ap, b in summ["by_approach"].items():
        L.append(f"| {ap} | {b['reference_total']} | {b['other_total']} | {b['total_error']:+d} | {b['total_error_pct']} | {b['wape_pct']} |")
    L += ["", f"Event matching: {w['matched']} matched; hand-only {w['manual_only_per_100']} and pipeline-only "
              f"{w['pipeline_only_per_100']} per 100 hand-counted vehicles (candidates; the tracking review resolves them). "
              f"Movement agreement on matched pairs: gate exits {w['movement_agreement']['gate']['pct']}% "
              f"(n = {w['movement_agreement']['gate']['matched']}), heading exits {w['movement_agreement']['heading']['pct']}% "
              f"(n = {w['movement_agreement']['heading']['matched']}).", ""]
    rep.append("\n".join(L))
    return cells


def second_counter(a, out, rep, cells):
    """B1: the second counter against the pipeline on its own closed clips; B2: against A1's hand counts where both
    counted the same clip and approach. Approaches watched below 99% (closed with --force) are left out of both."""
    if a.second_dir is None or not (a.second_dir / "FINAL.json").exists():
        rep.append("## B. Second counter\n\nNot yet available.\n")
        return
    fin1 = final_events(a.manual_dir, "hand counts")
    if fin1 is None and not a.allow_unblind:
        rep.append("## B. Second counter\n\nNot yet available: A1's FINAL.json is missing (the second count is reported "
                   "only after his blind phase is closed).\n")
        return
    fin2 = final_events(a.second_dir, "second counter")
    L = ["## B. Second counter", "",
         f"Blind count by {fin2['counter']}, closed {fin2['finalized']} for {', '.join(sorted(fin2['clips']))}."]
    if fin2["warnings"]:
        L.append("Warnings of the close (closed with --force): " + "; ".join(fin2["warnings"])
                 + ". Approaches watched below 99% are left out.")
    rows1, conf, meta, summ = [], {}, [], {}
    for clip in [c for c in pc.CLIPS if c.name in fin2["clips"]]:
        ev2, cov2, mins2 = manual_events(a.second_dir, clip, fin2)
        aps = [ap for ap in pc.OWNED[clip.camera] if cov2.get(ap, 0) >= 99]
        ev2 = [e for e in ev2 if e["approach"] in aps]
        if not ev2:
            continue
        pipe = [p for p in pipeline_events(clip) if p["approach"] in aps]
        for ap in aps:
            for m in MOVES:
                rows1.append(dict(clip=clip.name, approach=ap, movement=m,
                                  second=sum(e["approach"] == ap and e["movement"] == m for e in ev2),
                                  pipeline=sum(p["approach"] == ap and p["mcode"] == m for p in pipe),
                                  unsure=sum(e["approach"] == ap and e["movement"] == m and str(e["unsure"]) == "1" for e in ev2)))
        pairs, um, up = match(ev2, pipe, lambda e: float(e["t_common_s"]), lambda p: p["t_common"], -2.0, 6.0, 1.0)
        for e, p in pairs:
            k = (p["method"], e["movement"] == p["mcode"])
            conf[k] = conf.get(k, 0) + 1
        meta.append(dict(clip=clip.name, approaches=" ".join(aps), second=len(ev2), pipeline=len(pipe), matched=len(pairs),
                         second_only=len(um), pipeline_only=len(up), minutes_in_app=mins2))
    L += ["", "### B1. Against the pipeline (the second counter's clips)", ""]
    if rows1:
        for r in rows1:
            r["error"] = r["pipeline"] - r["second"]
        pc.write_csv(out / "second_counter_vs_pipeline_cells.csv", rows1)
        s = cell_stats([r for r in rows1 if r["movement"] != "U"], key_ref="second")
        n2 = sum(m["second"] for m in meta)
        agree = {meth: (conf.get((meth, True), 0), conf.get((meth, True), 0) + conf.get((meth, False), 0))
                 for meth in ("gate", "heading")}
        summ["vs_pipeline"] = dict(clips=meta, without_uturns=s,
                                   all_movements=cell_stats(rows1, key_ref="second"),
                                   second_only_per_100=round(100 * sum(m["second_only"] for m in meta) / n2, 2),
                                   pipeline_only_per_100=round(100 * sum(m["pipeline_only"] for m in meta) / n2, 2),
                                   movement_agreement={k: dict(agree=v[0], matched=v[1], pct=round(100 * v[0] / v[1], 1) if v[1] else None)
                                                       for k, v in agree.items()})
        for m in meta:
            L.append(f"{m['clip']} ({m['approaches']}; {m['minutes_in_app']} min in the app): second counter {m['second']}, "
                     f"pipeline {m['pipeline']}; {m['matched']} matched, second-counter-only {m['second_only']}, "
                     f"pipeline-only {m['pipeline_only']}.")
        g, h = summ["vs_pipeline"]["movement_agreement"]["gate"], summ["vs_pipeline"]["movement_agreement"]["heading"]
        L += ["", f"Cells without U-turns: total error {s['total_error']:+d} ({s['total_error_pct']:+.1f}%), mean absolute error "
                  f"{s['mae_per_cell']:.2f} vehicles per 5-min cell ({s['cells']} cells), weighted absolute percentage error "
                  f"{s['wape_pct']:.1f}%. Movement agreement on matched pairs: gate exits {g['pct']}% (n = {g['matched']}), "
                  f"heading exits {h['pct']}% (n = {h['matched']})."]
    else:
        L.append("No approach watched at least 99%.")
    L += ["", "### B2. Against A1's hand counts (same clip and approach)", ""]
    rows2, agr = [], []
    for clip in [c for c in pc.CLIPS if c.name in fin2["clips"] and (fin1 is None or c.name in fin1["clips"])]:
        ev2, cov2, mins2 = manual_events(a.second_dir, clip, fin2)
        ev1, cov1, _ = manual_events(a.manual_dir, clip, fin1)
        aps = [ap for ap in pc.OWNED[clip.camera] if cov2.get(ap, 0) >= 99 and cov1.get(ap, 0) >= 99]
        ev1, ev2 = [e for e in ev1 if e["approach"] in aps], [e for e in ev2 if e["approach"] in aps]
        if not ev2 or not ev1:
            continue
        for ap in aps:
            for m in MOVES:
                rows2.append(dict(clip=clip.name, approach=ap, movement=m,
                                  manual=sum(e["approach"] == ap and e["movement"] == m for e in ev1),
                                  second=sum(e["approach"] == ap and e["movement"] == m for e in ev2)))
        pairs, u1, u2 = match(ev2, ev1, lambda e: float(e["t_common_s"]), lambda e: float(e["t_common_s"]), -3.0, 3.0, 0.0)
        same = sum(x["movement"] == y["movement"] for x, y in pairs)
        agr.append(dict(clip=clip.name, approaches=" ".join(aps), a1=len(ev1), second=len(ev2), matched=len(pairs),
                        same_movement=same, a1_only=len(u2), second_only=len(u1)))
        L.append(f"{clip.name} ({', '.join(aps)}): A1 {len(ev1)}, second counter {len(ev2)} vehicles; {len(pairs)} matched "
                 f"within ±3 s, same movement in {same} ({100 * same / max(len(pairs), 1):.1f}%); only A1 {len(u2)}, "
                 f"only the second counter {len(u1)}.")
    if rows2:
        for r in rows2:
            r["difference"] = r["second"] - r["manual"]
        pc.write_csv(out / "second_counter_cells.csv", rows2)
        s = cell_stats([r for r in rows2 if r["movement"] != "U"], key_x="second")
        summ["vs_a1"] = dict(clips=agr, without_uturns=s)
        L += ["", f"Cells without U-turns: total difference {s['total_error']:+d} ({s['total_error_pct']:+.1f}%), mean absolute "
                  f"difference {s['mae_per_cell']:.2f} vehicles per cell, weighted absolute percentage difference {s['wape_pct']:.1f}%."]
    else:
        L.append("Not available: no clip and approach counted by both (A1's counting sample is the i300 clips, C-13).")
    if summ:
        pc.write_json(out / "second_counter_summary.json", dict(counter=fin2["counter"], finalized=fin2["finalized"],
                                                                 warnings=fin2["warnings"], **summ))
    rep.append("\n".join(L) + "\n")


def pooled_rate(census: int, unclear: int, x: int, s: int, unflagged: int, n: int) -> dict:
    """Events per 100 counted vehicles: the census of confirmed flagged candidates + the unflagged-vehicle sample share
    x / s extrapolated to all unflagged counted vehicles. 95% CI, a conservative sum of exact bounds: Garwood (Poisson)
    for the census, Clopper-Pearson for the sample share; 'cannot tell' and unanswered candidates (unclear) are added
    to the upper bound."""
    f_lo = chi2.ppf(0.025, 2 * census) / 2 if census else 0.0
    f_hi = chi2.ppf(0.975, 2 * census + 2) / 2
    p_lo = beta.ppf(0.025, x, s - x + 1) if x else 0.0
    p_hi = (beta.ppf(0.975, x + 1, s - x) if x < s else 1.0) if s else 1.0
    est = census + unflagged * x / s if s else None
    per100 = lambda v: round(100 * float(v) / n, 2) if n and v is not None else None  # noqa: E731
    return dict(census=census, unclear_or_unanswered=unclear, sample_events=x, sample_answered=s, unflagged=unflagged,
                counted=n, estimated_events=round(est, 2) if est is not None else None, per_100=per100(est),
                census_only_per_100=per100(census),
                ci95_per_100=[per100(f_lo + unflagged * p_lo), per100(f_hi + unclear + unflagged * p_hi)])


def review(a, out, rep, cells):
    names = {c.name for c in pc.CLIPS}
    dirs = ([d for d in sorted(a.review_dir.glob("*")) if d.name in names and (d / "review.csv").exists()]
            if a.review_dir.exists() else [])
    fin = pc.final_clips(a.manual_dir)
    held = [d.name for d in dirs if not a.allow_unblind and (fin is None or d.name not in fin)]
    dirs = [d for d in dirs if d.name not in held]
    if not dirs:
        rep.append("## C. Tracking review\n\nNot yet available"
                   + (f" (blind counts not closed by FINAL.json: {', '.join(held)})" if held else "") + ".\n")
        return
    tall, mov, per, L = [], [], [], ["## C. Tracking review", ""]
    if held:
        L += [f"Skipped, blind counts not closed by FINAL.json: {', '.join(held)}.", ""]
    for d in dirs:
        cand = {c["cand_id"]: c for c in pc.read_csv(d / "candidates.csv")}
        ans = pc.read_csv(d / "review.csv")
        n_pipe = sum(c["pipeline"] for c in (cells or []) if c["clip"] == d.name) or len(pipeline_events(pc.clip_by_name(d.name)))
        det = sorted({c["detail"] for c in cand.values() if c["type"] == "vehicle"})
        mm = [re.fullmatch(r"sampled counted vehicle \((\d+) unflagged of (\d+)\)", x) for x in det]
        if len(mm) != 1 or mm[0] is None:
            raise RuntimeError(f"{d.name}: cannot read the number of unflagged counted vehicles from the vehicle "
                               f"candidates (details {det})")
        unfl, n_built = int(mm[0].group(1)), int(mm[0].group(2))
        if n_built != n_pipe:
            raise RuntimeError(f"{d.name}: the candidates were built on {n_built} counted vehicles, the counts give {n_pipe}")
        types = {}
        for r in ans:
            types.setdefault(r["type"], {}).setdefault(r["answer"], 0)
            types[r["type"]][r["answer"]] += 1
            if r["type"] == "movement":
                c = cand[r["cand_id"]]
                mov.append(dict(clip=d.name, approach=c["approach"], method=c["method"], pipeline=c["pipeline_movement"],
                                reviewer=r["answer"]))
        totals = {t: sum(1 for c in cand.values() if c["type"] == t) for t in {c["type"] for c in cand.values()}}
        for t, cnt in sorted(types.items()):
            for ansr, n in sorted(cnt.items()):
                tall.append(dict(clip=d.name, type=t, answer=ansr, n=n, candidates=totals.get(t, 0), pipeline_vehicles=n_pipe))
        A = lambda t, x: types.get(t, {}).get(x, 0)                                     # noqa: E731
        done = {r["cand_id"] for r in ans}
        unans = lambda ts: sum(1 for c in cand.values() if c["type"] in ts and c["cand_id"] not in done)  # noqa: E731
        bd_yes = [cand[r["cand_id"]] for r in ans if r["type"] == "break_double" and r["answer"] == "yes"]
        bd_tracks = {c[x] for c in bd_yes for x in ("track_a", "track_b") if c[x] != ""}
        po_same = [cand[r["cand_id"]] for r in ans if r["type"] == "pipeline_only" and r["answer"] == "double count (same camera)"]
        veh = types.get("vehicle", {})
        rec = dict(clip=d.name, counted=n_pipe, unflagged=unfl,
                   id_break=A("break", "yes"), id_break_double=A("break_double", "yes"), id_jump=A("jump", "yes"),
                   id_unclear=sum(A(t, "cannot tell") for t in ID_TYPES) + unans(ID_TYPES),
                   dc_break_double=len(bd_yes), dc_pipeline_only_same=sum(c["track_a"] not in bd_tracks for c in po_same),
                   dc_other_camera=A("pipeline_only", "double count (other camera)"),
                   dc_unclear=A("break_double", "cannot tell") + A("pipeline_only", "cannot tell") + unans(("break_double", "pipeline_only")),
                   false_counts=A("pipeline_only", "false count"),
                   missed_hand_count_unmatched=A("manual_only", "pipeline missed it"),
                   missed_uncounted_track=A("uncounted", "missed (never counted)"),
                   sample_answered=sum(n for x, n in veh.items() if x != "cannot tell"), sample_cannot_tell=veh.get("cannot tell", 0),
                   sample_id_changed=veh.get("ID changed or fragment", 0), sample_counted_twice=veh.get("counted twice", 0),
                   sample_unanswered=unans(("vehicle",)), candidates=len(cand), answered=len(ans))
        rec["id_census"] = rec["id_break"] + rec["id_break_double"] + rec["id_jump"]
        rec["dc_census"] = rec["dc_break_double"] + rec["dc_pipeline_only_same"] + rec["dc_other_camera"]
        per.append(rec)
        L.append(f"{d.name}: {n_pipe} pipeline-counted vehicles ({unfl} unflagged); answered {len(ans)} of {len(cand)} candidates. "
                 f"Confirmed ID switches and fragments {rec['id_census']} (break {rec['id_break']}, break_double "
                 f"{rec['id_break_double']}, jump {rec['id_jump']}; cannot tell or unanswered {rec['id_unclear']}); double counts "
                 f"same camera {rec['dc_break_double'] + rec['dc_pipeline_only_same']} (break_double {rec['dc_break_double']}, "
                 f"pipeline-only {rec['dc_pipeline_only_same']}), other camera {rec['dc_other_camera']}; false counts "
                 f"{rec['false_counts']}; pipeline misses, two sources that may describe the same vehicle: unmatched hand count "
                 f"{rec['missed_hand_count_unmatched']}, uncounted track {rec['missed_uncounted_track']}; vehicle sample: ID "
                 f"changed {rec['sample_id_changed']}, counted twice {rec['sample_counted_twice']} of {rec['sample_answered']} "
                 f"answered (cannot tell {rec['sample_cannot_tell']}, unanswered {rec['sample_unanswered']}).")
    pc.write_csv(out / "review_tallies.csv", tall)
    T = {k: sum(r[k] for r in per) for k in per[0] if k != "clip"}
    rates = dict(clips=[r["clip"] for r in per],
                 method="per 100 pipeline-counted vehicles: (census + unflagged x sample share) / counted; 95% CI = "
                        "Garwood bounds of the census + Clopper-Pearson bounds of the sample share x unflagged, 'cannot "
                        "tell' and unanswered candidates added to the upper bound (conservative)",
                 id_switches=pooled_rate(T["id_census"], T["id_unclear"], T["sample_id_changed"], T["sample_answered"],
                                         T["unflagged"], T["counted"]),
                 double_counts=pooled_rate(T["dc_census"], T["dc_unclear"], T["sample_counted_twice"], T["sample_answered"],
                                           T["unflagged"], T["counted"]),
                 per_clip=per)
    pc.write_json(out / "tracking_rates.json", rates)
    fmt = lambda r: (f"{r['per_100']} per 100 counted vehicles (95% CI {r['ci95_per_100'][0]}–{r['ci95_per_100'][1]}; "  # noqa: E731
                     f"census alone {r['census_only_per_100']})")
    i, dc = rates["id_switches"], rates["double_counts"]
    L += ["", f"Pooled over {', '.join(rates['clips'])}: {T['counted']} pipeline-counted vehicles, {T['unflagged']} unflagged, "
              f"{T['sample_answered']} sampled and answered. ID switches and fragments: {i['census']} confirmed + "
              f"{i['sample_events']}/{i['sample_answered']} in the sample → {fmt(i)}. Double counts (same and other camera): "
              f"{dc['census']} confirmed + {dc['sample_events']}/{dc['sample_answered']} in the sample → {fmt(dc)}. "
              "The CI adds exact bounds (conservative); `tracking_rates.json`."]
    if mov:
        pc.write_csv(out / "heading_exit_checks.csv", mov)
        L += ["", "| Exit method | Approach | Answered | Correct | Accuracy % | Cannot tell |", "|---|---|---|---|---|---|"]
        for meth in ("heading", "gate"):
            for ap in ["all"] + sorted({m["approach"] for m in mov}):
                s = [m for m in mov if m["method"] == meth and (ap == "all" or m["approach"] == ap)]
                ok = [m for m in s if m["reviewer"] != "cannot tell"]
                good = sum(m["reviewer"] == m["pipeline"] for m in ok)
                if s:
                    L.append(f"| {meth} | {ap} | {len(ok)} | {good} | {100 * good / len(ok):.1f} | {len(s) - len(ok)} |" if ok
                             else f"| {meth} | {ap} | 0 | 0 | – | {len(s)} |")
    rep.append("\n".join(L) + "\n")


def queues(a, out, rep):
    q = pc.read_csv(a.queue_dir / "queue_recount.csv")
    if not q:
        rep.append("## D. Queue recount\n\nNot yet available.\n")
        return
    ref = {(r["approach"], r["cycle"]): r for r in pc.read_csv(QUEUES28)}
    rows = []
    for r in q:
        o = ref.get((r["approach"], r["cycle"]))
        if o is None:
            continue
        beyond = r["beyond_view"] == "y" or o["queue_beyond_view"] == "y"
        rows.append(dict(approach=r["approach"], cycle=r["cycle"], recount=int(r["n_vehicles"]), ryzhanskyi=int(o["queue_veh"]),
                         difference=int(o["queue_veh"]) - int(r["n_vehicles"]), recount_beyond_view=r["beyond_view"],
                         ryzhanskyi_beyond_view=o["queue_beyond_view"],
                         queue_length="lower bound (visible part)" if beyond else "complete"))
    if not rows:
        rep.append("## D. Queue recount\n\nNot yet available: no recounted frame matches the 28 Oct queues.\n")
        return
    pc.write_csv(out / "queue_recount_comparison.csv", rows)

    def agree(rs):
        d = np.array([r["difference"] for r in rs], float)
        return (f"{len(rs)} frames: mean difference {d.mean():+.2f} vehicles, mean absolute difference {np.abs(d).mean():.2f}, "
                f"max {np.abs(d).max():.0f}") if rs else "no frames"
    full = [r for r in rows if r["queue_length"] == "complete"]
    cens = [r for r in rows if r["queue_length"] != "complete"]
    rep.append("## D. Queue recount (Ryzhanskyi's end-of-red queue minus A1's recount)\n\n"
               "Both counted the visible standing vehicles on the same frame. Where either marked the queue as continuing "
               "beyond the view, both numbers are visible counts and only lower bounds of the queue length.\n\n"
               f"- Visible-count agreement, all frames: {agree(rows)}; "
               + "; ".join(f"{ap} {np.mean([r['difference'] for r in rows if r['approach'] == ap]):+.1f}"
                           for ap in sorted({r['approach'] for r in rows})) + ".\n"
               f"- Complete queues (neither beyond the view): {agree(full)}.\n"
               f"- Lower bounds (beyond the view): {agree(cens)}; "
               + (", ".join(f"{r['approach']} c{r['cycle']} ≥{max(r['recount'], r['ryzhanskyi'])}" for r in cens) or "none") + ".\n"
               "- Recount time: not reported. The `seconds` field of queue_recount.csv is the time the session was open, "
               "not the annotation time (acceptance record of 3 Nov).\n")


def setup(a, out, rep):
    L = []
    for who, d in (("A1", a.setup_dir), ("second person", a.setup_dir2)):
        for cam in ("center", "zarich"):
            p = d / f"{cam}_gates_redo.json"
            if p.exists():
                g = pc.read_json(p)
                cmp_ = d / f"{cam}_compare.md"
                fin = g.get("finished") or "no, quit with Esc"
                L.append(f"{who}, {cam}: {len(g.get('gates', []))} lines in {g.get('active_seconds', 0) / 60:.1f} min "
                         f"active time (finished: {fin}); comparison: "
                         f"{pc.posix(cmp_) if cmp_.exists() else 'not run yet'}.")
                if cmp_.exists():   # the comparison's headline lines (count effect)
                    L += [f"  {ln.lstrip('- ')}" for ln in cmp_.read_text(encoding="utf-8").splitlines()
                          if ln.startswith(("- Movements counted", "- Original movements", "- Heading-fallback",
                                            "Demand cells"))]
    rep.append("## E. Set-up redo\n\n" + ("\n".join(L) if L else "Not yet available.") + "\n")


def section(rep, title, fn, *args):
    """Run one section; a failure is noted in the report instead of losing the other sections."""
    try:
        return fn(*args)
    except (Exception, SystemExit) as e:  # noqa: BLE001
        rep.append(f"## {title}\n\nFAILED: {type(e).__name__}: {e}\n")
        FAILED.append(title)
        return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--manual-dir", type=Path, default=pc.OUT / "manual_counts")
    ap.add_argument("--second-dir", type=Path, default=pc.OUT / "counter2" / "manual_counts",
                    help="second counter (default: the second person on this laptop; Ryzhanskyi's helper: revision/perception/second_counter)")
    ap.add_argument("--review-dir", type=Path, default=pc.OUT / "tracking_review")
    ap.add_argument("--queue-dir", type=Path, default=pc.OUT / "queue_recount")
    ap.add_argument("--setup-dir", type=Path, default=pc.OUT / "setup_redo")
    ap.add_argument("--setup-dir2", type=Path, default=pc.OUT / "counter2" / "setup_redo")
    ap.add_argument("--allow-unblind", action="store_true", help="(synthetic tests only) run A-C without FINAL.json")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    rep = ["# Comment 1.3 perception metrics", "",
           f"Generated {pc.now_iso()} by `revision/tools/perception_metrics.py`. Pipeline counts: the movement files of "
           "28 Oct (owned approaches, t_common window of each clip). Hand counts: `perception_count.py`, as frozen by "
           "FINAL.json.", ""]
    cells = section(rep, "A. Counting", counting, a, a.out, rep)
    section(rep, "B. Second counter", second_counter, a, a.out, rep, cells)
    section(rep, "C. Tracking review", review, a, a.out, rep, cells)
    section(rep, "D. Queue recount", queues, a, a.out, rep)
    section(rep, "E. Set-up redo", setup, a, a.out, rep)
    (a.out / "perception_1_3_report.md").write_text("\n".join(rep) + "\n", encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # the Windows console code page lacks ≥ and →
    print("\n".join(rep))
    if FAILED:
        sys.exit(f"sections failed: {', '.join(FAILED)} (see the report)")


if __name__ == "__main__":
    main()
