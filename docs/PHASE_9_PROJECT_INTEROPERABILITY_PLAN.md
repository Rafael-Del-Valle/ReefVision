# Phase 9 — Project Interoperability

## Scope

Phase 9 introduces a database-independent ReefVision project exchange package. The first release supports complete export and safe inspection. Data import is intentionally preflight-only until stable ID-remapping and conflict rules are implemented.

## Exchange package

- Format name: `reefvision-project-exchange`
- Format version: `1.0`
- Extension: `.reefvision.zip`
- Manifest: `reefvision-exchange-manifest.json`
- Records: deterministic JSON Lines files under `records/`
- Optional original media under `media/`
- Optional model weights under `models/`

## Exported records

- project metadata and label classes
- images, boxes, masks, and image labels
- detection and classification predictions
- classification datasets
- videos and editable tracks
- immutable dataset versions and items
- registered model metadata
- training runs and experiments
- quality-control runs and issues
- review queues and queue items
- active-learning rounds

## Integrity guarantees

- Every record section has a row count and SHA-256 checksum.
- The manifest has a canonical ReefVision checksum stored in the database.
- Archive paths are relative and normalized.
- Export jobs create the archive in managed project storage.
- Original media and model weights are opt-in.
- Model weights remain excluded by default because size and redistribution licenses vary.

## Safe inspection

Inspection performs no database writes. It checks:

- ZIP validity
- unsafe or traversal paths
- file-count and expanded-size limits
- format name and major version
- required manifest
- section file existence
- section checksums
- section row counts
- whether media relinking would be required

## Import boundary

Import is not implemented in this phase. A safe importer still needs:

1. old-to-new ID maps for every project-scoped entity
2. duplicate project and checksum policies
3. class-map reconciliation
4. model and media relinking rules
5. transactional rollback
6. immutable history handling
7. preview of every conflict before commit

The UI therefore exposes Export and Inspect, but not Import.

## Scientist-Ready Phase 9 ? pose training datasets

Phase 9 also closes the loop from scientist-reviewed Pose Active Learning
into reproducible retraining data.

### Phase 9A ? immutable verified pose dataset

A completed pose Active Learning round may be frozen into exactly one
immutable pose-training dataset.

The materializer includes only candidates whose review state is `verified`.
Pending, in-review, and skipped candidates never become training truth.

Before materialization ReefVision revalidates:

- source project and video identity
- video SHA-256
- canonical video-track identity
- exact scientist-verified track revision
- canonical frame still exists
- recomputed verified pose SHA-256
- immutable pose-schema ID, revision, and content hash
- review-correction identity
- source model registrations and checkpoint SHA-256 values.

A live track changed after verification is blocked rather than silently
materialized. After successful materialization, later edits to live tracks do
not mutate the frozen dataset.

Each item snapshots:

- project/video/track/frame identity
- source video SHA-256 and revision
- label class
- canonical bbox and pose observations/keypoints
- pose schema content
- scientist-verified pose SHA-256
- acquisition algorithm provenance
- source model/provider/version/checkpoint provenance
- source job IDs
- scientist review/correction provenance
- immutable item SHA-256.

The dataset has its own deterministic manifest SHA-256 and retains the source
Phase 8 selection SHA-256 plus the Phase 8 retraining-manifest SHA-256.

### Native package

Phase 9A exports a deterministic ReefVision-native ZIP containing:

- `reefvision-pose-training-manifest.json`
- `items.jsonl`
- `README.txt`

This package is the immutable source-of-truth snapshot for subsequent external
format rendering.

Phase 9B will render the frozen dataset into SLEAP, COCO keypoints,
DeepLabCut, Ultralytics pose, and NWB while preserving a loss/provenance
manifest and extracting the exact source video frames required by each
training format.

### Phase 9B - exact source frames and external pose training formats

A frozen Phase 9A dataset can be rendered into:

- SLEAP `.slp`
- NWB
- COCO Keypoints
- DeepLabCut CSV
- Ultralytics Pose

The renderer never reads pose truth from the current live `VideoTrack`. Pose
annotations come exclusively from immutable `PoseTrainingDatasetItem`
snapshots.

Before any frame is exported ReefVision verifies that the managed source video
still matches the SHA-256 frozen into every dataset item.

Selected source frames are decoded sequentially from frame zero through the
highest requested frame. This avoids relying on codec-dependent random seek
behavior. Every selected frame is written as a lossless PNG with:

- original zero-based source frame index
- output path
- SHA-256
- byte size
- width and height
- decoder name/version
- frozen source-video SHA-256.

Repeated semantic landmarks are never silently renamed and forgotten.
External formats receive stable unique slot names such as `tentacle__1` and
`tentacle__2`, while the export manifest retains the original semantic label
and occurrence-index mapping.

Every external export is a ZIP containing:

- exact selected source-frame PNGs
- the native external-format artifact
- `reefvision-pose-training-export-manifest.json`
- `README.txt`.

The native artifact is explicitly marked lossy because external ecosystems do
not encode every ReefVision audit field. The ReefVision manifest retains the
full canonical frozen pose, verified-pose SHA, item SHA, scientist review and
correction provenance, Active Learning acquisition provenance, source
model/provider/checkpoint provenance, repeated-landmark mapping, and
conversion-loss policy.

COCO, DeepLabCut, and Ultralytics exports do not require the optional SLEAP-IO
runtime. SLEAP and NWB exports use the existing pinned pose-interoperability
runtime.

DeepLabCut CSV export fails closed when multiple frozen individuals occupy the
same image rather than silently collapsing them into a single-animal table.
