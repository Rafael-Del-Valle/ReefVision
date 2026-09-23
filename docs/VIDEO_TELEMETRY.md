# Video telemetry foundation

Task 2's calibration, native-pixel projection, and optional external accuracy
validation are documented in [VIDEO_GEOREFERENCING.md](VIDEO_GEOREFERENCING.md).
Task 1's verification record below is historical; the Task 2 document records the
combined backend regression results and updated public-schema observations.

## Existing architecture and integration

- Import: `api/routes/videos.py` accepts multipart video uploads and delegates to
  `services/video_assets.py:VideoAssetService.import_video`. OpenCV inspection
  supplies dimensions, frame count, FPS, and duration. Originals use managed,
  data-root-relative paths. Browser uploads do not expose sibling local files.
- Frames: `jobs/video.py:process_video_extract_job` sequentially decodes frames,
  preserving zero-based source indices even with extraction strides. Track
  interpolation in `services/video_tracks.py` derives seconds as index / FPS.
- Inference/ByteTrack: `ml/video_tracking.py:UltralyticsVideoTrackingProvider.track`
  enumerates YOLO streaming results with `persist=True` and `bytetrack.yaml`.
  It converts `boxes.id/cls/conf/xywh` into provider-neutral `TrackObservation`s.
  `jobs/video_tracking.py:process_video_tracking_job` maps classes and persists
  sparse keyframes, the provider track ID, model/job lineage, and progress.
  ReefVision's UUID and per-video track number remain separate from provider IDs.
- Persistence: SQLAlchemy `VideoAsset.metadata_json`, `VideoTrack.keyframes_json`,
  and `Job.request_json/result_json` use SQLite. `services/projects.py` manages
  projects; managed files resolve through `storage/projects.py`. Backups include
  database and managed assets. No telemetry column or Alembic migration is needed.
- Exports: `services/video_track_exchange.py` implements track CSV/MOT/COCO;
  `services/video_annotated_export.py` renders video; `services/project_exchange*`
  handle project packages; `exporters/` handles dataset formats. Project exchange
  serializes video metadata but does not currently package arbitrary sidecars.
  This milestone does not extend export formats or promise portable sidecar export.
- Boundaries: React `features/video/videoApi.ts` and `VideoTrackingWorkspace.tsx`
  consume typed HTTP models in `schemas/videos.py`. Backend pytest uses temporary
  storage/SQLite and fake video/provider adapters; frontend uses Vitest/Playwright.
- Existing sensor support: `storage/images.py` preserves image EXIF. Scientific
  3D/scale calibration modules exist, but there was no DJI/GPS telemetry ingestion.
- Selected integration: optional video-level telemetry metadata during import,
  with a source-neutral lookup object obtained from `VideoAssetService` for future
  jobs. No coordinates are attached to detections, tracks, or frontend elements.

## Implementation plan

1. Add synthetic fixtures and parser/pairing/lookup tests, run them red, then add
   `geospatial/models.py`, `dji_srt.py`, `synchronization.py`, and storage helpers.
2. Add import/persistence tests, run them red, then extend the existing import
   endpoint with optional `telemetry_file` and add backend `import_video_path`.
   Persist typed metadata inside the existing JSON field; old projects default
   to no telemetry. Invalid auto-discovered sidecars must not block video import.
3. Add an opt-in, read-only external-dataset test. Run backend tests, Ruff, mypy,
   frontend checks/build/tests, migration checks, and inspect the final Git diff.

Constraints: standard library parser; no runtime WhaleDrone dependency; no map,
projection, GIS export, calibration, or changes to YOLO/ByteTrack results.

## Contracts

Samples use SRT cue start times (seconds), decimal GPS degrees, meters, degrees,
m/s, and shutter exposure seconds. Missing/invalid optional values stay `None`.
Explicit frame counters retain their source numbering; SRT block numbers are
never assumed to be video frame indices. Wall-clock strings are ignored.

`TelemetrySource.sample_for_frame(index, fps)` uses zero-based index / FPS.
Nearest lookup sorts samples once, uses binary search, chooses the earlier
timestamp on ties, and returns the signed delta (sample time minus request time)
and absolute error. Out-of-range requests clamp to the nearest endpoint. Gaps
are not interpolated; optional `max_delta_s` rejects stale matches. This assumes
constant FPS; variable-frame-rate callers should use `sample_for_time` with PTS.

Pairing searches only siblings, matching filename stems and `.srt`
case-insensitively; unrelated files are ignored. Ambiguous pairs are rejected.
Path import preserves an external sidecar reference without copying the SRT;
multipart import stores an explicitly uploaded sidecar beside the managed video.
Metadata records found/available, source type/path, path kind, count, and any error.
External references may become unavailable if moved. Uploaded references are
data-root-relative. The dataset environment variable is never persisted.

Focal-length tokens can have different encodings and may mean 35mm equivalent
rather than physical lens focal length. Preserve `focal_length_raw`; normalize
explicit mm fields only. Calibration must resolve ambiguous `focal_len` values.
Legacy GPS tuples default to DJI longitude, latitude, altitude ordering; callers
may explicitly request latitude/longitude ordering. Unlabelled yaw and barometer
values are not guessed to be gimbal attitude or absolute altitude.

## Optional external validation

Set `REEFVISION_WHALEDRONE_ROOT` to an accessible directory outside this repository,
then explicitly run:

```powershell
.venv/Scripts/python.exe -m pytest apps/api/reefvision/tests/test_whaledrone_telemetry_integration.py --whaledrone-integration
```

Unset/missing roots or absent pairs skip cleanly. Normal unit tests use only tiny
synthetic SRTs; integration tests never download, copy, or modify dataset files.
DJI dialects still require validation against the actual external research files.

The parser accepts UTF-8 (optional BOM) and BOM-marked UTF-16, with a 32 MiB
sidecar limit. Explicit bad uploads return the existing HTTP 400 domain error;
auto-discovered bad sidecars record an error and allow ordinary video import.
Duplicate imports can attach previously missing telemetry without duplicating
the video. Existing usable telemetry is retained.

Dialect research included this [open-source format inventory](https://github.com/CallMarcus/dji-drone-metadata-embedder/blob/master/docs/SRT_FORMATS.md).
It is not a universal DJI specification; tuple ordering and focal-length encoding
must be established for a specific aircraft/firmware before georeferencing.

## Backend usage

```python
from pathlib import Path
from reefvision.services.video_assets import VideoAssetService

service = VideoAssetService(session, settings)
video = service.import_video_path(project_id, Path(selected_video_path))
source = service.telemetry_source(video.id)
if source is not None:
    match = source.sample_for_frame(30, video.fps, max_delta_s=0.5)
    if match is not None:
        sample, signed_delta_s = match.sample, match.delta_s
```

HTTP clients can send the existing `file` multipart field plus optional
`telemetry_file` to `POST /api/v1/projects/{id}/imports/videos`. Filenames must
have matching stems. GET/list video responses expose a typed `telemetry` object
derived from the persisted `metadata_json.telemetry` snapshot. UI changes are
outside this milestone; browser-only video uploads cannot auto-discover siblings.

Task 2 should consume the telemetry source alongside `TrackObservation.frame`
and `VideoAsset.fps`, with explicit camera intrinsics, lens/zoom provenance,
attitude conventions, altitude datum, and timing-error limits. Keep projection
separate from the detector/tracker and reuse existing calibration contracts where
appropriate; relative takeoff altitude is not automatically ground clearance.

## Changed files

All Python paths below are relative to `apps/api/reefvision/`.

| Files | Purpose |
| --- | --- |
| `geospatial/__init__.py`, `geospatial/models.py` | Module and typed samples, metadata, matches |
| `geospatial/dji_srt.py` | DJI dialect parsing and unit normalization |
| `geospatial/synchronization.py` | Source protocol and indexed nearest lookup |
| `storage/telemetry.py` | Pairing, bounded reads, encoding, managed sidecar writes |
| `services/video_assets.py` | Import integration and reusable telemetry source |
| `schemas/videos.py`, `api/routes/videos.py` | Typed metadata and optional multipart SRT |
| `tests/test_telemetry.py` | 39 parsing, pairing, timing, and adversarial tests |
| `tests/test_video_telemetry.py` | 10 API/import/persistence/rollback tests |
| `tests/fixtures/telemetry/modern.SRT`, `tests/fixtures/telemetry/legacy.srt` | Synthetic fixtures, 550/315 bytes |
| `tests/whaledrone.py`, `tests/test_whaledrone_location.py` | Development root resolution and unit test |
| `tests/test_whaledrone_telemetry_integration.py`, `tests/conftest.py` | Explicit opt-in external validation |
| Repository `docs/VIDEO_TELEMETRY.md` | Architecture, contracts, usage, and verification |

## Verification (2026-09-22)

- Full backend regression command: `.venv/Scripts/python.exe -m pytest apps/api/reefvision/tests -q`:
  **494 passed, 1 skipped**. Covers ordinary video import/extraction, tracking,
  ByteTrack provider contracts, track/run persistence, project exchange, backups,
  exports, and non-video workflows. No real model benchmark was run.
- Final focused suite: `test_telemetry.py`, `test_video_telemetry.py`,
  `test_whaledrone_location.py`, and `test_whaledrone_telemetry_integration.py`
  with `--whaledrone-integration`: **50 passed, 1 skipped**. This includes 18
  additional edge cases added during review after the full run collected tests.
  The final collection contains 513 tests. The external skip is because the
  dataset environment variable is unset; no actual WhaleDrone dialect was validated.
- `.venv/Scripts/python.exe -m ruff check apps/api`: passed.
- `.venv/Scripts/python.exe -m ruff format --check apps/api`: 434 files formatted.
- `.venv/Scripts/python.exe -m mypy -p reefvision`: 291 source files passed.
- `npm --prefix apps/web run format:check` and `typecheck`: passed.
- `npm --prefix apps/web run test`: **162 passed** across 44 files.
- `npm --prefix apps/web run test:e2e`: **7 passed**, including production UI build.
- `npm --prefix apps/web run build`: passed.
- Alembic `upgrade head`, `downgrade base`, `upgrade head`: passed in isolated
  system-temporary storage. No migration added because the schema is unchanged.
- `git diff --check`: passed. Untracked-file audit found only code, docs, and
  the two synthetic SRTs; no videos, annotations, calibration assets, downloaded
  data, or real WhaleDrone files were added. Existing local dataset ignore rules
  were sufficient. Nothing was downloaded from WhaleDrone.

Non-failing existing diagnostics: Starlette/httpx deprecation warning; frontend
MaskMeasurementPanel query warning; Vite chunk-size warning and Node color flags.
Independent review findings were reproduced in failing tests and corrected;
final scoped review and all focused tests passed.


## AirData camera-pose precedence

ReefVision can now ingest an optional AirData flight-log CSV alongside the
existing DJI SRT. AirData `gimbal_heading(degrees)` is normalized to
`TelemetrySample.gimbal_yaw_deg`; AirData `compass_heading(degrees)` remains
separate as aircraft yaw.

AirData uses flight-relative `time(millisecond)`, while DJI SRT cue times are
video-relative. The two streams are therefore not silently assumed to share an
origin. A caller must provide an independently established
`airdata_time_offset_s` such that:

```text
airdata_flight_time = video_time + airdata_time_offset_s
```

Any nonzero offset requires an evidence string. ReefVision does not fit this
offset from geographic residuals.

When both streams are aligned, source precedence is field-level:

1. AirData latitude/longitude are preferred when both are present.
2. AirData height-above-takeoff is preferred over SRT relative altitude.
3. AirData gimbal yaw/pitch/roll are preferred for camera pose.
4. Missing AirData fields fall back to the existing DJI SRT sample.
5. SRT-only videos retain the original Task 1 behavior unchanged.

Each merged match retains provenance for position, relative altitude, and each
gimbal attitude field, plus both source synchronization deltas. The effective
synchronization error is the largest absolute delta among sources that actually
contributed georeferencing fields.

The video import endpoint accepts optional `airdata_file`,
`airdata_time_offset_s`, and `airdata_time_offset_evidence`. AirData is stored
beside managed SRT telemetry; no flight logs are auto-downloaded or inferred by
filename.
