# ReefPose Phase 4 — pose-aware multi-animal association design

## Objective

Add scientifically auditable multi-animal pose tracking while preserving Phase 1–3B
single-animal inference, stable anatomical landmark identities, immutable truth,
provider-neutral model registration, and review workflows. Phase 4 must associate
detections over time; it must not silently convert ambiguous machine assignments into
verified animal identities.

## Scope and boundaries

Phase 4 will accept provider-normalized pose instances per frame and produce persistent
track identities, occlusion/gap state, association confidence, identity-break events,
and reviewable corrections. It will calculate IDF1, ID precision/recall, identity
switches, fragmentation, mostly-tracked/lost rates, and pose localization metrics only
when identity-labeled held-out truth is available.

It will not redesign the landmark schema, annotation store, Phase 3B evaluator, or
provider checkpoint formats. Behavior classification, anatomical measurement, and
social-interaction inference remain downstream consumers and cannot treat unreviewed
identity assignments as biological truth.

## Canonical data model

Introduce immutable/versioned multi-animal evaluation truth plus revisioned tracking
state:

- `PoseInstanceDetection`: frame, provider instance ID, stable landmark observations,
  bbox, confidence, model/checkpoint provenance.
- `PoseIdentityTrack`: stable ReefVision track ID, source job, current revision,
  lifecycle state, and optional researcher label.
- `PoseAssociationEdge`: previous/current detection IDs, cost components, gate result,
  chosen/rejected status, confidence, and algorithm version.
- `PoseOcclusionInterval`: track ID, first/last frame, cause (`missed`, `occluded`,
  `out_of_frame`, `identity_ambiguous`), and resolution.
- `PoseIdentityBreak`: frame, involved tracks/detections, reason, confidence, and review
  state.
- `PoseIdentityCorrection`: append-only scientist edit that splits, merges, relabels,
  or reconnects tracks while retaining before/after hashes and author/time.
- `MultiAnimalTruthDataset`: immutable identity-labeled frames/tracks with source-video,
  landmark-schema, and manifest hashes.

Machine state remains revisioned. Scientist-approved corrections create a new revision;
they never rewrite the historical association graph.

## Association pipeline

1. Normalize provider output into source-pixel instances with stable landmark IDs.
2. Predict each active track with a constant-velocity Kalman baseline; keep the motion
   model pluggable for learned temporal models later.
3. Build gated pairwise costs from bbox IoU, keypoint OKS where sigmas exist,
   normalized landmark distance, pose-shape similarity, motion residual, detection
   confidence, and optional appearance embedding.
4. Reject impossible pairs before assignment using configurable spatial, temporal,
   schema, and confidence gates.
5. Solve remaining bipartite assignment with Hungarian matching and deterministic tie
   breaking.
6. Keep unmatched tracks alive for a bounded gap, marking explicit occlusion state.
   Re-identification after longer gaps requires stronger appearance/pose evidence and
   records a possible identity break.
7. Start new tracks only after configurable confirmation frames; retain tentative
   detections in provenance.
8. Persist every accepted/rejected edge and cost component so assignments can be
   explained and replayed.

The initial vertical slice should use deterministic geometric/motion association. An
appearance encoder is an optional later extension and must be locally registered—no
automatic weight download.

## Manual correction and GUI

Extend the existing pose annotation/review workspace with synchronized video, track
lanes, identity colors, landmark overlays, uncertainty markers, and an association
event list. Researchers can split at frame, reconnect segments, merge false fragments,
swap identities over an interval, mark an animal absent/out-of-frame, and approve a
revision. The UI previews affected frames and requires confirmation for multi-track
edits. Undo creates a compensating correction; it does not delete history.

Workflow Builder receives a `pose_multi_animal_association` node consuming pose
instances and emitting revision-pinned multi-animal tracks. A review gate emits only
approved identity revisions for scientific measurement or behavior nodes.

## Evaluation

Evaluate only against immutable identity-labeled held-out videos. Report:

- IDF1, ID precision, and ID recall using frame-level identity matches;
- identity-switch count and switch rate per 1,000 matched detections;
- track fragmentation, mostly-tracked, mostly-lost, and false track initiations;
- association precision/recall by gap length, animal density, and occlusion duration;
- pose PCK/NME conditioned on correct identity, plus localization-independent identity
  metrics;
- per-video and aggregate denominators, bootstrap confidence intervals where sample
  size permits, and full configuration/provenance.

Matching thresholds and tie rules are part of the report identity. Provider output
with incompatible landmark schemas or coordinate conventions is excluded explicitly.
Synthetic crossing/occlusion fixtures validate engineering behavior only.

## Recovery and performance

Use the existing job worker. Persist progress by video/frame block and checkpoint active
track state so interruption recovery replays from a deterministic boundary. Cooperative
cancellation leaves a partial, non-approved artifact. GPU acceleration may be used for
provider inference or embeddings, while association must retain a tested CPU path.

## Acceptance sequence

1. Two synthetic animals crossing without occlusion retain identity deterministically.
2. Short missed detections bridge within the configured gap; longer gaps create an
   explicit break or new identity.
3. Occlusion/re-entry records uncertainty and never fabricates a confident match.
4. Manual split/merge/swap corrections create reversible revision history.
5. Saved workflow replay reproduces association hashes and typed artifacts.
6. Identity-labeled fixtures produce hand-calculated IDF1 and switch counts.
7. Cancellation, recovery, schema mismatch, tampered source, and failed-child behavior
   are covered by automated tests.
8. Real annotated multi-animal research videos are required before any biological
   accuracy claim.

## Recommended first implementation slice

Implement canonical instance/association persistence, deterministic gated Hungarian
association, gap/occlusion state, synthetic crossing tests, and IDF1/switch metrics.
Then add the correction UI and workflow review gate. Defer learned appearance embeddings
until the auditable geometric baseline and identity-truth workflow are validated.

