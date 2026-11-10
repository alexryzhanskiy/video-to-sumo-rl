# E14 demand: second real window (exploratory)

Route files for E14 (exploratory, decided 2 Nov 2026): pipeline turning counts of a second camera pair recorded on the same morning as the main recording (31 Mar 2025, common window from 09:38:05), shifted to start at 0 s. Only the four complete 300-s intervals are used (0-1200 s; 238, 235, 250 and 200 vehicles, 923 in all; U-turns left out). `counts_0938_shifted.xml` is the routeSampler input; the ten route files use routeSampler seeds 1401-1410 (SUMO 1.26.0, candidate routes `sumo/candidate.rou.xml` of the repository, default options, timestamp removed). Every file passes the count check (vehicles per relation and planned-departure interval equal the counts).

Run on MyPC with the unchanged `b7.py` (the frozen final design, x1.0 models, runs k = 1..5, SUMO seed 42 + 1000 + k + e with e = seed % 100):

    .venv/Scripts/python.exe e13/b7.py run --demand e13/e14_demand --out e13/runs/e14

The rows of `b7_final_episodes.csv` then carry eval_set B7 and map b7_x10_real0938; that label is only b7.py's; the set is E14. The non-learning baselines (fixed, actuated, tuned MaxPressure, Webster; same files and seeds) run on the laptop with `s2c.py e14`.

| File | SHA-256 |
|---|---|
| `counts_0938_shifted.xml` | `dde95d5caea27b4913c76611f6952b48fb86f0317a2f751bb9e8688d9470be50` |
| `x10/real0938/e14_real0938_x10_s1401.rou.xml` | `f9f916ce0f5ec06cf9e906b5ea5430d3655fb0a2b769e0e1057e4aa20c42a91b` |
| `x10/real0938/e14_real0938_x10_s1402.rou.xml` | `cb06e221b151c918d8483ba26c80c295f0bcbe1c2d39eb3260275808bcf952d0` |
| `x10/real0938/e14_real0938_x10_s1403.rou.xml` | `71cd943c33020c49bb398eb38de362404f26bd652dc6f472f99186fe81e38870` |
| `x10/real0938/e14_real0938_x10_s1404.rou.xml` | `73ef4a04ec6a275ab34a9813182bdff90e5f5177252368b168a0aab8a573b04c` |
| `x10/real0938/e14_real0938_x10_s1405.rou.xml` | `73c2ba19f321fdad489334d6802b4c2f0f531209e84e91571bc67e9d6ae8a551` |
| `x10/real0938/e14_real0938_x10_s1406.rou.xml` | `36018d0b640a053eafc3a6ce387951ddbf7894ed49f915f321b9ee4b8d371695` |
| `x10/real0938/e14_real0938_x10_s1407.rou.xml` | `16046ba262d9cac712a5f1e0f8d85d77bc74e9a42f7133cb214607f99981737f` |
| `x10/real0938/e14_real0938_x10_s1408.rou.xml` | `c6be1a7298c6bfcfd2d6a2591d96038fa78ad8119570de98a80b1e864b7c0e0d` |
| `x10/real0938/e14_real0938_x10_s1409.rou.xml` | `3a465d669f0fe7213e641ce8117d30da1940012b7b179c7f63b65bc1bc03a999` |
| `x10/real0938/e14_real0938_x10_s1410.rou.xml` | `150976ace736537eaa9477a1d17e60b69deb851442489ea3bb48c483ba85b63f` |
