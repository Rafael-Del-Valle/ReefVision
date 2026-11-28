# ReefPose Phase 1 Design

## Intent

ReefPose-S is ReefVision's first native PyTorch pose model. It provides a complete
single-animal engineering path from a frozen, scientist-verified pose dataset to a
locally trained checkpoint and source-coordinate predictions, without wrapping SLEAP
or Ultralytics and without claiming biological accuracy from synthetic tests.

## Goals

- Train a native convolutional, multi-scale heatmap model with a per-landmark
  visibility head on CPU or CUDA.
- Preserve arbitrary anatomical landmarks, repeated structures, skeleton edges,
  visibility semantics, schema revisions, and integrity hashes.
- Convert compatible ReefVision frozen pose-training exports instead of creating a
  second annotation or dataset store.
- Prevent group leakage in internally generated train/validation partitions and
  accept a separately frozen validation export when only one group is available.
- Save and restore model, optimizer, AMP scaler, schema, configuration, epoch,
  metrics, and reproducibility metadata.
- Register ReefPose checkpoints through ReefVision's provider-neutral Model Hub and
  execute them through the existing inference job with full keypoints retained in
  proposal provenance.
- Provide deterministic CPU engineering tests and an explicit synthetic RTX 3090
  benchmark for latency, throughput, memory, training-step speed, and parameter
  count.

## Non-goals

- Multi-animal detection, tracking, temporal refinement, transformer backbones, or
  graph refinement in Phase 1.
- Automatic pretrained-weight downloads.
- A new annotation database, dataset version type, or GUI editor.
- Biological accuracy claims without real held-out labeled animal data.
- Replacing or altering existing SLEAP and Ultralytics providers.

## Constraints

- Work only on `feature/reefpose-core`; do not push, merge, tag, or publish.
- Source images remain immutable and canonical output coordinates remain source-image
  pixels.
- Frozen ReefVision schema and dataset hashes are authoritative.
- PyTorch provider code remains under `reefvision.ml`.
- The supplied Python environment contains PyTorch, torchvision, NumPy, and Pillow,
  but not the repository's pytest/ruff/mypy stack. Phase 1 tests therefore use
  standard-library `unittest` while the normal repository checks remain required
  when their dependencies are available.

## Approaches considered

### 1. Native package plus a thin ReefVision provider adapter — selected

Keep the neural architecture, geometry, data conversion, training, checkpointing,
and benchmarking in a focused `reefvision.ml.reefpose` package. Add a small adapter
to the existing provider hub. This gives ReefPose clean extension seams for future
encoders, graph refiners, and temporal models while preserving ReefVision's data and
job contracts.

### 2. Load ReefPose through the generic custom-PyTorch plugin

This would require enabling arbitrary Python imports with an environment variable,
would not define a stable checkpoint/schema contract, and would not provide a safe
default registration path. It is unsuitable for a built-in framework.

### 3. Embed ReefPose directly in the Ultralytics workflow training service

This could reuse job plumbing immediately, but it would couple native model code to
Ultralytics-specific validation, architecture names, and export assumptions. It also
increases regression risk in the current production workflow. A provider-neutral
workflow dispatcher is better follow-up work after the native vertical slice is
validated.

## Architecture

`ReefPoseS` uses a four-stage convolutional encoder and a lightweight top-down
feature pyramid. The fused stride-4 feature map feeds one logit heatmap per landmark;
the deepest encoder feature feeds a global visibility classifier. The public model
returns a typed output so future backbones can implement the same contract.

Images use a recorded aspect-preserving letterbox transform. Keypoint targets are
fractional Gaussian heatmaps at stride 4. Decoding combines heatmap confidence with
visibility probability and applies the exact inverse letterbox/crop transform to
return source-image coordinates. A source bounding box can be supplied for the
single-animal crop use case.

The anatomy schema is an immutable value object. Each landmark has a stable ID,
name, optional description and group, occurrence index, and allowed/default
visibility. Skeleton edges reference stable landmark IDs. Canonical JSON produces
the integrity hash; the checkpoint stores both the schema and its revision/hash.
Legacy ReefVision repeated-label groups convert deterministically to stable IDs.

The data converter reads the existing `ultralytics_pose` export ZIP, validates the
scientist-verified truth policy, manifest schema/hash fields, frame hashes, schema
identity, coordinates, and visibility values, then creates in-memory training
records that reference extracted images. It never writes into ReefVision project
storage. Group-aware splitting keeps every group wholly in one partition and refuses
to invent a validation split when fewer than two groups exist.

The trainer uses AdamW, CUDA AMP when requested and available, deterministic seeds,
visibility-aware heatmap loss plus BCE visibility loss, JSONL epoch logs, cooperative
cancellation, and atomic checkpoints. Checkpoints are local-only and versioned.

The provider adapter inspects and loads trusted local ReefPose checkpoints, exposes
their anatomy metadata, produces one single-animal keypoint prediction, derives a
bounding box from confident landmarks, and supports the existing registration and
inference job. The job keeps the review-compatible bounding box while persisting the
complete anatomical prediction in proposal provenance. Existing SLEAP, Ultralytics,
and annotation contracts remain unchanged.

## Error handling

Public ReefPose validation errors use a package-local typed error so the standalone
core does not depend on FastAPI or SQLAlchemy. The ReefVision adapter translates
these into the existing structured `ValidationError`. Dataset archives reject path
traversal, missing or duplicate files, hash mismatches, unsupported formats,
non-finite/out-of-bounds coordinates, inconsistent landmark counts, and leakage.

## Validation

- Standard-library unit tests cover schema canonicalization, repeated landmarks,
  letterbox round trips, model shapes/gradients, target/loss masking, group leakage,
  export conversion, checkpoint round trips, inference restoration, cancellation,
  and provider metadata.
- CPU smoke training validates optimizer/checkpoint/log behavior on synthetic data.
- CUDA tests validate forward/backward/AMP and checkpoint inference on the RTX 3090.
- The benchmark uses only labeled synthetic tensors/images and reports engineering
  performance, not animal-pose accuracy.

## Remaining integration after Phase 1

- Add a provider-neutral branch to the Workflow Builder pose-training node and its
  job recovery UI.
- Add a first-class still-image keypoint review/editor surface instead of displaying
  only the derived bounding-box proposal.
- Surface anatomy descriptions, groups, and skeleton edges in Model Hub/GUI schema
  editing while retaining the existing schema revision tables.
- Package and validate the PyTorch 2.11 CUDA 12.8 stack for clean-machine desktop
  installation.

