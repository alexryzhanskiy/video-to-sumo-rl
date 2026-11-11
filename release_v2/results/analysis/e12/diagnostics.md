# E12 diagnostics: phase switching and stranded vehicles

From the pack's `metrics_N.csv` (decision times) and tripinfo files. Fixed plan for reference: 60 switches per 1800 s and 300 s of yellow + all-red per 1800 s (4 × 3 s + 2 × 4 s per 120-s cycle). DRL: 7 s per switch.

Decision gaps other than 5 s and 9 s: 0 in 1400 episodes.

| Set | Policy | Switches per 1800 s (mean) | Yellow + all-red, s (mean) | Deadlocked episodes | In deadlocks: unfinished vehicles (mean) | In deadlocks: share on the two most loaded approaches (mean) |
|---|---|---|---|---|---|---|
| held-out x1.0 | IDQN-wait | 57 | 401 | 25/50 | 121 | 0.56 |
| held-out x1.0 | IDQN-queue | 61 | 425 | 4/50 | 114 | 0.54 |
| held-out x1.0 | MPLight | 75 | 527 | 21/50 | 135 | 0.54 |
| held-out x1.0 | IDQN-pressure | 47 | 327 | 18/50 | 127 | 0.55 |
| held-out x1.2 | IDQN-wait | 61 | 426 | 18/50 | 114 | 0.57 |
| held-out x1.2 | IDQN-queue | 64 | 447 | 3/50 | 123 | 0.55 |
| held-out x1.2 | MPLight | 83 | 581 | 20/50 | 134 | 0.54 |
| held-out x1.2 | IDQN-pressure | 52 | 362 | 9/50 | 111 | 0.59 |
| held-out x1.5 | IDQN-wait | 77 | 539 | 19/50 | 127 | 0.54 |
| held-out x1.5 | IDQN-queue | 52 | 362 | 14/50 | 114 | 0.58 |
| held-out x1.5 | MPLight | 115 | 804 | 10/50 | 119 | 0.56 |
| held-out x1.5 | IDQN-pressure | 52 | 367 | 4/50 | 118 | 0.56 |
| scenario S1 | IDQN-wait | 47 | 332 | 16/25 | 119 | 0.56 |
| scenario S1 | IDQN-queue | 58 | 406 | 4/25 | 116 | 0.57 |
| scenario S1 | MPLight | 78 | 543 | 10/25 | 141 | 0.54 |
| scenario S1 | IDQN-pressure | 41 | 286 | 12/25 | 128 | 0.55 |
| scenario S2 | IDQN-wait | 51 | 356 | 13/25 | 116 | 0.55 |
| scenario S2 | IDQN-queue | 58 | 407 | 2/25 | 102 | 0.56 |
| scenario S2 | MPLight | 75 | 525 | 10/25 | 135 | 0.53 |
| scenario S2 | IDQN-pressure | 46 | 319 | 8/25 | 122 | 0.56 |
| scenario S3 | IDQN-wait | 57 | 400 | 16/25 | 116 | 0.55 |
| scenario S3 | IDQN-queue | 61 | 427 | 0/25 | – | – |
| scenario S3 | MPLight | 80 | 559 | 10/25 | 136 | 0.52 |
| scenario S3 | IDQN-pressure | 50 | 350 | 10/25 | 133 | 0.56 |
| scenario S4 | IDQN-wait | 47 | 330 | 16/25 | 117 | 0.58 |
| scenario S4 | IDQN-queue | 56 | 394 | 3/25 | 111 | 0.57 |
| scenario S4 | MPLight | 81 | 570 | 10/25 | 140 | 0.54 |
| scenario S4 | IDQN-pressure | 38 | 264 | 14/25 | 125 | 0.55 |
| transfer x1.2 | IDQN-wait | 51 | 360 | 27/50 | 116 | 0.55 |
| transfer x1.2 | IDQN-queue | 55 | 384 | 8/50 | 115 | 0.58 |
| transfer x1.2 | MPLight | 77 | 537 | 20/50 | 134 | 0.54 |
| transfer x1.2 | IDQN-pressure | 42 | 294 | 26/50 | 125 | 0.55 |
| transfer x1.5 | IDQN-wait | 51 | 359 | 27/50 | 121 | 0.56 |
| transfer x1.5 | IDQN-queue | 47 | 331 | 17/50 | 119 | 0.54 |
| transfer x1.5 | MPLight | 64 | 447 | 27/50 | 129 | 0.54 |
| transfer x1.5 | IDQN-pressure | 37 | 260 | 30/50 | 122 | 0.54 |
