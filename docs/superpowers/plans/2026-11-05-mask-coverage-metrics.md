# Mask area and coverage implementation plan

## Goal

Deliver a coherent, immutable verified-mask area/coverage slice through API, UI, workflows, exchange, evidence export, and currentness validation without overstating physical calibration.

## Tasks

1. Add exact run-set union/intersection helpers and synthetic known-value tests for empty, overlapping, polygon, raster, and ROI geometry.
2. Add typed mask-coverage definition/selection/result/validation schemas and service tests that first fail for the absent API.
3. Implement definition creation, preview, persistence, per-image/class/group summaries, scalar calibrated physical area/density, hashes, currentness, and CSV.
4. Add standalone project routes and register them in the API router.
5. Add executable Workflow Builder node support with deterministic replay and a frontend template.
6. Extend project exchange validation/remapping/re-hashing for `mask_coverage`, including literal group keys and atomic corruption rejection.
7. Add a researcher-facing mask-coverage panel under Computed Metrics with explicit class/ROI/group/image selection and provenance/availability displays.
8. Run focused backend/frontend tests, Ruff, strict mypy, TypeScript, Prettier, production build, Playwright where relevant, and exact-slice regression review.
9. Commit and push the validated Checkpoint B slice, update PR #71 and issue #76, and inspect exact-SHA CI.

## Acceptance

- Known overlapping masks demonstrate summed area differs from union area.
- Coverage denominators and coordinate-frame/algorithm provenance are explicit.
- Missing/corrupt geometry and missing ROI denominators fail closed.
- Zero-target reviewed images persist as true zero coverage.
- Compatible scalar calibrations are correct; mixed supported length units normalize to metres, while missing, unknown-unit, invalid, or projective calibration leaves physical values unavailable.
- Changed mask, image, label, grouping, raster content, or calibration makes saved evidence stale.
- API, UI, workflow, exchange, CSV, and immutable-result paths use the same service contract.
