# Task 2.5: WhaleDrone validation

## Current results

The authorized minimal external download and real-data run are complete.
See [WHALEDRONE_VALIDATION_RESULTS.md](WHALEDRONE_VALIDATION_RESULTS.md) for the
**conditional 55-point baseline**, all measured metrics, and unresolved pose/datum
disagreements. Task 3 remains gated. The reporting protocol below is reusable;
the initial availability and verification records are retained as history.

## Initial availability check (historical, before download authorization)

`REEFVISION_WHALEDRONE_ROOT` is unset in the process and Windows user environment.
The previously supplied external directory does not exist. No source MP4, SRT,
calibration, annotation file, or dataset index was loaded for Task 2.5. No download
has been performed. A request for an existing external path or authorization to
download a minimal external bundle is pending.

**Attempted: 0; projected: 0; excluded: 0.** All geographic-error, directional-bias,
and synchronization metrics are unavailable (`null`), not zero. There is no
evidence yet about real accuracy or dominant systematic errors. Task 2.5 has not
passed operationally, and the Task 3 decision gate remains closed.

The generated CSV has headers only, and the JSON records
`NOT_RUN_DATASET_UNAVAILABLE`. These are status artifacts, not validation results.

## Validation implementation

The existing `georeference_pixel()` and all projection/calibration math are unchanged.
Validation calls that function directly, then uses ground truth solely for WGS84
geodesic error measurement. Task 2.5 adds reporting and developer tooling:

- `geospatial/validation.py`: retains source video, raw frame/time provenance,
  normalized frame/time, matched telemetry, signed/absolute synchronization error,
  population standard deviation, and signed local East/North residuals.
- `tests/whaledrone_report.py`: normalizes external annotations, records invalid
  selected rows, builds summaries, runs geometric sanity checks on matched poses,
  and writes generated CSV/JSON artifacts.
- `tests/test_whaledrone_georeferencing_integration.py`: uses actual MP4 metadata,
  requires documented synchronization/camera/height conventions, reads the external
  dataset in place, and writes reports under `.artifacts/whaledrone-validation/`.
- `tests/conftest.py` and focused tests: explicit input options and synthetic
  checks of statistics, timing precedence, missing data, and report serialization.

The application has no dependency on WhaleDrone. Both external integration tests
skip when the environment variable is unset. Reports are ignored by Git via the
existing `.artifacts/` rule; source dataset files are never copied there.

## Selection and normalization

Before examining any predictions, inspect the available clips and select one
unambiguously mapped RGB wide-camera clip with constant, calibration-compatible
zoom. Prefer near-nadir observations well inside the image and at least 20 point
annotations (50 preferred). Record the selection rationale. The index is required
for the published renamed DVM identifiers; it is not geographic ground truth.
The existing helper rejects ambiguous index mappings. A caller-selected video is
recommended; automatic fallback is the first complete unambiguous indexed clip,
which still needs camera and synchronization evidence before evaluation.

The current DVM adapter maps:

| Normalized value | Source |
| --- | --- |
| source video | CSV `video` basename resolved through the dataset index |
| annotation ID | source CSV row number plus `name` |
| object ID | `name` (class remains unknown unless provided by a future source adapter) |
| zero-based frame | `frame` minus the independently verified frame base |
| relative seconds | explicitly specified and verified time column, if available |
| native point | `image_x`, `image_y` |
| reference latitude/longitude | `lat`, `lon` |

The raw `frame` and `time` strings are retained even when their semantics have not
been verified. DVM point annotations use their own image reference point; bounding
box centers are never substituted. Vector rows are retained as exclusions because
their geographic centroid is not necessarily the projection of a pixel midpoint.
Missing GPS is an exclusion, never inferred from other columns. Selected malformed
rows and out-of-duration annotations are retained with reasons.

At most 100 source rows are selected by evenly spaced row positions, before any
predictions. The summary records total matching rows, selected rows, other-video
rows, and rows not selected by the limit. Every selected row contributes to the
attempted count, including failures. This rule does not select by error. If fewer
than 20 points are successfully projected, the result is labeled
`PRELIMINARY VALIDATION`; even a larger sample is only a single-clip result.

Native dimensions come from the actual calibration and MP4. Any mismatch rejects
the run. No resize/crop/letterbox transformation is guessed. Missing calibration
rejects a configured run. Published schema information from Task 2 does not replace
inspection of the selected local files.

## Synchronization and height

Use verified zero-based frame divided by actual floating-point MP4 FPS first.
Verified relative video seconds are the fallback. Preserve both when available.
The `time` column is not automatically interpreted as relative seconds. If the
frame convention is unknown, leave frame base unset and use a documented relative
time column instead. Unknown frame/time semantics are a run prerequisite failure.

Choose the nearest SRT sample; exact ties select the earlier sample. The primary
threshold is **0.100 seconds**. Retain the nearest match and its signed/absolute
delta even when excluded for exceeding that threshold. No per-annotation time
tuning is allowed. A nonzero global offset requires independent evidence via
`--whaledrone-time-offset-evidence`; it cannot be silently supplied. The summary
records measured SRT median/minimum/maximum positive sampling intervals.

Relative SRT altitude is not automatically ocean clearance. Supply a verified
takeoff-to-surface offset and its evidence. Do not derive it by fitting reference
GPS or individually using annotation heights to improve errors. Required GPS,
height, or gimbal values missing from a matched sample cause recorded exclusions.
AirData is not required by the implementation.

## Generated report conventions

`whaledrone_validation.csv` includes all requested observation columns plus source
provenance, resolved camera height, zoom, distance from image center, and exclusion
reason. `video_time_s` is the chosen frame-derived or relative time before any
documented global offset; the raw relative annotation time is separately retained.
Signed sync delta is relative to the actual offset-adjusted lookup time.

`whaledrone_validation_summary.json` includes:

- Attempted/projected/excluded counts and exclusion counts by reason.
- Mean, median, RMSE, population standard deviation (`ddof=0`), min, max, p95
  geographic distance in meters. P95 uses NumPy `method="linear"` (type 7),
  consistent with Task 2's linear percentile calculation.
- Mean/median/population standard deviation of signed East and North residuals.
  These are the WGS84 GT-to-prediction distance resolved along true East/North at
  the reference point, not UTM grid coordinate differences. This avoids zone and
  grid-convergence ambiguity and is appropriate for local directional diagnostics.
- Mean/median/max/p95 absolute synchronization error and mean signed delta in ms.
  Top-level synchronization metrics describe successfully projected observations;
  `all_matched_sync` separately includes matched observations that were excluded.
- Pearson correlations between geographic error and relative altitude, resolved
  camera height, image-center distance, gimbal pitch, and absolute sync error.
  Each includes its pair count and predictor range. Correlations are null with
  fewer than three pairs or zero variance. Small-sample patterns are descriptive.
- Geometric sanity: maximum target-to-drone distance, near-nadir native-center
  offsets, and opposite-pixel footprint checks using actual matched poses.
  The 10 km local projection guard rejects gross geographic displacements; it is
  not an accuracy threshold. No near-nadir samples means no real center check.

DVM reference coordinates were derived using telemetry and calibration, so this
experiment measures agreement with that reference pipeline. It does not establish
independent surveyed accuracy. No numeric error threshold selects A/B/C/D; the
summary leaves `accuracy_category` null for explicit report review.

## Running after the external bundle is available

Set `REEFVISION_WHALEDRONE_ROOT` in the validation process. Obtain frame-base,
camera-mode, and surface-height evidence from source metadata/documentation before
examining residuals. Then run from the repository root, using verified values:

```powershell
.venv/Scripts/python.exe -m pytest `
  apps/api/reefvision/tests/test_whaledrone_georeferencing_integration.py `
  --whaledrone-integration `
  --whaledrone-video $selectedOriginalVideo `
  --whaledrone-frame-base $verifiedFrameBase `
  --whaledrone-sync-evidence $syncEvidence `
  --whaledrone-camera-evidence $cameraEvidence `
  --whaledrone-takeoff-height-m $verifiedTakeoffHeightMeters `
  --whaledrone-height-evidence $heightEvidence -q -s
```

For a verified relative-time column, add `--whaledrone-time-column`; frame base can
then be omitted if unknown. Default time offset is zero. Reports overwrite the
generated output filenames on an explicit completed run; archive prior reports
outside the dataset if comparisons are needed. The test performs no downloads.

Before Task 3, obtain the bundle, establish these conventions, run the complete
selected set, inspect exclusions and residual trends, and review the report.
If a global convention correction is demonstrated, fix it globally and rerun the
whole set. If parameter fitting is needed, define a debug/evaluation split before
tuning. No global convention corrections or accuracy conclusions were made here.

## Verification before external download (historical)

- Full backend: **559 passed, 2 skipped** in 237.76 seconds. Both skips require
  external integration opt-in.
- Final focused geometry/report/adapter run with `--whaledrone-integration`:
  **47 passed, 2 skipped**. Both external tests explicitly report the unset root.
  This run includes the final review fixes for excluded-row frame/time precedence
  and empty sanity checks, added while the full regression run was in progress.
- Ruff check passed; formatter passed for **446 files**; mypy passed for
  **296 source files**; `git diff --check` passed.
- Independent review findings were fixed and regression-tested. Final review found
  no remaining actionable issues. The existing Starlette/httpx warning remains.
- Generated reports are Git-ignored. The untracked dataset-extension audit found
  only the two existing synthetic SRT fixtures. No real WhaleDrone files were
  downloaded, copied, modified, or committed. The status reports contain no real
  dataset observations.
- Projection, API/frontend, persistence, and inference interfaces are unchanged;
  no frontend, migration, or tracking integration work was performed.

These checks validate the reporting software and preserve regressions. They do not
answer the requested real-data accuracy question, which remains blocked on the
external bundle and its verified acquisition/synchronization metadata.
