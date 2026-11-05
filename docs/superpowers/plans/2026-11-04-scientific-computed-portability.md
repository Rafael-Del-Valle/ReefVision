# Scientific Computed Portability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Round-trip computed metric definitions/results and environmental-event definitions through ReefVision 1.1 project exchange with safe ID remapping, reproducible hashes, and atomic failure.

**Architecture:** Extend the existing enriched exchange inventory and importer dependency order. Use a dedicated evidence-aware remapper/validator for computed results, then run production validators before the existing transaction commits.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, SQLAlchemy, pytest, Ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-11-04-scientific-computed-portability-design.md`

## Global Constraints

- Work only from `develop/reefvision-1.1`; push only after reconciling the exact remote head.
- Preserve exchange `1.0` compatibility and fail closed on unsupported versions.
- Preserve literal source/provider provenance; remap only declared project-scoped relationships.
- Add no migration and do not rewrite published migrations `0038`, `0039`, or `0040`.
- Keep imports atomic and cross-project isolated.

## Review Focus

- A UUID-looking literal in source provenance must not be remapped just because it equals a project record ID.
- A computed result whose input snapshot or checksum differs from its source scientific record must be rejected.
- Workflow-linked results must point to imported runs/nodes in the same imported project.
- Definitions without results and event definitions without scientific records must still select format `1.1` and survive exchange.
- A failed late validation must remove every imported row and only the newly-created import directory.

---

### Task 1: Failing portability and integrity regressions

**Files:**
- Create: `apps/api/reefvision/tests/test_computed_metric_project_exchange.py`
- Modify: `apps/api/reefvision/tests/test_computed_metrics_review.py`

**Interfaces:**
- Consumes: existing exchange HTTP/job helpers and computed/environmental APIs.
- Produces: round-trip, reproducibility, tamper, legacy, and rollback acceptance tests.

- [ ] Write a save -> export -> import -> inspect test with computed definition/result, event definition, and workflow provenance.
- [ ] Assert imported IDs are disjoint, source provenance literals are unchanged, and recalculation/evaluation matches the stored result.
- [ ] Add table-driven archive corruptions for definition hash, result hash, missing input, mismatched snapshot, foreign project, and unsupported formula version.
- [ ] Run the focused tests and confirm failure is caused by the current export block/missing sections.

### Task 2: Explicit computed exchange remapping and validation

**Files:**
- Create: `apps/api/reefvision/services/project_exchange_computed.py`
- Modify: `apps/api/reefvision/services/project_exchange.py`
- Modify: `apps/api/reefvision/services/project_exchange_v1.py`
- Modify: `apps/api/reefvision/services/project_exchange_import.py`
- Modify: `apps/api/reefvision/services/project_exchange_import_v1.py`

**Interfaces:**
- Produces: `COMPUTED_SECTIONS`, `validate_computed_exchange_records(...)`, and `remap_computed_sections(...)`.
- Consumes: the established scientific remapper output and shared archive ID map.

- [ ] Add the three record sections and enriched-format detection; remove the computed export refusal.
- [ ] Register model dependencies in definition -> scientific input -> result order.
- [ ] Validate definition schemas/hashes/formula version and result scalar/payload/link/snapshot/reproducibility contracts.
- [ ] Rebuild remapped input snapshots, declared subject/input/workflow links, provenance input hashes, and result content hashes.
- [ ] Validate imported definitions/results/events through production services before commit.
- [ ] Run focused tests until green, then existing scientific/legacy exchange suites.

### Task 3: Documentation, migration coordination, and verification

**Files:**
- Modify: `docs/SCIENTIFIC_ENVIRONMENTAL_CONTEXT.md`
- Modify: `docs/roadmap/REEFVISION_1_1.md`

**Interfaces:**
- Produces: exact portability scope, evidence, limitations, and cross-version migration reconciliation notes.

- [ ] Document exchange coverage and immutable source-archive/hash behavior.
- [ ] Record that 1.1 `0038` and independent 1.6 `0038` must be reconciled with a new integration migration rather than rewritten.
- [ ] Run Ruff format/lint, strict mypy, focused exchange/computed/event tests, full backend tests, and relevant migration tests.
- [ ] Review the diff for cross-project leakage, silent loss, and accidental provenance rewriting.
- [ ] Commit cohesively, fetch/reconcile remote changes, push `HEAD` to `develop/reefvision-1.1`, update PR #71 and issue #76, and inspect exact-SHA CI.
