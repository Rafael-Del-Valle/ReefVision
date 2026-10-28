# ReefVision 1.1 development roadmap

Status date: 2026-10-28 UTC. Development only; no release acceptance claimed.

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
The baseline Alembic head was 0037; this branch adds 0038 and 0039. Public IDs are UUIDs, source coordinates are
pixels, and model predictions remain separate from verified annotations.

Reusable implementations inspected:

| Area                  | Existing implementation                                                         | 1.1 work                                                             |
| --------------------- | ------------------------------------------------------------------------------- | -------------------------------------------------------------------- |
| Telemetry             | `geospatial/dji_srt.py`, `synchronization.py`, video georeferencing services    | Extend; preserve explicit alignment and height evidence              |
| Geographic records    | `GeoReferencedObservation`, configuration hash and stale-state services         | Reuse; do not duplicate projection or invent uncertainty             |
| Movement/export       | Geographic movement analytics and GIS export services                           | Heading, pairwise analysis, GeoPackage and reference acceptance      |
| Image calibration     | `image_scale_calibration.py`, `scientific_mask_measurements.py`, image metadata | Preserve canonical calibration; snapshot it in scientific provenance |
| Tracking/heatmaps     | Video tracks, pose visualization and behavior services                          | Human/model/reviewer layers and uncertainty                          |
| Workflows             | Graph records, persisted execution, typed node registry and results packages    | Safe computed metrics; comprehensive editor deferred to 2.0          |
| Environmental context | No dedicated provider/cache/project scientific-record subsystem found           | Add persistent typed records and bounded provider import             |

## Milestones and acceptance

| Phase                                   | Dependencies                            | Implemented                                                                                                                   | Tested                                                                                                           | Release-validated | Acceptance remaining                                                                                                                                      |
| --------------------------------------- | --------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- | ----------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1 Scientific foundation                 | Validated baseline                      | Core records, units, UTC, WGS84/pixels, calibration snapshots, provenance, QC and cache tables                                | API, integrity, serialization, migration round trip and legacy exchange tests pass                               | No                | Additional CRS transforms, scientific project exchange, broader real-project migration acceptance                                                         |
| 2 Telemetry and geographic measurements | 1; existing georeferencing              | Existing telemetry/calibration reused; stale-coordinate exclusion and WGS84 segment bearings added                            | 71 focused backend tests pass, including datum-change/invalidation/recomputation; frontend regression tests pass | No                | Propagated geographic uncertainty, pairwise geographic motion, mask geometry, GeoPackage, absolute UTC/VFR alignment, surveyed drone references           |
| 3 Environmental context                 | 1                                       | Local JSON import, NOAA station temperature, persistent 24-hour cache/offline, bounded lookup and project workspace           | Provider/API/cache tests and live NOAA smoke test pass; UI unit tests/build pass                                 | No                | Copernicus current/temperature/salinity grids, credential settings, unattended daily refresh, detection/track lookup controls, browser/desktop acceptance |
| 4 Current visualizer                    | 2, 3                                    | Not started                                                                                                                   | No                                                                                                               | No                | Streamlines, time/depth, layers, trajectories, cache/provenance, desktop acceptance                                                                       |
| 5 Scientific heatmaps                   | 1; existing pose/annotation records     | Existing partial infrastructure                                                                                               | Not assessed for 1.1                                                                                             | No                | Independent reviewer/model layers and disagreement validation                                                                                             |
| 6 Computed metrics                      | 1; calibration and verified annotations | First scalar vertical slice: safe unit-aware arithmetic, immutable definitions/results, API/CSV/UI, executable workflow nodes | Domain/API/migration/workflow/UI regressions pass; broad final-head validation recorded below                    | No                | Aggregate annotation/mask counts and coverage, replicate/group contracts, broader formula functions and field-data acceptance                             |
| 7 Event/environment analysis            | 2, 3, 6                                 | Not started                                                                                                                   | No                                                                                                               | No                | Event windows; automated tidal/lunar context for dated, georeferenced observations; reproducible analysis and exports                                     |

Optional advection is deferred until core acceptance. Existing 1.0.x GUI,
GPU and scientific acceptance issues do not block additive foundation work,
but must be reconciled before a combined 1.1 release. Do not merge, tag,
publish installers, bundle model weights or mark the release complete.

## Planned tidal and lunar context (v1.1)

**Status (2026-10-21): planned only; not implemented or release-validated.**
This expands Phase 7 (event/environment analysis), reuses the Phase 3 provider/cache contracts
and Phase 6 computed metrics, and must work both from Environmental Context and as executable
Workflow Builder nodes. Preserve all earlier milestone scope; do not substitute this plan
for a functioning implementation.

### Automatic observation context and scientist-facing UI

- When an image, video frame, track, or biological event has a valid observation timestamp
  and georeferenced site, show a **Tidal & Lunar Context** section in its Environmental
  Context inspector, and offer a bulk action to calculate the same context for an
  entire dataset. Permit explicit researcher-supplied observation time and location
  when source metadata is missing, recording how they were supplied; never silently
  substitute ingestion time, the user's current location, or a guessed site.
- Display the astronomical lunar phase (new, waxing crescent, first quarter, waxing
  gibbous, full, waning gibbous, last quarter, waning crescent), illumination fraction,
  lunar age, and a timestamp. Prefer reproducible **offline astronomical calculation**,
  recording algorithm/ephemeris version and time convention. Moonrise/set, if later
  added, requires observation location and an appropriate astronomy library.
- For available tidal data, display a small time-series curve with the matched
  observation time, rising/falling/near-high/near-low water-level state, nearest
  high/low-water timestamps and elapsed time, station/model identity, reference
  datum, distance from site, quality and whether values are **predicted** or
  **observed**. Expose missing/uncertain/stale data rather than drawing a plausible
  curve from no measurements.
- Label water-level rise/fall separately from **flood/ebb current**. Do not infer
  local current direction from water-level trend; use an independently validated
  current model or current observation where that feature is available.
- Offer spring/neap characterization only from an appropriate local tidal-range
  prediction/series, with method and uncertainty; do not equate lunar phase alone
  with a definitive spring/neap tidal state.

### Tidal data and scientific constraints

- Add a NOAA CO-OPS adapter for tide predictions and, separately, observed water
  levels where supported. Match station, time window, units, tidal datum, timezone,
  provider QC and refresh/cache identity, preserving raw responses and immutable
  acquisition provenance. Keep observed and modeled/predicted values distinct.
- Allow a user-confirmed station selection and explicit maximum acceptable
  distance/offset; a nearby coastal station may not represent a mesophotic/offshore
  reef. Support researcher-provided tide-gauge or validated regional model inputs
  as future-compatible alternatives without silently transferring coastal
  predictions offshore.
- Handle UTC normalization, local display, daylight-saving transitions,
  timezone-naive/rejected timestamps, gaps, partial series, conflicting datums,
  datum-unsupported stations, cache expiry and offline use. Missing inputs mean
  **unavailable**, not zero. Do not claim tidal phase accuracy without adequate
  time coverage and a supported reference.

### Analysis, Workflow Builder and export

- Match environmental context to organism observations, verified annotations,
  behavior/tracking events and spawning/feeding events using explicit time,
  location, depth and quality bounds; record offsets and coverage, and leave
  unmatched records unmatched.
- Support event-window comparisons before/at/after events (including configured
  hour/day lags) and exploratory relationships between polyp activity, abundance,
  movement, tides, lunar illumination and other environmental variables.
  Present sampling effort, repeated-measure/temporal autocorrelation caveats,
  and **association rather than causation**. Avoid claiming significance from
  naive pooled daily images or mismatched experimental units.
- Make the operations available as **real, executable typed Workflow Builder
  nodes**, e.g. lunar-context, tide-context, environment/event join, and lagged
  comparisons. Require persisted output, immutable source linkage, provenance,
  deterministic formula/algorithm version, robust failures and a saved-workflow
  roundtrip regression. A node registry entry or standalone UI alone does not
  count as completion.
- Provide exportable observation-environment tables (CSV and geographic export
  where coordinates are valid) with units, UTC timestamps, station/model IDs,
  source kind, datum, quality flags, match offsets, calculation versions and
  explicit missing values; retain provenance so analyses are reproducible offline.

### Minimum acceptance evidence (unchecked until implemented)

- [ ] Timestamp/GPS/manual-metadata linking works for cold-open images,
      video frames, tracks and event observations, with no inferred provenance.
- [ ] Deterministic lunar phase/illumination is tested on reference new/full/
      quarter dates across timezone and year boundaries; calculations work offline.
- [ ] Tide provider fixtures cover observed vs predicted, high/low detection,
      rising/falling transitions, datum mismatch, missing/gapped series,
      distant/offshore stations, and offline cache integrity/revision handling.
- [ ] The inspector and bulk dataset action display the same validated
      results with visible provenance, limits and stale/unavailable states.
- [ ] Executable saved Workflow Builder runs, reproducible exports and
      event-window/lag comparisons have representative scientific regressions.
- [ ] Windows/Tauri installed-GUI behavior and representative scientific
      data are accepted independently from backend/unit/CI tests.

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

## Computed metrics checkpoint (2026-10-28)

The first Phase 6 vertical slice is implemented. A safe AST interpreter accepts
only declared symbols, numeric constants, parentheses, unary signs and
`+ - * /`; it does not execute Python or arbitrary calls. It performs unit and
dimension validation, converts supported scalar/density/rate/percent units,
rejects non-finite and zero-division results, and propagates independent
first-order uncertainty when all inputs provide uncertainty.

Definitions and results are immutable project-scoped records with formula
version, definition/result SHA-256, original and normalized quantities,
uncertainty, input record IDs and snapshots, exact subject/time identity,
calibration currency and evidence-category checks. Standalone API/UI calculation,
CSV export and saved Workflow Builder execution use the same service. The
workflow source requires explicit record IDs; its typed result artifact carries
the persisted result ID and checksum. Same-node replay is idempotent, while a
conflicting replay fails without overwriting provenance.

Focused TDD evidence: 16 expression-domain tests; 45 computed-metric
API/migration/scientific-lineage tests; 36 combined workflow/computed-metric
regressions; and 2 scientist-panel plus 4 workflow-template frontend tests
passed. Final local validation on 2026-10-28 passed 1,328 backend tests with 4
explicit live/hardware skips, 506 frontend tests, TypeScript, production build,
Prettier, Ruff and strict mypy across 421 source files. Configured Playwright
acceptance passed 13 tests and skipped the external live-OSM demo. The build
retains the existing large-chunk advisory and backend retains the existing
Starlette TestClient deprecation warning. Exact-head remote CI is tracked in
draft PR #71 rather than inferred here.

This is intentionally a scalar, exact-observation slice. It does not yet infer
counts or coverage directly from annotation/mask collections, combine subjects,
define biological replicates, calculate bulk dataset summaries, or expose
general functions/exponentiation. Those require explicit aggregation and
evidence contracts; silently grouping frames, tracks or model predictions is
not acceptable. Representative field data, Windows installed-app behavior and
independent scientific acceptance also remain open.

Migration `0039_computed_metrics.py` follows this branch's existing, untouched
`0038_scientific_data.py`. Independent 1.6 work in PR #77 also uses a migration
number `0038`; merge sequencing must preserve both histories and create a
deliberate Alembic merge/renumber decision in the integrating branch. Neither
already-shared migration is rewritten in this 1.1 work.

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
6. Extend computed metrics beyond the first exact-subject scalar slice with
   aggregate verified-annotation/mask counts and coverage, explicit replicate
   grouping, bulk calculation/export and additional reviewed formula functions;
   keep the comprehensive visual node editor reserved for 2.0.

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

The first combined-head CI browser run executed the new workspace flow and
failed on an ambiguous test selector: "Unknown depth" matched both the record
value and inspector guidance. The assertion now matches the exact value;
application behavior was unchanged. Browser CI must pass on this correction
before its acceptance is claimed.

Rulings made for this milestone: restrict explicit coordinates to source pixels
and WGS84 until validated CRS transforms exist; keep canonical image calibration
and snapshot it; refuse old exchange exports for enriched projects until the
format can preserve them; implement daily cache expiry on request before adding
a scheduler. These choices avoid silent transformations or data loss, with the
cost of limited CRS/export support and no unattended daily refresh yet.
