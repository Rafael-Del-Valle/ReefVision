# Post-Phase-6 provider and active-learning foundation

## Scope

This milestone completes the practical source-runtime Phase 7 cycle and the installed-model portion
of Phase 8. It does not implement Phase 9 interoperability, Phase 10 workflow composition, long
training runs, or packaged-desktop acceptance.

## Provider contract

Every provider asset exposes identity, version, architecture, task, capabilities, checkpoint
identity, source/revision/license metadata, dependency and device requirements, input/output/prompt
types, training/inference/video support, lifecycle state, failures, health, and successful runtime
timestamps. Lifecycle operations cover discovery, verification, diagnosis, lazy load, real health,
inference, cancellation, unload, trusted-external metadata repair, and restart reopening.

The runtime holds at most one model. A new load unloads the previous model, out-of-memory errors
release accelerator resources, and inference has no download path. Metadata verification is not a
claim that a framework can load a checkpoint.

## Installed managed families

The managed manifest has 28 entries:

- YOLO11 detection n/s/m/l/x;
- YOLOv8 detection n/s/m/l/x;
- YOLO11 segmentation n/s/m/l/x;
- YOLOv8 segmentation n/s/m/l/x;
- RT-DETR l/x;
- Ultralytics SAM ViT-B, SAM 2 Base image, MobileSAM, and FastSAM Small;
- YOLO-World v2 and YOLOE prompt-free segmentation.

YOLO-World requires explicit text classes and the separately verified managed CLIP text checkpoint.
YOLOE is represented as prompt-free segmentation, not ordinary closed-set detection. RT-DETR
training is not advertised. Segmentation proposals preserve native polygons or source-aligned
raster masks and can be accepted into editable mask annotations.

The original Meta SAM ViT-B `.pth` and the Depth Anything V2 Small Hugging Face directory are
trusted external registrations. They retain their original paths and file checksums; ReefVision
does not copy or delete them.

## Acceptance harness

Run the real-checkpoint harness separately from deterministic unit tests:

```powershell
.\.venv\Scripts\python.exe scripts\provider-acceptance.py `
  --device auto `
  --original-sam C:\Users\rafae\Documents\ReefVision\Models\sam_vit_b_01ec64.pth `
  --depth-anything C:\Users\rafae\Documents\ReefVision\Models\Depth-Anything-V2-Small-hf
```

The harness creates one deterministic local image, blocks network connections, validates models
sequentially, unloads each model, proves a second load, writes an atomic JSON report, and appends
database acceptance records. Its result is software/runtime acceptance only, not scientific coral
or fish validation.

## Active-learning cycle

The baseline embedding provider uses a verified local YOLO11n or YOLOv8n checkpoint, stable RGB
preprocessing, Ultralytics backbone features, global pooling, and L2 normalization. Persisted
identity prevents vectors from different checkpoints or source-image revisions from overwriting one
another.

Queue selection supports uncertainty, confidence margin, entropy when probability vectors exist,
cosine novelty, diversity, blended weights, class balance, project/group/fragment limits,
exact/near-duplicate suppression, and manual inclusion/exclusion. Each item stores one or more
human-readable selection reasons.

Only completed or explicitly skipped queue revisions can be promoted. Completed images must be in
the reviewed annotation state. Promotion and immutable dataset creation share one transaction and
are retry-idempotent. A later training failure cannot destroy the completed queue or dataset.

## Scientific and runtime boundaries

- Model predictions and prompt candidates remain unverified until explicit acceptance.
- Depth Anything produces relative depth; raw output is distinct from display normalization and
  has no physical unit without calibration.
- Synthetic acceptance does not establish scientific accuracy.
- SAM 2 image prompting is operational, but video propagation is unavailable without a compatible
  SAM 2 video runtime/API and video checkpoint arrangement.
- Ensemble-disagreement selection is deferred.
- Source-runtime browser/API tests do not establish packaged-desktop operation.
