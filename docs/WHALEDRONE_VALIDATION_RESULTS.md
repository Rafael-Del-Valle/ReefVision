# 2026-09-23 AirData end-to-end operational validation

This section supersedes the earlier SRT-only availability status for the current
AirData integration. The historical Task 2.5 baseline remains below for provenance.

The production AirData parser, managed sidecar persistence, persisted alignment,
field-level AirData precedence, project height datum, and existing
`georeference_pixel()` path were exercised together against WhaleDrone clips
`DJI_20260116154954_0001_V.MP4` and
`DJI_20260116155837_0003_V.MP4`.

A real-data parser defect was found during this validation: the AirData file uses
whitespace-padded column names such as `" compass_heading(degrees)"`. The parser
now strips header whitespace before matching fields. A regression test covers this
case, and all 5,522 rows in the Jan-16 AirData flight log expose
`aircraft_yaw_deg` after the fix.

AirData/video offsets are established from source telemetry only. The alignment
search compares the SRT heading/GPS stream against AirData aircraft heading/GPS
across the feasible flight-time range, then refines hierarchically. DVM
annotations and geographic residuals are excluded from offset selection.

| Metric | Clip 0001 | Clip 0003 |
| --- | ---: | ---: |
| Persisted AirData offset | 6.19 s | 528.55 s |
| Expected unique frames projected | 44/44 | 58/58 |
| Projected point rows | 88 | 138 |
| Max effective sync error | 98.60 ms | 99.63 ms |
| Median SRT↔AirData heading disagreement | 0.30° | 0.20° |
| Median SRT↔AirData GPS disagreement | 0.045 m | 0.081 m |
| Mean AirData↔DVM yaw disagreement | 0.215° | 0.814° |
| Mean AirData↔DVM pitch disagreement | 0.116° | 0.390° |
| Mean resolved↔DVM height disagreement | 0.017 m | 0.160 m |
| Mean DVM-coordinate agreement | 4.407 m | 2.957 m |
| Median DVM-coordinate agreement | 2.228 m | 2.014 m |
| RMSE DVM-coordinate agreement | 5.847 m | 4.273 m |

For every projected observation in both clips, position, relative altitude, gimbal
yaw, gimbal pitch, and gimbal roll provenance resolves to AirData. Both clips stay
inside the 100 ms synchronization gate. Clip 0003 was inspected against the actual
source MP4 metadata; clip 0001 used the documented 3840×2160 / 29.97003 FPS
fallback because the original MP4 was not present in the local external bundle.

**Operational result: PASS.** AirData ingestion, managed persistence/reload,
alignment evidence, field precedence, project datum use, synchronization, and
projection execution are validated end to end on both clips.

The remaining meter-scale ReefVision↔DVM coordinate difference is treated as a
projection/reference-agreement diagnostic, not an ingestion failure and not an
independent absolute-accuracy result. DVM coordinates are themselves derived from
AirData and camera calibration. The next scientific task is to isolate any
remaining ReefVision↔DVM camera/world convention difference before making
georeferenced track coordinates a normal UI feature.

---

# Task 2.5 real-data results

The unchanged `georeference_pixel()` produces **10.553 m mean error, 7.509 m median
error, and 16.058 m RMSE** against this clip's DVM-derived coordinates.
This is **conditional reference agreement, not independently surveyed accuracy**.
The primary run uses real SRT relative altitude with zero additional datum offset;
the actual takeoff-to-ocean offset remains unverified. The summary records
`CONDITIONAL_BASELINE_COMPLETED`, `height_datum_verified=false`, and
`scientifically_validated=false`. Executing the code does not establish the
verified-surface-height contract. Task 3 remains gated for explicit review.

## External inputs and selection

Root used: `C:\Users\rafae\Documents\Datasets\WhaleDrone`.
`REEFVISION_WHALEDRONE_ROOT` was set for validation and saved in the Windows user
environment. Eight source files, totaling **2,918,586,922 bytes**, were downloaded
at Hugging Face revision `e78c4db9b5e77a582fdac3cb24085c9d8286f818`.
All eight match upstream hashes. Only one MP4 and one SRT were downloaded; no
AirData CSV, other video, or complete dataset was fetched.

| Input | Actual value, relative to external root |
| --- | --- |
| Video | `videos/Jan-16th-2026-02-49PM-Flight-Airdata/DJI_20260116155837_0003_V.MP4` |
| SRT | `telemetry/DJI_20260116155837_0003_V.SRT` |
| Annotation | `annotations/annotations_Jan-16th-2026-02-49PM-Flight-Airdata.csv` |
| Calibration | `camera_calibration_DJIM3T_RGBwide.json` |
| Mapping | `dataset_index.xlsx`, sheet `filelist`: `6MQWPNj0SkQ.mp4` uniquely maps to the selected original |
| Supporting files | `TECHNICAL_README.md`, `telemetry/README_time_sync.md`, `MX_2026_platform_specs.csv` |
| Native dimensions | **3840 × 2160**, actual video and calibration agree |
| FPS / frames / duration | **29.97002997002997** / **8,073** / **269.3691 s** |
| Annotation frame base | **0-based**, from DVM source behavior; historical-version limitation below |
| SRT frame counter | **1-based**; every selected match equals annotation frame + 1 |
| SRT sampling cadence | Median **33 ms**, min **33 ms**, max **34 ms**, 8,073 samples |
| Synchronization | Frame / actual FPS → nearest relative SRT cue; earlier exact tie |
| Sync threshold / fitted offset | **100 ms** / **none**, offset stays zero |
| Camera mode | RGB wide; all SRT records have **1× zoom** and `focal_len=24.00`, documented as **35 mm equivalent** |

The clip contains 138 point annotations among 278 matching source rows. Before
predictions, the existing deterministic limit selected 100 evenly spaced source
rows: **55 points and 45 vectors**. IDs and baseline assumptions were frozen in
`selection_before_predictions.json`. No selection used resulting errors. Another
internal identifier in this flight maps to two originals and was not used.

The pixel is the annotated body-midsection point (`image_x`, `image_y`) in the
native distorted image, not a bounding-box center. Reference GPS is `lat`, `lon`.
`frame` supplies the zero-based source frame; `time` is an absolute UTC timestamp,
retained as raw provenance rather than misinterpreted as relative seconds.
The row number plus `name` identifies each annotation, and `name` is retained as
object identity. DVM vector centroids are excluded because they need not correspond
to projection of the image midpoint.

## Primary geographic agreement

**Attempted selected rows: 100; projected: 55; excluded: 45.** All exclusions are
`Unsupported vector geographic reference point`. All 55 point observations project;
none fails synchronization or geometry. They cover **45 distinct frames** with
repeated objects in some frames.

| Metric | Meters |
| --- | ---: |
| Mean geolocation error | 10.552736 |
| Median | 7.508944 |
| RMSE | 16.058388 |
| Population standard deviation | 12.104197 |
| Minimum | 0.190851 |
| Maximum | 68.502146 |
| 95th percentile | 24.473057 |
| Mean East bias | +2.957446 |
| Mean North bias | -4.632625 |
| Median East bias | +2.218817 |
| Median North bias | -3.650729 |
| East population standard deviation | 12.504364 |
| North population standard deviation | 8.444228 |

Distances use WGS84 geodesics. Directional residuals are the GT-to-prediction
geodesic vector resolved into true East/North at the reference point, rather than
UTM grid differences. Standard deviation uses population `ddof=0`; p95 uses the
linear/type-7 convention. No geographic-error acceptance threshold was applied.

## Synchronization and error patterns

Nearest-SRT absolute timing errors: mean **6.915 ms**, median **7.033 ms**, maximum
**15.067 ms**, p95 **12.150 ms**. Mean signed delta is **-6.915 ms**.
These are nearest-sample distances after assuming common relative frame origins.
They do **not** independently verify DVM/AirData-to-SRT clock alignment.

| Predictor versus geographic error | Pearson r, N=55 |
| --- | ---: |
| Relative altitude / resolved baseline camera height | +0.2275 |
| Distance from native image center | +0.2978 |
| Gimbal pitch (increasing toward horizontal) | +0.9112 |
| Absolute nearest-SRT timing error | -0.0693 |

The **46 near-nadir** observations (`abs(pitch+90) <= 1°`) have mean **6.705 m**,
median **6.234 m**, RMSE **7.586 m**, and maximum **18.768 m**.
The **9 oblique** observations have mean **30.217 m**, median **23.075 m**, RMSE
**35.802 m**, and maximum **68.502 m**. These descriptive post-run groups do not
replace the primary result. The two largest errors share frame 205. Observations
are clustered within one clip; these correlations are not independent causal
estimates or evidence of general accuracy.

Actual-pose sanity checks passed: 37 unique near-nadir poses put opposing image
pixels on opposite sides of the center footprint. Maximum target-to-drone distance
was **185.298 m**. Native image-center displacement at nadir need not be exactly
zero because the calibration principal point differs from the image center.

## Unresolved inputs and Task 3 gate

The following pose/timestamp discrepancies were identified before projection;
no parameters were fitted to reference GPS errors:

1. **Yaw:** wrapped reference-minus-SRT mean **+19.960°**, median **+19.500°**, range
   **+13.900° to +38.700°**. This is consistent with large lateral disagreement for
   oblique, distant targets, but does not identify which heading source is correct.
2. **Height datum:** reference height minus SRT relative altitude has mean
   **4.942 m**, median **4.947 m**, range **3.573–7.114 m**. DVM supports a takeoff
   altitude addition, but the saved setting and physical datum for this flight
   are not established by the minimum bundle. No +5 m correction was fitted.
3. **Reference clock/pose lookup:** after the documented CET→UTC conversion for
   diagnostic comparison only, annotation timestamps exceed matched SRT wall-clock
   times by median **1.306 s**, range **1.203–1.418 s**. This is separate from the
   small nearest-SRT error and may affect reference pose/GPS lookup during motion.
   No shift was applied to the primary frame-based run. Reference pitch differs
   from matched SRT pitch by as much as **-12.5°** at one selected observation.
4. **Historical exporter provenance:** published DVM code initializes frame zero,
   uses `floor(currentTime*frameRate)`, and converts frame to time as
   `frame/nb_frames*duration`. The exact exported version reports `pre:e0e2bc3`,
   which was unavailable in the current upstream repository. Frame base was not
   chosen by minimizing spatial error; this source-version limitation remains.

**No global projection convention corrections were applied.** No yaw, pitch,
height, time, pixel, focal length, or calibration parameter was tuned. The only
data-driven code fix recognizes the published `videos/<flight>/` directory layout.
Reporting now explicitly distinguishes a conditional height baseline from a
verified datum. Projection math, tracking, persistence, and UI remain unchanged.

The orientation, height, and reference-time discrepancies are the strongest
identified unresolved inputs; their individual causal contributions are not yet
established. Before Task 3, resolve the original DVM synchronization/heading
settings and physical height datum using acquisition evidence. If fitting becomes
necessary, reserve new evaluation observations before fitting. The current 55
observations have been inspected and must not be described as unseen holdout data.
No A/B/C/D integration category has been selected automatically.

## Artifacts and provenance

Generated outputs are Git-ignored under `.artifacts/whaledrone-validation/`:

- `whaledrone_validation.csv`: 100 selected rows with all required fields/reasons.
- `whaledrone_validation_summary.json`: metrics, conditional status, provenance,
  synchronization scope, and additional diagnostic summaries.
- `whaledrone_validation_diagnostics.csv` / `.json`: reference-pose/clock differences
  and near-nadir/oblique summaries.
- `selection_before_predictions.json`: frozen selection and assumptions.
- `source_manifest.json`: eight external paths, sizes, SHA-256 hashes, pinned
  revision, and upstream-hash verification.
- `run.log`: actual opt-in integration execution.
- `reproduce_baseline.ps1`: reruns the primary validation without downloading or
  tuning. It regenerates the primary CSV/JSON; separately produced diagnostic
  files remain available, but their added summary fields are not regenerated.

No source WhaleDrone files were copied into ReefVision or its fixtures. No external
source files were edited, and no dataset files were committed. Generated reports
contain derived observation/reference values and remain ignored by Git.

## Verification

Both external integration tests passed with explicit opt-in. The standard backend
suite passed with **560 passed, 2 optional integrations skipped**. Ruff lint and
format checks, mypy (296 source files), and `git diff --check` passed. The only test
warning was the existing Starlette/httpx deprecation warning. Generated CSV/JSON
outputs are ignored, and no downloaded source files were added to the repository.

Source documents: external `TECHNICAL_README.md` §§2–5, the time-sync README, and
platform specifications. DVM code was inspected at immutable revision
[`e56c85ce`](https://github.com/SDU-UAS-Center/DVM/tree/e56c85ce1073301eb4d6d0cbf649ccf967949d6b):
[`VideoFrame.min.js`](https://github.com/SDU-UAS-Center/DVM/blob/e56c85ce1073301eb4d6d0cbf649ccf967949d6b/src/dvm/static/VideoFrame.min.js),
[`video_annotator.js`](https://github.com/SDU-UAS-Center/DVM/blob/e56c85ce1073301eb4d6d0cbf649ccf967949d6b/src/dvm/static/video_annotator.js),
[`drone_log_data.py`](https://github.com/SDU-UAS-Center/DVM/blob/e56c85ce1073301eb4d6d0cbf649ccf967949d6b/src/dvm/drone/drone_log_data.py).
