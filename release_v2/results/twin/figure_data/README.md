# Figure data from the perception and twin session (for the lead's rendering)

Made with `revision/tools/twin_figure_data.py`, which only collects recorded values (no fitting). Every CSV is tidy: one row per plotted point, with the estimate, its interval and n. All values are from cycles 2–12, SUMO 1.26.0. The source files are named in the script's docstring.

## SI figure: twin validation (current twin) — `SI_twin_validation_data.csv`

1. **Question:** how closely does the fixed-plan twin (SUMO default vehicle, field-phased plan) reproduce the queues and the discharge measured in the video?
2. **Panels** (one per quantity, 2 × 2): (a) end-of-red queue counted up to the camera's visible length (SVB_N 9 and SVB_S 5 vehicles per lane, Prybuzka in full); (b) discharged queue; (c) saturated headway; (d) start-up time to the first crossing.
3. **Axes:** x is the approach (SVB_N, SVB_S, PRB_E, PRB_W), categorical, with observed and simulated dodged side by side. y units: vehicles for (a) and (b), seconds for (c) and (d).
4. **n:**
   - observed: 11 cycles per approach; headways 85–288 per approach;
   - simulated: 15 runs (`sumo/demand.rou.xml` with 5 SUMO seeds, plus 10 held-out ×1.0 demand realizations), giving 165 cycles per approach and about 1,200–4,000 headways.
5. **Intervals:**
   - queues: mean with a 95% t interval, over cycles (observed) or over run means (simulated);
   - headway and start-up time: median with the interquartile range of the pooled values.
   - The point estimates are those of the validation analysis.

Note for the caption: the start-up time shows the twin's main gap (0.44 s simulated against 2.2–3.1 s observed). The calibration figure shows that calibrating it failed.

## SI figure: twin calibration (negative result) — `SI_twin_calibration_data.csv`, `SI_twin_calibration_criterion.csv`

1. **Question:** can the start-up of the simulated queue be calibrated (`startupDelay`, `tau`, `accel`) without degrading the discharge? Answer: no. The frozen criterion is met in neither fold.
2. **Panels:**
   - (a) start-up time to the first crossing, (b) saturated headway, (c) discharged queue: three sources per approach (observed, default vehicle θ0, fitted vehicle θ*A = 1.75 s, 1.0 s, 3.0 m/s²);
   - (d) the criterion: check-half errors of θ0 and θ* per fold (A: fit on even cycles, check on odd cycles; B: the swap), with the criterion limit of each error drawn as a reference mark (`criterion_limit`).
3. **Axes:**
   - (a)–(c): x is the approach, with the three sources dodged; y in seconds for (a) and (b) and in vehicles for (c).
   - (d): x is the error (start-up in s, headway in percentage points, queue in vehicles), with fold A and fold B grouped. Three small multiples are probably clearer, because the units differ.
4. **n:**
   - observed: 11 cycles; headways 85–288 per approach;
   - simulated: 15 calibration runs per vehicle (`sumo/demand.rou.xml` with 5 SUMO seeds, plus 10 E12 training realizations), giving 165 cycles per approach;
   - (d): errors over the 4 approaches on 5 or 6 check cycles.
5. **Intervals:**
   - as in the validation figure: queues as mean with a 95% t interval over cycles or run means; t1 and h as median with the interquartile range;
   - (d) has no interval: the errors are the criterion statistics themselves.
   - Abbreviations for the caption: θ0, θ*A, t1, h.

## Not yet available

- **Counting accuracy (manual counts against the pipeline):** after A1's blind counts (`export --final`, due Sun 1 Nov) and the second counter (due Tue 3 Nov). Data CSV and spec by Wed 4 Nov.
- **Figure 2** stays as v1 (A1, 29 Oct), so no track or line geometry is needed.
