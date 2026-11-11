# Blurred camera frames and Figure 2

License plates and faces were blurred.

**Rights.** The camera frames belong to Khmelnytskyi City Council and are reproduced with its permission. The frames and every image that contains them (all PNG and PDF files here) are not covered by the CC BY 4.0 licence of this package or by any other licence; `Figure_2_data.csv` is under CC BY 4.0.

| File | What |
|---|---|
| `center_undistorted_ref_blurred.png` | Rectified frame of Camera 1 (center), 2688 × 1520 px, from the 5-min clip `i300` at 2.0 s |
| `zarich_undistorted_ref_blurred.png` | Rectified frame of Camera 2 (zarich), 2688 × 1520 px, same time |
| `Figure_2_center_blurred.png` | The pipeline's vehicle tracks of Camera 1 (2,571 tracks with at least 8 points) drawn over the dimmed blurred frame |
| `Figure_2_zarich_blurred.png` | The same for Camera 2 (3,046 tracks) |
| `Figure_2.png`, `Figure_2.pdf` | Figure 2 of the article: (a) Camera 1, (b) Camera 2, with the entry stop lines (white, labelled) and exit lines (teal, dashed) of the counting segments; 178 × 55.5 mm, PNG at 600 dpi |
| `Figure_2_data.csv` | The segments drawn in Figure 2: panel, camera, segment, approach, label, endpoints in rectified pixels, whether inside the frame, tracks drawn in the panel |

**Blurring.** Persons, vehicles and their licence-plate areas were found with YOLO11x (confidence ≥ 0.10, two passes) and pixelated into blocks of at least 12 px by averaging, then smoothed; every person box was enlarged by 20 %, small vehicles were blurred whole, and larger vehicles got a band over their lower part. Averaging removes the detail inside each block, so plate characters and facial features cannot be recovered. One of the authors then checked every file at 100 % zoom for readable plates and recognisable faces before release. The renders and Figure 2 were drawn from the blurred frames only. The unblurred frames, the video and the track files are not released.

The segment coordinates are those of `calib/gates_center.json` and `calib/gates_zarich.json` in the first-version repository (https://github.com/alexryzhanskiy/video-to-sumo-rl).
