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

### Phase 3 — Segmentation datasets and training

Status: immutable segmentation datasets and exports implemented; model-training integration remains next.

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

Next:

- task-aware training-draft eligibility for detection, instance segmentation, and semantic segmentation
- segmentation dataset preflight warnings in the training workspace
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

Status: video asset and track foundations exist; no production tracker integration in this branch.

Priorities after segmentation and measurement stabilization:

- frame extraction and annotation review
- detector-plus-tracker association
- editable track identities and interpolation
- trajectory, speed, occupancy, and behavioral summaries

### Phase 7 — Active learning

Status: review-queue and prediction foundations exist.

Next vertical slice:

- uncertainty ranking from detector confidence and disagreement
- diversity-aware sampling
- direct queue-to-annotation workflow for masks and boxes

### Phase 8 — Advanced model providers

Status: model catalog and Prompt Assist provider foundations exist.

This branch extends provider output preservation by storing accepted Prompt Assist raster masks. Additional SAM, SAM2, U-Net, nnU-Net, depth, and video providers should remain modular and capability-gated.

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
