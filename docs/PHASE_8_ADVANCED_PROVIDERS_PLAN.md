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

## Scientist-Ready 1.0 - pose-specific Active Learning

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
-> temporal landmark association
-> pose uncertainty scoring
-> frame/clip acquisition
-> scientist opens candidate in Pose Annotation Editor
-> correction or explicit save
-> verified canonical pose track revision
-> append-only review provenance
-> Phase 9 retraining manifest input

Predictions must never silently become verified training truth.

## Phase 8B - provider-native uncertainty and model disagreement

Phase 8B extends pose acquisition without inventing uncertainty information
that the active provider did not produce.

### Provider uncertainty contract

Every machine pose keyframe may carry
`pose-provider-uncertainty-0001` evidence containing:

- provider ID and version
- explicitly available uncertainty signals
- mean/minimum keypoint confidence
- heatmap entropy only when the provider/runtime actually exposes it
- PAF/link ambiguity only when the provider/runtime actually exposes it.

Current ReefVision Ultralytics and SLEAP-NN video wrappers expose keypoint
scores. They do not currently expose raw pose heatmaps or PAF tensors through
the ReefVision inference contract. ReefVision therefore records those
capabilities as unavailable rather than deriving surrogate heatmap/PAF values
from keypoint confidence.

The Active Learning score denominator includes optional provider signals only
when that evidence is actually available, so a provider that does not expose
heatmaps or PAFs is not penalized for missing signals.

### Cross-model disagreement

When multiple registered pose models have overlapping predictions for the same
video, label class, and frame, ReefVision may add a model-disagreement
acquisition signal.

Repeated semantic landmarks are compared without assuming occurrence-index
identity across models. The comparison uses an order-independent symmetric
nearest-landmark distance within each semantic label, normalized by the source
bounding-box diagonal, with an explicit repeated-landmark count mismatch term.

Comparator requirements:

- different registered source model
- same video
- same ReefVision label class
- exact same frame
- bounding-box IoU of at least 0.10
- pose observations available on both tracks.

Comparator model IDs, track IDs, IoU values, method, normalization, and
per-comparison disagreement remain in candidate provenance.

### Phase 8B acceptance

- Provider keypoint uncertainty survives inference -> keyframe persistence.
- Ultralytics/SLEAP-NN do not claim heatmap or PAF support they do not expose.
- Native heatmap/PAF values enter scoring only as finite normalized provider
  evidence.
- Missing optional provider signals do not dilute acquisition scores.
- Cross-model disagreement is reproducible and provenance-complete.
- Repeated landmark labels are compared without relying on model-specific
  occurrence ordering.
- Candidate cards distinguish unavailable provider evidence from a real
  zero-valued uncertainty score.
