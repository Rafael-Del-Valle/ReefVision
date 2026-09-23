# Native-pixel georeferencing (Task 2)

Task 2.5 reporting updates and its current availability status are in
[WHALEDRONE_VALIDATION.md](WHALEDRONE_VALIDATION.md). The Task 2 verification record
below remains historical.

## Scope and integration plan

Reuse Task 1 `TelemetrySample` and `TelemetrySource`. Existing camera intrinsics
in `schemas/video_science.py` / `VideoScienceService` contain only fx/fy/cx/cy;
adapt those structurally with explicit dimensions and distortion instead of
changing that persistence contract. YOLO `boxes.xyxy` and tracking `boxes.xywh`
are already restored to source-image coordinates by Ultralytics; do not unletterbox
them twice. Raw model-space points require the actual resized dimensions and padding.

1. `geospatial/calibration.py`, `storage/georeferencing.py`: reusable typed
   calibration, existing-intrinsics adapter, validated external DVM JSON loader.
2. `geospatial/projection.py`, `geodesy.py`: undistorted rays, explicit camera
   rotation, flat-plane intersection, WGS84 geographic conversion, one high-level API.
3. `geospatial/validation.py`: meter-error statistics and per-point diagnostics.
   Developer-only WhaleDrone helpers resolve the dataset index and compare
   native annotation points with synchronized SRT; tests remain opt-in and offline.
4. Synthetic tests first; run Task 1 and full backend regressions, Ruff, formatter,
   mypy, and independent review. No map/export/detection-persistence changes.

## Mathematical contract

Camera coordinates are OpenCV: x right, y down, z forward. The intermediate
camera body frame is forward/right/down: `(z_camera, x_camera, y_camera)`.
World attitude uses NED with yaw clockwise from true North, pitch positive up
(DJI nadir -90 degrees), roll positive right-wing-down. Apply active rotations
`Rz(yaw) Ry(pitch) Rx(roll)` to body vectors, then convert NED to ENU as
`(east, north, up) = (ned_y, ned_x, -ned_z)`. Gimbal attitude is absolute; do not
add aircraft yaw or apply aircraft attitude a second time. Unknown/missing
gimbal components are errors, never zero-filled.

The camera sits at `(0,0,h)` above a horizontal z=0 surface. For a unit ENU ray
r, `t=-h/r.up` and offsets are `(t*r.east,t*r.north)`. Reject upward, near-horizontal,
nonfinite, or excessively distant intersections. This is a planar ocean/beach/flat
ground approximation, not DEM/terrain intersection or underwater refraction.

Surface height must be explicit: either a measured camera-to-surface height or
relative telemetry altitude plus a documented takeoff-to-surface offset. A zero
offset is a caller assertion requiring evidence, not an implicit default.
Negative absolute SRT altitude is not interpreted as negative ocean clearance.

Use OpenCV distortion inversion and a reprojection residual check. WGS84 offsets
are mapped by geodesic azimuth/distance using GeographicLib (small pure-Python
dependency), independent of UTM zone. This is a local planar approximation whose
surface distance is the computed offset norm; do not use it for long-range rays.

## Published WhaleDrone schema findings

Inspected public upstream files in memory; no dataset artifacts were saved in
ReefVision. A representative SRT has bracketed named latitude/longitude, relative
and absolute altitude, gimbal yaw/pitch/roll, `FrameCnt`, `focal_len`, and
`dzoom_ratio`. No aircraft attitude occurs in the inspected sample. Numbering
starts at 1 while cue time starts at zero. Values use degrees and meters according
to dataset docs. Named GPS fields eliminate tuple-order ambiguity for this dialect;
Task 1's explicit legacy tuple-order option remains unchanged for other aircraft.

The camera calibration JSON uses `image_resolution`, `camera_matrix` (scalar
intrinsics plus `matrix_row_major`), and `distortion_coefficients.vector_opencv_order`.
Calibration is for 3840x2160 RGB wide imagery. The published 24 mm camera spec is
35mm equivalent; raw `focal_len` is not used to synthesize intrinsics. Zoom must
match the calibration; this milestone does not guess a zoom/crop correction.

`dataset_index.xlsx`, sheet `filelist`, maps `DVM_video_name` to `video_ID` and
`flight_ID`. At least one internal filename maps to two distinct clips: require
an unambiguous mapping. Do not use the obsolete developer `Directory_file` paths.
Annotations have `video`, `frame`, `image_x/y`, `lat/lon`, and exported pose/height.
Choose point rows (`length` absent) for primary validation: vector centroid GPS
can differ from projection of a pixel midpoint under perspective/distortion.

DVM reference coordinates are computed from Airdata and camera calibration, not
independent surveyed locations. Report agreement with DVM separately from claims
about absolute geographic accuracy. SRT clocks are UTC+1 and Airdata UTC, but
projection synchronization uses relative frame time only; never apply a one-hour
offset to the relative SRT timeline. Frame-base and any clip offset are explicit
validation inputs, not fitted to minimize geographic error.

Sources: [dataset technical reference](https://huggingface.co/datasets/LucieLprt-Dvldr/WhaleDrone/blob/main/TECHNICAL_README.md),
[calibration schema](https://huggingface.co/datasets/LucieLprt-Dvldr/WhaleDrone/blob/main/camera_calibration_DJIM3T_RGBwide.json),
[time reference](https://huggingface.co/datasets/LucieLprt-Dvldr/WhaleDrone/blob/main/telemetry/README_time_sync.md),
[DJI frames](https://developer.dji.com/doc/mobile-sdk-tutorial/en/basic-introduction/basic-concepts/flight-control.html),
[OpenCV](https://docs.opencv.org/4.x/d9/d0c/group__calib3d.html),
[GeographicLib](https://geographiclib.sourceforge.io/html/python/code.html).

## Using the geometry API

This example uses synthetic inputs. Runtime callers can instead load a file with
`storage.georeferencing.load_camera_calibration(Path(...))` and obtain a Task 1
`TelemetrySource.sample_for_frame(frame_index, fps, max_delta_s=...)` match.

```python
from reefvision.geospatial.calibration import CameraCalibration
from reefvision.geospatial.models import TelemetrySample
from reefvision.geospatial.projection import SurfaceReference, georeference_pixel

calibration = CameraCalibration(
    width_px=1000, height_px=800,
    fx_px=500, fy_px=500, cx_px=500, cy_px=400,
    distortion_coefficients=(), source_id="synthetic-example",
)
telemetry = TelemetrySample(
    sample_index=1, time_s=0, latitude=0, longitude=0,
    gimbal_yaw_deg=0, gimbal_pitch_deg=-90, gimbal_roll_deg=0,
)
result = georeference_pixel(
    pixel_x=550, pixel_y=350, telemetry=telemetry, calibration=calibration,
    surface=SurfaceReference(camera_height_m=100, evidence="Synthetic geometry"),
)
assert abs(result.east_offset_m - 10) < 1e-9
assert abs(result.north_offset_m - 10) < 1e-9
```

Results retain native source pixels, telemetry sample/time, resolved height,
surface-reference evidence, calibration content checksum (when loaded from a
file), and projection method. `CameraCalibration.from_intrinsics(...)` adapts
existing four-field ReefVision intrinsics with explicit dimensions and distortion.
An empty distortion tuple explicitly means an ideal pinhole model; it is not
inferred when an external file omits distortion.

## Optional external validation

Normal application operation and tests require no WhaleDrone files. Nothing is
downloaded automatically. The development helper accepts only an existing external
`REEFVISION_WHALEDRONE_ROOT`; unset, missing, or in-repository roots skip cleanly.
The intended future location supplied by the user stays outside the repository;
there is no hard-coded fallback to it.

After obtaining the dataset externally, verify its index/annotation frame base and
takeoff height above the observed surface. Then run from the repository root:

```powershell
# Set REEFVISION_WHALEDRONE_ROOT to the external dataset directory first.
# Set these variables from documented evidence, not by minimizing GPS errors.
.venv/Scripts/python.exe -m pytest `
  apps/api/reefvision/tests/test_whaledrone_georeferencing_integration.py `
  --whaledrone-integration `
  --whaledrone-frame-base $verifiedFrameBase `
  --whaledrone-sync-evidence $syncEvidence `
  --whaledrone-camera-evidence $cameraEvidence `
  --whaledrone-takeoff-height-m $verifiedTakeoffHeightMeters `
  --whaledrone-height-evidence $heightEvidence -q -s
```

`--whaledrone-video` optionally selects an original video filename. Otherwise the
helper chooses the first complete, unambiguous annotated clip in deterministic
filename order. It reads the index, calibration, annotations, video metadata, and
paired SRT in place. Ambiguous index mappings are never guessed. Task 2.5 selects
at most 100 source rows evenly across the clip, independent of their errors, and
retains vector or invalid rows as explicit exclusions.
Video dimensions must match calibration and frame indices must be within the clip.
An independently established clip offset can be supplied with
`--whaledrone-time-offset-s` (default zero). Missing frame-base or height evidence
skips projection instead of guessing. Task 2.5 uses a 0.100 s synchronization limit
and retains timing diagnostics for excluded observations.

The JSON report prints attempted/failed counts, successful sample count, mean,
median, RMSE, minimum, maximum, and linearly interpolated 95th percentile in meters.
Each point retains synchronization delta, pitch, zoom, distance from the principal
point, reference height difference, predicted position, and any projection error.
Failed points remain visible and do not masquerade as zero-error observations.
There is no invented real-data accuracy threshold; inspect all residuals and
failures before integrating the output. Compare timing, pose, altitude, calibration,
and coordinate conventions if results are poor.

### Real-data status at the end of Task 2 (historical)

This initial deferral is superseded by Task 2.5's
[conditional real-data results](WHALEDRONE_VALIDATION_RESULTS.md).

The user confirmed that WhaleDrone is not downloaded locally and explicitly
deferred quantitative real-data validation. **Evaluated real samples: 0.** Mean,
median, RMSE, minimum, maximum, and p95 are **not available**, not zero. No systematic
real-data error pattern can yet be established. Public schema inspection and
synthetic tests do not establish field accuracy, frame-base semantics, or the
takeoff-to-ocean datum for a selected clip.

## Limitations and Task 3

This implementation assumes absolute gimbal attitude referenced to true North,
native pixels from the calibrated camera mode, matching zoom, and a horizontal
surface. Confirm those assumptions for each new telemetry source. It does not
estimate magnetic declination, GPS/antenna-to-camera lever arm, terrain, tides,
wave height, rolling shutter, underwater refraction, or calibration uncertainty.
Nearest-sample synchronization does not interpolate attitude. The 10 km maximum
intersection range is a rejection guard, not a claim that a plane is accurate at
that range; use a smaller caller limit appropriate to the scene.

Before Task 3, run the external diagnostic and resolve any systematic residuals.
Then add a narrow service taking frame index, native detection point, telemetry
source, calibration, and surface reference. Persist provenance and explicit failure
status alongside validated detection locations, then propagate locations through
ByteTrack observations without changing tracking identity. Keep raw pixels and
telemetry so results can be recomputed when calibration improves. Map/GIS output
should follow this validation, not substitute for it.

## Changed components

Paths below are relative to `apps/api/reefvision` unless otherwise noted.

| Component | Purpose |
| --- | --- |
| `geospatial/calibration.py` | Typed calibration and existing-intrinsics adapter |
| `storage/georeferencing.py` | Bounded external JSON loading and content provenance |
| `geospatial/projection.py` | Native coordinates, rays, rotation, intersection, high-level API |
| `geospatial/geodesy.py` | WGS84 displacement and meter distances |
| `geospatial/validation.py` | Metric statistics and per-point diagnostics |
| `tests/test_georeferencing.py`, `tests/test_georeferencing_validation.py` | Synthetic geometry and report tests |
| `tests/whaledrone_georeferencing.py`, associated tools/integration tests | Read-only index/annotation adapter and optional validation |
| `tests/whaledrone.py`, telemetry integration test, `tests/conftest.py` | Separate telemetry-directory support and validation options |
| Root `pyproject.toml` | GeographicLib dependency and integration marker |
| Root `docs/VIDEO_GEOREFERENCING.md`, `docs/VIDEO_TELEMETRY.md` | Contracts, usage, and validation record |

No Task 2 changes were made to persistence, API/frontend contracts, YOLO inference,
or ByteTrack behavior. Frontend and migration checks are therefore not required for
this increment; Task 1's earlier verification is recorded separately.

## Verification (2026-09-22)

- Full backend command `.venv/Scripts/python.exe -m pytest apps/api/reefvision/tests -q`:
  **545 passed, 2 skipped** in 386.68 seconds. The skips require explicit external
  integration opt-in. This covers existing imports, tracking, persistence, and
  non-video workflows alongside the new geometry tests. Ten review regression
  cases were added after this run collected tests and passed in the final focused
  run below; the final test collection contains **557 tests**.
- Final focused run of the geometry, validation-report, external-adapter, and both
  external integration test files with `--whaledrone-integration`: **43 passed,
  2 skipped**. Both skips explicitly report the unset external root.
- Synthetic cases verify distortion inversion, camera axes, letterbox restoration,
  nadir and known metric offsets, all cardinal headings, combined yaw/pitch/roll,
  surface datum offsets, geographic displacement/dateline crossing, invalid rays,
  missing telemetry, zoom mismatch, and bounded native pixels/intersection distance.
- Adapter tests use temporary synthetic workbook/CSV/placeholder files. They
  verify index ambiguity rejection, frame-base conversion, malformed numeric
  annotations, and truncated rows. No real dataset fixture is embedded.
- Ruff check passed; Ruff format check passed for **444 files**; mypy passed for
  **296 source files**; `git diff --check` passed.
- Independent review found no blocking math issues. Its truncated-CSV finding was
  reproduced in four failing tests and fixed; follow-up review found no remaining
  actionable issues.
- Untracked-file audit found only code, documentation, and Task 1's two synthetic
  SRT fixtures (315 and 550 bytes). No videos, real SRTs, annotations, calibration
  assets, dataset indexes, or download directories were added. No commits were made.
- The existing non-failing Starlette/httpx deprecation warning remains.


## AirData integration and project height datum

Task 2 now accepts a merged telemetry source. When aligned AirData is available,
its gimbal heading/pitch/roll, GPS position, and height-above-takeoff are preferred;
missing fields fall back to the existing DJI SRT parser. SRT-only behavior is
unchanged.

AirData flight-relative time must be aligned to video time explicitly; nonzero
alignment offsets require independent evidence and are never fitted from DVM
geographic residuals. Validation observations retain telemetry-source provenance.

Projects persist `georeference_height_offset_m`, defaulting to 0.0 m. This is a
project/survey datum value, not a DJI constant. Callers that use relative
telemetry altitude should pass that project value to
`SurfaceReference.takeoff_height_above_surface_m` together with evidence for the
surface datum. The WhaleDrone +5.0 m DVM setting is therefore represented as
project configuration rather than hard-coded projection behavior.
