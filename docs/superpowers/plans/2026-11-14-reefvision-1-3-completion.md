# ReefVision 1.3 completion implementation plan

**Goal** — Complete the 1.3 static-image comparison, guided scientific configuration, and native temporal refinement workflows on draft PR #87.

**Architecture** — Keep immutable source evidence and existing frame methods. Static studies reuse frozen image versions and installed detector adapters. A residual temporal model uses reviewed sequence targets and frozen frame-model observations. Standalone and workflow entry points use typed requests and the same services.

## Static-image comparisons

- Write regression fixtures for frozen reviewed boxes, stable class IDs, related samples, ambiguous model lineage, and incomplete inference.
- Extend `schemas/static_comparison.py`, `services/static_comparison.py`, job dispatch, project exchange, and the scientific comparison route. Store raw predictions as evidence distinct from annotations and compute paired statistics on shared valid samples.
- Extend the scientific comparison workspace and publication service with dataset and model selection, review of the per-image results, and export.

## Guided workflows

- Test typed configuration and replay in `ScientificNodeControls.test.tsx`. Cover project scope, required evidence, review changes, and default values.
- Add `ScientificNodeControls.tsx` in the visual editor. Use existing source lists, acquisition controls, and the same request fields as standalone services. Keep advanced JSON available and maintain existing graph compatibility.
- Exercise an entire project-to-analysis graph in live Chromium and reopen its saved revision. Validate node summaries and source navigation.

## Temporal ReefPose

- Write tests for grouping before window construction, time gaps, identity and schema boundaries, missing targets, causal isolation, normalization, and chunked output parity. Implement the Conv1d adapter and evaluation in new `ml/reefpose/temporal*` modules.
- Extend the frozen pose and identity services, background worker, Model Hub, and exchange paths with temporal dataset, checkpoint, and result provenance. Apply a new Alembic revision only if relational metadata has to change.
- Add guided temporal controls to training, video and Workflow Builder. Verify training, checkpoint reload, cancel and resume, refinement and explicit review, paired scientific evaluation, and downstream revision handling.

## Delivery

Run Python Ruff, typing and full pytest with pose interoperability, npm format/type/unit/build and Chromium workflows, Alembic round-trips, and RTX 3090 tests. Commit independent changes, push to PR #87, check exact-head CI and Windows payload and disposable installer results. Keep original research media, the 1.2 branch, installed application and publication status intact.
