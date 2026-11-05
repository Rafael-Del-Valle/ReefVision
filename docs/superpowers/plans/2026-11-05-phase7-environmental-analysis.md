# Phase 7 environmental-analysis implementation plan

## Goal

Deliver the largest coherent, scientifically defensible Phase 7 slice through immutable persistence, API, NOAA/lunar services, event windows, joins/lags, workflows, CSV, project exchange, and the Environmental Context UI while preserving all existing contracts.

## Checkpoint A: persistence and deterministic lunar analyses

1. Write failing migration/model tests for `0042`, legacy upgrades, downgrades, data preservation, and transaction rollback.
2. Add the immutable environmental-analysis definition/result models, migration, model exports, typed shared schemas, canonical hashing, ownership validation, and CRUD/currentness services.
3. Write failing astronomical reference/boundary/batch tests, then extend the lunar service and add persisted single/batch analysis endpoints.
4. Add definition/result list/read/validation and lunar CSV evidence export.
5. Run focused tests plus Ruff/mypy for the slice, review the diff, commit, fetch, and safely push the checkpoint to PR #71's head branch.

## Checkpoint B: NOAA tidal context and temporal analyses

1. Write failing NOAA adapter tests for predictions versus observations, explicit datum/station/UTC parameters, provider errors, cache reuse, offline operation, and raw provenance.
2. Extend the existing NOAA/environmental-context services to persist water-level `ScientificRecord` rows and cache raw provider responses without adding a competing sample store.
3. Write failing tidal-context tests for nearest records, station/time/distance tolerances, predicted stage qualification, observed/predicted separation, and insufficient evidence.
4. Write failing event-window tests for inclusive/exclusive boundaries, overlapping-window merge, empty matches, legacy-threshold snapshots, and UTC handling.
5. Write failing join/lag tests for capture-time evidence, time/location/depth enforcement, deterministic ties, repeated-use counts, missing evidence, and descriptive-only output.
6. Implement typed services/endpoints and CSV evidence exports using the shared immutable analysis persistence layer.
7. Run focused and regression tests, static checks, review, commit, fetch, and safely push.

## Checkpoint C: workflows, exchange, and React

1. Write failing Workflow Builder registration/execution/replay tests for all five analysis kinds, then implement nodes that call the standalone services.
2. Write failing project-exchange round-trip, ID-remap, hash-corruption, missing-reference, and atomic-failure tests, then add definition/result sections and validators.
3. Write failing React tests for analysis navigation, lunar persistence, observed/predicted tidal controls, matching tolerances, provenance/QC, windows, joins/lags, result history, and CSV actions.
4. Implement API client types and Environmental Context UI using the existing visual system and accessibility patterns.
5. Add Workflow Builder templates and node metadata for the new executable nodes.
6. Run backend and frontend focused suites, full backend suite, Ruff, strict mypy, TypeScript, Prettier, production build, and relevant Playwright coverage.
7. Review final diff and schema compatibility, commit, fetch, safely push, update draft PR #71 and issue #76 with exact-SHA evidence, and inspect CI without merging, tagging, or releasing.

## Acceptance

- Migration `0042` upgrades/downgrades cleanly and preserves legacy scientific data; failed imports/creates are atomic.
- Numeric NOAA samples remain scientific records with cached raw provider evidence; analyses remain typed immutable composite results.
- Lunar reference and boundary tests state tolerances and algorithm limits.
- Tidal outputs never conflate observed and predicted products or fabricate unsupported stage labels.
- Event windows, temporal/spatial/depth joins, and lagged comparisons are deterministic and expose repeated-use risk.
- API, UI, workflows, CSV, and project exchange use the same service contracts and canonical hashes.
- PR #71 remains draft; no merge, tag, or release is performed; ReefVision 1.1 is not declared complete unless every requested acceptance criterion is verified.
