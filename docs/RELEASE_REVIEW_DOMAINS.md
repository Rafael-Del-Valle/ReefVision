# ReefVision release review domains

**Status:** mandatory stabilization structure

**Applies to:** `feat/all-phases-advancement` and stabilization branches derived from it

## Purpose

PR #8 is too large to review as one undifferentiated change. Release review must proceed through the domains below. A domain is reviewable only when its named journey passes and its evidence is attached to the candidate commit.

No new product capability belongs in these reviews. Allowed changes are defect fixes, deletion of dead or duplicate code, test improvements, documentation corrections, packaging repairs, and simplification of existing user journeys.

## Review rules

1. Each review PR covers one domain, plus the smallest unavoidable shared changes.
2. A production file belongs to one primary domain. Cross-domain edits require a written explanation in the PR body.
3. New database migrations and new production modules remain blocked by the feature freeze.
4. Synthetic tests can establish determinism and safety, but they do not replace real-model, real-image, video, scientific, or installed-app evidence.
5. A feature without a demonstrated journey is excluded from the release candidate or visibly marked unavailable.
6. Generated payloads, encoded source archives, self-deleting publishers, and temporary source-application workflows are not accepted as implementation delivery.

## Domain 1 — Core projects and annotation

**Primary paths**

- `apps/api/reefvision/api/routes/annotations.py`
- `apps/api/reefvision/services/annotations.py`
- `apps/api/reefvision/services/raster_edits.py`
- `apps/api/reefvision/storage/masks.py`
- `apps/web/src/features/annotation-editor/`
- project, image-import, class-management, gallery, and thumbnail modules

**Required journey**

Create an octocoral project → import PNG and TIFF images → confirm checksums and thumbnails → create, edit, save, reload, and delete boxes, polygons, and raster masks → restart ReefVision → confirm revisions and managed files remain intact.

**Exit evidence**

- backend annotation and mask suites pass;
- frontend annotation-editor tests pass;
- manual source-coordinate editing succeeds on representative coral images;
- no annotation is silently accepted from a model.

## Domain 2 — Datasets, training, inference, and evaluation

**Primary paths**

- dataset-version and export services
- `apps/api/reefvision/jobs/*training*.py`
- `apps/api/reefvision/ml/segmentation*.py`
- Ultralytics training, tuning, metrics, and report modules
- training, tuning, evaluation, and report workspaces

**Required journey**

Create an immutable group-aware dataset → export detection and segmentation formats → run one real YOLO detection training job and one real YOLO segmentation job → register resulting checkpoints → evaluate class-wise metrics → run inference → review and correct predictions → reproduce the same dataset manifest after restart.

**Exit evidence**

- real checkpoints load and run without implicit downloads;
- reports match stored metrics and provenance;
- failed or cancelled jobs leave no false-success artifacts;
- detection and segmentation proposals remain review-required.

## Domain 3 — Coral measurements and scientific validation

**Primary paths**

- measurement routes, schemas, services, and geometry modules
- measurement export and validation modules
- `apps/web/src/features/measurements/`

**Required journey**

Select reviewed coral masks → calculate pixel-based measurements → inspect centerlines and derived values → export tables → compare a representative subset with manual measurements → document unit and calibration limits.

**Exit evidence**

- polygon and raster measurements agree on controlled fixtures;
- repeat runs are deterministic;
- relative depth is never presented as physical size;
- physical units require explicit calibration and camera metadata.

**Release exclusion**

The coral-skeleton workbench is deferred. It must return as ordinary reviewed source files with focused tests and a demonstrated journey. The incomplete encoded payload and publisher mechanism were removed during stabilization.

## Domain 4 — Classification

**Primary paths**

- classification models, routes, schemas, services, jobs, and tests
- `apps/web/src/features/classification/`

**Required journey**

Create image-level and crop-level classification assignments → build an immutable classification dataset → train a real six-class and binary classifier → evaluate confusion and calibration → run inference → review predictions → export scientifically interpretable results.

**Exit evidence**

- local architecture and checkpoint resolution work on a clean installation;
- class mappings survive export and restart;
- evaluation uses real predictions rather than only synthetic fixtures;
- unavailable architectures are visibly unavailable.

## Domain 5 — Video and tracking

**Primary paths**

- video assets, jobs, tracking, behavior, evaluation, and export modules
- `apps/web/src/features/videos/`

**Required journey**

Import a representative fish video → run one ByteTrack and one BoT-SORT job → inspect trajectories → correct identity and observation errors → define zones → calculate behavior summaries → export CSV, JSON, MOT, NumPy, and rendered video → restart and confirm persistence.

**Exit evidence**

- codec and frame-access behavior is documented;
- tracking metrics are compared with reviewed ground truth;
- long-video cancellation and restart behavior are verified;
- pixel and physical units are never mixed.

## Domain 6 — Providers, Prompt Assist, depth, and active learning

**Primary paths**

- provider catalog, lifecycle, readiness, verification, and sidecar modules
- assist, depth, embeddings, review queues, and active-learning modules
- provider, depth, embedding, and review-queue workspaces

**Required journey**

Inspect provider readiness → load an installed provider → create positive and negative prompts → review and accept or reject a candidate mask → generate versioned embeddings → build an explainable active-learning queue → annotate selected images → promote them into a new immutable dataset version.

**Exit evidence**

- real SAM-family and Depth Anything checkpoints pass acceptance;
- provider readiness distinguishes metadata checks from inference success;
- active-learning scores are reproducible and explainable;
- external API use is opt-in and preserves request/cost provenance.

## Domain 7 — Interchange and workflow composition

**Primary paths**

- interchange, archive, COCO, LabelMe, CVAT, and Roboflow modules
- workflow validation, persistence, execution, cleanup, and consensus modules
- `apps/web/src/features/advancement/`

**Required journey**

Export a reviewed dataset → open it in external consumers → re-import supported results → compare IDs, dimensions, classes, geometry, splits, and checksums → create a simple workflow graph using already proven services → validate, persist, reopen, and execute it without arbitrary user code.

**Exit evidence**

- frontend and backend port compatibility rules agree;
- external round trips are recorded with real consumer versions;
- workflow artifacts retain lineage and deterministic checksums;
- the node editor does not reimplement task services.

## Domain 8 — Desktop, storage, recovery, and release

**Primary paths**

- `apps/api/reefvision/desktop.py`
- Tauri and PyInstaller configuration
- bootstrap, build, MSI, recovery, cache, and release-validation scripts
- storage settings, backups, diagnostics, and recovery workspaces
- `.github/workflows/`

**Required journey**

Install on a clean Windows machine → launch without a developer terminal → choose storage location → create a project and import data → close and reopen → create and verify a backup → restore to a new managed location → build and verify MSI → uninstall without deleting user data.

**Exit evidence**

- complete release-validation report passes;
- MSI payload and hashes are recorded;
- packaged sidecar health and restart persistence pass;
- no release gate is marked passed from source inspection alone.

## Review order

1. Core projects and annotation
2. Datasets, training, inference, and evaluation
3. Coral measurements and scientific validation
4. Classification
5. Video and tracking
6. Providers, Prompt Assist, depth, and active learning
7. Interchange and workflow composition
8. Desktop, storage, recovery, and release

Domains may be prepared in parallel, but Domain 8 cannot pass until the applicable journeys from Domains 1–7 have evidence on the same candidate commit.
