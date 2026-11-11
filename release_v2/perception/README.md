# Blind hand counts and tracking review (pseudonymised)

Two people counted vehicles by hand, blind to the pipeline's counts, on two 5-min clips (common time 300–600 s) of the two cameras: `center_i300` (approaches SVB_N, PRB_E) and `zarich_i300` (SVB_S, PRB_W). A1 is the first counter, A2 the second. Only A1's event log is released; A2's is not. Each approach was counted in its own pass, at 1× speed, one key press per vehicle and movement. A1 also answered the tracking review. No frames or crops are included.

## `hand_counts/A1`

`events.csv`, one row per key press:

| Column | Meaning |
|---|---|
| `annotator` | A1 |
| `event_id` | Running number within the clip, in the order the presses were made |
| `clip`, `camera`, `interval` | Clip id, camera (`center`, `zarich`), 5-min interval (`i300` = 300–600 s) |
| `approach` | SVB_N, SVB_S (Svobody), PRB_E, PRB_W (Prybuzka) |
| `movement` | L left, T through, R right, U U-turn |
| `t_clip_s`, `t_common_s` | Time of the press in the clip and on the common time base of both cameras (s) |
| `frame` | Video frame at the press (25 fps) |
| `speed` | Playback speed (1.0 = real time) |
| `unsure` | 1 if the counter marked the press as unsure |
| `deleted` | 1 if the counter deleted the press as a correction (deleted presses are not counted) |
| `session_no` | Counting session, numbered in time order per annotator |

`counts_5min.csv`: the closed counts per camera, approach and movement for the 5-min interval, with the number of unsure presses and the share of the clip watched (`watched_pct`).

`coverage.json`: the close record (clips, watched share per approach, warnings, SHA-256 of the original files at close), and per clip the sessions (approaches, seconds) and the seconds of video watched per approach.

Removed: names and initials, session ids, wall-clock times of presses and deletions, file paths.

## `tracking_review/<clip>`

`candidates.csv`: the review items built from the pipeline's tracks (seeded, `build_meta.json`): candidate id, type (`movement` exit checks by gate or heading, `break` possible ID switches or fragments, `uncounted`, `manual_only`, `pipeline_only`, `vehicle` control sample, `jump`, `break_double`), clip time, the tracks involved, the approach, the question shown and the pipeline's movement.

`review.csv`: the answer to each candidate (`annotator` A1, `cand_id`, `type`, `answer`, `seconds` spent). Wall-clock times removed.

The metrics computed from these files and from A2's unreleased log (counting error against the pipeline, agreement of A1 and A2, tracking error rates, movement accuracy) are in `results/analysis/perception/`; the code is `code/tools/perception_metrics.py` and `perception_adjudicate.py`.
