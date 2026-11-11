# E3 check: frozen policies on held-out demand and scenarios (Ryzhanskyi's runs of 27-28 Oct 2026)

Episodes re-read: 1500. Differences between the kit's CSV columns / Ryzhanskyi's flags and the values recomputed here: 0.


Full = at least 99% of the route file's vehicles entered the network by 1800 s. Deadlock = no arrival for at least 300 s while vehicles are in the network. Means over all episodes (10 route files × 5 training runs, or 5 × 5 for the scenarios).

## Clearance yellow3

| Policy | Set | Episodes | Full | Deadlocks | Arrived by 1500 s (mean) | Arrived by 1800 s (median / mean) | Not inserted (mean) | Unfinished (mean) | Mean wait of arrived, s (median) | Demand |
|---|---|---|---|---|---|---|---|---|---|---|
| IDQN-wait | x1.0 | 50 | 86% | 4 | 1248 | 1355 / 1284 | 55 | 15 | 13.3 | 1355 |
| IDQN-queue | x1.0 | 50 | 80% | 1 | 1207 | 1354 / 1239 | 99 | 17 | 13.7 | 1355 |
| MPLight | x1.0 | 50 | 68% | 1 | 1208 | 1335 / 1270 | 51 | 34 | 30.2 | 1355 |
| IDQN-wait | x1.2 | 50 | 44% | 22 | 1155 | 1460 / 1216 | 346 | 64 | 25.9 | 1626 |
| IDQN-queue | x1.2 | 50 | 88% | 0 | 1519 | 1614 / 1601 | 7 | 17 | 22.1 | 1626 |
| MPLight | x1.2 | 50 | 8% | 3 | 1116 | 1130 / 1219 | 354 | 54 | 16.2 | 1626 |
| IDQN-wait | x1.5 | 50 | 0% | 40 | 645 | 656 / 684 | 1238 | 114 | 66.7 | 2036 |
| IDQN-queue | x1.5 | 50 | 0% | 5 | 1182 | 1631 / 1334 | 634 | 68 | 34.3 | 2036 |
| MPLight | x1.5 | 50 | 0% | 0 | 1216 | 1350 / 1385 | 596 | 55 | 15.3 | 2036 |
| IDQN-wait | S1 | 25 | 60% | 5 | 1293 | 1564 / 1343 | 181 | 40 | 19.0 | 1564 |
| IDQN-queue | S1 | 25 | 60% | 3 | 1305 | 1558 / 1360 | 170 | 34 | 17.8 | 1564 |
| MPLight | S1 | 25 | 20% | 2 | 1243 | 1305 / 1314 | 164 | 86 | 37.8 | 1564 |
| IDQN-wait | S2 | 25 | 80% | 3 | 1222 | 1355 / 1255 | 80 | 21 | 12.8 | 1355 |
| IDQN-queue | S2 | 25 | 64% | 2 | 1139 | 1354 / 1165 | 162 | 28 | 12.8 | 1355 |
| MPLight | S2 | 25 | 76% | 0 | 1213 | 1334 / 1274 | 46 | 35 | 28.3 | 1355 |
| IDQN-wait | S3 | 25 | 48% | 3 | 1200 | 1270 / 1224 | 84 | 46 | 16.8 | 1355 |
| IDQN-queue | S3 | 25 | 60% | 0 | 1205 | 1350 / 1230 | 96 | 29 | 15.8 | 1355 |
| MPLight | S3 | 25 | 60% | 2 | 1200 | 1337 / 1267 | 54 | 34 | 33.2 | 1355 |
| IDQN-wait | S4 | 25 | 80% | 4 | 1220 | 1355 / 1254 | 75 | 25 | 16.6 | 1355 |
| IDQN-queue | S4 | 25 | 72% | 3 | 1171 | 1350 / 1208 | 118 | 29 | 17.1 | 1355 |
| MPLight | S4 | 25 | 44% | 2 | 1070 | 1213 / 1138 | 151 | 66 | 41.7 | 1355 |

Episodes with the full demand served, ×1.0 held-out, per training run (of 10):

| Policy | run 1 | run 2 | run 3 | run 4 | run 5 |
|---|---|---|---|---|---|
| IDQN-wait | 9 | 6 | 10 | 10 | 8 |
| IDQN-queue | 10 | 10 | 10 | 3 | 7 |
| MPLight | 4 | 10 | 0 | 10 | 10 |

## Clearance yellow3+allred4

| Policy | Set | Episodes | Full | Deadlocks | Arrived by 1500 s (mean) | Arrived by 1800 s (median / mean) | Not inserted (mean) | Unfinished (mean) | Mean wait of arrived, s (median) | Demand |
|---|---|---|---|---|---|---|---|---|---|---|
| IDQN-wait | x1.0 | 50 | 42% | 15 | 917 | 1202 / 972 | 320 | 63 | 35.3 | 1355 |
| IDQN-queue | x1.0 | 50 | 40% | 8 | 956 | 1184 / 1014 | 291 | 50 | 33.1 | 1355 |
| MPLight | x1.0 | 50 | 0% | 9 | 861 | 874 / 904 | 338 | 112 | 50.2 | 1355 |
| IDQN-wait | x1.2 | 50 | 2% | 27 | 766 | 684 / 858 | 675 | 92 | 42.5 | 1626 |
| IDQN-queue | x1.2 | 50 | 14% | 19 | 1010 | 1082 / 1121 | 429 | 75 | 46.8 | 1626 |
| MPLight | x1.2 | 50 | 0% | 11 | 850 | 998 / 916 | 628 | 81 | 26.4 | 1626 |
| IDQN-wait | x1.5 | 50 | 0% | 32 | 586 | 528 / 631 | 1295 | 110 | 84.1 | 2036 |
| IDQN-queue | x1.5 | 50 | 0% | 5 | 922 | 1122 / 1028 | 934 | 74 | 53.1 | 2036 |
| MPLight | x1.5 | 50 | 0% | 17 | 879 | 1030 / 968 | 968 | 100 | 28.8 | 2036 |
| IDQN-wait | S1 | 25 | 12% | 9 | 924 | 1088 / 1011 | 470 | 83 | 42.5 | 1564 |
| IDQN-queue | S1 | 25 | 20% | 4 | 932 | 910 / 1014 | 490 | 59 | 39.6 | 1564 |
| MPLight | S1 | 25 | 0% | 25 | 636 | 637 / 636 | 790 | 137 | 37.7 | 1564 |
| IDQN-wait | S2 | 25 | 40% | 9 | 942 | 1222 / 995 | 297 | 63 | 32.3 | 1355 |
| IDQN-queue | S2 | 25 | 48% | 4 | 926 | 1266 / 976 | 334 | 45 | 32.9 | 1355 |
| MPLight | S2 | 25 | 0% | 4 | 867 | 872 / 904 | 338 | 113 | 51.7 | 1355 |
| IDQN-wait | S3 | 25 | 36% | 8 | 966 | 1059 / 1032 | 257 | 66 | 39.7 | 1355 |
| IDQN-queue | S3 | 25 | 28% | 6 | 927 | 1007 / 986 | 309 | 60 | 35.6 | 1355 |
| MPLight | S3 | 25 | 0% | 3 | 871 | 882 / 911 | 330 | 113 | 44.4 | 1355 |
| IDQN-wait | S4 | 25 | 20% | 12 | 767 | 940 / 825 | 437 | 92 | 41.0 | 1355 |
| IDQN-queue | S4 | 25 | 28% | 7 | 793 | 928 / 868 | 414 | 73 | 54.7 | 1355 |
| MPLight | S4 | 25 | 0% | 25 | 485 | 480 / 485 | 732 | 138 | 41.1 | 1355 |

Episodes with the full demand served, ×1.0 held-out, per training run (of 10):

| Policy | run 1 | run 2 | run 3 | run 4 | run 5 |
|---|---|---|---|---|---|
| IDQN-wait | 5 | 2 | 10 | 4 | 0 |
| IDQN-queue | 9 | 6 | 5 | 0 | 0 |
| MPLight | 0 | 0 | 0 | 0 | 0 |

