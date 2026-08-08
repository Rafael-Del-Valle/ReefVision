# Phase 8 — Advanced Providers and Prompt Assist

## Scope

Phase 8 defines how optional vision models enter ReefVision without presenting unimplemented or unvalidated adapters as working features.

## Implemented foundation

- Provider-neutral contracts for:
  - text-prompt detection
  - image-prompt segmentation
  - video mask propagation
  - monocular relative-depth prediction
- Explicit manifests for:
  - Segment Anything
  - Grounding DINO
  - OWLv2
  - Florence-2
  - SAM 2
  - MobileSAM
  - FastSAM
  - Depth Anything V2
- Fail-closed provider preflight that checks:
  - declared task support
  - required prompt fields
  - registered model ownership and provider match
  - provider-hub availability
  - execution-adapter status
  - requested device
  - output contract
- A Provider Lab frontend component that displays manifests and preflight blockers without launching blocked providers.

## Provider policy

A provider is executable only after all of the following are true:

1. Compatible dependencies are pinned.
2. The checkpoint format has a safe inspector.
3. The provider implements a typed ReefVision adapter.
4. Outputs enter an existing human-review workflow.
5. Prompt, checkpoint, image, and provider provenance are persisted.
6. Packaged Windows behavior is tested on a clean installation.

## Depth Anything V2 boundary

Depth Anything V2 is represented as a relative-depth provider. Its contract produces a float array, preview, and value range. It does not claim calibrated physical distance, 3D reconstruction, or coral surface area. Those require a separate calibration and geometry model.

## Deferred implementation

- Optional provider-pack installer and version lock files.
- Grounding DINO and OWLv2 proposal adapters.
- SAM 2 image and video propagation adapters.
- Depth Anything V2 array persistence and viewer overlay.
- Florence-2 advisory caption and phrase-grounding review UI.
- MobileSAM and FastSAM benchmark-based adapter selection.
- Clean-machine desktop packaging validation.
