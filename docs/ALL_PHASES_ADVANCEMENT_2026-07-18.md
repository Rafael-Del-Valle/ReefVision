# ReefVision all-phase advancement — July 18, 2026

## Scope

This branch advances every roadmap phase in order. It does not claim that every long-term phase is complete. It establishes concrete, testable capabilities across all ten phases and records the remaining scientific, model, hardware, interoperability, and packaged-desktop release gates.

## Phase 1 — Multitask foundation

### Added

- Read-only project integrity endpoint and desktop workspace.
- Managed project-root validation.
- Image, thumbnail, raster-mask, model, export, training-artifact, and video path inspection.
- Optional SHA-256 verification for immutable image, model, and video content.
- Detection of missing files, unsafe paths, path-type mismatches, incomplete masks, missing checkpoints, stale active jobs, and failed jobs without error messages.
- Per-resource record counts, referenced paths, available paths, missing paths, checksum counts, and disk usage.

### Remaining

- Safe repair actions with explicit previews.
- Orphan-file discovery and cleanup.
- Full Windows packaged-app and restart acceptance.

## Phase 2 — Editable mask annotations

### Added

- Revision-safe raster topology cleanup.
- Small disconnected-component removal.
- Largest-component retention.
- Enclosed-hole filling.
- Four- or eight-neighbor connectivity.
- New immutable raster revision for every cleanup.
- Prior mask-file preservation.
- `topology_cleaned` audit events and cleanup statistics.
- Raster-editor desktop controls.

### Remaining

- Polygon self-intersection repair.
- General raster/polygon conversion tools with editable previews and conversion controls.
- Very-large-mask performance profiling.

## Phase 3 — Segmentation

### Added

- Segmentation evaluation endpoint and desktop evaluation surface.
- Confidence and review-status filtering.
- Verified polygon and raster ground-truth loading.
- Greedy one-to-one instance matching.
- Instance precision and recall.
- False-positive and false-negative counts.
- IoU, Dice, pixel precision, and pixel recall.
- Per-class and project-level summaries.

### Remaining

- Boundary F1, Hausdorff distance, and size-stratified results.
- Real YOLO and nnU-Net model acceptance.
- Visual false-positive and false-negative overlays.

## Phase 4 — Coral measurements

### Added

- Sample standard deviation of measurement bias.
- Ninety-five-percent confidence interval for mean bias.
- Bland–Altman lower and upper limits of agreement.
- Pearson correlation.
- Deterministic agreement tests.

### Remaining

- Representative manual coral reference dataset.
- Interobserver and intraobserver validation.
- Accepted scientific error thresholds by metric.

## Phase 5 — Classification

### Added

- Classification evaluation endpoint and desktop evaluation surface.
- Confusion matrices.
- Per-class support, predicted count, true positives, false positives, and false negatives.
- Per-class precision, recall, and F1.
- Accuracy, macro precision/recall/F1, and weighted F1.
- Confidence bins and expected calibration error.
- Top-label Brier score.
- Warnings when current annotation classes were changed by accepted predictions.

### Remaining

- Immutable held-out evaluation directly from dataset snapshots.
- Temperature scaling and threshold recommendations.
- Real six-class and binary-state training/inference acceptance.

## Phase 6 — Video and fish tracking

### Added

- Advanced behavior-analysis service.
- Net displacement and path tortuosity.
- Mean and maximum acceleration.
- Mean and cumulative turning angle.
- Mean distance to frame/tank walls.
- Physical-unit conversions for displacement, acceleration, and wall distance.
- Mean pairwise fish distance.
- School polarization.
- Desktop API compatibility through defaulted response fields.

### Remaining

- Visual track overlay and frame-accurate identity correction.
- MOTA, MOTP, IDF1, HOTA, fragmentation, and identity-switch evaluation.
- Long-video chunking and performance profiling.

## Phase 7 — Active learning

### Added

- Migration-backed persisted image embeddings.
- Image, project, embedding-model, model-checksum, dimension, vector checksum, and source provenance.
- Safe upsert, listing, and deletion APIs.
- Cosine-novelty calculation.
- Priority/base-score normalization.
- Configurable novelty versus priority weighting.
- Deterministic farthest-point-style greedy selection.
- Per-group batch limits.
- Missing-embedding warnings.
- Desktop diversity-selection controls.

### Remaining

- Automatic embedding-generation jobs.
- Direct integration into review-queue generation.
- Ensemble disagreement.
- Dataset-version creation and retraining-cycle orchestration.

## Phase 8 — Advanced providers and Prompt Assist

### Added

- Explicit positive and negative point-prompt API.
- Optional point-prompt context boxes.
- Point validation against image bounds.
- Accumulated point prompts across a session.
- Mixed point-and-brush refinement.
- Positive/negative point counts in session responses.
- Full accepted prompt provenance.
- Reset behavior covering points and brushes.
- Provider-free runtime tests.

### Remaining

- Real SAM-family checkpoint acceptance.
- Direct desktop point interaction on the annotation canvas.
- Video mask propagation and depth-estimation providers.

### July 20 corrective clarification

Prompt Assist acceptance may now materialize the current reviewed raster candidate as either a
`raster_mask` (the API default) or an editable `polygon`. The polygon option is an
acceptance-time representation choice for one current Prompt Assist candidate, not a general
raster/polygon conversion tool. It accepts only one source-aligned simple contour and rejects
holes, multipart masks, non-faithful simplification, or overly complex contours with a structured
validation error. The user can retain the faithful raster output instead.

Both output kinds remain proposals until the user explicitly accepts the current candidate and
class. Only that acceptance creates the linked verified mask and bounding-box records; previews
and prompt edits never become verified annotations automatically.

## Phase 9 — Project interoperability

### Added

- Immutable COCO instance export.
- Per-split `instances_<split>.json` files.
- Frozen project categories and class metadata.
- Bounding-box annotations.
- Polygon segmentation arrays.
- Raster segmentation as uncompressed column-major COCO RLE.
- Raster checksum and dimension verification.
- Source image IDs, annotation IDs, checksums, group keys, and snapshot checksums.
- Export manifest and ZIP archive.
- Desktop COCO export control.

### Remaining

- COCO import.
- Class-mapping preview.
- CVAT, LabelMe, and Roboflow bidirectional exchange.
- Portable full-project archives.

## Phase 10 — Fusion and node editor

### Added

- Typed workflow graph schema.
- Node and port definitions.
- Image, video, detector, segmenter, classifier, tracker, measurement, behavior, active-learning, and export nodes.
- Registered-model task validation.
- Required-input validation.
- Source/target port validation.
- Compatible artifact-type validation.
- Duplicate input-connection prevention.
- Cycle detection.
- Deterministic workflow checksums.
- Topological order and parallel execution stages.
- Coral segmentation/measurement, polyp detection/classification, and fish tracking/behavior templates.
- Desktop JSON workflow planner and execution-plan preview.

### Remaining

- Workflow persistence and versioning.
- Actual node execution and artifact handoff.
- Resume, cancellation, caching, and recovery.
- Drag-and-drop visual graph editing.
- GPU resource planning and concurrent multi-GPU execution.

## Acceptance automation

Run from PowerShell at the repository root:

```powershell
.\scripts\all-phases-acceptance.ps1
```

The harness checks:

- Ruff lint and format.
- Strict mypy.
- Focused tests for all ten phases.
- Alembic `0019 → 0023 → 0019 → head` migration round trip.
- Full backend tests unless skipped.
- Frontend formatting, TypeScript, unit tests, and production build.
- Environment and commit metadata.

The script does not replace real scientific/model validation or the packaged-Windows smoke test.

## Release boundary

The branch should remain a draft integration branch until the acceptance harness runs successfully in an executable checkout and all real-model, representative-data, restart-persistence, external-format, and Windows-package gates are completed.
