# Pre-registration of E13 (option B) — v1, frozen

Manuscript CSR-2026-08-0123. Draft of 29 Oct 2026 (Claude, lead session), from the decisions in `revision/reports/option_B_agreed_plan_2026-10-29.md`.

**Status: FROZEN on 29 Oct 2026 at 18:30 EET (UTC+2), approved by Pavlo Radiuk, before any E13 training or evaluation run.** The SHA-256 of this file and of the B6 protocol are in `E13_preregistration_v1.sha256`. Any change after this point is a deviation and is logged in section 11 with the date and reason.

Built before the freeze (code and tests only, no result files used for choices): the E13 kit, demand files, the replay tool and the calibration code.

## 0. Why this experiment

E12 (28 Oct) showed that every retrained DRL policy is below the field fixed plan on held-out demand. The E12 files point to three design causes:

- learning was still rising at episode 100;
- policies lock onto one phase (median 0 switches inside the deadlock window);
- there are no green-time limits, the phase order is free, and an all-red follows every switch.

E13 tests whether DRL designs with the constraints of a real controller, more training and varied training demand reach the fixed plan on new demand. E12 and E3 stay in the paper unchanged.

## 1. Simulation set-up (all E13 runs)

- **Network:** `sumo/intersection.net.xml` (signal `nC`), SUMO **1.26.0** with libsumo, `--time-to-teleport -1`, `--tripinfo-output.write-unfinished`, `--tripinfo-output.write-undeparted`, step 1 s.
- **Twin:** the calibrated vehicle type from B6 (section 8) if B6 meets its success criterion by Sun 1 Nov 20:00. It is passed to every E13 run (training, evaluation and baselines) as the additional file `revision/twin/calibrated_vtype.add.xml` (`-a`), which overrides `DEFAULT_VEHTYPE`; no route file defines a vType. Otherwise SUMO's default vehicle type is used, as in E3, E6 and E12. The choice is recorded in section 11 before the first E13 run.
- **Clearance:** 3 s yellow after every green that ends. A 4 s all-red only when the next green belongs to the other street (Svobody ↔ Prybuzka), exactly as in the field plan. This applies to the new DRL designs and to tuned MaxPressure. The fixed, actuated and Webster plans have it by construction.
- **Episode length:** 1800 s for every evaluation. Training uses 1500 s at ×1.0 and 1800 s at ×1.2 and ×1.5, as in E12; L4 uses 1800 s.
- **Phases** (index = RESCO action in E12):
  - 0 = Svobody through `[1,7]`;
  - 1 = Svobody left `[0,6]`;
  - 2 = Prybuzka through `[4,10]`;
  - 3 = Prybuzka left `[3,9]`.
  - Field order: 0 → 1 → 2 → 3 → 0.

## 2. Designs (the ladder)

All designs use the E12 code base (`revision/e12_kit`, RESCO copy).

- **Unchanged from E12:** algorithms (pfrl DQN for IDQN; MPLight), network architectures, hyperparameters, replay buffer, decision interval of 5 s, and the exploration schedule. Epsilon decays linearly from 1.0 to 0.0 over all training steps, as in E12.
- **Rewards** (4, as in E12):
  - IDQN-wait (`wait`);
  - IDQN-queue (`queue`, Eq. 18);
  - MPLight (`pressure`);
  - IDQN-pressure (`pressure_inout`).

| Rung | Change, cumulative | Training demand | Episodes | Rewards |
|---|---|---|---|---|
| L0 | E12 as trained (all-red at every switch, free order, no limits), re-evaluated frozen | E12 | 100 | 4 |
| L1 | + green limits: minimum 12 s, maximum 60 s, enforced by action masking (free order). + inputs: current phase one-hot and elapsed green time / 60 s appended to each state | E12 training files (20 per load) | 100 | 4 |
| L2 | + field phase order: 2 actions, "extend current green" or "go to the next phase in field order"; the same limits and inputs | as L1 | 100 | 4 |
| L3 | + longer training | as L1 | 300 | best 2 (rule 5.2) |
| L4 | + one general model for all loads, trained on varied demand (section 3) | mixed set | 300 | best 2 (rule 5.2) |

**Green limits in detail.**

- At a decision, "change" is allowed only if the current green has lasted ≥ 12 s.
- If the green would exceed 60 s by the next decision, the change is forced.
  - L1: to the phase with the highest Q-value among the other three.
  - L2–L4: to the next phase in the order.

**Base design for L3 and L4.** The better of L1 and L2 (rule 5.2).

**Seeds.**

- Training run k = 1..5: torch/NumPy/random seed 42 + k.
- SUMO training seeds as in E12.
- Evaluation episode of run k on file index e: SUMO seed 42 + 1000 + k + e, as in E12.

**Machines.** All DRL training and evaluation on MyPC (16 threads, `OMP/MKL=1`, libsumo), after the kit's `verify` passes there.

## 3. Demand sets

All are generated with routeSampler from the observed counts, like E12. Seeds are disjoint from every earlier set (held-out 1001–1010, scenarios 2001–2005, E12 training 3001–3020).

| Set | Use | Content | Seeds |
|---|---|---|---|
| Training, per load | L1–L3 | The E12 training files, 20 per load (×1.0, ×1.2, ×1.5) | 3001–3020 |
| Training, mixed | L4 | 60 files: 30 proportional (×0.8, ×1.0, ×1.2, ×1.4, ×1.6; 6 each) + 30 perturbed (S1–S4 types with randomised factors on loads in [1.0, 1.4]; parameters documented before generation, none equal to the test scenarios) | 6001–6060 |
| **Validation** | All choices (rules 5.2, 6.2) | 10 files per load (×1.0, ×1.2, ×1.5) + 2 per scenario type S1–S4 | 4001–4010; scenarios 4101–4102 |
| Test A | Continuity with E3, E6 and E12; exploratory | The existing held-out (30) and scenario (20) files | 1001–1010; 2001–2005 |
| **Locked test** | Run **once**, after all choices, for every rung, reward and baseline; confirmatory for the final design only | 10 files per load + 5 per scenario S1–S4 | 5001–5010; scenarios 5101–5105 |

The locked-test files are generated, hashed (SHA-256 list in `revision/prereg/locked_test_hashes.txt`) and not used in any run before step 7.3. A rerun is allowed only after a technical failure (crash or incomplete output), with the reason logged.

## 4. Metrics (per episode, 1800 s)

- **Arrived by 1800 s** (primary for the success criterion).
- **Total delay including unserved vehicles** (main delay measure). For every vehicle in the demand file:
  - arrived or still in the network at 1800 s: `timeLoss + departDelay` from tripinfo (with `write-unfinished`);
  - never inserted by 1800 s: 1800 − scheduled departure.
  - Reported as mean seconds per demanded vehicle and total vehicle-hours. Vehicles are matched by ID against the route file.
  - Checked in SUMO 1.26.0 by a unit test (`revision/tools/twin_sumo_unit_tests.py`, `revision/twin/unit_tests/unit_tests.json`):
    - with both tripinfo options, never-inserted vehicles are written with `depart="-1"`, `departDelay` = end − planned departure and `timeLoss` = 0;
    - inserted but unfinished vehicles carry `arrival="-1"` and `timeLoss`/`departDelay` up to the end;
    - so total delay = Σ (`departDelay` + `timeLoss`) over the tripinfo.
  - Earlier runs without `write-undeparted` (E3, E6, E12) get the same quantity from the route file (1800 − planned departure for the missing IDs).
- **Deadlock:** no arrival for ≥ 300 s while vehicles are in the network (E12 definition).
- **Full demand:** entries ≥ 0.99 × demand.
- **Also reported:** not inserted, unfinished vehicles, mean wait of arrived vehicles, number of switches, and seconds of yellow + all-red.

## 5. Validation and selection (all on the validation set only)

### 5.1 Score

For a (rung, reward) candidate, the score is the mean over ×1.0 and ×1.2 of (mean arrivals − fixed-plan arrivals) / mean demand, in %.

- Candidates with any deadlock at ×1.0 or ×1.2 rank below all candidates without one.
- Ties within 0.1 percentage points go to the lower mean total delay.
- Per-load models (L1–L3) are scored on their own load. The general model (L4) is scored on each load.

### 5.2 Rules

1. **Base design for L3/L4:** whichever of L1 or L2 has the higher mean score over the 4 rewards.
2. **The two rewards for L3/L4:** the two rewards with the highest score in the base design.
3. **Final design:** the single (rung, reward) candidate with the best score over L1–L4. L0 is not a candidate.

These rules are applied by a script, and the selection is logged before the locked test is run.

## 6. Baselines (on the same twin)

### 6.1 Fixed and actuated

- Fixed plan: the field plan, as in E6.
- Actuated: SUMO's actuated program `sumo/intersection_act.net.xml`, unchanged from E6 (minDur/maxDur 6/60 s for through and 5/25 s for left phases).

### 6.2 Tuned MaxPressure (E5)

- **Decision and pressure.** A decision every 5 s. The pressure of a phase is Σ over its movements of (vehicles on incoming lanes − vehicles on outgoing lanes).
- **Limits and clearance.** Green limits of 12–60 s and the clearance as in section 1.
- **Two variants:**
  - (a) free order: switch to the highest-pressure phase if it exceeds the current phase's pressure by ≥ h vehicles;
  - (b) field order: go to the next phase if its pressure exceeds the current phase's by ≥ h.
- **Grid:** h ∈ {0, 2, 4, 6, 8, 12} × variant, tuned **per load** on the training files (20 per load), with the same score as rule 5.1 (computed on the training files).
- **Use of the validation set:** reported, not used for tuning.

### 6.3 Webster plan (per load)

- **Phases and clearance:** the same four phases, yellow 3 s, all-red 4 s at the two street changes.
- **Lost time:** L = 20 s per cycle.
- **Saturation flow:** per lane group, from the discharge headway measured in the (calibrated) twin under the fixed plan.
- **Flows:** the demand counts × load.
- **Cycle:** C₀ = (1.5 L + 5) / (1 − Y), bounded to 60–150 s.
- **Greens:** proportional to the critical flow ratios and bounded to 12–60 s.
- The computation and the inputs are logged.

## 7. Evaluation and statistics

### 7.1 Exploratory evaluations

- Every candidate on validation and test A.
- The E12 models (L0) re-evaluated on the twin used for E13.
- The ladder, the scenarios, transfer and ×1.5 are all **exploratory**. They are reported with run-level means, 95% CIs and sign counts. Holm correction applies within each table family where tests are shown.

### 7.2 Confirmatory question (the only one)

> Is the final design non-inferior to the fixed plan in arrivals by 1800 s on the locked test, at ×1.0 and at ×1.2?

- **Unit:** the training run (n = 5).
- **Difference per run:** d_k = mean over the 10 locked-test files of (arrivals of the final design − arrivals of the fixed plan, same file and SUMO seed).
- **Margin:** m = 0.01 × mean demand of that load's locked-test files.
- **Test:** H0: mean(d) ≤ −m against H1: mean(d) > −m. One-sided one-sample t-test on d_k (df = 4), α = 0.025 one-sided per load, Holm over the two loads.
- **Reported alongside:** d_z, the 95% CI and the sign count (k of 5 runs above −m).

### 7.3 Success criterion

Fixed now:

1. H0 is rejected at both loads after Holm.
2. There is **no deadlock** in any locked-test episode of the final design at ×1.0 and ×1.2.

Total delay is the main secondary measure. A claim of "lower delay" is made only if its 95% CI over runs lies wholly below zero at that load. ×1.5 and the scenarios are reported, not judged.

### 7.4 Power note

With n = 5 and the E12 run-to-run SD (up to 147 vehicles at ×1.0), non-inferiority is only shown for stable designs. This is accepted. No runs are added after seeing results.

## 8. B6 twin calibration

The full protocol is `revision/twin/B6_protocol_draft.md` (29 Oct, approved by the lead before any fit). It is frozen with this document, and its SHA-256 is listed in `E13_preregistration_v1.sha256`. In short:

- **Parameters:** `startupDelay`, `tau` and `accel` of `DEFAULT_VEHTYPE`; everything else stays at SUMO defaults.
- **Grid:** startupDelay 0–3 s (step 0.25) × tau 1.0–2.0 s (step 0.1) × accel {1.0, 1.4, 1.8, 2.2, 2.6, 3.0} m/s² = 858 sets. Exhaustive search, with the tie rule in the protocol.
- **Simulated runs per set:** 15 fixed-plan runs at ×1.0, with common random numbers:
  - `sumo/demand.rou.xml` with seeds 1–5;
  - E12 training files 3001–3010 with seed 1;
  - no test-A, validation or locked-test file.
- **Observed data:** Ryzhanskyi's 1.2 discharge and queue data, cycles 2–12, with E8's definitions:
  - t1 = first crossing after the green onset;
  - h = saturated headway from position 4;
  - q = discharged queue.
- **Folds:**
  - A (primary): fit on even cycles, check on odd cycles;
  - B: the swap.
- **Objective:** the mean of the squared relative errors of t1, h and q.
- **Success** (on the check half, in both folds, against the default vehicle θ0):
  1. start-up error ≤ 0.5 × θ0's;
  2. headway error ≤ θ0's − 2.0 percentage points;
  3. queue error ≤ θ0's + 0.5 vehicles.
- **Adopted vehicle:** fold A's θ*. Fold B's θ* and the all-cycle fit are reported as stability checks.
- **Plausibility flag:** if the adopted vehicle leaves more than 1% of the ×1.0 demand unserved by 1800 s under the field plan, the lead and Pavlo decide before adoption.
- **Deadline:** if the grid has not finished by Sun 1 Nov 20:00, the criterion counts as not met, and E13 uses the default vehicle.

## 9. Other planned analyses (exploratory)

- **B1 replay** on the original twin with the E12 models.
  - Episodes: for each of the 4 policies, the first two deadlocked held-out ×1.0 episodes in sorted order (run, file), 8 in total.
  - Recorded each second: phase, halting vehicles per lane.
  - Recorded at each decision: the state vector and the Q-values.
- **B7 perception-error robustness.**
  - Demand perturbed within the measured counting error (from Pavlo's manual counts) and with ±10% / ±20% reassignment of heading-fallback exits.
  - Controllers: fixed plan, actuated, tuned MaxPressure and the final design, each frozen.
  - Output: the ranking stability.
- **B8 gain waterfall** (descriptive). The relative difference of IDQN-wait against the fixed plan in total delay and in arrivals, through these steps:
  1. the original paper;
  2. harmonised metrics (E7);
  3. held-out demand, yellow only (E3);
  4. + field all-red (E3/E4);
  5. retrained (E12);
  6. the E12 models on the E13 twin;
  7. E13 final design.
- **Perception (Comment 1.3):** counting error, tracking errors, queue recount, E10 field of view, GEH recomputed (K15), E8 with per-lane caps. These are descriptive and owned by the perception & twin session.

## 10. Reporting

- All rungs, rewards and runs are reported, including failures.
- E3, E6 and E12 are reported unchanged.
- The original results appear as the first step of the waterfall.
- Any deviation from this document after the freeze is logged in section 11 with date and reason, and stated in the paper.

## 11. Log (after the freeze)

| Date | Entry |
|---|---|
| | Twin used for E13 (calibrated / default): |
| | Selection log (rules 5.2): |
| | Locked test run: |
| | Deviations: |
