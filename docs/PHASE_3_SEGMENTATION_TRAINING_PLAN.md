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

## Existing training foundation

ReefVision already has:

- training providers and architecture discovery;
- training drafts and summaries;
- immutable dataset selection;
- task, checkpoint, device, precision, and parameter fields;
- preflight, leakage audit, and resource snapshots;
- queued and cancelable background training jobs;
- Ultralytics detection execution with epoch callbacks;
- metrics histories, logs, artifacts, checkpoints, and experiment records;
- registration of completed detection checkpoints;
- detection inference and prediction review.

The current implementation is deliberately hard-coded to `detect`. Phase 3 extends
that foundation rather than replacing it.

## Vertical slice 3A — Task-aware dataset eligibility

Status: started.

- Define stable training task identifiers for detection and instance segmentation.
- Count frozen boxes, polygon masks, and raster masks by split.
- Block detection training without boxes.
- Block Ultralytics instance-segmentation training without train-split polygons.
- Warn when validation has no polygons.
- Warn when raster masks would be excluded from a YOLO polygon training run.
- Surface these counts and messages in training preflight.

## Vertical slice 3B — Ultralytics instance-segmentation training

- Discover installed `*-seg.yaml` Ultralytics architectures separately from detection.
- Accept task `segment` in training drafts and provider capability responses.
- Resolve only task-compatible catalog models and registered checkpoints.
- Prepare the immutable dataset with `write_yolo_segmentation_export`.
- Launch Ultralytics with a segmentation architecture or checkpoint.
- Preserve task-specific metrics, logs, checkpoints, and experiment provenance.
- Add focused worker tests proving the segmentation export is used and the detection
  training path is unchanged.

Initial limitation: YOLO segmentation consumes polygon annotations. Raster masks are
not silently converted. They remain available for the semantic-training slice.

## Vertical slice 3C — Trained segmentation-model registration

- Add a segmentation model purpose and provider metadata contract.
- Register completed segmentation checkpoints from training runs.
- Preserve dataset, split, model-source, package, parameter, and metrics provenance.
- Prevent detection checkpoints from being selected for segmentation and vice versa.

## Vertical slice 3D — Segmentation inference and review

- Add an Ultralytics segmentation inference provider.
- Store predicted masks separately from verified annotations.
- Render proposal masks only in the appropriate annotation type.
- Allow accept, reject, edit-and-accept, and bulk review with explicit confirmation.
- Preserve original confidence, polygon/mask geometry, source model, and run provenance.

## Vertical slice 3E — Semantic segmentation provider contract

- Use indexed semantic PNG exports as the provider-neutral dataset contract.
- Add a modular trainer interface suitable for nnU-Net or another semantic provider.
- Keep semantic training separate from Ultralytics instance segmentation.
- Do not add full nnU-Net orchestration until the task contract and preflight are stable.

## Merge and validation strategy

1. Keep PR #3 focused on Phase 2 and complete its packaged-desktop acceptance report.
2. Keep this branch stacked until Phase 2 is accepted.
3. Validate each Phase 3 vertical slice independently with backend and frontend tests.
4. Rebase the Phase 3 branch onto the accepted Phase 2 baseline before opening or
   retargeting its pull request.
5. Do not allow Phase 3 code to weaken existing detection training, detection exports,
   or bounding-box inference and review.
