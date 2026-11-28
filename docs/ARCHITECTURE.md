# ReefVision Architecture

## Current architecture

ReefVision uses a React/TypeScript frontend and a FastAPI/Python backend. The backend owns persistence, validation, managed paths, and domain rules. SQLite is the initial database and Alembic owns schema migration history.

```text
Browser -> React/Vite -> HTTP /api/v1 -> FastAPI routes
                                      -> services
                                      -> repositories -> SQLite
                                      -> storage -> managed local directories
```

Each FastAPI application instance owns its configured SQLAlchemy engine and session factory. This prevents development, testing, and alternate data roots from accidentally sharing a global database connection.

## Dependency direction

- API routes depend on schemas and services.
- Services coordinate repositories, domain templates, transactions, and storage operations.
- Repositories contain SQLAlchemy queries.
- Storage modules are the only place that resolves managed filesystem paths.
- Domain code does not depend on FastAPI.
- The frontend is not the sole enforcer of persistence or validation rules.

## Managed project storage

Project directories are created as:

```text
<REEFVISION_DATA_DIR>/projects/<project-uuid>/
```

The database stores `projects/<project-uuid>` rather than an absolute path. Resolution verifies that the resulting path remains beneath the configured data root.

## Stable classes

`class_index` is intentionally separate from `display_order`. A researcher can rearrange the interface without changing YOLO class identities. Classes are deactivated rather than removed.

## Configuration

Configuration is read from `REEFVISION_*` environment variables. Development defaults use `.reefvision` beneath the current repository. Tests override all paths with temporary directories.

### Local checkpoint approval

Model Hub asks the researcher to approve the source of each legacy PyTorch checkpoint. A client posting to `/api/v1/projects/{project_id}/models/register` supplies the multipart field `trust_checkpoint=true` after confirmation. ReefVision records the source decision and SHA-256 with the registration. The native ReefPose reader enforces weights-only loading. Transformer archives containing only safetensors weights also support registration without pickle approval.

With `REEFVISION_ALLOW_UNSAFE_PICKLED_MODELS` unset, completed local training jobs can register their own checksummed outputs. An older or exchanged run can return HTTP 409 with `checkpoint_approval_required`, the filename and the SHA-256. Approve the exact file by resubmitting `approved_checkpoint_sha256` to the same register-from-run route. Explicit `false` disables unrestricted checkpoint loading even after approval. Explicit `true` retains the previous trusted-environment policy.

After a transfer or restore without this device's approval record, open **Model Hub > Registered Models > Review checkpoint trust**. Compare the filename, source and full SHA-256, then approve the checkpoint on the device. The local API verifies project ownership, bytes and size before recording the decision outside project storage. The `POST /api/v1/projects/{project_id}/models/{model_id}/approve-checkpoint` request accepts the reviewed `sha256`. Project Exchange carries historical provenance while the new model identity requires its own execution approval.

## Runtime model

For development:

1. The React development server runs separately.
2. FastAPI runs on localhost.
3. The frontend communicates with the API through generated or typed API clients.
4. A background worker process claims queued jobs from the database.

For the packaged desktop build:

1. Tauri bundles the compiled React/Vite frontend assets.
2. The Rust desktop shell starts the FastAPI backend as a local sidecar executable.
3. The packaged backend runs Alembic migrations against the user data directory before serving requests.
4. The frontend asks Tauri for the runtime API base URL before React renders, so the same UI can run in a browser or in the desktop shell.
5. Desktop data is stored beneath the operating system application-data directory instead of the repository-local `.reefvision` development default.

Later milestones add image-managed storage and a separate local worker. Framework-specific machine-learning code must remain behind adapter interfaces.

## Model-provider hub

The current provider layer now separates provider identity, capability reporting, and runtime availability from the specific routes or React components that consume those providers.

```text
Model Hub UI -> /api/v1/model-providers
             -> /api/v1/runtime-providers/status
             -> provider hub
             -> provider preflight + provider factories
             -> concrete detection or assist adapters
```

The provider hub owns:

- stable provider IDs;
- capability matrices;
- runtime backend status reporting;
- registerable versus blocked provider states;
- centralized provider factories for model registration, inference, and assist-session loading.

This keeps ReefVision operational when future provider families remain unimplemented or require optional packs.

### Inspect-only local provider manifests

The 1.5 provider-foundation slice adds a deliberately non-executable discovery boundary. ReefVision scans direct JSON files beneath `<data_dir>/provider-manifests`, validates them against a strict schema, records their source digest, and exposes both valid and invalid records in **Models & AI → Providers**.

```text
provider-manifests/*.json
  -> strict bounded JSON reader
  -> manifest or isolated discovery error
  -> provider catalog API
  -> Providers workspace
  -> metadata-only Workflow Builder snapshot
```

Discovery never imports Python modules, resolves entry points, launches commands, installs packages, or loads model code. Local records therefore cannot use inference routes; their preflight response is explicitly blocked. The Workflow Builder node copies validated metadata and the source digest into an artifact so a scientific workflow can cite the manifest without granting it execution authority. Executable plugins, permission handling, lifecycle management, and a stable SDK remain separate 2.0 work.

## Dataset-version subsystem

Milestone 6 adds an immutable dataset-version service layer that snapshots eligible images, active annotations, class-map metadata, split assignments, and a canonical manifest checksum into dedicated database tables. The snapshot is stored in the database rather than derived lazily from mutable current annotations.

```text
Browser Versions tab -> /api/v1/projects/{id}/dataset-version-previews
                     -> /api/v1/projects/{id}/dataset-versions
                     -> dataset version service
                     -> dataset_version* tables
                     -> export jobs -> storage/datasets.py -> managed export artifacts
```

Exports are queued as background jobs. The worker reads immutable `dataset_version_items`, copies the managed source images into a derived export directory, writes YOLO label files from the frozen annotation JSON, emits a canonical export manifest, and zips the artifact for download.

## Quality-control subsystem

Milestone 7 adds a versioned quality-control pipeline that evaluates projects or immutable dataset versions without mutating annotations, predictions, or dataset snapshots.

```text
Browser Quality Control tab
  -> /api/v1/projects/{id}/quality-control-runs
  -> /api/v1/dataset-versions/{id}/quality-control-runs
  -> quality-control service
  -> versioned rule registry
  -> quality_control_runs + quality_control_issues
  -> jobs worker for background execution and cancellation
```

The QC service builds an evaluated context from current project records or a dataset-version snapshot, then executes deterministic rule objects that are independent of API routes, repositories, or frontend rendering. Each issue stores its rule ID and version, severity, human-readable explanation, measured values, thresholds, fingerprint, and lifecycle metadata so historical runs remain inspectable even after the project changes.

The worker now understands `qc` jobs alongside imports, thumbnails, inference, and exports. Cancelling a QC job updates both the job record and the corresponding QC run record without rewriting historical findings.

## Review-prioritization subsystem

Milestone 7 also adds an explainable review-queue service for active-learning style ranking without training or automatic annotation changes.

```text
Browser Review Queue tab
  -> /api/v1/projects/{id}/review-queues
  -> /api/v1/dataset-versions/{id}/review-queues
  -> review-queue service
  -> current annotation/prediction state + latest or selected QC run
  -> review_queues + review_queue_items
```

Queue generation is synchronous and deterministic for a fixed scope, ruleset version, weight configuration, and input checksums. The formula stores raw signal values, normalized signal values, weights, score breakdowns, and a per-item checksum so users can inspect exactly why an image was ranked. Ranked items open the annotation editor with contextual highlights and a return path back to the originating QC or review-queue workflow.
