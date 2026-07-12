# ReefVision Product and Implementation Specification

**Document status:** Initial build specification  
**Application name:** ReefVision  
**Working release target:** ReefVision 0.1  
**Primary use case:** Local-first marine image annotation, dataset management, model-assisted labeling, and quality control for coral-polyp object-detection research.

---

## 1. Product specification

### 1.1 Product vision

ReefVision is a local-first scientific image-annotation and computer-vision platform designed initially for coral-polyp detection. It should make it possible to:

1. Create and organize research projects.
2. Import full-resolution marine images.
3. Define configurable annotation classes.
4. Draw, edit, review, and delete bounding-box annotations.
5. Import and export YOLO-format datasets.
6. run object-detection models locally.
7. Review model predictions before accepting them as verified annotations.
8. Create immutable dataset versions and reproducible train/validation/test splits.
9. identify images that need additional annotation or review.
10. preserve image metadata, annotation history, and dataset lineage.

The initial application must serve the current octocoral-polyp workflow while remaining general enough for fish, benthic organisms, segmentation, and video tracking later.

### 1.2 Initial scientific configuration

ReefVision must allow arbitrary classes, but a project template should be available with these six classes:

| Default ID | Class name | Species | State |
|---:|---|---|---|
| 0 | Muricea Closed | *Muricea pendula* | Closed |
| 1 | Thesea Closed | *Thesea nivea* | Closed |
| 2 | Muricea Open | *Muricea pendula* | Open |
| 3 | Swiftia Open | *Swiftia exserta* | Open |
| 4 | Swiftia Closed | *Swiftia exserta* | Closed |
| 5 | Thesea Open | *Thesea nivea* | Open |

Class IDs must be project-specific and stable after annotations exist. Reordering the visible class list must not silently change stored class IDs.

### 1.3 Target user

The initial user is a researcher working locally on Windows with large coral images and YOLO datasets. The interface should therefore prioritize:

- Fast keyboard-driven annotation.
- Reliable autosave.
- High-resolution pan and zoom.
- Dense small-object annotation.
- Explicit review of model-generated boxes.
- Reproducible dataset exports.
- Recovery after an interrupted session.
- Clear scientific provenance rather than social or cloud collaboration features.

### 1.4 Core user workflows

#### Workflow A: Create a project

The user creates a project, enters a name and optional description, selects a blank class list or the octocoral template, and chooses or accepts a managed local storage location.

#### Workflow B: Import images

The user imports individual images or a directory. ReefVision:

- validates supported formats;
- computes a SHA-256 checksum;
- reads width, height, and available metadata;
- detects duplicates;
- copies or links the source according to the selected import policy;
- creates thumbnails without altering the original image;
- reports successful, duplicate, and failed imports.

#### Workflow C: Manually annotate an image

The user opens an image, selects a class, draws bounding boxes, edits boxes, changes classes, and deletes incorrect boxes. Changes autosave. The user can mark the image as unannotated, in progress, annotated, or reviewed.

#### Workflow D: Import an existing YOLO dataset

The user selects a YOLO `data.yaml` file or image/label directories. ReefVision validates class names, image-label correspondence, normalized coordinates, malformed rows, and out-of-range boxes. The user receives a validation report before committing the import.

#### Workflow E: Export a dataset

The user chooses a dataset version or current working set, split rules, and export location. ReefVision writes a complete YOLO dataset containing images or links, label files, `data.yaml`, a manifest, and export provenance.

#### Workflow F: Generate model predictions

The user registers a local model checkpoint, chooses images and prediction parameters, and starts a prediction job. Predictions are stored separately from human-approved annotations.

#### Workflow G: Review predictions

The user sees pending predictions overlaid on the image. Each prediction may be accepted, edited and accepted, or rejected. Bulk acceptance is allowed only with an explicit confidence threshold and confirmation.

#### Workflow H: Create a dataset version

The user creates an immutable snapshot with a name, notes, selected images, annotation state, class map, and split assignment. Later annotation edits do not alter prior versions.

### 1.5 Functional requirements for version 0.1

ReefVision 0.1 must include:

- Local project creation and deletion safeguards.
- Image import, duplicate detection, thumbnails, and gallery filtering.
- Configurable object-detection classes.
- Bounding-box creation and editing.
- Undo and redo within the current annotation session.
- Autosave and crash-safe persistence.
- Annotation counts by image and class.
- YOLO detection import and export.
- Model registration and local batch inference through an adapter interface.
- Prediction review and conversion to verified annotations.
- Immutable dataset versions.
- Random train/validation/test splits with a seed.
- Group-aware splitting to prevent related images or tiles from crossing splits.
- Basic quality-control checks.
- Unit, API, and end-to-end tests.
- Windows development instructions.

### 1.6 Non-goals for version 0.1

Do not implement these in the initial release:

- Cloud accounts or multi-user authentication.
- Real-time collaboration.
- Subscription or payment systems.
- Hosted model training.
- Polygon, mask, keypoint, or classification annotation.
- Video tracking.
- Public dataset hosting.
- Mobile applications.
- A plugin marketplace.
- Full Roboflow feature parity.
- Automatic deletion or modification of original source images.

These are future extensions and must not complicate the first stable object-detection workflow.

### 1.7 Quality attributes

#### Reliability

- No annotation may disappear after the API confirms a successful save.
- Database writes involving multiple related records must be transactional.
- Original imported image files must never be overwritten.
- Interrupted imports and inference jobs must be recoverable or restartable.

#### Performance

Initial targets on a normal local workstation:

- Project gallery should display the first page within two seconds for a project containing 5,000 indexed images after thumbnails exist.
- Normal annotation actions should feel immediate and should not wait for full-size image re-encoding.
- The annotation editor should support at least 1,500 bounding boxes on one image without becoming unusable.
- List endpoints must use pagination.

These are engineering targets, not scientific-performance claims.

#### Reproducibility

Every dataset export must include:

- ReefVision version.
- Project ID.
- Dataset-version ID when applicable.
- Export timestamp.
- Class map.
- Included image checksums.
- Split assignment.
- Annotation counts.
- Random seed and grouping key used for splitting.
- Model information when predictions contributed to accepted annotations.

#### Usability

- Destructive actions require confirmation.
- Unsaved or failed saves must be visible.
- Keyboard shortcuts must be documented in the interface.
- Dense annotations must remain selectable at high zoom.
- Model predictions must be visually distinguishable from verified annotations.

---

## 2. Technical architecture

### 2.1 Selected stack

#### Frontend

- React
- TypeScript
- Vite
- React Router
- TanStack Query for API state
- Zustand or a small equivalent store for editor-only state
- Konva through `react-konva` for the annotation canvas
- Vitest and React Testing Library
- Playwright for end-to-end tests

#### Backend

- Python 3.11 or newer
- FastAPI
- Pydantic
- SQLAlchemy 2.x
- Alembic migrations
- SQLite for the initial local database
- Pillow for image metadata and thumbnail generation
- PyYAML for YOLO configuration files
- pytest
- Ruff
- mypy

#### Machine learning

- A provider-neutral `DetectorAdapter` interface.
- An initial Ultralytics-compatible object-detection adapter.
- Inference must run as a background job rather than blocking an HTTP request.
- The application database records job status and result provenance.
- Model-specific code must remain under `apps/api/reefvision/ml/adapters/`.

#### Storage

- SQLite stores metadata, relationships, status, and provenance.
- Original images, thumbnails, model checkpoints, exports, and temporary files remain on the filesystem.
- Database records store managed relative paths rather than machine-specific absolute paths whenever possible.

### 2.2 Runtime model

For development:

1. The React development server runs separately.
2. FastAPI runs on localhost.
3. The frontend communicates with the API through generated or typed API clients.
4. A background worker process claims queued jobs from the database.

For the first distributable build:

- Provide a local launcher that starts the API, worker, and built frontend.
- Browser-based local use is acceptable before a desktop wrapper is added.
- A later milestone may package the frontend with Tauri, but Tauri is not required for the first scientifically usable release.

### 2.3 Architectural boundaries

- `domain`: entities, enums, and domain rules without FastAPI dependencies.
- `services`: project, import, annotation, export, versioning, and inference operations.
- `repositories`: database access.
- `api`: HTTP routes and request/response models.
- `ml`: model adapter interfaces and implementations.
- `storage`: safe path handling, checksums, thumbnails, and managed files.
- `jobs`: background-job definitions and worker loop.

The frontend must not contain scientific persistence rules. The backend must reject invalid annotations even when the frontend already validates them.

---

## 3. Repository structure

```text
reefvision/
├─ AGENTS.md
├─ README.md
├─ CONTRIBUTING.md
├─ CHANGELOG.md
├─ LICENSE
├─ .editorconfig
├─ .gitignore
├─ .env.example
├─ pyproject.toml
├─ package.json
├─ pnpm-workspace.yaml
├─ docker-compose.yml                 # optional development convenience only
├─ docs/
│  ├─ REEFVISION_PRODUCT_SPEC.md
│  ├─ ARCHITECTURE.md
│  ├─ DATA_MODEL.md
│  ├─ USER_WORKFLOWS.md
│  ├─ TESTING.md
│  └─ decisions/
│     ├─ 0001-local-first.md
│     ├─ 0002-sqlite-filesystem-storage.md
│     └─ 0003-predictions-separate-from-annotations.md
├─ apps/
│  ├─ web/
│  │  ├─ package.json
│  │  ├─ vite.config.ts
│  │  ├─ tsconfig.json
│  │  ├─ src/
│  │  │  ├─ app/
│  │  │  │  ├─ router.tsx
│  │  │  │  └─ providers.tsx
│  │  │  ├─ api/
│  │  │  │  ├─ client.ts
│  │  │  │  └─ generated/
│  │  │  ├─ components/
│  │  │  ├─ features/
│  │  │  │  ├─ projects/
│  │  │  │  ├─ gallery/
│  │  │  │  ├─ annotation-editor/
│  │  │  │  ├─ imports/
│  │  │  │  ├─ exports/
│  │  │  │  ├─ models/
│  │  │  │  ├─ predictions/
│  │  │  │  ├─ versions/
│  │  │  │  └─ quality-control/
│  │  │  ├─ hooks/
│  │  │  ├─ stores/
│  │  │  ├─ styles/
│  │  │  ├─ test/
│  │  │  └─ main.tsx
│  │  └─ tests/
│  │     └─ e2e/
│  └─ api/
│     ├─ alembic.ini
│     ├─ migrations/
│     ├─ reefvision/
│     │  ├─ main.py
│     │  ├─ config.py
│     │  ├─ api/
│     │  │  ├─ dependencies.py
│     │  │  └─ routes/
│     │  ├─ domain/
│     │  │  ├─ entities.py
│     │  │  ├─ enums.py
│     │  │  └─ errors.py
│     │  ├─ db/
│     │  │  ├─ base.py
│     │  │  ├─ session.py
│     │  │  └─ models/
│     │  ├─ repositories/
│     │  ├─ schemas/
│     │  ├─ services/
│     │  ├─ storage/
│     │  ├─ importers/
│     │  │  └─ yolo_detection.py
│     │  ├─ exporters/
│     │  │  └─ yolo_detection.py
│     │  ├─ ml/
│     │  │  ├─ contracts.py
│     │  │  └─ adapters/
│     │  │     └─ ultralytics_detector.py
│     │  ├─ jobs/
│     │  │  ├─ worker.py
│     │  │  └─ handlers/
│     │  └─ tests/
│     │     ├─ unit/
│     │     ├─ integration/
│     │     └─ fixtures/
│     └─ scripts/
│        ├─ dev.py
│        └─ create_demo_project.py
├─ packages/
│  ├─ ui/
│  └─ config/
├─ test-data/
│  ├─ images/
│  ├─ yolo-valid/
│  ├─ yolo-invalid/
│  └─ models/
└─ scripts/
   ├─ bootstrap.ps1
   ├─ dev.ps1
   ├─ test.ps1
   └─ build.ps1
```

Do not create empty abstraction layers merely to match this tree. Add a directory when its first real implementation is introduced.

---

## 4. Database schema

Use UUID strings as public identifiers. Internal integer primary keys are acceptable, but API responses and exported manifests must use UUIDs. Store all timestamps in UTC.

### 4.1 `projects`

| Column | Type | Rules |
|---|---|---|
| id | UUID/text | primary identifier |
| name | text | required |
| slug | text | unique |
| description | text | nullable |
| storage_root | text | managed path |
| default_annotation_type | text | initially `bbox` |
| created_at | datetime | required |
| updated_at | datetime | required |
| archived_at | datetime | nullable |

### 4.2 `label_classes`

| Column | Type | Rules |
|---|---|---|
| id | UUID/text | primary identifier |
| project_id | FK | required |
| class_index | integer | unique within project |
| name | text | unique within project |
| scientific_name | text | nullable |
| state_name | text | nullable |
| display_color | text | required hex value |
| is_active | boolean | default true |
| created_at | datetime | required |
| updated_at | datetime | required |

Once referenced by an annotation or immutable dataset version, `class_index` may not be changed. A class may be deactivated rather than deleted.

### 4.3 `images`

| Column | Type | Rules |
|---|---|---|
| id | UUID/text | primary identifier |
| project_id | FK | required |
| original_filename | text | required |
| managed_path | text | required |
| thumbnail_path | text | nullable until generated |
| sha256 | text | indexed |
| width_px | integer | greater than zero |
| height_px | integer | greater than zero |
| file_size_bytes | integer | nonnegative |
| media_type | text | required |
| import_source | text | nullable |
| capture_timestamp | datetime | nullable |
| group_key | text | nullable |
| metadata_json | JSON/text | default empty object |
| annotation_status | enum | `unannotated`, `in_progress`, `annotated`, `reviewed`, `excluded` |
| created_at | datetime | required |
| updated_at | datetime | required |

A project may reject an exact duplicate based on `(project_id, sha256)` unless the user explicitly imports it as a separate logical image.

`group_key` identifies related images that must remain in the same dataset split. Examples include a source whole-image ID, coral-fragment ID, individual specimen ID, dive ID, or video ID.

### 4.4 `annotations`

Coordinates are stored in absolute source-image pixels.

| Column | Type | Rules |
|---|---|---|
| id | UUID/text | primary identifier |
| image_id | FK | required |
| label_class_id | FK | required |
| x_min | float | `0 <= x_min < x_max <= image width` |
| y_min | float | `0 <= y_min < y_max <= image height` |
| x_max | float | bounded |
| y_max | float | bounded |
| source_type | enum | `human`, `accepted_prediction`, `imported` |
| source_model_id | FK | nullable |
| source_prediction_id | FK | nullable |
| created_by | text | default `local_user` |
| created_at | datetime | required |
| updated_at | datetime | required |
| deleted_at | datetime | nullable soft delete |
| revision | integer | incremented on updates |

Do not store YOLO-normalized values as the canonical representation. Convert only at import and export boundaries.

### 4.5 `annotation_events`

Append-only history for audit and recovery.

| Column | Type | Rules |
|---|---|---|
| id | UUID/text | primary identifier |
| annotation_id | UUID/text | may refer to deleted annotation |
| image_id | FK | required |
| event_type | enum | `created`, `updated`, `class_changed`, `deleted`, `restored` |
| before_json | JSON/text | nullable |
| after_json | JSON/text | nullable |
| actor | text | required |
| created_at | datetime | required |

Normal undo and redo can be kept in frontend session state, but committed changes must produce events.

### 4.6 `models`

| Column | Type | Rules |
|---|---|---|
| id | UUID/text | primary identifier |
| project_id | FK | nullable for globally registered model |
| name | text | required |
| framework | text | e.g. `ultralytics` |
| task_type | text | initially `object_detection` |
| checkpoint_path | text | required |
| checkpoint_sha256 | text | required |
| class_map_json | JSON/text | required |
| metadata_json | JSON/text | default empty object |
| created_at | datetime | required |

### 4.7 `jobs`

| Column | Type | Rules |
|---|---|---|
| id | UUID/text | primary identifier |
| project_id | FK | required |
| job_type | enum | `thumbnail`, `import`, `inference`, `export`, `qc` |
| status | enum | `queued`, `running`, `succeeded`, `failed`, `cancel_requested`, `cancelled` |
| progress_current | integer | default 0 |
| progress_total | integer | default 0 |
| request_json | JSON/text | required |
| result_json | JSON/text | nullable |
| error_message | text | nullable |
| created_at | datetime | required |
| started_at | datetime | nullable |
| completed_at | datetime | nullable |

### 4.8 `predictions`

Predictions are not annotations.

| Column | Type | Rules |
|---|---|---|
| id | UUID/text | primary identifier |
| job_id | FK | required |
| model_id | FK | required |
| image_id | FK | required |
| predicted_class_index | integer | required |
| mapped_label_class_id | FK | nullable when class cannot be mapped |
| confidence | float | between 0 and 1 |
| x_min | float | source-image pixels |
| y_min | float | source-image pixels |
| x_max | float | source-image pixels |
| y_max | float | source-image pixels |
| review_status | enum | `pending`, `accepted`, `edited_and_accepted`, `rejected` |
| accepted_annotation_id | FK | nullable |
| reviewed_at | datetime | nullable |
| created_at | datetime | required |

### 4.9 `dataset_versions`

| Column | Type | Rules |
|---|---|---|
| id | UUID/text | primary identifier |
| project_id | FK | required |
| version_number | integer | unique per project |
| name | text | required |
| notes | text | nullable |
| parent_version_id | FK | nullable |
| class_map_json | JSON/text | immutable |
| manifest_sha256 | text | required after snapshot |
| created_at | datetime | required |

### 4.10 `dataset_version_items`

This table freezes image membership, split, and annotation content.

| Column | Type | Rules |
|---|---|---|
| id | UUID/text | primary identifier |
| dataset_version_id | FK | required |
| image_id | FK | required |
| image_sha256 | text | frozen |
| split | enum | `train`, `val`, `test`, `unspecified` |
| group_key | text | nullable |
| annotation_snapshot_json | JSON/text | frozen list |
| annotation_count | integer | required |

The unique constraint is `(dataset_version_id, image_id)`.

### 4.11 `exports`

| Column | Type | Rules |
|---|---|---|
| id | UUID/text | primary identifier |
| project_id | FK | required |
| dataset_version_id | FK | nullable |
| format | text | initially `yolo_detection` |
| output_path | text | required |
| manifest_path | text | required |
| request_json | JSON/text | required |
| status | enum | required |
| created_at | datetime | required |
| completed_at | datetime | nullable |

---

## 5. Annotation and interchange schemas

### 5.1 Canonical API annotation

```json
{
  "id": "ann_uuid",
  "image_id": "image_uuid",
  "label_class_id": "class_uuid",
  "geometry": {
    "type": "bbox",
    "x_min": 154.25,
    "y_min": 82.0,
    "x_max": 207.75,
    "y_max": 141.5
  },
  "source": {
    "type": "human",
    "model_id": null,
    "prediction_id": null
  },
  "revision": 3,
  "created_at": "2026-07-08T01:00:00Z",
  "updated_at": "2026-07-08T01:03:00Z"
}
```

### 5.2 Validation rules

- Coordinates refer to the original image dimensions.
- Zero-area and negative-area boxes are invalid.
- Boxes must remain within image boundaries.
- The minimum default box size is 2 by 2 pixels, configurable later.
- Floating-point coordinates are accepted internally.
- Importers may clamp very small floating-point boundary errors only within a documented tolerance.
- A label class must belong to the same project as the image.
- Updates require the latest `revision`; stale updates receive HTTP 409 to prevent silent overwrites.

### 5.3 Batch-save request

```json
{
  "image_id": "image_uuid",
  "base_image_revision": 12,
  "operations": [
    {
      "operation": "create",
      "client_id": "temporary-client-id",
      "annotation": {
        "label_class_id": "class_uuid",
        "geometry": {
          "type": "bbox",
          "x_min": 10,
          "y_min": 20,
          "x_max": 35,
          "y_max": 55
        }
      }
    },
    {
      "operation": "update",
      "annotation_id": "ann_uuid",
      "expected_revision": 3,
      "changes": {
        "geometry": {
          "type": "bbox",
          "x_min": 11,
          "y_min": 21,
          "x_max": 36,
          "y_max": 56
        }
      }
    },
    {
      "operation": "delete",
      "annotation_id": "another_ann_uuid",
      "expected_revision": 1
    }
  ]
}
```

The backend applies the batch transactionally: either every valid operation commits, or none commits.

### 5.4 YOLO detection conversion

For image width `W` and height `H`:

```text
x_center = ((x_min + x_max) / 2) / W
y_center = ((y_min + y_max) / 2) / H
box_width = (x_max - x_min) / W
box_height = (y_max - y_min) / H
```

Each exported row is:

```text
<class_index> <x_center> <y_center> <box_width> <box_height>
```

Use sufficient decimal precision to prevent meaningful coordinate drift. Import-export round trips must remain within 0.5 source-image pixels per edge.

### 5.5 Dataset manifest

Each export must include `reefvision-manifest.json`:

```json
{
  "schema_version": "1.0",
  "reefvision_version": "0.1.0",
  "project_id": "project_uuid",
  "dataset_version_id": "version_uuid",
  "created_at": "2026-07-08T01:00:00Z",
  "format": "yolo_detection",
  "class_map": {
    "0": "Muricea Closed",
    "1": "Thesea Closed"
  },
  "split": {
    "strategy": "group_aware_random",
    "seed": 42,
    "ratios": {
      "train": 0.7,
      "val": 0.2,
      "test": 0.1
    },
    "group_key_field": "group_key"
  },
  "images": [
    {
      "image_id": "image_uuid",
      "sha256": "hex_digest",
      "relative_path": "images/train/example.jpg",
      "split": "train",
      "group_key": "source_image_001",
      "annotation_count": 224
    }
  ]
}
```

---

## 6. API surface for the initial release

Use `/api/v1`.

### Projects and classes

- `POST /projects`
- `GET /projects`
- `GET /projects/{project_id}`
- `PATCH /projects/{project_id}`
- `POST /projects/{project_id}/archive`
- `GET /projects/{project_id}/classes`
- `POST /projects/{project_id}/classes`
- `PATCH /classes/{class_id}`
- `POST /classes/{class_id}/deactivate`

### Images

- `POST /projects/{project_id}/imports/images`
- `GET /projects/{project_id}/images`
- `GET /images/{image_id}`
- `GET /images/{image_id}/content`
- `GET /images/{image_id}/thumbnail`
- `PATCH /images/{image_id}`
- `POST /images/{image_id}/exclude`

### Annotations

- `GET /images/{image_id}/annotations`
- `POST /images/{image_id}/annotations/batch`
- `GET /images/{image_id}/annotation-events`

### YOLO

- `POST /projects/{project_id}/imports/yolo/validate`
- `POST /projects/{project_id}/imports/yolo/commit`
- `POST /projects/{project_id}/exports/yolo`

### Models and predictions

- `POST /projects/{project_id}/models`
- `GET /projects/{project_id}/models`
- `POST /projects/{project_id}/prediction-jobs`
- `GET /jobs/{job_id}`
- `POST /jobs/{job_id}/cancel`
- `GET /images/{image_id}/predictions`
- `POST /predictions/{prediction_id}/accept`
- `POST /predictions/{prediction_id}/reject`
- `POST /predictions/bulk-review`

### Versions and quality control

- `POST /projects/{project_id}/dataset-versions`
- `GET /projects/{project_id}/dataset-versions`
- `GET /dataset-versions/{version_id}`
- `POST /projects/{project_id}/quality-control`
- `GET /jobs/{job_id}/quality-control-report`

---

## 7. Codex execution rules

Codex must follow these rules for every milestone:

1. Read `AGENTS.md` and this specification before editing.
2. Inspect the current repository and report discrepancies between the repository and specification.
3. Work on one milestone per branch or pull request.
4. Before implementation, write a concise plan listing files to add or change.
5. Add or update tests in the same change as production code.
6. Add an Alembic migration for every database change.
7. Never edit a previously applied migration.
8. Never overwrite source images or user-selected export directories without explicit conflict handling.
9. Keep model predictions separate from approved annotations.
10. Keep canonical bounding-box coordinates in source-image pixels.
11. Do not add cloud services, authentication, Docker-only requirements, or distributed queues during version 0.1.
12. Do not introduce an abstraction unless it is used by the current milestone or clearly required by the next committed interface.
13. Run formatting, type checking, unit tests, integration tests, and relevant end-to-end tests before declaring the milestone complete.
14. Report:
    - files changed;
    - migrations added;
    - tests run and results;
    - unresolved issues;
    - manual verification steps.
15. Do not begin the next milestone until the current acceptance tests pass.

---

## 8. Milestone-by-milestone implementation plan

## Milestone 0 — Repository foundation

### Objective

Create a reproducible monorepo with the frontend, backend, database migration system, tests, and Windows scripts.

### Codex implementation instructions

1. Create the repository structure required for the initial apps.
2. Configure Python dependencies and development tooling.
3. Configure the React/Vite/TypeScript frontend.
4. Add FastAPI with `/api/v1/health`.
5. Add SQLAlchemy session management and an empty initial Alembic migration.
6. Add CORS configuration restricted to the local development frontend.
7. Add root scripts for install, development, test, lint, type check, and build.
8. Add a deterministic test configuration using a temporary SQLite database.
9. Add CI configuration that runs backend and frontend tests.
10. Write setup instructions for Windows PowerShell.
11. Add architecture decision records for local-first storage and prediction separation.

### Acceptance tests

- A clean checkout can be bootstrapped using documented commands.
- `GET /api/v1/health` returns HTTP 200 and a version field.
- Backend formatting, linting, mypy, and pytest pass.
- Frontend formatting, TypeScript checking, and Vitest pass.
- The frontend loads and displays API health status.
- Alembic can upgrade a blank database to `head` and downgrade to base.
- Tests do not write to the user's real ReefVision data directory.
- No production feature beyond foundation scaffolding is included.

---

## Milestone 1 — Projects, classes, and managed storage

### Objective

Allow creation and retrieval of projects and label classes, including the octocoral template.

### Codex implementation instructions

1. Implement `projects` and `label_classes` tables and migrations.
2. Implement safe project storage-root creation.
3. Add project CRUD endpoints, using archive rather than immediate deletion.
4. Add class creation, update, ordering, and deactivation endpoints.
5. Enforce unique class index and class name within a project.
6. Prevent class-index changes after the class is referenced.
7. Add the built-in six-class octocoral template.
8. Build the project dashboard and project-creation dialog.
9. Build the class-management screen.
10. Add API, service, and end-to-end tests.

### Acceptance tests

- A blank project can be created and reopened after application restart.
- The octocoral template creates exactly the six specified classes and indices.
- Duplicate project slugs are rejected or deterministically disambiguated.
- Duplicate class names or indices in one project are rejected.
- The same class name may exist in separate projects.
- Archiving a project removes it from the default dashboard but does not delete its files.
- Path traversal such as `../` cannot escape the configured ReefVision data root.
- Project and class screens survive a browser refresh without losing data.

---

## Milestone 2 — Image import and gallery

### Objective

Import images safely, generate thumbnails, and provide a searchable paginated gallery.

### Codex implementation instructions

1. Add the `images` and `jobs` tables.
2. Implement file validation for JPEG, PNG, TIFF, and WebP.
3. Compute SHA-256, dimensions, file size, and available metadata.
4. Implement managed-copy import first. Leave external-link import for later.
5. Detect project-level duplicates before copying.
6. Use atomic copy operations and cleanup partial files on failure.
7. Generate thumbnails in background jobs.
8. Add an import report with successful, duplicate, unsupported, and failed files.
9. Implement paginated image-list endpoints with filters for filename, annotation status, and group key.
10. Build the gallery with thumbnail, filename, dimensions, status, and annotation count placeholders.
11. Allow setting and editing `group_key`.
12. Include fixture images and tests for corrupted and duplicate files.

### Acceptance tests

- Importing ten valid images produces ten database records and managed files.
- Importing one of those images again reports a duplicate and does not create an unnoticed second copy.
- A corrupted image is reported as failed without aborting valid files in the same import.
- Original source files remain unchanged.
- Thumbnail failure does not invalidate the original image record and can be retried.
- Gallery pagination returns stable results.
- Filename, status, and group-key filters work.
- The gallery remains usable when a thumbnail is missing.
- Restarting the API does not lose job or image records.

---

## Milestone 3 — Manual bounding-box annotation

### Objective

Deliver the first scientifically usable annotation editor.

### Codex implementation instructions

1. Add `annotations` and `annotation_events` tables.
2. Add image-level annotation revision tracking.
3. Implement transactional annotation batch-save.
4. Return HTTP 409 for stale revision updates.
5. Build a full-screen editor using the original image dimensions as the coordinate system.
6. Implement:
   - pan;
   - zoom centered near cursor;
   - fit-to-screen;
   - draw box;
   - select one or multiple boxes;
   - move;
   - resize;
   - change class;
   - delete;
   - undo;
   - redo;
   - next and previous image;
   - class keyboard shortcuts.
7. Distinguish selected, unselected, and hidden classes.
8. Add debounced autosave plus an explicit save-state indicator.
9. Preserve unsaved operations locally until the server confirms success.
10. Support at least 1,500 displayed boxes using rendering optimizations.
11. Add annotation counts by class and image status controls.
12. Add unit tests for coordinate transforms and end-to-end editor tests.

### Recommended initial shortcuts

- `1`–`9`: choose class.
- `B`: box tool.
- `V`: select tool.
- `Delete` or `Backspace`: delete selection.
- `Ctrl+Z`: undo.
- `Ctrl+Shift+Z` or `Ctrl+Y`: redo.
- `F`: fit image.
- `A`: previous image.
- `D`: next image.
- `[` and `]`: decrease or increase box-outline visibility.
- `H`: hide or show annotations.

Shortcuts must not trigger while typing in a text field.

### Acceptance tests

- A box drawn at any zoom level saves with correct source-image coordinates.
- Reloading the browser returns the box in the same location.
- Moving, resizing, reclassifying, and deleting a box persist.
- Undo and redo work before autosave and do not corrupt server state.
- Two stale editor sessions cannot silently overwrite one another.
- A failed save produces a visible error and retains the unsaved operation for retry.
- Boxes cannot be saved outside image boundaries.
- Zero-area boxes are rejected.
- 1,500 fixture boxes can be rendered, zoomed, and selected without browser failure.
- Annotation events record create, update, class-change, and delete operations.
- Image annotation status can be changed and persists.

---

## Milestone 4 — YOLO import and export

### Objective

Make ReefVision interoperable with existing YOLO detection datasets.

### Codex implementation instructions

1. Implement a two-stage YOLO import: validate, then commit.
2. Support loading from `data.yaml` and explicit image/label directories.
3. Parse class names from list or indexed mapping forms.
4. Validate each label row:
   - five fields;
   - integer class index;
   - finite numeric coordinates;
   - normalized values within valid bounds;
   - nonzero width and height;
   - class index exists.
5. Match images and label files deterministically.
6. Treat missing label files as configurable: background image or validation warning.
7. Produce a machine-readable and human-readable validation report.
8. Commit valid imports transactionally in manageable batches.
9. Implement YOLO export from current annotations and immutable dataset versions.
10. Include `data.yaml`, labels, images, and `reefvision-manifest.json`.
11. Support copy mode first; optional hard-link mode may be added only with safe fallback.
12. Add round-trip tests.

### Acceptance tests

- A valid fixture dataset imports with correct images, classes, and boxes.
- Malformed rows are reported with filename and line number.
- Unknown class IDs prevent commit unless explicitly resolved.
- Importing and exporting a fixture dataset preserves every box edge within 0.5 source-image pixels.
- Empty-label/background images remain represented.
- Export never modifies project-managed originals.
- `data.yaml` paths are valid relative paths within the export.
- An export is reproducible from the same immutable dataset version.
- The manifest contains checksums, class map, image membership, and annotation counts.
- A cancelled or failed export does not leave a directory that appears complete.

---

## Milestone 5 — Model registry, inference jobs, and prediction review

### Objective

Run local object-detection inference and turn selected predictions into reviewed annotations.

### Codex implementation instructions

1. Add `models`, `jobs`, and `predictions` persistence.
2. Define a `DetectorAdapter` protocol with:
   - model loading;
   - model metadata inspection;
   - class-map retrieval;
   - batch prediction;
   - cancellation checks;
   - normalized result conversion into source-image pixel boxes.
3. Implement the first Ultralytics-compatible adapter without leaking framework objects outside the adapter.
4. Validate model checkpoint existence and compute checksum during registration.
5. Require explicit mapping from model class indices to project classes.
6. Implement queued inference jobs with status and progress.
7. Store prediction parameters including confidence threshold, NMS IoU, image size, maximum detections, and device request.
8. Store raw accepted result metadata needed for provenance.
9. Overlay predictions separately from annotations.
10. Implement accept, edit-and-accept, reject, and bulk review.
11. Converting a prediction to an annotation must be transactional and idempotent.
12. Add recovery behavior for a worker that exits during a job.
13. Add a fake detector adapter for deterministic tests.

### Acceptance tests

- A fake model can generate deterministic predictions for fixture images.
- Prediction creation does not change verified annotation counts.
- Accepting one prediction creates exactly one annotation linked to that prediction.
- Repeating an accept request does not create a duplicate annotation.
- Edited-and-accepted geometry is stored as the approved annotation geometry.
- Rejected predictions remain rejected after restart.
- Model and job provenance appear in accepted annotations and exports.
- A missing or incompatible checkpoint produces a clear failed job rather than crashing the API.
- Job progress updates and cancellation work between images.
- Pending predictions are visually distinguishable from verified annotations.
- Bulk acceptance requires an explicit threshold and confirmation.

---

## Milestone 6 — Dataset versions and leakage-aware splits

### Objective

Create immutable, reproducible snapshots and group-aware train/validation/test splits.

### Codex implementation instructions

1. Add `dataset_versions`, `dataset_version_items`, and `exports`.
2. Build a snapshot service that freezes:
   - image checksum;
   - class map;
   - annotation JSON;
   - group key;
   - split;
   - annotation counts.
3. Generate sequential project version numbers.
4. Support:
   - manual split assignment;
   - seeded random split;
   - seeded group-aware random split.
5. Default to group-aware splitting when any selected image has a group key.
6. Prevent one non-null group key from appearing in multiple splits.
7. Warn when requested ratios cannot be closely achieved because of group sizes.
8. Compute and store a canonical manifest checksum.
9. Build a version-comparison view showing image and annotation-count changes.
10. Export directly from a selected immutable version.

### Acceptance tests

- Creating version 1 and then editing working annotations does not change version 1.
- The same seed, image set, ratios, and group keys produce the same split.
- No group crosses train, validation, and test.
- A different seed may produce a different valid split.
- Split totals and per-class counts are shown before version creation.
- Ratio deviations caused by groups are reported.
- Version manifests have stable checksums for identical content.
- Exports from an old version remain unchanged after current-project edits.
- Version comparison correctly reports added, removed, and changed images and annotations.

---

## Milestone 7 — Quality control and active-learning queue

### Objective

Identify annotation problems and prioritize images that most need human review.

### Codex implementation instructions

1. Implement a background QC job that checks:
   - invalid or tiny boxes;
   - boxes touching image boundaries;
   - exact duplicate boxes;
   - highly overlapping same-class boxes;
   - unusually high or low annotation counts;
   - images marked reviewed with zero annotations;
   - unmapped model predictions;
   - class imbalance summaries.
2. Build a QC report with links back to affected images.
3. Implement an active-learning scoring interface independent of a specific model framework.
4. Initial queue signals:
   - low mean prediction confidence;
   - many pending predictions;
   - disagreement between model count and verified count;
   - image not yet reviewed;
   - optional class-rarity weighting.
5. Store the scoring formula and input values so ranking is explainable.
6. Allow users to generate and save a review queue.
7. Do not claim uncertainty calibration; call these prioritization scores.
8. Add deterministic tests for QC and ranking.

### Acceptance tests

- Fixture duplicate and out-of-bounds boxes are detected.
- Every QC issue includes project, image, rule ID, severity, and explanation.
- Clicking a report item opens the correct image.
- Re-running QC after correction resolves the issue.
- Active-learning rankings are deterministic for identical inputs.
- Each ranked image shows the factors contributing to its score.
- The queue never automatically changes verified annotations.
- Images can be marked reviewed directly from the queue.

---

## Milestone 8 — Packaging, backup, and release candidate

### Objective

Produce a stable local release that another Windows user can install and evaluate.

### Codex implementation instructions

1. Add a production frontend build served by the local backend or launcher.
2. Add a Windows launcher and documented data-directory behavior.
3. Add database and project backup:
   - pause or coordinate writes;
   - copy database;
   - copy or verify managed assets;
   - produce backup manifest and checksums.
4. Add restore validation without overwriting the current data directory by default.
5. Add application-level error logging with paths scrubbed where appropriate.
6. Add version display and database-schema compatibility checks.
7. Create a demo project with small non-sensitive fixture images.
8. Run the complete test suite and a scripted smoke test.
9. Write user documentation for project creation, annotation, YOLO import/export, inference, versions, and recovery.
10. Tag the release only after all acceptance tests pass.

### Acceptance tests

- A release build starts without Node or a Python development environment exposed to the user, or the limitation is explicitly documented for the release candidate.
- Existing projects reopen after upgrading from the prior milestone database.
- Backup and restore reproduce project, image, class, annotation, version, and model metadata.
- Restore detects missing or checksum-mismatched assets.
- The application refuses to open a database created by an unsupported newer schema without making changes.
- A clean Windows test environment completes the documented smoke workflow.
- The demo workflow covers project creation, import, manual annotation, export, prediction review, and version creation.
- No test or demo path points to a developer-specific drive.

---

## 9. Future milestones after version 0.1

These should remain separate proposals:

### Segmentation

Add polygon and mask schemas, COCO import/export, and model adapters.

### Video and fish tracking

Add video ingestion, frame extraction, detections, track IDs, trajectories, calibration, and export. Do not model video as a collection of unrelated images; introduce explicit video and frame entities.

### Training management

Add local model-training configurations, run metrics, artifact registration, and comparison only after dataset versioning is stable.

### Photogrammetry integration

Link annotations to 3D assets or surface-area measurements without embedding photogrammetry processing into the core annotation editor.

### Collaboration

Add users, roles, assignment, consensus annotations, and audit identities only when local single-user reliability is established.

---

## 10. Definition of done for every milestone

A milestone is complete only when:

- All listed acceptance tests pass.
- Production code and tests are committed together.
- Database migrations upgrade and downgrade correctly.
- Public API changes are documented.
- User-visible behavior is documented.
- No high-severity lint, type, or security findings remain.
- The application can reopen existing milestone data.
- Codex reports any deviation from this specification.
- A human can complete the milestone's primary workflow through the interface.
