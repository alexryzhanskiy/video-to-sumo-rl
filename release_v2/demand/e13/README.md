# E13 demand sets (validation, locked test, L4 training mix)

Generated on 29 Oct 2026 for experiment E13, following `revision/prereg/E13_preregistration_v1.md` section 3 (not edited). Files only: no controller and no training was run. SUMO 1.26.0 (eclipse-sumo wheel in `revision/.venv`), routeSampler from that installation, candidate routes `sumo/candidate.rou.xml`. Seeds are disjoint from every earlier set (held-out 1001–1010, scenarios 2001–2005 and 52001–52005, E12 training 3001–3020, originals 42).

## Contents and file counts

| Folder | Content | Route files | Seeds |
|---|---|---|---|
| `validation/x10`, `x12`, `x15` | routeSampler realizations of the ×1.0 / ×1.2 / ×1.5 counts, made exactly like the held-out files | 10 + 10 + 10 | 4001–4010 (each load) |
| `validation/scenarios/S1`–`S4` | S1–S4 test scenarios (same parameters as `revision/demand/scenarios`), `make_scenarios.py` | 2 per scenario = 8 | 4101–4102 (S2 Prybuzka axis: 54101–54102) |
| `locked_test/x10`, `x12`, `x15` | as validation | 10 + 10 + 10 | 5001–5010 (each load) |
| `locked_test/scenarios/S1`–`S4` | as validation scenarios | 5 per scenario = 20 | 5101–5105 (S2 Prybuzka axis: 55101–55105) |
| `mix/x08`, `x10`, `x12`, `x14`, `x16` | L4 training mix, proportional loads ×0.8 / ×1.0 / ×1.2 / ×1.4 / ×1.6 | 6 each = 30 | 6001–6006, 6007–6012, 6013–6018, 6019–6024, 6025–6030 |
| `mix/perturbed` | L4 training mix, S1–S4-type perturbations on a base load in [1.0, 1.4] | 30 (S1 8, S2 8, S3 7, S4 7) | 6031–6060 (S2 Prybuzka axis: seed + 50000) |
| `mix/counts` | turn counts ×0.8, ×1.4, ×1.6 (totals 1084, 1900, 2165) | – | – |
| `mix/perturbed/counts` | per perturbed file: base-load counts, transformed counts (S1/S3/S4) or axis counts (S2), rounding logs | 90 files | – |
| `work/{validation,locked,mix}_S2_parts` | S2 per-axis routeSampler outputs before merging | 4 + 10 + 16 | – |

Totals: validation 38, locked test 50, mix 60 route files. Each set has its own `generation_log.json` (command, counts file, seeds, expected total, SUMO version, creation time per file); the scenario folders also hold `scenario_params.json`, the scenario turn counts, rounding logs and `SCENARIOS.md`.

## Methods

**Load factors ×1.0, ×1.2, ×1.5 (validation, locked test, mix ×1.0/×1.2).** `make_heldout.py`: `routeSampler -r sumo/candidate.rou.xml -t <counts> -o <out> --seed <s>`, default options otherwise, counts `sumo/turn_counts_edges.xml`, `sumo/turn_counts_12.xml`, `sumo/turn_counts_15.xml`, timestamp removed from the header. This is the held-out method of P01; only the seeds and the `--kind` (file prefix and logged purpose) differ.

**How ×1.2 and ×1.5 were derived, and the new factors.** No script in the repository writes scaled counts; the rule was recovered from the files. `sumo/turn_counts_12.xml` and `sumo/turn_counts_15.xml` equal, in all 60 (interval, relation) cells, the ×1.0 count × factor rounded to the nearest integer with ties to even (Python `round()`), with no adjustment of the total. ×1.5 has 25 ties, all resolved to even (for example 7 × 1.5 = 10.5 → 10); round-half-up would miss 9 cells. Hence the ×1.5 total is 2036, not 2032.5. `make_mix_e13.py counts` applies the same rule. It first checks that the rule reproduces both repository files and stops if it does not. The new factors give ×0.8 = 1084 (exact 1084.0), ×1.4 = 1900 (exact 1897.0) and ×1.6 = 2165 (exact 2168.0) vehicles. For 0.8, 1.4 and 1.6 no ties are possible. Then routeSampler is run as above.

**Validation and locked-test scenarios.** `make_scenarios.py` with a copy of `revision/demand/scenarios/scenario_params.json` in which only the `seeds` line differs (`[4101, 4102]`, `[5101, 5102, 5103, 5104, 5105]`). That means S1 Svobody through + left ×1.3, S2 40-s window per 120-s cycle at offsets 0/60 s, S3 peak share 0.5 in 600–1200 s, and S4 left ×1.4.

**Perturbed mix (`make_mix_e13.py`, new).** The existing tools cannot put a scenario on a base load, because `make_scenarios.py` always starts from the ×1.0 counts. The new script adds only that step and reuses the unchanged functions of `make_scenarios.py` (`build_s1`, `build_s3`, `build_s4`, `split_axis`, `s2_density`, `merge_parts`, `window_shares`):

1. The ×1.0 counts are scaled to the file's base load with the rule above (ties to even).
2. The S-type transform of `make_scenarios.py` is applied to the scaled counts, with that file's parameters (S1/S3 largest-remainder rounding, S4 round-half-up, as in the test scenarios).
3. routeSampler runs with the file's seed. For S2 there is one run per axis with `--depart-distribution`, seeds s and s + 50000 and prefixes `sv_`/`pr_`, and the two outputs are merged and sorted. The first header line names `make_mix_e13.py`.

`make_mix_e13.py draw` wrote all parameters to `mix/mix_params.json` before any mix file was generated. That file has SHA-256 `6e7f7793d03981fff9b0b7aa87ad30ca262893ecc61a53e5d8e148c1e43dbd67`, and the script refuses to overwrite it. The draw rules:

- **RNG:** `numpy.random.default_rng(6000)`. For each perturbed file in seed order it draws the base load ~ U[1.0, 1.4], then the type parameter(s).
- **Rounding:** loads, factors and shares to 4 decimals; S2 times to 0.1 s.
- **Type order:** fixed. Seed 6031 + i gets type i mod 4 (S1, S2, S3, S4, S1, …), which gives S1 8, S2 8, S3 7 and S4 7 files.
- **S1:** factor ~ U[1.1, 1.4].
- **S2:** window ~ U[30, 50] s and a common offset shift δ ~ U[−20, 20] s. Offsets are δ mod 120 (Svobody) and (60 + δ) mod 120 (Prybuzka), so the test's 60-s separation is kept.
- **S3:** peak_share ~ U[0.4, 0.6], in the peak window 600–1200 s.
- **S4:** left_factor ~ U[1.2, 1.6], i.e. ±0.2 around the test value 1.4.
- **Fixed parameters:** all other scenario parameters are those of the test scenarios.
- **Exclusion rule:** redraw if the base load is 1.0 or the randomised parameters equal the test values. There were 0 redraws, so no parameter set equals a test scenario.

| Seed | Type | Base load | Type parameter(s) | Vehicles | T1800 (fixed plan) | Mean departDelay (s) | Sanity flags |
|---|---|---|---|---|---|---|---|
| 6031 | S1 | 1.2471 | factor 1.3947 | 2025 | 1716 | 176.80 | T1800, departDelay |
| 6032 | S2 | 1.1915 | window 35.4 s, offsets 112.4/52.4 s | 1612 | 1602 | 44.74 | – |
| 6033 | S3 | 1.1242 | peak_share 0.5443 | 1524 | 1524 | 60.22 | departDelay |
| 6034 | S4 | 1.1419 | left_factor 1.4748 | 1548 | 1255 | 113.27 | T1800, departDelay |
| 6035 | S1 | 1.0012 | factor 1.1989 | 1493 | 1493 | 21.83 | – |
| 6036 | S2 | 1.0342 | window 36.4 s, offsets 106.5/46.5 s | 1397 | 1397 | 16.35 | – |
| 6037 | S3 | 1.0693 | peak_share 0.5278 | 1450 | 1450 | 41.23 | – |
| 6038 | S4 | 1.0649 | left_factor 1.3292 | 1440 | 1361 | 42.68 | – |
| 6039 | S1 | 1.0588 | factor 1.1737 | 1563 | 1520 | 43.53 | – |
| 6040 | S2 | 1.3408 | window 43.8 s, offsets 4.9/64.9 s | 1811 | 1663 | 104.77 | departDelay |
| 6041 | S3 | 1.3612 | peak_share 0.4476 | 1846 | 1729 | 89.05 | departDelay |
| 6042 | S4 | 1.1574 | left_factor 1.3833 | 1569 | 1358 | 84.41 | departDelay |
| 6043 | S1 | 1.2190 | factor 1.1486 | 1784 | 1656 | 89.50 | departDelay |
| 6044 | S2 | 1.0492 | window 46.0 s, offsets 15.9/75.9 s | 1421 | 1421 | 14.69 | – |
| 6045 | S3 | 1.0169 | peak_share 0.4181 | 1368 | 1368 | 5.46 | – |
| 6046 | S4 | 1.0341 | left_factor 1.2072 | 1397 | 1382 | 21.44 | – |
| 6047 | S1 | 1.0425 | factor 1.1076 | 1495 | 1495 | 15.95 | – |
| 6048 | S2 | 1.2297 | window 38.4 s, offsets 108.6/48.6 s | 1666 | 1624 | 52.37 | – |
| 6049 | S3 | 1.0389 | peak_share 0.5082 | 1409 | 1409 | 24.43 | – |
| 6050 | S4 | 1.1789 | left_factor 1.4493 | 1596 | 1282 | 116.99 | T1800, departDelay |
| 6051 | S1 | 1.3690 | factor 1.1673 | 2013 | 1774 | 147.86 | departDelay |
| 6052 | S2 | 1.3183 | window 40.4 s, offsets 17.2/77.2 s | 1783 | 1655 | 96.22 | departDelay |
| 6053 | S3 | 1.0747 | peak_share 0.4890 | 1461 | 1461 | 25.49 | – |
| 6054 | S4 | 1.2274 | left_factor 1.2282 | 1664 | 1516 | 79.75 | departDelay |
| 6055 | S1 | 1.2156 | factor 1.2672 | 1881 | 1694 | 122.74 | departDelay |
| 6056 | S2 | 1.2684 | window 46.1 s, offsets 19.7/79.7 s | 1717 | 1677 | 63.42 | departDelay |
| 6057 | S3 | 1.1793 | peak_share 0.4989 | 1596 | 1593 | 50.59 | – |
| 6058 | S4 | 1.2835 | left_factor 1.5143 | 1740 | 1280 | 165.59 | T1800, departDelay |
| 6059 | S1 | 1.3211 | factor 1.2972 | 2059 | 1771 | 172.19 | departDelay |
| 6060 | S2 | 1.1977 | window 49.6 s, offsets 13.1/73.1 s | 1624 | 1601 | 47.07 | – |

**S2 window shares.** The achieved in-window shares are 75.5–84.2%, against 80.7–87.6% from the continuous formula w / (w + 0.1 (120 − w)). The cause is that `make_scenarios.s2_density` works in 5-s bins. A window edge that falls inside a bin spreads that bin's vehicles over the whole bin. The test scenario's edges (0, 40, 60, 100 s) lie on bin limits, so it is unaffected. With the binning taken into account, the expected shares agree with the achieved ones within 2.5 percentage points per axis (computed from `s2_density`; per-file values are in `mix/generation_log.json`, `window_share`).

## Commands (from the repository root)

`SUMO_HOME=revision/.venv/Lib/site-packages/sumo` (absolute path), `PY=revision/.venv/Scripts/python.exe`, `E=revision/demand/e13`. The tools import `demandlib` from their own folder, which `-I` prevents (it implies `-P`). They were therefore run with `-E -s`. routeSampler is called by the tools with the plain interpreter, as in P01.

```
$PY -E -s revision/tools/make_heldout.py --candidate sumo/candidate.rou.xml --load x10=sumo/turn_counts_edges.xml --load x12=sumo/turn_counts_12.xml --load x15=sumo/turn_counts_15.xml --seeds 4001-4010 --kind validation --out-dir $E/validation
$PY -E -s revision/tools/make_scenarios.py --candidate sumo/candidate.rou.xml --base-counts sumo/turn_counts_edges.xml --params $E/validation/scenarios/scenario_params.json --out-dir $E/validation/scenarios --work-dir $E/work/validation_S2_parts
$PY -E -s revision/tools/make_heldout.py ... --seeds 5001-5010 --kind locked --out-dir $E/locked_test        (same --load options)
$PY -E -s revision/tools/make_scenarios.py ... --params $E/locked_test/scenarios/scenario_params.json --out-dir $E/locked_test/scenarios --work-dir $E/work/locked_S2_parts
$PY -E -s revision/tools/make_mix_e13.py draw --test-params revision/demand/scenarios/scenario_params.json --out $E/mix/mix_params.json
$PY -E -s revision/tools/make_mix_e13.py counts --base-counts sumo/turn_counts_edges.xml --check x12=sumo/turn_counts_12.xml --check x15=sumo/turn_counts_15.xml --factor x08=0.8 --factor x14=1.4 --factor x16=1.6 --out-dir $E/mix/counts
$PY -E -s revision/tools/make_heldout.py --candidate sumo/candidate.rou.xml --load x08=$E/mix/counts/turn_counts_x08.xml --seeds 6001-6006 --kind mix --out-dir $E/mix
   (likewise x10=sumo/turn_counts_edges.xml 6007-6012; x12=sumo/turn_counts_12.xml 6013-6018; x14=$E/mix/counts/turn_counts_x14.xml 6019-6024; x16=$E/mix/counts/turn_counts_x16.xml 6025-6030)
$PY -E -s revision/tools/make_mix_e13.py perturbed --candidate sumo/candidate.rou.xml --base-counts sumo/turn_counts_edges.xml --params $E/mix/mix_params.json --out-dir $E/mix --work-dir $E/work/mix_S2_parts
```

`make_heldout.py` received three new `--kind` values (`validation`, `locked`, `mix`). They set the file prefix and the logged purpose only; `heldout` and `train` are unchanged.

## Checks

**Static checks** (`check_demand.py` over the old and new logs together, so that distinctness covers all sets): report in `check_report.csv`. 258 files were checked and 253 pass.

- All 50 locked-test files pass, as do all 30 validation load files.
- 5 files fail `counts_match` (one also fails `in_range`): `validation/scenarios/S3/scenario_S3_s4102`, `mix/x08/mix_x08_s6005`, `mix/x14/mix_x14_s6022`, `mix/x16/mix_x16_s6026`, and the existing E12 file `revision/demand/train/x10/train_x10_s3015` (not touched).
- The cause is the same in all five. One vehicle drawn in the last 0.005 s of an interval is written by routeSampler with two decimals as exactly the interval end. For example, vehicle `1200_211` gets `depart="1500.00"`, and `600_351` gets `900.00`. Its ID still names the interval it was drawn for. Counting such a departure in the interval that ends there, all five files match their counts exactly.
- This is a property of the held-out method (probability about 2% per file). The files were kept as generated.

**Seed overlap.** The routeSampler seeds of all generation logs were compared (originals 42, held-out, scenarios, E12 training, and the five new logs). No two sets share a seed.

**Determinism.** `validation_x12_s4005`, `mix_S1_s6031` and `mix_S2_s6032` were regenerated in place and are byte-identical to the first generation.

**Fixed-plan sanity runs** (`sanity_fixed.py` as in P01: field plan, end 1800 s, seed 1, no teleports; validation and mix only). The outputs are `sanity_fixed.csv` and `sanity_fixed_summary.md`, with tripinfo in `revision/runs/e13_demand_sanity/`. A file is flagged if T1800 < 0.85 × demand, if the mean wait exceeds 3 × that of the original ×1.0 file, or if the mean departDelay exceeds 60 s.

| Group | n | Demand | T1800 mean [min–max] | Mean departDelay (s) [min–max] | Flagged |
|---|---|---|---|---|---|
| validation ×1.0 | 10 | 1355 | 1355 | 6.0 [5.0–8.0] | 0 |
| validation ×1.2 | 10 | 1626 | 1615.9 [1607–1626] | 30.0 [21.2–35.0] | 0 |
| validation ×1.5 | 10 | 2036 | 1768.0 [1739–1804] | 167.7 [153.8–179.9] | 10, departDelay (accepted: same decision as held-out ×1.5, P01, 26 Oct) |
| validation S1 / S2 / S3 / S4 | 2 each | 1564 / 1355 / 1355 / 1355 | 1506.0 / 1355 / 1355 / 1292.5 | 50.9 / 14.3 / 19.8 / 34.4 | 0 |
| mix ×0.8 / ×1.0 / ×1.2 | 6 each | 1084 / 1355 / 1626 | 1084 / 1355 / 1618.8 | 2.4 / 5.4 / 30.6 | 0 |
| mix ×1.4 | 6 | 1900 | 1743.8 [1709–1794] | 120.6 [99.5–135.5] | 6, departDelay (open) |
| mix ×1.6 | 6 | 2165 | 1750.2 [1733–1780] | 211.3 [203.2–219.5] | 6, T1800 + departDelay (open) |
| mix perturbed S1 / S2 / S3 / S4 | 8 / 8 / 7 / 7 | 1493–2059 | per file above | 5.5–176.8 | 5 / 3 / 2 / 5 (open) |

The validation flags are the expected ×1.5 overload. In the mix, 27 of 60 training files are flagged (open, for Pavlo and the lead):

- all ×1.4 and ×1.6 files;
- the perturbed files with heavy base loads or heavy S1/S4 factors (per-file list in the table above).

No file gridlocked. There were no teleports, and the longest gap between arrivals in any of the 101 runs is 90 s (E12's deadlock definition is 300 s). Every run has at least 31 arrivals in 1500–1800 s.

## Locked test

The locked-test files were not simulated in any way. They were generated, checked statically, and hashed at once. `revision/prereg/locked_test_hashes.txt` holds 72 SHA-256 lines in `sha256sum` text format, with paths relative to `revision/`: every file under `demand/e13/locked_test/` and the S2 parts in `demand/e13/work/locked_S2_parts/`. Verify from `revision/` with `sha256sum -c --strict prereg/locked_test_hashes.txt`; it passed after all other work here.

## Notes

- `validation/scenarios/SCENARIOS.md` says "five realizations" (fixed text in `make_scenarios.py`); the validation set has two per scenario (seeds 4101–4102).
- `locked_test/generation_log.json` and `locked_test/scenarios/generation_log.json` contain creation times and are part of the hash list; do not regenerate or rewrite them.
