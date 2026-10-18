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
Alembic currently ends at 0037. Public IDs are UUIDs, source coordinates are
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
| 1 Scientific foundation | Validated baseline | In progress | Pending | No | Typed spatial/time/unit/provenance records, scoped IDs, additive migration, compatibility and integrity tests |
| 2 Telemetry and geographic measurements | 1; existing georeferencing | Existing reusable infrastructure | Baseline tests being run | No | Heading/pairwise fixtures, uncertainty reporting, mask geometry, GeoPackage, real drone reference |
| 3 Environmental context | 1 | Planned | No | No | Local import, NOAA, Copernicus, bounded lookup, daily cache, offline, credentials |
| 4 Current visualizer | 2, 3 | Planned | No | No | Streamlines, time/depth, layers, trajectories, cache/provenance, desktop acceptance |
| 5 Scientific heatmaps | 1; existing pose/annotation records | Existing partial infrastructure | Not assessed for 1.1 | No | Independent reviewer/model layers and disagreement validation |
| 6 Computed metrics | 1; calibration and verified annotations | Existing measurements only | Not assessed for 1.1 | No | Safe arithmetic/unit engine, matching run/frame identity, saved calculations/provenance |
| 7 Event/environment analysis | 2, 3, 6 | Planned | No | No | Event windows, tides/lunar provenance and reproducible exports |

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
