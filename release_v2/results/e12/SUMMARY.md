# E12 summary (MyPC, 2026-10-28 22:47:54)

Training runs done: 60/60 (0 failed). Evaluation episodes analysed: 1400/1400. Settings: README.md. Computed from the files in `runs/` by `e12.py pack`; the full analysis is done on the main PC.

Full = at least 99% of the route file's vehicles entered the network by 1800 s. Deadlock = no arrival for at least 300 s while vehicles are in the network. Not inserted = demand minus vehicles that entered. All evaluation episodes last 1800 s and use the field clearance (3 s yellow + 4 s all-red).

## Frozen evaluation

| Set | Policy | Episodes | Full | Deadlocks | Arrived by 1500 s (mean) | Arrived by 1800 s (median / mean) | Not inserted (mean) | Unfinished (mean) | Mean wait of arrived, s (median) | Demand (mean) |
|---|---|---|---|---|---|---|---|---|---|---|
| held-out x1.0 | IDQN-wait | 50 | 0% | 25 | 553 | 603 / 613 | 634 | 107 | 107.3 | 1355 |
| held-out x1.0 | IDQN-queue | 50 | 70% | 4 | 1159 | 1342 / 1230 | 93 | 33 | 41.5 | 1355 |
| held-out x1.0 | MPLight | 50 | 0% | 21 | 528 | 588 / 537 | 730 | 88 | 12.0 | 1355 |
| held-out x1.0 | IDQN-pressure | 50 | 30% | 18 | 825 | 900 / 869 | 403 | 83 | 42.6 | 1355 |
| held-out x1.2 | IDQN-wait | 50 | 0% | 18 | 764 | 958 / 835 | 701 | 89 | 75.6 | 1626 |
| held-out x1.2 | IDQN-queue | 50 | 0% | 3 | 1030 | 1148 / 1152 | 406 | 68 | 49.5 | 1626 |
| held-out x1.2 | MPLight | 50 | 0% | 20 | 631 | 734 / 684 | 858 | 84 | 16.4 | 1626 |
| held-out x1.2 | IDQN-pressure | 50 | 0% | 9 | 961 | 1014 / 1029 | 524 | 73 | 37.7 | 1626 |
| held-out x1.5 | IDQN-wait | 50 | 0% | 19 | 626 | 595 / 698 | 1215 | 122 | 74.4 | 2036 |
| held-out x1.5 | IDQN-queue | 50 | 0% | 14 | 973 | 1143 / 1080 | 862 | 93 | 61.9 | 2036 |
| held-out x1.5 | MPLight | 50 | 0% | 10 | 862 | 900 / 947 | 1020 | 68 | 19.7 | 2036 |
| held-out x1.5 | IDQN-pressure | 50 | 0% | 4 | 942 | 1114 / 1055 | 906 | 75 | 72.0 | 2036 |
| scenario S1 | IDQN-wait | 25 | 0% | 16 | 473 | 552 / 506 | 941 | 117 | 104.6 | 1564 |
| scenario S1 | IDQN-queue | 25 | 36% | 4 | 1237 | 1494 / 1378 | 134 | 51 | 44.2 | 1564 |
| scenario S1 | MPLight | 25 | 0% | 10 | 531 | 615 / 540 | 935 | 89 | 13.1 | 1564 |
| scenario S1 | IDQN-pressure | 25 | 0% | 12 | 811 | 754 / 848 | 614 | 102 | 46.5 | 1564 |
| scenario S2 | IDQN-wait | 25 | 0% | 13 | 496 | 571 / 552 | 692 | 111 | 86.8 | 1355 |
| scenario S2 | IDQN-queue | 25 | 76% | 2 | 1175 | 1353 / 1262 | 67 | 26 | 42.0 | 1355 |
| scenario S2 | MPLight | 25 | 0% | 10 | 568 | 606 / 583 | 686 | 86 | 9.4 | 1355 |
| scenario S2 | IDQN-pressure | 25 | 24% | 8 | 872 | 951 / 902 | 368 | 84 | 39.0 | 1355 |
| scenario S3 | IDQN-wait | 25 | 0% | 16 | 514 | 558 / 555 | 687 | 113 | 78.8 | 1355 |
| scenario S3 | IDQN-queue | 25 | 60% | 0 | 1173 | 1301 / 1252 | 62 | 41 | 42.2 | 1355 |
| scenario S3 | MPLight | 25 | 0% | 10 | 575 | 627 / 584 | 685 | 86 | 13.5 | 1355 |
| scenario S3 | IDQN-pressure | 25 | 28% | 10 | 833 | 921 / 884 | 388 | 83 | 42.0 | 1355 |
| scenario S4 | IDQN-wait | 25 | 0% | 16 | 377 | 480 / 410 | 826 | 119 | 93.3 | 1355 |
| scenario S4 | IDQN-queue | 25 | 48% | 3 | 1100 | 1272 / 1194 | 107 | 54 | 54.1 | 1355 |
| scenario S4 | MPLight | 25 | 0% | 10 | 462 | 593 / 469 | 797 | 89 | 11.5 | 1355 |
| scenario S4 | IDQN-pressure | 25 | 12% | 14 | 676 | 551 / 731 | 521 | 103 | 55.4 | 1355 |
| transfer x1.2 | IDQN-wait | 50 | 0% | 27 | 509 | 575 / 565 | 946 | 115 | 124.0 | 1626 |
| transfer x1.2 | IDQN-queue | 50 | 44% | 8 | 1200 | 1464 / 1341 | 224 | 61 | 48.8 | 1626 |
| transfer x1.2 | MPLight | 50 | 0% | 20 | 600 | 717 / 611 | 928 | 86 | 12.6 | 1626 |
| transfer x1.2 | IDQN-pressure | 50 | 8% | 26 | 855 | 830 / 923 | 603 | 100 | 46.1 | 1626 |
| transfer x1.5 | IDQN-wait | 50 | 0% | 27 | 469 | 452 / 523 | 1391 | 121 | 138.9 | 2036 |
| transfer x1.5 | IDQN-queue | 50 | 0% | 17 | 1138 | 1444 / 1290 | 658 | 88 | 51.0 | 2036 |
| transfer x1.5 | MPLight | 50 | 0% | 27 | 602 | 390 / 631 | 1310 | 95 | 16.3 | 2036 |
| transfer x1.5 | IDQN-pressure | 50 | 0% | 30 | 855 | 956 / 931 | 994 | 111 | 44.5 | 2036 |

## Training (last 10 of 100 episodes of each run, online learning on)

| Policy | Load | Runs | Entered (mean) | Arrived by the end (mean) | Demand |
|---|---|---|---|---|---|
| IDQN-wait | x1.0 | 5 | 998 | 883 | 1355 |
| IDQN-wait | x1.2 | 5 | 1275 | 1189 | 1626 |
| IDQN-wait | x1.5 | 5 | 1282 | 1166 | 2036 |
| IDQN-queue | x1.0 | 5 | 1216 | 1125 | 1355 |
| IDQN-queue | x1.2 | 5 | 1255 | 1196 | 1626 |
| IDQN-queue | x1.5 | 5 | 1426 | 1337 | 2036 |
| MPLight | x1.0 | 5 | 818 | 725 | 1355 |
| MPLight | x1.2 | 5 | 1006 | 929 | 1626 |
| MPLight | x1.5 | 5 | 1130 | 1059 | 2036 |
| IDQN-pressure | x1.0 | 5 | 1153 | 1070 | 1355 |
| IDQN-pressure | x1.2 | 5 | 1239 | 1183 | 1626 |
| IDQN-pressure | x1.5 | 5 | 1238 | 1178 | 2036 |
