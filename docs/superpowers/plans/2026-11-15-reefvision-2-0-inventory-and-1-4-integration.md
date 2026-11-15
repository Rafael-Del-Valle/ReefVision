# ReefVision 2.0 Inventory and 1.4 Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish the enforceable 1.1–2.0 feature inventory and reconcile the
validated 1.3 line with draft ReefVision 1.4 before completing its spatial
analysis feature entries.

**Architecture:** A canonical JSON inventory is validated and rendered to
Markdown by one standard-library script. ReefVision 1.4 remains the bounded
product branch: merge the validated 1.3 head explicitly, preserve both
histories, retire unresolved SLEAP-specific supported paths, reconcile
migrations through new revisions, then close 1.4 features individually.

**Tech Stack:** Python 3.12, JSON, pytest, FastAPI/SQLAlchemy/Alembic,
React/TypeScript/Vitest/Playwright, Tauri/MSI, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-11-15-reefvision-through-2-0-program-design.md`

## Global Constraints

- Preserve original media, source-pixel coordinates, immutable dataset
  versions, stable class indices, explicit review, and group-aware splits.
- Do not edit an applied migration.
- No cloud collaboration, stereo, hyperspectral implementation, implicit
  model download, or publication.
- New user-facing tools require a tested normal navigation path.
- Advanced controls belong in an existing task workspace unless the activity
  is durable and distinct.
- Missing representative inputs block only their named evidence checks.
- Push only fast-forward updates to draft branches; never force-push.

## Review Focus

- Inventory records whose broad milestone is green but whose own evidence is
  missing must remain open.
- Historical archives containing unknown/retired providers must remain
  readable without loading executable provider code.
- Independent migration lineages with the same revision label must be
  diagnosed from schema/content, never guessed from the label alone.
- 3D geometry descriptors must not be labeled biological condition,
  anatomical branch length, or verified specimen identity.
- UI entry-point tests must begin from project navigation and preserve project,
  media, and review context.

---

### Task 1: Canonical feature inventory and release gate

**Files:**
- Create: `docs/roadmap/REEFVISION_2_0_FEATURE_INVENTORY.json`
- Create: `docs/roadmap/REEFVISION_2_0_FEATURE_INVENTORY.md`
- Create: `scripts/check_release_feature_inventory.py`
- Create: `apps/api/reefvision/tests/test_release_feature_inventory.py`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Produces: `load_inventory(path: Path) -> dict[str, object]`
- Produces: `validate_inventory(document: object) -> list[str]`
- Produces: `render_inventory(document: dict[str, object]) -> str`
- Produces: CLI `python scripts/check_release_feature_inventory.py
  [--check-render]`

- [ ] Write failing tests for required fields, unique IDs, dependency
  references, allowed status transitions, exact blocked inputs, explicit
  deferral reasons, user entry points, evidence categories, and deterministic
  Markdown rendering.
- [ ] Run the focused pytest and confirm missing script/data failures.
- [ ] Implement the standard-library loader, validator, renderer, and CLI.
- [ ] Populate every feature from the product spec, version roadmaps, approved
  design/specs, draft PRs #71/#85/#87/#79/#77/#78, and issue #76. Include
  projective density, repeated measures, biological condition, early plugin
  foundations, 3D matching, and long-gap/video ReefPose re-identification as
  separate records.
- [ ] Mark hyperspectral, cloud collaboration, and stereo explicitly deferred;
  do not omit them.
- [ ] Add the validator to CI and verify deterministic generation.
- [ ] Commit the inventory gate.

### Task 2: Exact SLEAP distribution audit and supported-build retirement

**Files:**
- Create: `docs/decisions/0010-sleap-supported-build-retirement.md`
- Create: `docs/THIRD_PARTY_SLEAP_AUDIT.md`
- Modify: `apps/api/reefvision/ml/provider_hub.py`
- Modify: `apps/api/reefvision/ml/sleap_nn_provider.py`
- Modify: `apps/api/reefvision/ml/video_tracking.py`
- Modify: `apps/api/reefvision/services/pose_interoperability.py`
- Modify: SLEAP-specific API schemas/routes, web controls, installer scripts,
  optional dependencies, CI paths, docs, and tests identified by the audit.
- Create: provider-retirement and historical-project compatibility tests.

**Interfaces:**
- Produces: structured unavailable-provider metadata for historical
  `sleap_nn` registrations and runs.
- Preserves: neutral canonical pose records and non-SLEAP exports.

- [ ] Freeze the exact component/version/distribution inventory and upstream
  license evidence for `sleap-nn==0.3.3`, `sleap-io==0.9.2`, the original
  SLEAP application, transitive packages, MSI contents, optional extras,
  fixtures, and weights.
- [ ] Write failing tests proving the supported build exposes no active
  SLEAP-specific registration, inference, SLP import/export, install, menu, or
  enabled CI path while historical records remain readable and exportable
  through neutral formats.
- [ ] Remove active support and correct all license/status copy.
- [ ] Verify no default/optional packaged payload silently includes the retired
  runtime.
- [ ] Commit the audit and retirement.

### Task 3: Reconcile validated 1.3 and draft 1.4 ancestry

**Files:**
- Modify: all merge-conflicted source/tests/docs after an explicit merge of
  `f44053a9` into the refreshed #79 head.
- Create: `docs/roadmap/REEFVISION_1_4_INTEGRATION_AUDIT.md`

**Interfaces:**
- Consumes: validated 1.3 APIs, migrations, Workflow Builder contracts, and
  draft 1.4 spatial services.
- Produces: one 1.4 integration head containing both histories.

- [ ] Refresh #79 and issue #76; record both exact SHAs and compare inventory.
- [ ] Merge the validated 1.3 head without rewriting either side.
- [ ] Resolve conflicts by preserving newer 1.3 release/data contracts and
  independently useful 1.4 spatial features.
- [ ] Run targeted tests for every resolved subsystem before continuing.
- [ ] Record rejected/superseded draft behavior explicitly.
- [ ] Commit the reconciliation.

### Task 4: Reconcile migration histories without editing applied revisions

**Files:**
- Create: new 1.4 Alembic merge/reconciliation revision(s).
- Create: lineage fixture databases and preservation tests.
- Modify: migration documentation and Windows upgrade acceptance.

**Interfaces:**
- Consumes: validated 1.3 lineage and draft 1.4 spatial schema/history.
- Produces: one unambiguous upgrade graph and structured rejection for unknown
  or inconsistent histories.

- [ ] Write failing lineage tests using copies from every supported branch.
- [ ] Fingerprint protected rows, indexes, foreign keys, IDs,
  `sqlite_sequence`, and managed-asset manifests.
- [ ] Add new merge/reconciliation migrations; never modify old files.
- [ ] Prove upgrade, downgrade where supported, backup restore, and older-code
  rejection without mutating originals.
- [ ] Record the independent future 1.6 `0038` history in the inventory, but
  defer its database compatibility matrix to the 1.6 integration milestone.
- [ ] Commit the migration reconciliation.

### Task 5: Persistent versioned 3D project assets

**Files:**
- Create/modify: focused spatial asset models, migration, repository, storage,
  service, schemas, routes, exchange adapters, frontend task panel, and tests.

**Interfaces:**
- Produces: project-scoped mesh/point-cloud assets with UUID, managed path,
  source SHA-256, format, units, coordinate frame, transform, calibration
  evidence, review state, and immutable revisions.
- Reuses: existing bounded preview and measurement engines.

- [ ] Write failing storage/API/exchange tests for valid, malformed, oversized,
  missing-calibration, stale, and tampered assets.
- [ ] Persist assets without changing originals and run expensive parsing as
  background jobs.
- [ ] Add the contextual 3D task entry point and first-use navigation test.
- [ ] Add standalone and executable saved Workflow Builder parity.
- [ ] Commit the asset slice.

### Task 6: Reviewed 3D measurements and longitudinal matching

**Files:**
- Modify: spatial measurement/comparison services, schemas, UI inspectors,
  workflow nodes, exchange, reports, and tests.

**Interfaces:**
- Produces: reviewed dimensions, extents, surface paths, area, conditional
  volume, uncertainty/QC, registration evidence, specimen correspondence, and
  longitudinal change.
- Keeps separate: spatial 3D matching and appearance-based ReefPose
  re-identification.

- [ ] Add known-geometry RED tests for scale exponents, transforms,
  watertightness, topology, stale inputs, and withhold reasons.
- [ ] Require reference evidence and method metadata before labeling an
  anatomical branch length.
- [ ] Require explicit reviewed registration and organism correspondence
  before reporting cross-date change.
- [ ] Test accepted, rejected, disputed, and unresolved candidates.
- [ ] Add GUI entry-path and saved Workflow Builder parity tests.
- [ ] Commit the reviewed measurement/comparison slice.

### Task 7: Biological-condition measurement contract

**Files:**
- Create: condition rubric/models/services/schemas/routes/workflow node/UI
  inspector/export/tests and any required new migration.

**Interfaces:**
- Produces: reviewed condition observations tied to a declared rubric,
  source evidence, reviewer, revision, and uncertainty.
- Does not consume geometric change as an automatic health label.

- [ ] Write failing tests for rubric versioning, independent review,
  disagreement, missing evidence, stale geometry, exchange, and replay.
- [ ] Implement contextual condition review in the 3D/scientific task.
- [ ] Add standalone and saved Workflow Builder parity.
- [ ] Validate with deterministic fixtures; keep representative held-out
  specimens blocked until supplied.
- [ ] Commit the condition slice.

### Task 8: 1.4 feature-by-feature and release acceptance

**Files:**
- Modify: inventory status/evidence, 1.4 reports, PR #79 evidence, and issue
  #76.

**Interfaces:**
- Produces: final 1.4 SHA and evidence without merging/tagging/publishing.

- [ ] Audit every 1.4 inventory entry independently.
- [ ] Run Ruff/format, mypy, full backend, frontend format/type/unit,
  Playwright entry flows, Alembic round trips, exchange/restore, and build.
- [ ] Build and verify the exact-SHA Windows installer.
- [ ] Run installed clean/upgrade/rollback workflows.
- [ ] Run physical/representative checks when inputs exist; record exact
  missing inputs otherwise.
- [ ] Push without force and update #79 and #76.
- [ ] Write the next bounded 1.5 plan only after this head is clean.
