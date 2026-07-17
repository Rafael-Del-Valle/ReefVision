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

Implementation status: vertical slices 3A through 3D are present on the branch and
await executable validation. Slice 3E has a provider-neutral contract and an explicitly
blocked nnU-Net placeholder; semantic training execution is not presented as available.

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

Status: implemented, validation pending.

- A dedicated Ultralytics segmentation provider validates task `segment` and converts
  `masks.xy` output into source-coordinate polygon predictions.
- Inference jobs dispatch by registered model task.
- Migration `0017` adds proposal geometry, polygon content, and accepted-mask linkage while
  defaulting all existing proposals to `bounding_box`.
- Pending polygon-mask proposals retain confidence, class mapping, model checksum,
  inference settings, provider identity, and task provenance.
- The annotation editor exposes a registered-segmenter selector and a Run segmentation
  action for the open image.
- Pending mask proposals render as source-coordinate polygon overlays.
- Accept, reject, class-remap, edited-polygon accept, and mixed bulk review are supported.
- Accepted proposals become verified polygon `MaskAnnotation` records, increment the image
  revision, create append-only mask audit events, and retain original and accepted geometry.
- Detection proposals continue through the original bounding-box acceptance path.

UI note: until the legacy box proposal layer is made geometry-aware, a mask proposal may
also show its bounding extent alongside the polygon overlay. The polygon is the persisted
and accepted geometry.

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

1. Run Alembic upgrade through `0017` and downgrade to base on a test database.
2. Run Ruff, Ruff formatting, strict mypy, and the complete backend test suite.
3. Run focused Phase 3 tests for task preflight, worker dispatch, training, registration,
   inference, proposal review, migration lineage, and semantic contracts.
4. Run frontend formatting, TypeScript, Vitest, Playwright, and production build.
5. Build and launch the packaged Windows desktop application.
6. Confirm one detection training and inference regression path remains unchanged.
7. Train a one-epoch segmentation smoke model from verified polygon annotations.
8. Register the result, run it on an image, and accept and reject polygon proposals.
9. Close and reopen the project and verify accepted masks, audit events, measurements, and
   proposal review states persist.
10. Keep this branch stacked until Phase 2 packaged-desktop acceptance passes, then rebase it
    onto the accepted Phase 2 baseline before opening or retargeting its pull request.
