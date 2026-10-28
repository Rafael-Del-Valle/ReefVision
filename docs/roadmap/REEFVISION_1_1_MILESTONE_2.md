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

### Task 3 evidence

- Implemented optional bounded Copernicus Toolbox worker, secure environment-only
  configuration, modeled grid parsing, pinned versions, refresh/offline reuse and
  shared NOAA/Copernicus persistence. Added cache inventory/open APIs.
- Implemented current vectors in the existing Leaflet map with speed/direction,
  exact time/depth selection, extent/visibility controls, offline geometry and
  explicitly spatial-only fresh WGS84 organism overlays.
- Provider tests: 17 passed; provider plus NOAA cache tests: 31 passed. UI suite:
  480 passed in 97 files; type checking, Ruff, mypy and production build passed.
- Added exact API route regression after detecting a duplicate URL prefix in the
  subject inspector (1 failed / 4 passed before correction; 5 passed after).
- Added malformed exchange-cache regressions (2 failed / 1 passed before guard);
  invalid inventory structures now produce structured validation failures.
- Local browser acceptance remains blocked: Chromium download returned invalid ZIP
  data and the executable is unavailable. Expanded Playwright acceptance covers
  subject-context routing and actual Leaflet current-marker visibility in CI.
- Ruling: keep optional provider dependencies out of the default desktop installer;
  a separately configured researcher runtime is required for live acquisition.
  Cache inspection and visualization remain usable without it.
- Ruling: preserve potential temperature and reject ambiguous salinity/current-axis
  semantics. A narrower supported dataset set is preferable to mislabeled values.
- Full backend regression run is in progress. Copernicus live credentials, packaged
  runtime execution and field comparison remain external acceptance gates.

### Task 4 evidence — first computed-metric vertical slice

- Implemented a safe arithmetic interpreter with declared-symbol and AST
  whitelists, unit/dimension conversion, finite-result checks and first-order
  independent uncertainty propagation. Arbitrary calls, attributes, booleans,
  exponentiation and incompatible units fail closed.
- Added immutable checksummed metric definitions/results and additive migration
  `0039_computed_metrics.py` after the existing, unchanged
  `0038_scientific_data.py`. Results retain formula version/hash, original and
  normalized values/units, uncertainty, exact subject/time identity, input IDs
  and snapshots, calibration status, evidence category and workflow provenance.
- Added standalone project API, result CSV, and a Computed Metrics workspace for
  explicit symbol/dimension definitions and symbol/record-ID bindings. The UI
  exposes formula/input provenance and does not hide the verified-annotation vs
  unverified-prediction boundary.
- Added executable typed `scientific_records_source` and `computed_metric`
  Workflow Builder nodes plus a reusable template. Saved graph execution persists
  a result and checksummed artifact; same-node replay is idempotent and conflicting
  retry is rejected.
- TDD evidence: expression domain 16 passed; computed API/migration/scientific
  lineage 45 passed; combined workflow/metric regressions 36 passed; panel 2
  passed; workflow-template 4 passed. Pre-review local validation on 2026-10-28 passed
  1,328 backend tests with 4 explicit live/hardware skips, 506 frontend tests,
  TypeScript, production build, Prettier, Ruff and strict mypy across 421 source
  files. Configured Playwright acceptance passed 13 tests and skipped the
  external live-OSM demo. Exact-head remote CI remains the final integration gate.
- Ruling: the initial slice requires all scalar inputs to share exact observation
  time and full subject identity. It does not silently aggregate frames, objects,
  tracks, verified annotations and predictions. Aggregate counts/coverage,
  replicate/group design, bulk dataset calculations and broader formula functions
  remain Phase 6 follow-on work.
- Review hardening: infer dimensions without dummy numeric inputs; stabilize
  quotient derivatives and uncertainty norms; bound formula size/complexity and
  return structured errors for numeric overflow. Hash the stored formula version
  and explicitly reject unsupported engines. Reject duplicate record bindings,
  bounds/mixed uncertainty kinds, and ambiguous empty-subject context. Preserve
  supported uncertainty kinds in provenance. Absolute temperatures allow direct
  conversion only until distinct interval semantics exist. CSV has no row cap
  and includes normalized quantities and workflow IDs; the UI offers load more
  and total counts. Project exchange fails closed when computed definitions or
  results exist because exchange does not yet preserve/remap them.
- Lineage coordination: independent 1.6 PR #77 also introduces a migration numbered
  `0038`. Integration must preserve both already-shared histories and explicitly
  merge or renumber in the integrating branch; this 1.1 work does not rewrite
  either `0038` migration.
