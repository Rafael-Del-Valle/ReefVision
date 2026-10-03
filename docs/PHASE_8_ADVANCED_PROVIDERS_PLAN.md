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

## Scientist-Ready 1.0 ? pose-specific Active Learning

Pose annotations are first-class Active Learning inputs. Phase 8 is not
accepted if Active Learning is limited to image detection/classification.

### Phase 8A acquisition and review acceptance

The implementation must:

1. Select either individual frames or short clips from canonical temporal
   pose observations.
2. Rank candidates with explicit, persisted components for:
   - low landmark confidence
   - uncertain/occluded/missing landmarks
   - temporal association uncertainty
   - repeated-landmark ambiguity
   - explicit or nearby identity breaks
   - temporal motion anomalies
3. Preserve the scoring algorithm/version, component weights, source video
   checksum, source track revision, immutable pose schema/revision, source
   observation IDs, association-decision IDs, identity-break IDs, model IDs,
   job IDs, score components, reason codes, and a SHA-256 provenance digest.
4. Avoid redundant neighboring frames or overlapping clips according to a
   scientist-configurable spacing rule.
5. Route each selected candidate directly into the existing
   Pose Annotation Editor at the selected video track and focus frame.
6. Keep model output non-canonical until explicit scientist review.
7. Mark corrected model landmarks as corrected provenance through the
   existing Pose Annotation Editor.
8. Record scientist verification as an append-only
   PoseLandmarkCorrection audit event.
9. Block candidates that become stale before scientist review starts.
10. Preserve a SHA-256 digest of the verified canonical pose keyframe and
    canonical track revision.
11. Expose a versioned retraining provenance manifest. Phase 8 establishes
    the manifest contract; Phase 9 materializes verified pose datasets and
    loss-aware SLEAP/COCO/DLC/YOLO/NWB exports.

### Required end-to-end Phase 8A journey

pose inference / imported pose
? temporal landmark association
? pose uncertainty scoring
? frame/clip acquisition
? scientist opens candidate in Pose Annotation Editor
? correction or explicit save
? verified canonical pose track revision
? append-only review provenance
? Phase 9 retraining manifest input

Predictions must never silently become verified training truth.
