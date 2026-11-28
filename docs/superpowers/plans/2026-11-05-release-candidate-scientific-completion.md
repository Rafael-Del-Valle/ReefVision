# ReefVision 1.1 Scientific Completion Implementation Plan

> Execute test-first. Every production edit follows a focused failing test. Preserve the existing `0042` migration head unless a relational schema change becomes unavoidable.

**Goal:** Complete the largest coherent, scientifically valid geographic, annotation-comparison, and current-visualization slice while preserving reproducibility and exchange safety.

**Architecture:** Add pure deterministic domain kernels first, then typed services/routes, existing workflow execution, exchange validation/remapping, and React panels. Reuse immutable computed/environmental result rows and content hashing.

## Task A1: robust geographic inverse

Files: `apps/api/reefvision/services/geographic_movement_analytics.py`, its focused tests.

1. Add failing antipodal, near-antipodal, latitude, stationary, and dateline reference tests.
2. Replace duplicate Vincenty math with the shared GeographicLib WGS84 helper.
3. Run the focused geographic analytics suite and static checks.

## Task A2: pairwise uncertainty-aware geographic result

Files: geographic schemas/service/route, workflow execution/registry, exchange validation, frontend API/panel/tests.

1. Add failing schema and service tests for two fresh same-project endpoints, stale/cross-project rejection, deterministic hash, and unknown versus compatible one-sigma uncertainty.
2. Implement typed request/result and immutable source snapshots; export CSV/GeoJSON.
3. Add a saved-workflow node calling the same service and exchange remapping tests.
4. Add researcher selection/results UI and frontend tests.

## Task B1: deterministic annotation comparison kernel

Files: new comparison schema/domain/service/route and tests.

1. Add failing tests for class-aware stable one-to-one IoU, duplicates/ties, class mismatch, zero denominators, explicit reference semantics, and mask union overlap.
2. Implement the pure kernel and typed result with sampling-unit and limitations metadata.
3. Persist through immutable computed definitions/results with exact evidence snapshots and hashes.

## Task B2: comparison heatmap integration

Files: heatmap API/UI, workflow, exchange, CSV/JSON export and tests.

1. Add failing route/currentness/export/workflow/exchange tests.
2. Add saved comparison preview/calculate/currentness and disagreement heatmap payload.
3. Add React source/reference controls, overlay/summary, unavailable reviewer message, and tests.

## Task C1: current-field numerical kernel

Files: new current-field domain module and tests.

1. Add failing tests for uniform, shear/rotational fields, RK4 convergence, holes, bounds, stagnation, invalid axes, and dateline/polar safety.
2. Implement strict rectilinear bilinear sampling and bounded versioned RK4 integration.
3. Run focused numerical and static checks.

## Task C2: trajectory overlay and integration

Files: environmental-analysis schemas/service/routes, workflow/exchange, current UI and tests.

1. Add failing tests for exact UTC/depth matching, unknown evidence exclusion, time gaps/duplicates, stale points, and deterministic source hashes.
2. Add typed current-streamline and trajectory-context analysis kinds using existing environmental-analysis rows.
3. Add workflow execution, exchange remapping, CSV export, UI overlays/legends, and frontend tests.

## Task D: validation and delivery

1. Update the roadmap with implemented/deferred evidence and scientific limitations.
2. Run focused backend tests, Ruff, mypy, frontend tests, TypeScript, Prettier, and production build.
3. Commit each coherent passing checkpoint. Before push, fetch and prove the remote branch is an ancestor; push normally.
4. Update draft PR #71 and issue #76 with commit SHAs, commands, results, limitations, and exact-SHA CI links.
5. Inspect exact-SHA CI and report one of the required verdicts without merging, tagging, or releasing.
