# Phase 3: Segmentation Datasets, Training, and Inference

## Starting point

This branch is stacked on `feat/editable-mask-annotations` at commit
`aec3bf6729d547588b2fb702949552034afc07a5`.

The Phase 2 dependency surface is already present:

- revisioned polygon and raster annotations;
- immutable mask-aware dataset versions;
- frozen polygon geometry and raster checksums;
- YOLO polygon-segmentation exports;
- indexed semantic-mask PNG exports;
- dataset export jobs and desktop download controls.

Phase 2 acceptance remains a release and merge gate, but it does not block isolated
Phase 3 development on this stacked branch.

## Delivery status

Implementation status: vertical slices 3A through 3D are present on the branch. Slice 3D
now has synthetic provider, persisted-job, review, restart, rollback, and detection-regression
coverage; real-checkpoint and packaged-desktop acceptance remain. Slice 3E has a
provider-neutral contract and a separately capability-gated semantic provider workflow.

The stable detection worker, detection export, detector registration, and bounding-box
review flow remain separate. Task dispatch sends only `segment` runs through the new
segmentation worker.

## Vertical slice 3A — Task-aware dataset eligibility

Status: implemented, validation pending.

- Stable task identifiers exist for detection and instance segmentation.
- Training preflight counts frozen boxes, polygon masks, and raster masks by split.
- Detection training is blocked without bounding boxes.
- Ultralytics instance-segmentation training is blocked without train-split polygons.
- Missing validation polygons produce an explicit metrics warning.
- Raster masks produce an explicit exclusion warning rather than being silently ignored.
- Preflight responses expose polygon and raster counts for the selected dataset version.

## Vertical slice 3B — Ultralytics instance-segmentation training

Status: implemented, validation pending.

- Installed `*-seg.yaml` architectures are discovered separately from detection models.
- Installed segmentation architectures appear as ready, offline scratch-training catalog
  entries rather than fake pretrained checkpoints.
- Training drafts and provider capability responses accept task `segment`.
- Catalog and registered-checkpoint resolution enforce task compatibility.
- The task-aware worker uses `write_yolo_detection_export` for `detect` and
  `write_yolo_segmentation_export` for `segment`.
- Segmentation runs launch Ultralytics with `name="segment"`.
- All CSV metrics are preserved, and mask-specific metrics are indexed in the artifact
  manifest and job result.
- Logs, checkpoints, cancellation, experiments, package versions, and provenance are
  preserved using the existing training foundation.
- Focused tests cover task dispatch, polygon export selection, segmentation launch naming,
  and mask-metric retention.

Initial limitation: YOLO segmentation consumes polygon annotations. Raster masks are not
silently converted and remain available for the semantic-training contract.

## Vertical slice 3C — Trained segmentation-model registration

Status: implemented, validation pending.

- Model purpose `segmenter` is distinct from `detector` and `assist`.
- Uploaded or run-derived segmenters must inspect as an actual Ultralytics `segment`
  checkpoint.
- Completed segmentation checkpoints can be registered from training runs.
- Dataset, split, source architecture, checkpoint, catalog selection, parameter registry,
  metrics, package, and experiment provenance are retained.
- Detection checkpoints cannot seed segmentation training, and segmenters cannot enter
  the detector inference path.
- Registered segmenters appear in the project model registry and are selectable from the
  annotation-editor segmentation launcher.

UI note: the existing Training workspace artifact button still contains the legacy text
"Register as detector model." The backend action is task-aware and registers a segment run
as `segmenter`; the label and detector-only artifact sublist are remaining presentation
polish, not a registration blocker.

## Vertical slice 3D — Segmentation inference and review

Status: implemented with automated synthetic coverage; real-model acceptance pending.

- A dedicated Ultralytics segmentation provider validates task `segment`, requests
  `retina_masks=True`, and prefers valid source-coordinate `masks.xy` polygons.
- Invalid, self-intersecting, out-of-bounds, or overly complex polygons fall back to the
  corresponding `masks.data` instance as a source-sized binary PNG; an instance without
  either valid geometry is not degraded to a bounding-box-only proposal.
- Inference jobs dispatch by registered model task.
- Migration `0017` adds proposal geometry, polygon content, and accepted-mask linkage while
  defaulting all existing proposals to `bounding_box`; existing migration `0018` adds the
  immutable raster payload path and checksum used by fallback proposals.
- Pending polygon and raster proposals retain confidence, class mapping, bounding extent,
  model checksum, inference settings, provider identity, job ID, and training-run lineage.
- Raster proposal PNGs are normalized, atomically written beneath the owning project, stored
  as restart-safe project-relative paths, and checksum-verified when served or accepted.
- A failed segmentation job removes every partial proposal row and both uncommitted and
  previously committed proposal-mask artifacts from that job.
- The annotation editor exposes a registered-segmenter selector and a Run segmentation
  action for the open image.
- Pending polygon and raster masks render in the normal transformed review canvas and use
  the same selection, class-remap, accept, reject, and mixed bulk-review controls as boxes.
- Accept, reject, class-remap, edited-polygon accept, and mixed bulk review are supported.
- Accepted proposals become editable polygon or raster `MaskAnnotation` records, increment
  the image revision, create append-only mask audit events, and retain original geometry,
  model/job/training lineage, class mapping, confidence, and accepted geometry.
- Polygon and raster acceptance is retry-idempotent; accepted-prediction provenance survives
  subsequent polygon, brush, automask, and topology-cleanup edits.
- Detection proposals continue through the original bounding-box acceptance path.

Current inference limitations: tiled inference is not implemented, and scientific acceptance
still requires representative real Ultralytics segmentation checkpoints and coral images.

## Vertical slice 3E — Semantic segmentation provider contract

Status: contract implemented; execution intentionally unavailable.

- Indexed semantic PNG exports are the provider-neutral dataset contract.
- The contract validates immutable dataset and split hashes, image/mask directories,
  classes metadata, class indices, and foreground pixel values.
- A modular training and inference protocol is suitable for nnU-Net or another semantic
  provider pack.
- The planned nnU-Net provider returns an explicit capability blocker and cannot launch
  training or inference.
- Semantic training remains separate from Ultralytics polygon instance segmentation.

## Validation gates

Before this branch is considered integration-ready:

1. Run Alembic upgrade through head (including `0017` and `0018`) and downgrade to base on
   a test database.
2. Run Ruff, Ruff formatting, strict mypy, and the complete backend test suite.
3. Run focused Phase 3 tests for task preflight, worker dispatch, training, registration,
   inference, proposal review, migration lineage, and semantic contracts.
4. Run frontend formatting, TypeScript, Vitest, Playwright, and production build.
5. Build and launch the packaged Windows desktop application.
6. Confirm one detection training and inference regression path remains unchanged.
7. Train a one-epoch segmentation smoke model from verified polygon annotations.
8. Register the result, run it on an image, and accept and reject polygon and raster-fallback
   proposals.
9. Close and reopen the project and verify accepted masks, audit events, measurements, and
   proposal review states persist.
10. Keep this branch stacked until Phase 2 packaged-desktop acceptance passes, then rebase it
    onto the accepted Phase 2 baseline before opening or retargeting its pull request.
