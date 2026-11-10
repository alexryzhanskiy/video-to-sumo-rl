# B6 twin calibration: protocol (draft for the E13 pre-registration)

Written 29 Oct 2026 by the perception & twin session, before any fit was run. Internal. Status: **draft, waiting for the lead's OK**. Nothing in sections 3–7 has been run yet. Section 1 lists the only runs made so far: feasibility checks, not fits.

## 1. Pre-fit facts (already checked)

All checks use SUMO 1.26.0 (`revision/.venv`). Outputs are in `revision/twin/unit_tests/` (`unit_tests.json`); the script is `revision/tools/twin_sumo_unit_tests.py`.

- **`startupDelay` exists in SUMO 1.26.0 and acts.** On the original demand (seed 1, field plan, 1500 s), a `DEFAULT_VEHTYPE` with `startupDelay="1.5"` changes the tripinfo: 1200 instead of 1283 vehicles arrive. With `startupDelay="0"` the run is identical to the default.
  - SUMO applies the delay after every stop.
  - A fractional delay reduces the first step's speed in proportion, so values below the 1-s step length are meaningful.
- **How the calibrated type reaches every route file.** No route file defines a vType, so every vehicle uses `DEFAULT_VEHTYPE`.
  - Calibrated runs load one additional file, `revision/twin/calibrated_vtype.add.xml`, which holds `<vType id="DEFAULT_VEHTYPE" startupDelay=".." tau=".." accel=".."/>`.
  - Pass it with `-a` / `--additional-files`, comma-separated with any other additional file, or as `<additional-files>` in a `.sumocfg`.
  - Additional files are loaded before the routes, so the override applies to every vehicle. The tripinfo still says `vType="DEFAULT_VEHTYPE"`.
  - Unit test: overrides with SUMO's default values (`<vType id="DEFAULT_VEHTYPE"/>`; `startupDelay="0"`; explicit `tau="1" accel="2.6" decel="4.5" sigma="0.5"`) give a tripinfo **byte-identical** to the run without the file (header comment removed).
  - Condition: no route file may define `DEFAULT_VEHTYPE` itself. RESCO and E13 must pass the file in every run, including training, evaluation and baselines.
- **Tripinfo with unfinished and never-inserted vehicles (for pre-registration section 4).** Synthetic case on the repository network, end at 60 s:

  | Vehicle state at the end | `write-unfinished` only | `write-unfinished` + `write-undeparted` |
  |---|---|---|
  | arrived | written, `arrival` ≥ 0 | same |
  | inserted, still driving | written: `arrival="-1.00"`, `vaporized="end"`, `duration` = end − depart, `timeLoss` / `waitingTime` up to the end | same |
  | due but not yet inserted (insertion backlog) | **not written** (10 of 40 queued vehicles written, 30 missing) | written: `depart="-1"`, `departDelay` = end − planned depart, `duration` / `routeLength` / `timeLoss` / `waitingTime` = 0, `vaporized="end"` |
  | planned depart after the end (even if already loaded by the 200-s look-ahead) | not written | not written |

  Consequences:
  - With `write-unfinished` alone (the E3/E12 kit), never-inserted vehicles are missing. They must be counted as demand due by the end minus tripinfo entries.
  - A total delay that includes unserved vehicles must add each written vehicle's `departDelay` to its `timeLoss`. For never-inserted vehicles, `departDelay` is their only delay, and it is written only with `write-undeparted`.
  - Recommendation: run E13 with both options.

## 2. Question and data

- **Question.** Do three driver parameters of SUMO's default Krauss vehicle make the fixed-plan twin reproduce the discharge observed in the video better than the default vehicle, on signal cycles not used for fitting?
- **Parameters:**
  - `startupDelay`: extra delay before a stopped vehicle starts;
  - `tau`: desired time headway;
  - `accel`: maximum acceleration.
- **Kept at SUMO defaults:** `decel` 4.5, `sigma` 0.5, `length` 5, `minGap` 2.5, the speed-factor distribution, the 1-s step length, and `--time-to-teleport -1`.
- **Observed data.** Ryzhanskyi's files, as in E8 (`revision/incoming/2026-10-26/validation/validation_1_2/`):
  - `discharge_headways.csv`: crossing times, positions and headways;
  - `observed_queue.csv`: the `discharged_queue` column.
  - The 28 Oct `1.2_discharge.csv` holds the same crossings without 20 trailing non-queue crossings, which do not change these metrics.
  - Cycles 2–12. Cycle 1 is excluded: the simulation starts empty.
- **Simulated runs per parameter set (15 runs, ×1.0 demand):**
  - `sumo/demand.rou.xml` with SUMO seeds 1–5;
  - the E12 training realizations `revision/demand/train/x10/train_x10_s3001…s3010.rou.xml` with SUMO seed 1.
  - The held-out ("test A") files and any E13 validation or locked-test file are not used.
  - **Lead: confirm that 3001–3010 are not E13 validation or test files.**
  - Network `sumo/intersection.net.xml`; field plan shifted as in E8 (offset 16 s, so the Svobody green starts at 16 s and the Prybuzka green at 84 s; `run_meta.json` of E8); end 1500 s.
  - The same seeds for every parameter set (common random numbers).

## 3. Measured quantities (identical definitions for observed and simulated)

Per approach *a* ∈ {SVB_N, SVB_S, PRB_E, PRB_W} and cycle *k*, using Ryzhanskyi's rules, which E8 already uses:

- Crossings of all lanes of the approach in the green + yellow window: Svobody 49 s, Prybuzka 33 s.
- The discharging queue starts if the first vehicle crosses ≤ 8 s after green, and ends at the first gap > 8 s. Headways count as saturated from queue position 4.
- **t1**: time from the green onset to the first crossing (position 1). This is the start-up quantity. It includes reaction and the distance from the stopping point to the stop gate, so the fitted `startupDelay` is an effective value.
- **h**: saturated headway (s), pooled over the cycles.
- **q**: discharged queue, the number of vehicles in the discharging queue.

Statistics per approach and set of cycles: median t1, median h, mean q. Simulated values pool the 15 runs.

Simulated crossing times come from `instantInductionLoop` detectors at the end of every approach lane (no TraCI, so a run takes about 1 s).

**Measurement check before the grid** (gate): at the default parameters, the detector-based values must reproduce the TraCI-based E8 values (`revision/runs/e8_validation/sim_discharge_headways.csv`) for the 5 original-demand runs:

- the same q for every cycle;
- t1 and h within 0.01 s.

If this fails, the grid uses the E8 TraCI extraction instead (slower, same definitions).

Also before the grid: the default point is run on the laptop and on Colab, and the per-cycle results must be identical.

## 4. Split

- **Fold A (primary):** fit on the even cycles {2, 4, 6, 8, 10, 12}; check on the odd cycles {3, 5, 7, 9, 11}.
- **Fold B (swap check):** fit on odd, check on even.
- The same cycle numbers are used on both sides.
- Observed sample per half and approach: 6 or 5 cycles for t1 and q; 30–161 saturated headways for h.

## 5. Objective and search

Objective on the fit half, the mean of three equally weighted blocks of squared relative errors:

J(θ) = ⅓ [ ¼ Σₐ ((t1ₐˢⁱᵐ − t1ₐᵒᵇˢ)/t1ₐᵒᵇˢ)² + ¼ Σₐ ((hₐˢⁱᵐ − hₐᵒᵇˢ)/hₐᵒᵇˢ)² + ¼ Σₐ ((qₐˢⁱᵐ − qₐᵒᵇˢ)/qₐᵒᵇˢ)² ]

Exhaustive grid of 13 × 11 × 6 = **858 parameter sets** × 15 runs = 12,870 SUMO runs. The grid includes the default θ0 = (0, 1.0, 2.6).

| Parameter | Grid | Default | Reason for the range |
|---|---|---|---|
| `startupDelay` (s) | 0, 0.25, …, 3.0 | 0 | observed first crossings of 2.2–3.1 s against 0.4 s in the default twin |
| `tau` (s) | 1.0, 1.1, …, 2.0 | 1.0 | below 1.0 is below the 1-s step length (SUMO warns); the default twin already discharges too fast (E8: −5 to −16%) |
| `accel` (m/s²) | 1.0, 1.4, 1.8, 2.2, 2.6, 3.0 | 2.6 | plausible passenger-car start-up accelerations, on both sides of the default |

- **Selection:** θ* = argmin J on the fit half.
- **Ties:** among the points with J ≤ 1.01 × J_min, take the one closest to θ0 in range-normalized Euclidean distance. Remaining ties go to the smaller `startupDelay`, then the smaller `tau`, then the larger `accel`.
- No refinement and no second grid.

## 6. Success criterion (decided now; evaluated on the check half)

Errors on a set of cycles, for a parameter set θ:

- **E_su(θ)** = mean over the 4 approaches of |median t1ˢⁱᵐ − median t1ᵒᵇˢ| (s);
- **E_h(θ)** = mean over the 4 approaches of |median hˢⁱᵐ − median hᵒᵇˢ| / median hᵒᵇˢ (percentage points);
- **E_q(θ)** = mean over the 4 approaches of |mean qˢⁱᵐ − mean qᵒᵇˢ| (vehicles).

**Success** if all three hold on the check half **in both folds**, with θ0 = the default vehicle:

1. **Start-up:** E_su(θ*) ≤ 0.5 × E_su(θ0). The start-up error is at least halved.
2. **Headway:** E_h(θ*) ≤ E_h(θ0) − 2.0 percentage points. On all cycles, the default twin's E_h is 10% (E8).
3. **Queue:** E_q(θ*) ≤ E_q(θ0) + 0.5 vehicles (tolerance). On all cycles, the default twin's E_q is 2.0 vehicles (E8).

**Outcomes:**

- **Success:** the adopted vehicle is θ* of fold A (fit on even cycles). It is written to `revision/twin/calibrated_vtype.add.xml`, and all new runs use it (agreed plan).
- **Failure in either fold:** the plan continues on the current twin (default vehicle). The calibration is reported as a negative result in the Supplementary Information.
- **Deadline:** if the grid has not finished by Sun 1 Nov 20:00, the criterion is treated as not met.

**Reported, but not part of the criterion:**

- J for both folds; θ* of fold B and of all cycles 2–12;
- the HCM start-up lost time t4 − 4·h;
- the end-of-red queue: the E8 rerun with the per-lane visible cap (SVB_N 9, SVB_S 5 vehicles per lane; PRB_E and PRB_W in full), on the default and the calibrated twin;
- throughput of the fixed plan on the 15 runs (arrived by 1500 s and by 1800 s, and never-inserted vehicles);
- a plausibility flag. If the adopted θ* leaves more than 1% of the ×1.0 demand unserved by 1800 s with the field plan (original demand, seeds 1–5), the session tells the lead before adoption. The counted field flows were served in reality, so a twin that cannot serve them is suspect. The decision then rests with the lead and Pavlo.

## 7. Execution, files and deadline

- **Where:** Google Colab, CPU High-RAM runtime, driven by the perception & twin session in Pavlo's Chrome.
- **Software:** `eclipse-sumo==1.26.0` (and libsumo 1.26.0 for parity, although the grid needs no TraCI); `OMP_NUM_THREADS=1 MKL_NUM_THREADS=1`; one SUMO process per CPU core.
- **Uploaded to Colab:** only `sumo/intersection.net.xml`, the 6 route files of section 2, the E8 shift file, the detector file, and the scripts `revision/tools/twin_b6_grid.py` and `twin_b6_fit.py`. No video, kb, manuscript or review material.
- **Restarts:** each finished parameter set is written at once to Google Drive (`MyDrive/B6/results/<set>.json`), and a restart skips finished sets.
- **Runtime:** 12,870 runs at about 1 s is about 3.6 CPU-hours, so under 1 h on 8 cores.
- **Deliverables by the evening of Sun 1 Nov:**
  - `revision/twin/B6_calibration_report.md`;
  - `revision/twin/B6/grid_results.csv`, with every θ, fold and half, and all metrics;
  - `calibrated_vtype.add.xml`, only on success;
  - a message to the lead saying whether the criterion was met.
- **Deviations** from this protocol after the freeze are listed in the report with the reason.
