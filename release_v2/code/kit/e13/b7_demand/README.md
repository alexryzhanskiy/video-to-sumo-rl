# B7 demand (perception-error sensitivity), FOV variants

Route files for B7 (pre-registration section 9), generated on the laptop with SUMO 1.26.0 routeSampler from the field counts: `<load>/<variant>/b7_<variant>_<load>_s<seed>.rou.xml`, loads `x10` and `x12`, variants `base`, `fovm10`, `fovm20`, `fovp10`, `fovp20`, routeSampler seeds 7001–7005 (50 files). Byte-identical copies of the laptop's `revision/twin/B7/demand/`. Added 4 Nov 2026 (40 files): the counting-error variants `ce_bias` (seeds 7001–7005) and `ce_rand` (10 draws, seeds 7101–7110), from the blind hand counts of the two i300 clips, and `fov_meas` (seeds 7001–7005), the heading-exit confusion measured in the tracking review. In `x10/ce_rand/b7_ce_rand_x10_s7105.rou.xml` two vehicles of the 600–900 s interval depart at 900.00 s (two-decimal rounding); relation totals are exact. The fixed, actuated and MaxPressure runs on these files are still to do (`s2c.py b7`).

Run the frozen E13 final design on them (MyPC, after the locked test, only when Pavlo asks):

```bash
.venv/Scripts/python.exe e13/b7.py run --demand e13/b7_demand --workers 7
.venv/Scripts/python.exe e13/b7.py status --demand e13/b7_demand
```

Output: `e13/runs/b7/` (`b7_final_episodes.csv`). The fixed, actuated and tuned MaxPressure runs on the same files were done on Colab (`s2c.py b7`).
