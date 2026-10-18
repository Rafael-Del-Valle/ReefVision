# ReefVision 1.1 development roadmap

Status date: 2026-10-18 UTC. Development only; no release acceptance claimed.

## Baseline and audit

Development branch: `develop/reefvision-1.1`, from main
`9278d45e894cffa2da582df58c2dbf4a4bdac327`. The live baseline CI run
38546696335 passed backend and frontend. Stable v1.0.1 and v1.0.2 releases
exist; main contains integrations #44 and #69. No unmerged branch is imported.
Open PRs observed: #50, #58, #59, #61–66. Their open status does not mean
their entire diff is absent from the merged integrations. Issues #45–49,
#54, #56 and #57 remain open. Historical publishing failures were superseded
by successful run 38545559271. Release validation remains separate from code CI.

The application is React/TypeScript + TanStack Query + Leaflet, hosted in
Tauri with a local FastAPI worker/backend. SQLAlchemy owns the SQLite model;
The baseline Alembic head was 0037; this branch adds 0038. Public IDs are UUIDs, source coordinates are
pixels, and model predictions remain separate from verified annotations.

Reusable implementations inspected:

| Area | Existing implementation | 1.1 work |
| --- | --- | --- |
| Telemetry | `geospatial/dji_srt.py`, `synchronization.py`, video georeferencing services | Extend; preserve explicit alignment and height evidence |
| Geographic records | `GeoReferencedObservation`, configuration hash and stale-state services | Reuse; do not duplicate projection or invent uncertainty |
| Movement/export | Geographic movement analytics and GIS export services | Heading, pairwise analysis, GeoPackage and reference acceptance |
| Image calibration | `image_scale_calibration.py`, `scientific_mask_measurements.py`, image metadata | Preserve canonical calibration; snapshot it in scientific provenance |
| Tracking/heatmaps | Video tracks, pose visualization and behavior services | Human/model/reviewer layers and uncertainty |
| Workflows | Graph records, persisted execution, typed node registry and results packages | Safe computed metrics; comprehensive editor deferred to 2.0 |
| Environmental context | No dedicated provider/cache/project scientific-record subsystem found | Add persistent typed records and bounded provider import |

## Milestones and acceptance

| Phase | Dependencies | Implemented | Tested | Release-validated | Acceptance remaining |
| --- | --- | --- | --- | --- | --- |
| 1 Scientific foundation | Validated baseline | Core records, units, UTC, WGS84/pixels, calibration snapshots, provenance, QC and cache tables | API, integrity, serialization, migration round trip and legacy exchange tests pass | No | Additional CRS transforms, scientific project exchange, broader real-project migration acceptance |
| 2 Telemetry and geographic measurements | 1; existing georeferencing | Existing telemetry/calibration reused; stale-coordinate exclusion and WGS84 segment bearings added | 71 focused backend tests pass, including datum-change/invalidation/recomputation; frontend regression tests pass | No | Propagated geographic uncertainty, pairwise geographic motion, mask geometry, GeoPackage, absolute UTC/VFR alignment, surveyed drone references |
| 3 Environmental context | 1 | Local JSON import, NOAA station temperature, persistent 24-hour cache/offline, bounded lookup and project workspace | Provider/API/cache tests and live NOAA smoke test pass; UI unit tests/build pass | No | Copernicus current/temperature/salinity grids, credential settings, unattended daily refresh, detection/track lookup controls, browser/desktop acceptance |
| 4 Current visualizer | 2, 3 | Not started | No | No | Streamlines, time/depth, layers, trajectories, cache/provenance, desktop acceptance |
| 5 Scientific heatmaps | 1; existing pose/annotation records | Existing partial infrastructure | Not assessed for 1.1 | No | Independent reviewer/model layers and disagreement validation |
| 6 Computed metrics | 1; calibration and verified annotations | Existing measurements only | Not assessed for 1.1 | No | Safe arithmetic/unit engine, matching run/frame identity, saved calculations/provenance |
| 7 Event/environment analysis | 2, 3, 6 | Not started | No | No | Event windows, tides/lunar provenance and reproducible exports |

Optional advection is deferred until core acceptance. Existing 1.0.x GUI,
GPU and scientific acceptance issues do not block additive foundation work,
but must be reconciled before a combined 1.1 release. Do not merge, tag,
publish installers, bundle model weights or mark the release complete.

## First implementation design

Use additive typed scientific records in the existing database, with an
append-only API. Each measurement retains its original unit and value plus
normalized value/unit, UTC observation time, location/depth, source kind,
QC, uncertainty, source identity and processing metadata. IDs reference
existing images, videos, tracks, annotations, masks, predictions and jobs;
validate project and media ownership before committing any batch.

Image calibration remains in its existing canonical location. Scientific
records retain a hashed snapshot rather than silently replacing calibration
or assuming image scale applies to geographic coordinates. Coordinates are
explicit source pixels or WGS84; unsupported transformations fail closed.
Unknown uncertainty/depth remain unknown, never zero.

Environmental cache entries retain raw provider payloads, request identity,
checksum, acquisition/expiry times and URL. NOAA is the first remote adapter;
local researcher records work without a network. Refresh is explicit and
reuses a cache for 24 hours; offline requests never contact a provider.
Copernicus credentials and grid adapters follow after these contracts pass.

This approach avoids a second project store or heavyweight geospatial/data
dependencies. A generic unvalidated JSON bag would lose scientific guarantees;
replacing existing georeferencing/calibration would create migration risk.

## File-level execution plan

1. Add `schemas/scientific_data.py`, `domain/scientific_units.py`,
   `db/models/scientific_record.py`, migration `0038_scientific_data.py`,
   `services/scientific_data.py`, and `api/routes/scientific_data.py`.
   First test API persistence, unit conversion, UTC serialization, invalid
   identities, atomicity, calibration snapshots and migration round trips.
   Run the tests red, implement, run green, lint/type-check and commit.
2. Extend existing geographic analytics with reference-tested movement
   direction. Reuse existing WGS84 and stale-observation policies. Commit
   after the existing and new geospatial tests pass.
3. Add a bounded NOAA adapter and environmental cache service/routes using
   the phase-1 records. Test malformed/missing data, preserved provider flags,
   cache expiry/offline/integrity and matching location/time/depth. No
   fabricated fallback. Commit after provider/integration tests pass.
4. Add a project Environmental Context view using existing routing/query
   conventions. Test loading, errors, import, cached status and provenance;
   run frontend checks/build and relevant E2E. Commit after validation.
5. Obtain an independent whole-branch review, fix correctness findings,
   run migration/backend/frontend gates, push and open one draft PR.

Review focus: cross-project or contradictory source IDs; unknown depth vs
surface; absolute-temperature vs uncertainty conversion; mutable calibration;
cache corruption/failure presented as fresh observations. Each must have an
explicit regression or remain a documented blocker.

## Session evidence

Implementation and test results are recorded here as they are obtained.
Hardware, authenticated providers and installed Windows acceptance cannot be
inferred from synthetic tests. No such acceptance has been performed here.

Foundation checkpoint: typed project record API, unit normalization (including
temperature-difference uncertainty), scoped media/object/run identities,
original-pixel bounds, immutable calibration snapshots, SHA-256 integrity and
additive migration 0038 are implemented. Fourteen initial API tests failed on
the absent endpoints before implementation. The new migration test failed on
the absent tables before implementation. The existing domain-error contract
uses HTTP 400; schema errors use 422. Tests follow that existing convention.

Compatibility boundary: exchange format 1.0 cannot represent the new records.
Until its format is extended, enriched projects explicitly refuse exchange
export rather than silently lose data; legacy project exchange remains
available. Full database backups retain the new tables. No new model weights
or dependencies have been added to the application.
The existing `stage-bundled-models.py` and `build-desktop.ps1` enforce a
weight-free manifest; some workflow step labels still say "bundled checkpoints"
and are stale. This branch preserves the enforced registration-only policy.

Geographic checkpoint: movement analytics now exclude stale or unknown-freshness
coordinates and report an initial WGS84 bearing in degrees clockwise from true
north. Stationary pairs have no bearing. Cardinal, dateline and persisted
invalidation/recomputation fixtures passed; this does not validate drone camera
attitude, height references or survey-grade position uncertainty.

Environmental checkpoint: the first provider is NOAA CO-OPS station water
temperature. Original provider payloads, station identity, flags and timestamps
are preserved. Missing values are counted; malformed, mismatched and empty
responses fail transactionally. Cache expiry is 24 hours and refresh occurs on
request. Offline operation makes no provider request. Bounded lookup returns
observations with distance/time/depth offsets without interpolation, excludes
suspect/rejected measurements, and never treats unknown depth as surface depth.
The project workspace supports local JSON and NOAA import, record pagination,
source/variable filters, QC, units, UTC and provenance inspection.

Live acceptance smoke: on 2026-10-18, the actual adapter acquired 240 NOAA
Charleston station 8665530 temperature observations for 2026-10-16 into a
disposable database. A new database session in offline mode returned the same
240 record IDs. This validates the protocol/cache path, not sensor accuracy or
representativeness at an organism's location.

Validation checkpoint before final review:

- New scientific/provider/migration focused suite: 27 passed.
- Geographic movement/georeferencing focused suite: 71 passed.
- Frontend: 464 tests passed in 94 files; TypeScript and production build pass.
- Python Ruff and mypy (416 source files) pass.
- A full backend run after installing declared development extras reached
  1212 passed, 32 skipped and two failures. One was the environment's bundled
  FFmpeg executable/path; one was a test typo corrected while the run was in
  progress. A targeted rerun with `IMAGEIO_FFMPEG_EXE=/usr/bin/ffmpeg` passed
  all 14 affected packaging/environment tests. Final complete rerun follows
  review fixes; the earlier run is not represented as passing.
- New browser acceptance test is committed. Local Playwright could not launch:
  Chromium was absent and its installer received empty/invalid ZIP downloads.
  Browser execution and visual inspection remain unverified locally.

## Remaining acceptance gates and next milestones

1. Complete independent branch review, address integrity findings with
   regression tests, rerun gates and record final-head CI in draft PR #71.
2. Extend project exchange to carry scientific records/cache and remap their
   referenced IDs; validate actual researcher 1.0.x projects and installed-app restore.
3. Bind provider lookup in image/video/track inspectors and expose record
   revision selection, with explicit distance/time/depth limits.
4. Add a credential-configurable Copernicus subset/grid adapter and cached
   current, temperature and salinity fixtures before the current visualizer.
5. Extend telemetry uncertainty and surveyed georeferencing acceptance, then
   GeoPackage and pairwise movement exports. Keep approximate positions marked.
6. Implement the unit-checked computed-metric engine against verified
   annotations and matching run/frame outputs; keep the comprehensive visual
   node editor reserved for 2.0.

Windows installed-app/WebView, NVIDIA hardware, real drone/GCP reference data,
authenticated Copernicus and researcher sensor/reference acceptance are still
required. CI builds and synthetic fixtures cannot substitute for these gates.

Independent review identified two important findings. Both were reproduced by
failing tests before correction: same-project unrelated jobs were accepted as
model provenance; environmental lookup could return a superseded observation
after NOAA corrected its value, removed it or marked it suspect. Source job
kind/media/object lineage is now validated. Provider records retain immutable
history with a computed current-snapshot indicator, and normal lookup excludes
superseded snapshots. The workspace labels historical provider records. No
critical or deferred minor findings were reported by that review.
After these fixes, the focused scientific/environmental/migration suite passed
33 tests, including reopening a full backup snapshot and reusing the same
provider records offline. The frontend suite passed 465 tests in 94 files;
TypeScript, production build, Ruff and mypy passed again. The production build
retains the existing large-chunk warning.

Final local backend gate: `IMAGEIO_FFMPEG_EXE=/usr/bin/ffmpeg .venv/bin/python
-m pytest apps/api/reefvision/tests -q --pose-interop-integration` passed
**1248 tests, with 4 skipped**, in 393 seconds. The skips require the dedicated
live SAM acceptance job or an external WhaleDrone MP4/SRT reference pair.
There was one existing FastAPI/Starlette TestClient deprecation warning.
The system-FFmpeg override resolves this environment's non-executable packaged
binary; it does not prove packaged Windows FFmpeg acceptance. Final-head CI and
browser execution evidence are tracked in
[draft PR #71](https://github.com/Rafael-Del-Valle/ReefVision/pull/71).

Rulings made for this milestone: restrict explicit coordinates to source pixels
and WGS84 until validated CRS transforms exist; keep canonical image calibration
and snapshot it; refuse old exchange exports for enriched projects until the
format can preserve them; implement daily cache expiry on request before adding
a scheduler. These choices avoid silent transformations or data loss, with the
cost of limited CRS/export support and no unattended daily refresh yet.
