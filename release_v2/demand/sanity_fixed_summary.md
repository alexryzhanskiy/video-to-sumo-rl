Fixed-plan sanity runs: SUMO 1.26.0, `sumo/intersection.net.xml`, end 1800 s, seed 1, no teleports. Values are means over the files of a group; [min-max] for groups with several files. Flags: T1800 < 0.85 x demand; mean waiting > 3 x original_x10 (35.31 s); mean departDelay > 60 s.

| Group | n | demand | T1500 | T1800 | unfinished | not_inserted | mean_wait_s | mean_travel_s | mean_timeloss_s | mean_depart_delay_s | max_depart_delay_s | co2_kg_arrived | flagged |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| original_x10 | 1 | 1355 | 1283 | 1355 | 0 | 0 | 35.3 | 63.8 | 46.4 | 5.8 | 47.2 | 196.5 | 0 |
| original_x12 | 1 | 1626 | 1471 | 1620 | 6 | 0 | 52.4 | 83.1 | 65.7 | 31.1 | 178.9 | 281.1 | 0 |
| original_x15 | 1 | 2036 | 1479 | 1765 | 127 | 144 | 68.2 | 101.4 | 83.9 | 167.0 | 521.7 | 353.7 | 1 |
| heldout_x10 | 10 | 1355.0 | 1297.6 [1288-1311] | 1355.0 [1355-1355] | 0.0 | 0.0 | 36.2 [33.6-37.2] | 64.5 | 47.1 | 5.2 [4.4-6.7] | 41.5 | 197.9 | 0 |
| heldout_x12 | 10 | 1626.0 | 1475.6 [1418-1511] | 1621.0 [1611-1626] | 5.0 | 0.0 | 50.3 [45.1-55.5] | 80.8 | 63.4 | 28.8 [22.8-47.6] | 184.5 | 275.5 | 0 |
| heldout_x15 | 10 | 2036.0 | 1464.4 [1439-1493] | 1748.9 [1720-1769] | 114.1 | 173.0 | 67.3 [62.8-71.0] | 100.5 | 83.1 | 170.0 [153.4-182.7] | 540.2 | 348.1 | 10 |
| scenario_S1 | 5 | 1564.0 | 1391.0 [1375-1407] | 1506.2 [1485-1532] | 36.8 | 21.0 | 47.8 [45.2-49.7] | 77.9 | 60.5 | 50.9 [41.2-58.0] | 339.0 | 249.9 | 0 |
| scenario_S2 | 5 | 1355.0 | 1295.6 [1294-1298] | 1355.0 [1355-1355] | 0.0 | 0.0 | 37.5 [36.0-38.8] | 65.3 | 47.9 | 13.8 [13.4-14.2] | 62.3 | 198.2 | 0 |
| scenario_S3 | 5 | 1355.0 | 1299.8 [1295-1305] | 1355.0 [1355-1355] | 0.0 | 0.0 | 39.7 [37.1-40.6] | 68.4 | 50.9 | 16.1 [14.7-18.6] | 112.2 | 205.7 | 0 |
| scenario_S4 | 5 | 1355.0 | 1133.0 [1119-1164] | 1273.6 [1254-1305] | 70.2 | 11.2 | 76.8 [69.4-83.9] | 110.7 | 93.2 | 39.3 [27.1-46.7] | 319.4 | 274.5 | 0 |

Flags of `heldout_x15` accepted: x1.5 is the paper's overload condition; the original sumo/demand_15.rou.xml trips the same departDelay flag; accepted by Radiuk on 2026-10-26

Flags of `original_x15` accepted: x1.5 is the paper's overload condition; the original sumo/demand_15.rou.xml trips the same departDelay flag; accepted by Radiuk on 2026-10-26
