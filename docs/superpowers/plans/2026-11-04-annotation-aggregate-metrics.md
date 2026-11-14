# Annotation Aggregate Metrics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let researchers save, preview, calculate, inspect, export, workflow-rerun, and project-exchange reviewed annotation or verified-mask counts with explicit independent-unit grouping.

**Architecture:** Add discriminators/configuration columns to the existing computed definition/result tables through migration `0041`. A focused aggregate service resolves explicit reviewed images, snapshots canonical annotations or verified masks, groups by image or explicit `group_key`, and persists immutable aggregate payloads; standalone API, Workflow Builder, CSV, UI, and project exchange all reuse that service and payload contract. Existing scalar rows, hashes, APIs, formula evaluation, and workflow behavior remain unchanged.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, SQLAlchemy/Alembic, pytest, React/TypeScript, TanStack Query, Vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-11-04-annotation-aggregate-metrics-design.md`

## Global Constraints

- Work from audited `develop/reefvision-1.1` head `fcd217d2d5e205f0b246bbe89c47c6ce11941a5a` in the existing isolated worktree.
- Do not modify the dirty shared checkout, force-push, merge, tag, release, or publish installers.
- Add migration `0041` after `0040`; never edit `0038`, `0039`, or `0040` or resolve the independent 1.6 revision conflict here.
- Count only non-deleted canonical annotations or non-deleted masks with `status == "verified"` from images with `annotation_status == "reviewed"`.
- Pending/rejected predictions are exclusions, never verified observations.
- Annotation/mask count is never the independent-unit sample size.
- Missing group keys, duplicate image IDs, cross-project IDs, missing sources, stale/tampered snapshots, and unsupported kinds fail closed.
- Do not implement or imply mask coverage, physical area, density, ROI denominators, inferential statistics, or subject hierarchies in this slice.
- Preserve scalar metric behavior and exchange `1.0`/`1.1` compatibility.

## Review Focus

- Accepted-prediction annotations are canonical observations but pending/rejected proposals never enter the count; tests must distinguish both paths.
- Two images with one `group_key` produce two image samples but exactly one independent unit, regardless of annotation count.
- A reviewed image with zero eligible observations previews an explicit observed zero but cannot create a persisted result because missing work and true zero are not distinguishable yet.
- Aggregate definition configuration and result snapshots remap only declared IDs; a UUID-looking literal `group_key` must remain unchanged.
- Editing/deleting/reclassifying a source or changing image review/group state marks an immutable result stale and makes a workflow rerun produce a new snapshot, never rewrite the old result.

---

### Task 1: Discriminated persistence and standalone aggregate calculation

**Files:**

- Create: `apps/api/migrations/versions/0041_computed_annotation_aggregates.py`
- Modify: `apps/api/reefvision/db/models/computed_metric.py`
- Create: `apps/api/reefvision/schemas/computed_aggregate_metrics.py`
- Create: `apps/api/reefvision/services/computed_aggregate_metrics.py`
- Create: `apps/api/reefvision/api/routes/computed_aggregate_metrics.py`
- Modify: `apps/api/reefvision/api/router.py`
- Modify: `apps/api/reefvision/services/computed_metrics.py`
- Create: `apps/api/reefvision/tests/test_computed_aggregate_metrics.py`
- Create: `apps/api/reefvision/tests/test_computed_aggregate_migration.py`

**Interfaces:**

- Produces: `ComputedAggregateMetricService.create_definition(...)`, `preview(...)`, `calculate(...)`, `definition_response(...)`, and `result_response(...)`.
- Produces: aggregate definition/result schemas and API routes consumed by Tasks 2–5.
- Preserves: scalar `ComputedMetricService` endpoints by filtering `definition_kind == "scalar"` and `result_kind == "scalar"`.

- [ ] **Step 1: Write migration and API tests first**

  Add tests named for: `0040 -> 0041 -> 0040 -> 0041` scalar-row preservation; empty preview; duplicate/cross-project image rejection; reviewed versus annotated image eligibility; canonical-box versus verified-mask source separation; mixed class filters and per-class counts; pending proposal exclusion; image grouping; group-key grouping with two images/one independent unit; missing group-key rejection; and zero-observation calculation refusal. Hand-calculate literal group totals and means.

- [ ] **Step 2: Run the new tests and verify RED**

  Run: `python -m pytest apps/api/reefvision/tests/test_computed_aggregate_migration.py apps/api/reefvision/tests/test_computed_aggregate_metrics.py -q`

  Expected: collection/import failures because migration, schemas, routes, and service do not exist.

- [ ] **Step 3: Add migration `0041` and model discriminators**

  Add non-null `definition_kind`/`result_kind` with server default `scalar`, nullable definition `configuration_json`, and matching SQLAlchemy defaults. Downgrade removes only the new columns; existing scalar payloads/hashes are unchanged.

- [ ] **Step 4: Implement typed definition, preview, result, and validation schemas**

  Define explicit literals for source kind, grouping level, engine/schema versions, required review state, operation, and independence contract. Bound requests to 1–500 unique image UUIDs and class filters to project UUIDs.

- [ ] **Step 5: Implement the minimal aggregate service and routes**

  Resolve labels/images/project ownership; gather non-deleted annotations or verified masks in deterministic ID order; snapshot images, labels, observations, proposal exclusions, and metadata checksums; group and compute literal totals/means; hash definition/result payloads; persist only nonzero results; paginate aggregate definitions/results separately. Use `expression="count(<source_kind>)"`, `output_unit="count"`, and `formula_version="reefvision.annotation-aggregate.v1"` without scalar compilation.

- [ ] **Step 6: Keep scalar list/response behavior isolated**

  Update scalar queries and row validators to reject non-scalar rows rather than trying to parse aggregate JSON. Run existing scalar tests.

- [ ] **Step 7: Run Task 1 GREEN suite**

  Run: `python -m pytest apps/api/reefvision/tests/test_computed_aggregate_migration.py apps/api/reefvision/tests/test_computed_aggregate_metrics.py apps/api/reefvision/tests/test_computed_metrics.py apps/api/reefvision/tests/test_computed_metrics_review.py -q`

  Expected: all pass.

- [ ] **Step 8: Commit Task 1**

  Commit: `feat(1.1): persist replicate-aware annotation counts`

### Task 2: Staleness validation and aggregate CSV

**Files:**

- Modify: `apps/api/reefvision/services/computed_aggregate_metrics.py`
- Modify: `apps/api/reefvision/api/routes/computed_aggregate_metrics.py`
- Modify: `apps/api/reefvision/tests/test_computed_aggregate_metrics.py`

**Interfaces:**

- Consumes: Task 1 aggregate payload and service.
- Produces: `validate_result(project_id, result_id)` and `export_csv(project_id)` used by UI and documentation.

- [ ] **Step 1: Write failing source-mutation and CSV tests**

  Cover unchanged current result; deleted annotation; reclassified annotation; mask status/revision change; image review-status/group-key change; missing image; tampered result checksum; CSV values for overall/group/per-class counts, image count, independent-unit count, grouping contract, source IDs, workflow IDs, and checksums.

- [ ] **Step 2: Run tests and verify RED**

  Run: `python -m pytest apps/api/reefvision/tests/test_computed_aggregate_metrics.py -q -k "stale or csv or tamper"`

  Expected: validation/export routes or methods are missing.

- [ ] **Step 3: Implement current-source reconstruction and CSV**

  Rebuild the source snapshot through the same deterministic resolver without persisting; return `current`, saved/current source hashes, and explicit changed/missing reasons. CSV emits one overall row plus deterministic group rows without flattening away sample-size/grouping provenance.

- [ ] **Step 4: Run Task 2 GREEN suite**

  Run: `python -m pytest apps/api/reefvision/tests/test_computed_aggregate_metrics.py apps/api/reefvision/tests/test_computed_metrics.py -q`

  Expected: all pass.

- [ ] **Step 5: Commit Task 2**

  Commit: `feat(1.1): validate and export aggregate evidence`

### Task 3: Executable Workflow Builder integration

**Files:**

- Modify: `apps/api/reefvision/services/workflow_node_registry.py`
- Modify: `apps/api/reefvision/services/workflow_graphs.py`
- Modify: `apps/api/reefvision/services/workflow_execution.py`
- Create: `apps/api/reefvision/tests/test_workflow_computed_aggregates.py`
- Modify: `apps/web/src/features/workflow-graphs/workflowTemplates.ts`
- Modify: `apps/web/src/features/workflow-graphs/workflowTemplates.test.ts`

**Interfaces:**

- Consumes: Task 1 `ComputedAggregateMetricService.calculate(...)`.
- Produces: executable `annotation_aggregate` node with project input and `computed_metric_result` output.

- [ ] **Step 1: Write failing standalone/workflow equivalence tests**

  Build reviewed images with known counts and one shared group key. Assert standalone and workflow results have equal totals/groups/means, workflow IDs are persisted, artifact checksums match, rerun with a new run is deterministic, same-node replay is idempotent, conflicting input inventory is rejected, and failure leaves no result/artifact or successful node state.

- [ ] **Step 2: Run workflow tests and verify RED**

  Run: `python -m pytest apps/api/reefvision/tests/test_workflow_computed_aggregates.py -q`

  Expected: graph validation rejects unknown `annotation_aggregate` node.

- [ ] **Step 3: Register and execute the node**

  Add required `definition_id` and `image_ids`, validate the connected project artifact, call the aggregate service with run/node IDs, and emit aggregate counts/mean/unit/checksum. Add a reusable project-source-to-aggregate frontend template.

- [ ] **Step 4: Run Task 3 GREEN suite**

  Run: `python -m pytest apps/api/reefvision/tests/test_workflow_computed_aggregates.py apps/api/reefvision/tests/test_workflow_computed_metrics.py -q`

  Expected: all pass.

- [ ] **Step 5: Run workflow template tests**

  Run from `apps/web`: `npm test -- --run src/features/workflow-graphs/workflowTemplates.test.ts`

  Expected: all pass.

- [ ] **Step 6: Commit Task 3**

  Commit: `feat(1.1): execute aggregate metrics in workflows`

### Task 4: Project-exchange remapping and tamper rejection

**Files:**

- Modify: `apps/api/reefvision/services/project_exchange_computed.py`
- Modify: `apps/api/reefvision/services/project_exchange_import.py`
- Create: `apps/api/reefvision/tests/test_computed_aggregate_project_exchange.py`

**Interfaces:**

- Consumes: Task 1 aggregate definition/result payload and existing exchange ID map.
- Produces: aggregate-aware pre-import validation and explicit ID remapping inside existing computed sections.

- [ ] **Step 1: Write failing exchange round-trip and corruption tests**

  Export/import a workflow-produced group-key result. Assert disjoint project/definition/result/image/annotation/workflow IDs, literal UUID-looking group key unchanged, same totals/means, current validation after import, and deterministic workflow rerun. Table-drive corrupt definition hash/config IDs, result hash, missing image/observation, wrong class, duplicated observation, mismatched group totals/independent-unit count, workflow run/node mismatch, and foreign project; assert atomic database/directory rollback.

- [ ] **Step 2: Run exchange tests and verify RED**

  Run: `python -m pytest apps/api/reefvision/tests/test_computed_aggregate_project_exchange.py -q`

  Expected: current computed exchange validator treats aggregate rows as unsupported scalar rows or fails to remap aggregate relationships.

- [ ] **Step 3: Add aggregate-aware validation and remapping**

  Branch by discriminator. Explicitly remap definition class filters and result project/definition/image/annotation/mask/label/workflow IDs; preserve group keys and metadata literals; rebuild imported snapshots from remapped source rows; recompute aggregate definition/result hashes; run production aggregate response/current validators before commit.

- [ ] **Step 4: Run Task 4 GREEN suite**

  Run: `python -m pytest apps/api/reefvision/tests/test_computed_aggregate_project_exchange.py apps/api/reefvision/tests/test_computed_metric_project_exchange.py apps/api/reefvision/tests/test_scientific_project_exchange.py -q`

  Expected: all pass.

- [ ] **Step 5: Commit Task 4**

  Commit: `feat(1.1): preserve aggregate metric provenance in exchange`

### Task 5: Computed Metrics workspace and documentation

**Files:**

- Create: `apps/web/src/features/computed-metrics/AnnotationAggregatePanel.tsx`
- Modify: `apps/web/src/features/computed-metrics/computedMetricsApi.ts`
- Modify: `apps/web/src/features/computed-metrics/ComputedMetricsPanel.tsx`
- Create: `apps/web/src/features/computed-metrics/AnnotationAggregatePanel.test.tsx`
- Modify: `docs/SCIENTIFIC_ENVIRONMENTAL_CONTEXT.md`
- Modify: `docs/roadmap/REEFVISION_1_1.md`

**Interfaces:**

- Consumes: Tasks 1–2 aggregate API/CSV/currentness contracts.
- Produces: functional researcher workflow and accurate scope/limitations documentation.

- [ ] **Step 1: Write failing UI behavior tests**

  Assert a researcher can save a definition, enter explicit image IDs, preview eligible/excluded counts, see observations/images/independent units and per-class/group counts, calculate, reopen provenance/currentness, see validation failures, and use the aggregate CSV link. Assert the UI says `group_key` is researcher-declared and never labels annotation count as `n`.

- [ ] **Step 2: Run UI test and verify RED**

  Run from `apps/web`: `npm test -- --run src/features/computed-metrics/AnnotationAggregatePanel.test.tsx`

  Expected: component/module is missing.

- [ ] **Step 3: Implement typed API client and functional panel**

  Use existing cards/forms/query conventions. Keep scalar UI unchanged. Show source/review policy, filters, grouping contract, preview exclusions, result group table, current/stale state, workflow lineage, hashes, and CSV.

- [ ] **Step 4: Run UI GREEN suite**

  Run from `apps/web`: `npm test -- --run src/features/computed-metrics/AnnotationAggregatePanel.test.tsx src/features/computed-metrics/ComputedMetricsPanel.test.tsx src/features/workflow-graphs/workflowTemplates.test.ts`

  Expected: all pass.

- [ ] **Step 5: Update existing scientific documentation and roadmap**

  Document supported counts, review/source rules, observation/image/independent-unit distinctions, group-key assumptions, API/workflow/CSV/exchange behavior, migration `0041`, and explicit non-support for mask union/physical coverage, hierarchy, treatment inference, and inferential statistics. Keep RELEASE HOLD.

- [ ] **Step 6: Run final relevant gates**

  Backend focused aggregate/scalar/workflow/exchange/migration tests; full backend; API Ruff format/lint; strict mypy; frontend Prettier, TypeScript, full Vitest, production build, and relevant Playwright; migration upgrade/downgrade.

- [ ] **Step 7: Commit Task 5**

  Commit: `feat(1.1): expose annotation aggregate workspace`

- [ ] **Step 8: Review, reconcile, and deliver**

  Generate a whole-branch review package from `fcd217d2` to final HEAD. Review mathematical counts, eligibility leakage, independent-unit semantics, stale inputs, remapping, atomicity, and scalar compatibility; reproduce every significant finding RED before fixing. Fetch/reconcile concurrent branch work, fast-forward push, update PR #71 and issue #76, and inspect exact-SHA CI without merging or claiming release readiness.
