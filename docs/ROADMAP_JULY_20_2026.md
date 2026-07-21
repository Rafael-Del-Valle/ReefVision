# ReefVision July 20 Implementation Roadmap

Target date: July 20, 2026

This plan continues from the multitask, measurement, and video foundation at commit `a7d302c`. Work is being developed on `feat/editable-mask-annotations` and reviewed through draft pull request #3 against `roadmap/multitask-foundation`.

## Delivery principle

The July 20 goal is a sequence of safe vertical slices, not a simultaneous rewrite of annotation, training, measurement, and video. Each slice must preserve the stable bounding-box workflow, use source-image coordinates, retain provenance, and remain reversible through revisions or audit events.

## Phase status

### Phase 1 — Multitask foundation

Status: complete in the selected base commit.

Available foundations include task-aware model metadata, measurements, video assets and tracks, model-catalog support, and broader workflow capability definitions.

### Phase 2 — Editable mask annotations

Status: implementation complete for polygon and raster editing; executable validation is pending functioning CI runners.

Implemented:

- revisioned polygon and raster mask records
- soft deletion and append-only mask audit events
- transactional mask and bounding-box saves under one image revision
- polygon bounds, duplicate-point, minimum-area, and self-intersection validation
- backward compatibility for box-only clients
- managed raster-mask storage and content serving
- Prompt Assist acceptance that preserves the actual raster mask instead of only its bounding box
- linked box/mask/model/prediction provenance
- editable polygon canvas with source-coordinate creation, selection, class changes, deletion, undo/redo, and vertex dragging
- double-click polygon edge insertion and Alt-click vertex removal with a three-point minimum
- dedicated polygon and raster workspaces accessible from the existing annotation editor
- freehand raster paint and erase tools with source-coordinate brush sampling
- immutable raster revision files so older dataset snapshots remain reproducible
- autosave and revision-conflict behavior shared with the box workflow
- protection against sending server deletes for masks created and removed before their first save

Deferred from this slice:

- holes and multipart masks
- raster-to-polygon conversion and polygon simplification controls
- local multi-stroke undo before a server revision is committed

### Phase 3 — Segmentation datasets, training, inference, and review

Status: immutable datasets, Ultralytics polygon training, and mask-preserving inference/review are implemented; real-model and packaged-desktop validation remain.

Implemented:

1. mask-aware immutable dataset-version records and manifests
2. frozen polygon geometry and raster file checksums
3. per-image and per-class mask counts
4. YOLO polygon-segmentation export
5. indexed semantic-mask PNG export using polygon and raster masks
6. deterministic semantic overlap ordering
7. raster checksum verification at export time
8. selectable detection, polygon-segmentation, and semantic-mask exports in the UI
9. stable export IDs and paths assigned before the background job is queued
10. unchanged YOLO detection export behavior
11. task-aware Ultralytics instance-segmentation training and checkpoint registration
12. validated polygon-first instance proposals with managed source-aligned raster fallback
13. explicit mask accept/reject review that creates editable, provenance-linked mask annotations
14. atomic project-relative proposal storage, failed-job cleanup, restart-safe review, and retry-idempotent acceptance

Next:

- real-checkpoint inference acceptance across representative coral images
- tiled inference for source images that cannot be processed safely at one inference scale
- boundary metrics and visual false-positive/false-negative overlays
- provider-specific export adaptation where a trainer requires a format other than YOLO polygons or indexed PNGs

Out of scope for the July 20 slice unless the above is green:

- full nnU-Net orchestration
- large hyperparameter-search UI
- training every segmentation architecture in the model catalog

### Phase 4 — Coral measurements

Status: first mask-derived measurement slice implemented; validation is pending functioning CI runners.

Implemented per verified mask:

- area in source pixels
- perimeter in source pixels
- centroid
- bounding extent
- contained bounding-box count
- contained-box density per 1,000 mask pixels
- support for polygon and raster masks

Next:

- calibrated physical units
- total linear extension from editable centerlines
- surface-area models with depth/calibration metadata
- configurable polyp-state and species filters for density
- CSV and NumPy measurement exports

### Phase 5 — Classification workflows

Status: task/model foundations exist; no new July branch implementation yet.

Priorities after segmentation validation:

- image-level and crop-level dataset generation
- species and condition/state classification tasks
- task-aware evaluation summaries

### Phase 6 — Video and fish tracking

Status: core implementation complete in the current Phase 6 working tree, with deterministic
software-acceptance coverage. Real fish-video quality validation, long-video performance,
codec/container coverage, and packaged-Windows validation remain release gates.

Implemented vertical slice:

- project-managed, checksum-addressed video import, playback, and exact frame access;
- asynchronous detector plus ByteTrack or BoT-SORT jobs with cancellation, transactional persistence,
  restart-safe terminal state, request idempotency, and complete provenance;
- revisioned observation and identity correction with append-only audit events;
- scalar calibration, saved rectangular zones, trajectories, heatmaps, individual movement metrics,
  and school-level metrics with explicit pixel/physical units;
- ground-truth-gated localization, detection, continuity, fragmentation, and identity-switch
  evaluation with stored tracker/threshold comparisons;
- atomic managed CSV, JSON, MOTChallenge, NumPy, and rendered-video artifacts with manifests and
  checksums; and
- an integrated Video dashboard with job, correction, analysis, evaluation, and export workflows.

See `PHASE_6_VIDEO_TRACKING_IMPLEMENTATION.md` for implementation contracts, automated acceptance,
scientific-validity boundaries, and remaining limitations.

### Phase 7 — Active learning

Status: the practical source-runtime cycle is implemented: automatic versioned embeddings,
uncertainty/novelty/diversity selection, persistent explainable revisions, annotation review,
transactional immutable-dataset promotion, training linkage, and compatible model comparison.

Deferred: ensemble disagreement, scientific batch-quality validation, and packaged-desktop
acceptance.

### Phase 8 — Advanced model providers

Status: the practical provider workflow is implemented for installed YOLO detection/segmentation,
RT-DETR, managed SAM-family image prompting, YOLO-World text prompts, YOLOE prompt-free masks,
original Meta SAM, and Depth Anything V2. Capabilities gate load, health, prompt, and depth controls;
acceptance records distinguish metadata verification from real inference.

SAM 2 video propagation remains deferred because the installed image checkpoint/runtime does not
provide the required video predictor API. Packaged-desktop and scientific accuracy validation also
remain deferred.

### Phase 9 — Project data and interoperability

Status: mask-aware dataset manifests and segmentation exports are implemented.

Next:

- measurement tables and calibrated-unit metadata
- project JSON schema version update
- import validation for external segmentation datasets

### Phase 10 — Fusion/node editor

Status: deferred until the underlying task outputs are stable.

The node editor should compose proven detection, segmentation, tracking, depth, classification, and measurement services rather than becoming a second implementation of those services.

## Validation blocker

GitHub Actions currently creates CI and Windows Desktop jobs, but the jobs fail before checkout with no steps and no logs. Moving the cross-platform CI jobs from Windows to Ubuntu produced the same result. This is a repository or account Actions infrastructure blocker, not a reported test assertion or compiler failure. The branch must remain draft until backend, frontend, and desktop checks execute normally.

## Merge gates

Before merging the editable-mask branch:

- Alembic upgrades through `0016` and downgrades to base complete on a test database
- Ruff and mypy pass
- backend tests pass, including mask lifecycle, Prompt Assist persistence, measurements, frozen mask snapshots, segmentation exports, and raster revision preservation
- frontend formatting, TypeScript build, and Vitest pass
- existing bounding-box editor and detection-export regression tests pass
- Windows desktop package starts and serves persisted mask content
- manual test confirms box, polygon, and raster workspace switching
- manual test confirms detection, YOLO segmentation, and semantic-mask ZIP downloads

## Current delivery state

All July 20 implementation priorities listed above are present on the branch. The remaining work before merge is executable validation, correction of any failures uncovered by that validation, and manual desktop acceptance testing.
