# ReefVision georeferencing implementation plan

Status date: 2026-09-23

This plan turns the validated geospatial backend into a user-visible ReefVision
feature. Tasks are executed in order. A task is complete only after its acceptance
gate passes; later work must not silently weaken an earlier contract.

## Status legend

- **DONE**: implemented and acceptance evidence exists.
- **VERIFY**: implementation is complete; final local regression gate remains.
- **NEXT**: next task after the current gate closes.
- **TODO**: not started.
- **BLOCKED**: cannot proceed until a named dependency is resolved.

## Sprint A — validated backend foundation

### 1. Finish AirData branch cleanup — DONE

Scope:
- normalize real AirData CSV header whitespace;
- preserve SRT-only behavior;
- validate WhaleDrone 0001 and 0003 end to end;
- keep DVM agreement separate from absolute-accuracy claims;
- keep PR #35 draft until the final local regression gate passes.

Implemented evidence:
- real Jan-16 AirData file parses 5,522/5,522 aircraft headings;
- clip 0001: 44/44 expected unique frames projected;
- clip 0003: 58/58 expected unique frames projected;
- all critical georeferencing fields resolve to AirData;
- both clips stay within the 100 ms synchronization gate;
- current branch includes the final Ruff cleanup.

Acceptance gate:
- focused AirData + georeferencing tests pass;
- Ruff check passes;
- Ruff format check passes;
- mypy passes;
- working tree is clean after any formatter changes are intentionally committed.

### 2. Resolve/document ReefVision↔DVM projection convention — DONE

Compare ReefVision's camera-ray/body/world transform directly with DVM's published
implementation using the same AirData pose, height, calibration, pixel, and frame.
Do not tune parameters against target-coordinate residuals.

Acceptance gate:
- each camera/world convention difference is either corrected or documented;
- synthetic geometry remains correct;
- two-clip operational AirData validation still passes;
- DVM agreement remains explicitly labeled conditional reference agreement.

### 3. Add production VideoGeoreferencingService — DONE

Create one canonical service taking video ID, frame index, and native pixel. It
must resolve the video, telemetry source, calibration, project datum, timing gate,
and call `georeference_pixel()`.

Acceptance gate:
- service returns a typed successful result or explicit typed failure;
- callers do not manually assemble telemetry/surface/calibration state.

### 4. Wire project height datum automatically — VERIFY

Use persisted project `georeference_height_offset_m` when constructing
`SurfaceReference`. Persist datum evidence/description alongside the value.

Acceptance gate:
- production callers cannot accidentally omit the configured project datum;
- missing/unsupported datum state is explicit.

### 5. Persist/select camera calibration — NEXT

Add normal project/video calibration attachment and provenance: dimensions,
intrinsics, distortion, checksum, camera mode, zoom, and evidence.

Acceptance gate:
- calibration survives reload/project exchange;
- incompatible dimensions/zoom fail explicitly rather than being guessed.

## Sprint B — production data model and API

### 6. Expose typed telemetry/georeferencing state to frontend — TODO

Extend frontend video types for SRT, AirData, alignment, calibration, and readiness.

### 7. Upgrade video import UI for SRT + AirData — TODO

Allow video, SRT, AirData CSV, alignment evidence, and automated source-only
alignment where supported.

### 8. Add georeferencing readiness/status API and panel — TODO

Return/display Ready, missing telemetry, missing calibration, missing datum,
alignment unverified, synchronization failure, and per-field provenance.

### 9. Define organism image-location policy — TODO

Initial production policy: bbox center unless a more specific point is supplied.
Preserve the original bbox/pixel and record the point-selection method.

### 10. Add typed georeferenced observation schemas — TODO

Include frame/time, source pixel, target lat/lon, camera lat/lon, ENU offsets,
height, synchronization error, provenance, calibration checksum, datum evidence,
projection method, and explicit failure reason.

### 11. Georeference detections and tracked observations — TODO

Run georeferencing after detection/tracking without altering ByteTrack/BoT-SORT
identity assignment.

### 12. Persist georeferenced observations — TODO

Add normalized persistence for successful and failed georeferencing observations.
Keep raw pixel observations so results can be recomputed.

### 13. Add production georeferencing endpoints — TODO

Provide status, single-frame/single-point georeferencing, and georeferenced
track/video observation retrieval.

## Sprint C — visible map experience

### 14. Build map panel in VideoTrackingWorkspace — TODO

Display camera position, current-frame target points, selected track, and track
paths.

### 15. Synchronize map, video, frame, and track selection — TODO

Clicking a map point selects the corresponding video frame/track; changing video
frame updates map highlighting.

### 16. Add geographic track analytics — TODO

Path length, displacement, mean/max speed in metric units while retaining existing
pixel analytics.

### 17. Add georeferencing quality visualization — TODO

Expose telemetry source, synchronization quality, failure state, and warnings.
Never silently plot failed coordinates.

## Sprint D — interoperability and lifecycle

### 18. Add GIS exports — TODO

At minimum GeoJSON and CSV; support observation points and track LineStrings with
frame/time/class/confidence/provenance.

### 19. Add stale-result/recomputation handling — TODO

Hash the georeferencing configuration. Calibration, datum, alignment, or algorithm
changes must mark derived coordinates stale and support recomputation.

### 20. Add backend production-path tests — TODO

Cover service behavior, project datum wiring, calibration, AirData/SRT fallback,
persistence, failures, recomputation, and GeoJSON.

### 21. Add frontend and Playwright tests — TODO

Cover import, readiness, map rendering, frame synchronization, path selection,
warnings, and export flow.

### 22. Extend project exchange and backups — TODO

Preserve calibration, datum evidence, alignment metadata, and geospatial records,
or explicitly regenerate derived records on restore.

## Sprint E — final acceptance and release

### 23. Run production-service scientific acceptance — TODO

Re-run WhaleDrone 0001 and 0003 through the exact production service/UI data path.
Verify expected frames, persisted offsets, provenance, sync, reload, mapped
coordinates, and GIS output. Keep DVM agreement separate from absolute accuracy.

### 24. Full regression and Windows release validation — TODO

Run backend pytest, Ruff, format, mypy, frontend typecheck/Vitest/build/Playwright,
Alembic round-trip, backup/restore, project exchange, Tauri build, and fresh MSI
smoke test.

Acceptance gate:
- no blocking regressions;
- georeferencing is visible and usable in the packaged ReefVision application;
- documentation accurately states capabilities and limitations.
