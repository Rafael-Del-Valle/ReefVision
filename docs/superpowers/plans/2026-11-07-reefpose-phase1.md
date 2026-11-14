# ReefPose Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a native PyTorch ReefPose-S vertical slice with anatomy schemas,
frozen-dataset conversion, training/checkpoints, source-coordinate inference, provider
registration, and reproducible CPU/CUDA benchmarks.

**Architecture:** A standalone `reefvision.ml.reefpose` package owns the model and
runtime contracts. A thin adapter integrates checkpoints with the existing provider
hub and inference job while retaining full keypoints in proposal provenance.

**Tech Stack:** Python 3.12, PyTorch 2.11, torchvision, Pillow, NumPy, unittest.

**Spec:** `docs/superpowers/specs/2026-11-07-reefpose-phase1-design.md`

## Global Constraints

- Work only on `feature/reefpose-core`; do not push, merge, tag, or publish.
- Do not download pretrained checkpoints automatically.
- Do not alter or duplicate ReefVision annotations or immutable pose datasets.
- Preserve source images and return canonical source-image pixel coordinates.
- Synthetic tests and benchmarks are engineering validation only.

## Review Focus

- Non-square and odd-sized images must round-trip through letterbox geometry without
  axis swaps or padding drift (Task 2 tests).
- Absent landmarks must not contribute heatmap loss while still contributing
  visibility loss (Task 3 tests).
- Repeated labels must retain distinct stable identities and skeleton references
  through checkpoint save/load (Tasks 1 and 5 tests).
- Related groups must never cross train/validation partitions, including singleton
  and impossible-split inputs (Task 4 tests).
- Malformed or path-traversing export ZIPs and checkpoints must fail closed (Tasks 4
  and 5 tests).

---

### Task 1: Anatomy schema contract

**Files:**
- Create: `apps/api/reefvision/ml/reefpose/__init__.py`
- Create: `apps/api/reefvision/ml/reefpose/errors.py`
- Create: `apps/api/reefvision/ml/reefpose/schema.py`
- Test: `apps/api/reefvision/tests/reefpose/test_schema.py`

**Interfaces:**
- Produces: `LandmarkDefinition`, `SkeletonEdge`, `AnatomySchema`,
  `AnatomySchema.from_reefvision_groups(...)`, and canonical SHA-256 hashing.

- [ ] Write schema tests for stable IDs, repeated occurrences, descriptions/groups,
  skeleton integrity, revisions, visibility states, and deterministic hashes.
- [ ] Run the schema tests and verify they fail because the package is absent.
- [ ] Implement the immutable schema types and validation.
- [ ] Run the schema tests and verify they pass.
- [ ] Commit the anatomy schema milestone.

### Task 2: Model and exact geometry

**Files:**
- Create: `apps/api/reefvision/ml/reefpose/model.py`
- Create: `apps/api/reefvision/ml/reefpose/geometry.py`
- Test: `apps/api/reefvision/tests/reefpose/test_model_geometry.py`

**Interfaces:**
- Consumes: `AnatomySchema.keypoint_count`.
- Produces: `ReefPoseConfig`, `ReefPoseOutput`, `ReefPoseS`, `ImageTransform`,
  `letterbox_tensor(...)`, and coordinate transform/inverse methods.

- [ ] Write tests for configurable output shapes, trainable gradients, multi-scale
  encoder outputs, CPU execution, and non-square coordinate round trips.
- [ ] Run the tests and verify expected failures.
- [ ] Implement the convolutional encoder, feature pyramid, heads, and geometry.
- [ ] Run the tests and verify they pass.
- [ ] Commit the model milestone.

### Task 3: Targets and visibility-aware losses

**Files:**
- Create: `apps/api/reefvision/ml/reefpose/targets.py`
- Create: `apps/api/reefvision/ml/reefpose/losses.py`
- Test: `apps/api/reefvision/tests/reefpose/test_targets_losses.py`

**Interfaces:**
- Produces: `generate_gaussian_heatmaps(...)`, `ReefPoseTargets`,
  `ReefPoseLoss`, and `ReefPoseLossOutput`.

- [ ] Write tests for Gaussian centers, out-of-frame rejection, absent/occluded/
  visible weights, BCE visibility behavior, and finite backward gradients.
- [ ] Run the tests and verify expected failures.
- [ ] Implement targets and losses.
- [ ] Run the tests and verify they pass.
- [ ] Commit the target/loss milestone.

### Task 4: Frozen dataset conversion and leakage-safe loading

**Files:**
- Create: `apps/api/reefvision/ml/reefpose/data.py`
- Test: `apps/api/reefvision/tests/reefpose/test_data.py`

**Interfaces:**
- Consumes: existing Phase 9 export manifest and `AnatomySchema`.
- Produces: `PoseRecord`, `ReefPoseDataset`, `load_reefvision_pose_export(...)`,
  and `group_aware_split(...)`.

- [ ] Write tests using a tiny in-memory scientist-verified export ZIP for hash
  validation, repeated labels, source-pixel targets, crop geometry, path traversal,
  and group leakage/impossible splits.
- [ ] Run the tests and verify expected failures.
- [ ] Implement safe export extraction/conversion and the PyTorch dataset.
- [ ] Run the tests and verify they pass.
- [ ] Commit the data milestone.

### Task 5: Checkpoints, trainer, and inference

**Files:**
- Create: `apps/api/reefvision/ml/reefpose/checkpoints.py`
- Create: `apps/api/reefvision/ml/reefpose/training.py`
- Create: `apps/api/reefvision/ml/reefpose/inference.py`
- Test: `apps/api/reefvision/tests/reefpose/test_training_inference.py`

**Interfaces:**
- Consumes: Tasks 1-4.
- Produces: `ReefPoseTrainingConfig`, `ReefPoseTrainer`, `CheckpointState`,
  `save_checkpoint(...)`, `load_checkpoint(...)`, `ReefPosePredictor`, and typed
  landmark predictions.

- [ ] Write tests for CPU smoke training, AdamW updates, JSONL logs, cancellation,
  atomic checkpoint/resume, schema integrity, confidence values, and exact source
  coordinate restoration.
- [ ] Run the tests and verify expected failures.
- [ ] Implement checkpointing, training, and inference.
- [ ] Run the tests and verify they pass.
- [ ] Commit the train/infer milestone.

### Task 6: Provider and inference-job integration

**Files:**
- Create: `apps/api/reefvision/ml/reefpose/provider.py`
- Modify: `apps/api/reefvision/ml/providers.py`
- Modify: `apps/api/reefvision/ml/provider_hub.py`
- Modify: `apps/api/reefvision/jobs/inference.py`
- Test: `apps/api/reefvision/tests/reefpose/test_provider.py`

**Interfaces:**
- Produces: `ReefPoseRegistrationProvider` implementing the existing detection
  provider contract with keypoint-rich `DetectionPrediction` values.

- [ ] Write tests for trusted checkpoint inspection, registration metadata, provider
  lookup, pose task dispatch, source bounds, and keypoint provenance.
- [ ] Run the tests and verify expected failures.
- [ ] Implement provider registration and minimally extend pose inference dispatch.
- [ ] Run the tests plus existing provider/inference tests.
- [ ] Commit the provider milestone.

### Task 7: Synthetic CUDA benchmark and documentation

**Files:**
- Create: `apps/api/reefvision/ml/reefpose/benchmark.py`
- Create: `scripts/benchmark-reefpose.py`
- Create: `docs/REEFPOSE_PHASE1.md`
- Test: `apps/api/reefvision/tests/reefpose/test_benchmark.py`

**Interfaces:**
- Produces: deterministic JSON benchmark output with device/runtime metadata,
  parameter count, inference latency, images/s, peak memory, and train steps/s.

- [ ] Write benchmark contract tests that use tiny synthetic inputs.
- [ ] Run the tests and verify expected failures.
- [ ] Implement the benchmark and operator documentation.
- [ ] Run CPU then RTX 3090 benchmarks and save a result artifact under `docs/`.
- [ ] Run focused tests, formatting/lint/type checks when available, existing pose
  tests when dependencies permit, and a fresh Git diff/status audit.
- [ ] Commit the validated benchmark/documentation milestone.

