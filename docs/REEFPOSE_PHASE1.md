# ReefPose Phase 1

ReefPose-S is ReefVision's native PyTorch single-animal pose model. Phase 1 is a
working engineering vertical slice: anatomy schemas, frozen-dataset conversion,
training, checkpoints, inference, provider registration, and CPU/CUDA benchmarking.
It does not wrap SLEAP or Ultralytics and it never downloads pretrained weights.

## Architecture

The model uses a four-stage convolutional encoder, a top-down feature pyramid,
stride-4 landmark heatmaps, and a per-landmark visibility head. The model contract is
kept separate from the encoder implementation so future transformer encoders, graph
refiners, and temporal heads can preserve the same training and inference surfaces.

Anatomy schemas provide stable landmark IDs, display names, optional descriptions
and groups, occurrence indices for repeated structures, allowed visibility states,
skeleton edges, immutable revisions, and canonical SHA-256 integrity hashes.

Inference applies a recorded aspect-preserving letterbox transform and its exact
inverse. Results contain source-image pixel coordinates, landmark confidence,
visibility probability/state, a derived single-animal bounding box, and schema
identity.

## Training data

Use ReefVision's existing immutable, scientist-verified pose-training dataset and
export it as `ultralytics_pose`. ReefPose validates the export manifest, schema hash,
truth policy, frame checksums, coordinates, and landmark order before training. The
converter extracts to an explicit caller-owned directory and never changes project
images or writes a second annotation store.

Related records are split by group as an indivisible unit. A Phase 9 export currently
contains one source video, so it normally contains one leakage group; in that case,
provide a separately frozen validation dataset rather than randomly splitting frames
from the same video.

## Training and checkpoints

`ReefPoseTrainer` uses AdamW, visibility-aware Gaussian heatmap loss, binary
visibility loss, CUDA AMP when available/requested, deterministic seeds, gradient
clipping, JSONL logs, cooperative cancellation, and atomic `best.pt`, `last.pt`, or
`cancelled.pt` checkpoints. Checkpoints store the model configuration/weights,
anatomy revision/hash, optimizer, AMP scaler, epoch/global step, metrics, training
configuration, and runtime reproducibility metadata.

Checkpoint loading uses PyTorch's safe `weights_only=True` path. Treat model files as
local scientific artifacts and retain their dataset/checksum provenance.

## Provider integration

The Model Hub now exposes provider ID `reefpose`. Trusted local `.pt`/`.pth`
checkpoints can be registered as task `pose` and run by the standard image inference
job. The current still-image review model remains bounding-box oriented, so the job
stores a review-compatible derived box and retains the complete landmark array and
anatomy schema identity in proposal provenance.

Existing SLEAP registration/video inference, Ultralytics pose training, frozen pose
datasets, annotations, and schema revision tables are unchanged.

## Synthetic benchmark

Run from the repository root with the designated Python interpreter:

```powershell
C:\AI-Projects\venvs\reefpose\Scripts\python.exe scripts\benchmark-reefpose.py `
  --device cuda --input-size 256 --keypoints 8 --batch-size 16 `
  --warmup 10 --inference-iterations 100 --training-steps 50 `
  --output docs\reefpose-benchmark-rtx3090-2026-11-07.json
```

The JSON records the exact workload, software/device metadata, parameter count,
batch latency, images per second, peak allocated GPU memory, and training-step
throughput. Inputs and targets are random synthetic tensors. These results validate
runtime engineering only; they do not validate pose accuracy on animals.

## Remaining integration work

- Make the Workflow Builder pose-training node provider-neutral; it currently
  dispatches Ultralytics-specific training while ReefPose training is available
  through the native Python service.
- Add a first-class still-image keypoint review/editor UI that reads/writes the
  canonical pose entities instead of showing only the derived proposal box.
- Surface anatomy descriptions, groups, skeleton connections, and revisions in the
  Model Hub/GUI schema editor.
- Add multi-animal detection, anatomical graph refinement, transformer encoders, and
  temporal models as separate validated phases.
- Validate accuracy and calibration on real, held-out, labeled animal datasets.
- Package and clean-machine-test the PyTorch 2.11/CUDA 12.8 desktop runtime.

