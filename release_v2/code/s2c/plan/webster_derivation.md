# Webster plans per load (pre-registration 6.3)

Written by `s2c.py plan` on 2026-10-29 23:37:28. Flows: `sumo/turn_counts_edges.xml` (0–1500 s) × load, in veh/h. Saturation flow per lane group: 3600 / median saturated discharge headway in the default twin under the fixed plan (`plan/satflow.json`: through+right groups from `revision/runs/e8_validation/sim_discharge_headways.csv`, left groups measured with the same E8 extraction). L = 20 s (4 × 3-s yellow + 2 × 4-s all-red). Phases: 0 Svobody through, 1 Svobody left, 2 Prybuzka through, 3 Prybuzka left.

| Lane group | Phase | Count 0–1500 s (×1.0) | s, veh/h | q ×1.0 | y ×1.0 | q ×1.2 | y ×1.2 | q ×1.5 | y ×1.5 |
|---|---|---|---|---|---|---|---|---|---|
| SVB_N_through+right | 0 | 361 | 2750 | 866 | 0.315 | 1040 | 0.378 | 1300 | 0.472 |
| SVB_S_through+right | 0 | 328 | 2701 | 787 | 0.291 | 945 | 0.350 | 1181 | 0.437 |
| SVB_N_left | 1 | 59 | 1695 | 142 | 0.084 | 170 | 0.100 | 212 | 0.125 |
| SVB_S_left | 1 | 46 | 1683 | 110 | 0.066 | 132 | 0.079 | 166 | 0.098 |
| PRB_E_through+right | 2 | 174 | 2110 | 418 | 0.198 | 501 | 0.237 | 626 | 0.297 |
| PRB_W_through+right | 2 | 261 | 2596 | 626 | 0.241 | 752 | 0.290 | 940 | 0.362 |
| PRB_E_left | 3 | 60 | 1693 | 144 | 0.085 | 173 | 0.102 | 216 | 0.128 |
| PRB_W_left | 3 | 66 | 1669 | 158 | 0.095 | 190 | 0.114 | 238 | 0.142 |

| Load | Critical y (phases 0–3) | Y | C0, s | Cycle bound 60–150, s | Greens raw, s | Greens 12–60, s | Cycle used, s |
|---|---|---|---|---|---|---|---|
| x1.0 | 0.315, 0.084, 0.241, 0.095 | 0.735 | 132.0 | 132 | 48.0, 12.7, 36.8, 14.5 | 48, 13, 37, 14 | 132 |
| x1.2 | 0.378, 0.100, 0.290, 0.114 | 0.882 | 296.1 | 150 | 55.7, 14.8, 42.7, 16.8 | 56, 15, 42, 17 | 150 |
| x1.5 | 0.472, 0.125, 0.362, 0.142 | 1.102 | undefined (Y ≥ 1) | 150 | 55.7, 14.8, 42.7, 16.8 | 56, 15, 42, 17 | 150 |
