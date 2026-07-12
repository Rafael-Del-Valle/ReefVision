# ReefVision 1.5.0 Report

## v1.5.0-J completion state

This repository now contains an honest `v1.5.0-J` foundation slice rather than a full multi-provider completion. The implemented work adds a unified provider hub, runtime backend reporting, Model Hub catalog UI, and a prompt-assisted `Detect then segment` workflow that routes one pending detector proposal through a registered assist model and preserves provenance when the mask is accepted.

## Implemented providers

- `ultralytics`
  - formal provider catalog entry
  - pinned dependency preflight
  - local checkpoint registration
  - detection inference
  - segmentation-checkpoint registration for box-proposal workflows
  - packaged desktop operation claimed through the existing pinned stack
- `segment_anything`
  - formal provider catalog entry
  - pinned dependency preflight
  - local checkpoint registration
  - box and brush prompting
  - prompt-assisted proposal segmentation in the annotation editor
  - packaged desktop operation claimed through the existing pinned stack

## Requested providers still blocked

- `rt_detr`
- `grounding_dino`
- `owlv2`
- `florence2`
- `sam2`
- `mobilesam`
- `fastsam`
- `reefvision_unet`
- `bytetrack`
- `botsort`

These providers are represented in the catalog with explicit capability and availability metadata, but they remain unavailable because ReefVision does not yet have pinned dependencies, packaged desktop validation, or formal provider implementations for them.

## Capability-matrix summary

- Implemented image detection: `ultralytics`
- Implemented click/box/brush prompting: `segment_anything`
- Implemented packaged desktop operation: `ultralytics`, `segment_anything`
- Runtime backend reporting: `pytorch`, `torchscript`, `onnxruntime`, `openvino`, `tensorrt`
- Training, video propagation, semantic segmentation, and tracking remain cataloged but unavailable in this slice

## Prompt Assist workflow

The annotation editor now supports:

1. select one pending detector proposal
2. choose a registered assist model
3. send the proposal box to the assist model
4. review the candidate mask overlay
5. accept or discard the result

Accepted masks remain `assist_mask` annotations, and when they originate from a proposal they now also:

- set `source_prediction_id`
- update the proposal review status
- store assist acceptance provenance on the proposal
- keep source-prediction provenance on the final annotation

## Runtime and packaging notes

- Base packaged stack still centers on the pinned PyTorch runtime.
- Optional provider-pack architecture remains the intended path for larger Transformers, OpenVINO, or video-oriented families.
- No dynamic package installation is performed at app startup or when prompt assist runs.

## Tests run

Backend:

```powershell
.\reefvision\.venv\Scripts\python.exe -m pytest reefvision\apps\api\reefvision\tests\test_provider_dependencies.py reefvision\apps\api\reefvision\tests\test_model_inference.py -q
```

Frontend:

```powershell
C:\Program Files\nodejs\npm.cmd --prefix reefvision\apps\web run test -- src/App.test.tsx src/features/annotation-editor/AnnotationEditor.test.tsx
```

Static checks:

```powershell
.\reefvision\.venv\Scripts\python.exe -m ruff check reefvision\apps\api
C:\Program Files\nodejs\npm.cmd --prefix reefvision\apps\web run typecheck
```

## Known limitations

- The app version string still remains on the `1.4.0` line in this repository snapshot.
- The provider hub exposes future families honestly, but only two providers are actually wired end to end today.
- Ultralytics segmentation checkpoints currently feed ReefVision's box-proposal review workflow rather than editable instance masks.
- The runtime catalog reports backend availability, but ONNX Runtime, OpenVINO, and TensorRT are not yet wired into model execution.
