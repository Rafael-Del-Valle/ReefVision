# ReefVision 1.1 — scientific integration milestone 2

Baseline: `ce74a637`, extending the seven existing commits on
`develop/reefvision-1.1`, draft PR #71. Main remains `9278d45e`.
The user authorizes autonomous implementation, tests, commits and draft-PR updates;
release, merge, tag and hardware/scientific acceptance remain gated.

## Design and execution plan

1. **Scientific project exchange.** Extend the existing archive inventory and
   importer with format `1.1` (explicitly also accept legacy `1.0`). Preserve raw
   observations, calibration snapshots, coordinate frames, uncertainties and
   provider payloads. Remap only scientific linkage fields, never arbitrary source
   metadata or raw provider values. Validate IDs, foreign keys, payload hashes and
   cache membership before any database mutation. Use one import transaction and
   remove only newly created import files on failure. Files: existing
   `services/project_exchange*.py`, a scientific exchange helper, exchange tests.
   Acceptance: legacy and enriched round trips; repeated imports isolated; offline
   cache reopens; changed/corrupt/foreign/duplicate references rejected; injected
   finalization failure leaves every database table and source project unchanged.
2. **Environmental inspectors.** Reuse the bounded environmental lookup service
   and add subject-context resolution plus a shared inspector component. Explicit
   location/time evidence is required; stale georeferencing and ambiguous or
   missing timestamps produce an unavailable state. Show source kind, offsets,
   depth, QC, uncertainty and cache age. Files: environmental schemas/service/API,
   image/video/workspace panels and frontend tests. Acceptance: selected subject
   is carried through lookup, nearby station offsets visible, no invented values,
   unavailable/offline/error states tested.
3. **Copernicus and vector map.** Add a bounded, optional provider adapter with
   credential configuration outside project records and deterministic fixtures.
   Persist modeled samples with their dataset/time/depth/version provenance using
   existing scientific/cache tables. Reuse Leaflet for vector arrows, magnitude,
   time/depth/extent/layer controls and cached offline display. No credentials or
   provider-dependent acceptance claims in fixtures or archives. Acceptance:
   east/north vector numerical fixtures, bounded requests and failure handling,
   cache reopen, source-kind separation, UI controls and production build.
4. **Independent follow-on work.** Extend geographic pairwise/displacement exports,
   calculation definitions and heatmap integration only after the critical paths
   are validated. Reuse existing movement/workflow/heatmap modules. Physical
   calculations require calibration and explicit subject/run matching.
5. **Validation and integration.** Run focused tests per increment, broad backend
   and frontend suites, Ruff/format/mypy/type checking/build and migration tests.
   Use a fresh independent final code review. Push focused commits without
   rewriting shared history, inspect Actions and keep PR #71 a draft.

## Review focus

- Importing the same archive twice must not share scientific or cache identifiers.
- A cache refresh must retain historical measurements and current-snapshot status.
- Foreign references or failed artifact restoration must leave no partial project.
- Source provenance strings that happen to equal UUIDs must remain literal values.
- Missing or stale subject positions/times must never become environmental estimates.

## Status and decisions

- Remote verification: head unchanged at `ce74a637`; all 29 Actions checks passed,
  including Windows packaging and fresh install smoke testing of that baseline.
- Ruling: retain the existing isolated branch and native inline execution; the
  supplied execution directive already authorizes implementation and draft pushes.
- Ruling: archive exchange imports create a new project; full application backups
  remain exact database/filesystem restoration, with no identifier remapping.
- Scientific exchange: in progress. Other implementation tasks: pending.
- Baseline local validation: Python virtual environment is being restored; no
  new test outcome claimed until executed successfully.

### Task 1 evidence

- Implemented exchange `1.1` scientific inventory, explicit remapping, checksums,
  source-archive/ID-map provenance, strict version support and one-commit import.
- Baseline before changes: 35 backend tests passed; 14 environmental UI tests passed.
- New exchange regression tests: 11 failed / 1 passed before implementation;
  12 passed after implementation. Combined exchange/science/environment suite:
  52 passed, one upstream FastAPI/Starlette deprecation warning.
- Ruff passed; mypy passed for 417 source files. No migration changed.
- Task 1: complete pending whole-milestone review and CI; task 2: in progress.

### Task 2 evidence

- Implemented exact-subject environmental lookup with explicit position/time
  evidence, ambiguity handling, bounded joins and cache-age metadata.
- Shared inspector integrated into image annotations, selected video/frame/track,
  geographic analysis workspace and project geographic-position cards. Position
  references are append-only scientific records; nearby observations stay distinct.
- New backend tests: 5 failed before implementation, 5 passed after. Combined
  science/exchange/environment/subject tests: 49 passed, one upstream warning.
- Frontend: 470 tests passed in 95 files; TypeScript and production build passed.
  Build retains the existing large-chunk advisory. No new production dependency.
- Ruling: require explicit UTC subject evidence instead of inferring UTC from
  relative video time or camera/station GPS; automatic drone UTC alignment remains
  a later prerequisite, and existing georeferencing remains unchanged.
- Task 2: implemented and automated-tested; external scientific acceptance pending.
