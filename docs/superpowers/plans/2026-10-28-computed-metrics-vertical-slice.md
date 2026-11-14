# Computed Metrics Vertical Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the first complete ReefVision 1.1 computed-metric slice: safe unit-aware expressions, immutable persisted definitions/results, standalone API/UI/CSV use, and executable saved Workflow Builder replay.

**Architecture:** A small AST interpreter accepts only numeric constants, declared symbols, parentheses, unary signs, and `+ - * /`; it carries physical dimensions and first-order independent uncertainty derivatives without `eval`. A project-scoped service resolves immutable scientific-record inputs, enforces exact subject/time/run provenance and verified-versus-prediction separation, then stores checksummed definition and result snapshots. Workflow nodes reuse that same service, so standalone and saved executions share validation and persistence.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, SQLAlchemy/Alembic, React 19, TypeScript, TanStack Query, Vitest, pytest.

**Spec:** `docs/roadmap/REEFVISION_1_1.md` (Phase 6), `docs/roadmap/REEFVISION_1_1_MILESTONE_2.md` (Task 4), and the 2026-10-28 continuation brief.

## Global Constraints

- Work only on `develop/reefvision-1.1`; preserve the existing 1.1 scientific records, environmental providers, annotations, predictions, tracking, and workflow execution.
- Never use `eval`, execute arbitrary code, guess measurements, or combine incompatible dimensions.
- Keep verified annotation/mask evidence distinct from unverified model-prediction evidence.
- Physical image length/area inputs require a current immutable calibration snapshot.
- Retain original and normalized units, formula/engine version, immutable input snapshots, uncertainty, subject/run identity, checksums, and workflow provenance.
- Add a new migration after `0038`; do not modify the already-applied `0038_scientific_data.py`. Document the independent 1.6 `0038` lineage coordination in the roadmaps/PR.
- Remain local/offline-first; add no model downloads, hosted services, or heavyweight calculation dependency.

## Review Focus

- Reject names, calls, attributes, exponentiation, booleans, and non-finite/zero-division results instead of evaluating them.
- Reject addition/subtraction across incompatible dimensions and output units that do not match the derived dimension.
- Reject cross-project records, mismatched subject/frame/object/run/time identity, and a verified/prediction mixture atomically.
- Reject stale/missing image calibration for physical length or area while allowing pixel and non-image environmental dimensions.
- Replays from one workflow node must return the same immutable result; a conflicting retry must fail rather than overwrite provenance.

---

### Task 1: Safe unit-aware expression engine

**Files:**

- Create: `apps/api/reefvision/domain/computed_metrics.py`
- Modify: `apps/api/reefvision/domain/scientific_units.py`
- Test: `apps/api/reefvision/tests/test_computed_metrics_domain.py`

**Interfaces:**

- Produces: `compile_expression(expression: str, symbols: set[str]) -> CompiledMetricExpression` and `evaluate_expression(compiled, inputs: dict[str, MetricQuantity], output_unit: str) -> MetricEvaluation`.
- `MetricEvaluation` exposes display and normalized value/unit, dimensional signature, per-symbol derivatives, and propagated uncertainty when every input uncertainty is available.

- [ ] Write tests for arithmetic precedence, conversion (`cm` + `m`), density, count rate, percent output, and uncertainty propagation.
- [ ] Run the focused domain test and confirm imports/behaviors fail because the engine is absent.
- [ ] Implement the AST whitelist, dimension algebra, finite/zero guards, conversions, and derived units (`%`, count density, count rate).
- [ ] Add rejection tests for code execution syntax, undeclared symbols, incompatible dimensions, division by zero, non-finite values, and invalid output units; run RED then GREEN.
- [ ] Run Ruff, mypy, and the domain test.
- [ ] Commit the domain increment.

### Task 2: Immutable definitions, results, API, migration, and CSV

**Files:**

- Create: `apps/api/reefvision/db/models/computed_metric.py`
- Create: `apps/api/reefvision/schemas/computed_metrics.py`
- Create: `apps/api/reefvision/services/computed_metrics.py`
- Create: `apps/api/reefvision/api/routes/computed_metrics.py`
- Create: `apps/api/migrations/versions/0039_computed_metrics.py`
- Create: `apps/api/reefvision/tests/test_computed_metrics.py`
- Create: `apps/api/reefvision/tests/test_computed_metrics_migration.py`
- Modify: `apps/api/reefvision/db/models/__init__.py`
- Modify: `apps/api/reefvision/api/router.py`
- Modify: `apps/api/reefvision/tests/test_mask_migration_lineage.py`

**Interfaces:**

- Consumes: Task 1 expression compiler/evaluator and existing `ScientificDataService.response` integrity checks.
- Produces: immutable project-scoped `ComputedMetricDefinition`/`ComputedMetricResult`, create/list/calculate endpoints, and a provenance-complete CSV export.

- [ ] Write API and migration tests for a definition, calculation, immutable snapshots, pagination/listing, CSV, upgrade/downgrade, and legacy project preservation.
- [ ] Run focused tests and confirm missing tables/routes fail.
- [ ] Implement models, schemas, migration, service, routes, integrity hashes, exact identity/calibration/source-category validation, and transactional persistence.
- [ ] Add RED tests for cross-project IDs, subject/time mismatch, verified/prediction mixing, stale calibration, corrupt records, and invalid formulas; make them GREEN.
- [ ] Run focused API/migration/scientific-record tests, Ruff, and mypy.
- [ ] Commit the persistence/API increment.

### Task 3: Executable typed Workflow Builder integration

**Files:**

- Modify: `apps/api/reefvision/services/workflow_node_registry.py`
- Modify: `apps/api/reefvision/services/workflow_execution.py`
- Create: `apps/api/reefvision/tests/test_workflow_computed_metrics.py`
- Modify: `apps/web/src/features/workflow-graphs/workflowTemplates.ts`
- Modify: `apps/web/src/features/workflow-graphs/workflowTemplates.test.ts`

**Interfaces:**

- Consumes: Task 2 definition/result service.
- Produces: executable `scientific_records_source` (`scientific_record_collection`) and `computed_metric` (`computed_metric_result`) nodes with persisted result IDs and checksummed artifacts.

- [ ] Write a saved-workflow regression that saves, queues, executes, and reloads a graph/result; confirm registry/execution fail before implementation.
- [ ] Register typed nodes and implement source/calculation handlers using explicit record IDs and symbol bindings.
- [ ] Add RED/GREEN failure tests for missing records, bindings outside the source artifact, scientific validation failures, and idempotent same-node replay.
- [ ] Add a reusable UI workflow template and validate its graph shape in Vitest.
- [ ] Run focused workflow/backend/frontend tests plus typecheck.
- [ ] Commit the workflow increment.

### Task 4: Standalone scientist-facing UI and roadmap evidence

**Files:**

- Create: `apps/web/src/features/computed-metrics/computedMetricsApi.ts`
- Create: `apps/web/src/features/computed-metrics/ComputedMetricsPanel.tsx`
- Create: `apps/web/src/features/computed-metrics/ComputedMetricsPanel.test.tsx`
- Modify: `apps/web/src/App.tsx`
- Modify: `docs/roadmap/REEFVISION_1_1.md`
- Modify: `docs/roadmap/REEFVISION_1_1_MILESTONE_2.md`

**Interfaces:**

- Consumes: Task 2 API and Task 3 workflow node availability.
- Produces: project navigation for defining expressions/input dimensions, running explicit record bindings, inspecting immutable result provenance/uncertainty, and exporting CSV.

- [ ] Write a panel test covering definition creation, explicit binding execution, visible unit/formula/input provenance, failure feedback, and CSV export; confirm it fails before the UI exists.
- [ ] Implement the typed API client and panel; add project navigation without hiding model/verified separation or unsupported scope.
- [ ] Run panel tests RED→GREEN, then all frontend tests, Prettier, TypeScript, and production build.
- [ ] Update both 1.1 roadmaps with objective scope/evidence and explicit remaining Phase 6 limitations/0038 coordination.
- [ ] Run focused backend tests, migration round trip, Ruff, mypy, frontend suite/build, and as much of the full backend/Playwright matrix as the environment supports.
- [ ] Commit documentation/validation evidence, request whole-branch review, fix important findings via RED→GREEN, push, update draft PR #71 and issue #76, then inspect exact-head CI.
