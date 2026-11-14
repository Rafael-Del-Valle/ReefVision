# ReefPose Phase 3B Design

## Intent

Phase 3B turns the existing synchronous, ReefPose-only scientific evaluator into a
recoverable local job that can compare compatible registered pose models on one
immutable scientist-verified holdout. The result must be useful from Model Hub and
Workflow Builder, exportable without reinterpretation, and honest about providers or
metrics that cannot be compared.

## Goals

- Queue evaluation without holding an API request open.
- Persist configuration, progress, cancellation, recovery, partial completed runs,
  warnings, exclusions, errors, and integrity identities in the existing `jobs` table.
- Evaluate one or more schema-compatible ReefPose or Ultralytics pose checkpoints on
  exactly the same frozen dataset.
- Treat unavailable or unsupported SLEAP execution as an explicit per-model exclusion.
- Consolidate completed child evaluation runs into reproducible JSON and CSV reports.
- Add a real Workflow Builder node that invokes the same worker and emits a typed
  comparison artifact.
- Add a dedicated Model Hub comparison panel with progress, metric tables, compact
  per-landmark/error/calibration visualizations, cancellation, and exports.
- Preserve the Phase 3A synchronous API and immutable completed evaluation runs.

## Non-goals

- Installing SLEAP, changing system security, or downloading model weights.
- Multi-animal identity tracking or Phase 4 ID metrics.
- Statistical significance testing or claims of biological validation.
- A distributed queue, new job framework, or an independent annotation/dataset system.
- Resuming inside a partially evaluated model. Recovery resumes at the next model;
  already committed immutable child runs are reused.

## Constraints

- Work only on `feature/reefpose-core` from `50ecd1b2`.
- Preserve existing ReefPose, Ultralytics, SLEAP, schema, training, Model Hub, and
  Workflow contracts.
- Use source-image pixel coordinates and stable landmark identifiers.
- Never register incomplete scientific results as completed evaluation runs.
- Keep framework imports inside ML adapters and optional until execution.
- No new dependency or automatic model download.

## Approaches considered

### 1. Existing `Job` as the comparison aggregate — selected

The queued job request contains the ordered model IDs, dataset ID, thresholds, device,
and a canonical request hash. Its result contains completed evaluation IDs, comparison
rows, exclusions, warnings, integrity hash, and recovery history. This reuses existing
polling, cancellation, retry, and startup recovery without a second lifecycle table.

Tradeoff: comparison identity is a job ID rather than a dedicated domain-table ID. The
job is nevertheless durable and project-scoped, and every scientific child result
remains an immutable `PoseEvaluationRun`.

### 2. New comparison and child-link tables

This gives richer relational queries but duplicates generic job state, requires a new
migration and synchronization rules, and adds little to the current local-first UI.
It is deferred until comparison cohorts need annotations or publication workflow state.

### 3. Browser-orchestrated independent evaluation jobs

This avoids a backend aggregate but cannot enforce a shared dataset/configuration,
cannot recover a comparison atomically, and makes reproducible consolidated export
fragile. It is rejected.

## Backend design

### Submission and duplicate prevention

`POST /projects/{project_id}/pose-evaluation-comparisons` accepts ordered unique model
IDs, one frozen dataset ID, device, PCK/calibration/confidence thresholds, and optional
OKS sigmas. The service validates project ownership, task/provider compatibility,
schema identity, leakage, and checkpoint/dataset metadata before creating a job.

A canonical request hash covers project, sorted model identities and checkpoint hashes,
dataset manifest hash, and scientific configuration. Migration `0040` adds a nullable,
uniquely indexed `jobs.deduplication_key`. Active comparison jobs retain the key;
terminal jobs clear it. Submission first checks for the active job and also handles the
unique-key race, so two concurrent requests cannot launch the same comparison.

### Worker lifecycle

The normal local worker handles `pose_evaluation`. It atomically claims the queued job,
sets progress total to `model_count * dataset_item_count`, and evaluates models in the
requested order. The evaluator accepts cancellation and progress callbacks and commits
only completed immutable child runs. Job result state is updated after each model so an
interruption can reuse child run IDs whose model/checkpoint/dataset/configuration hashes
still match.

Queued jobs cancel immediately. Running jobs cooperatively stop between frames and
models. Startup recovery uses the existing generic requeue behavior. A recovered worker
validates and reuses completed child runs, then continues remaining models. Reuse
requires completed status, exact model/checkpoint SHA and size, dataset ID/manifest SHA,
schema identity, full scientific configuration, and a recomputed immutable result hash.
Failures
retain prior child results and end the aggregate job as failed; explicit incompatibility
is recorded as an exclusion and does not fabricate metrics.

Submission rejects foreign, malformed, duplicate, non-pose, leakage-prone, or
schema-mismatched inputs. A valid registered provider that cannot execute in the current
runtime becomes a structured exclusion. An unexpected error after execution begins fails
the aggregate while preserving completed child runs and a partial report.

### Provider-neutral inference

`reefvision.ml.pose_evaluation` defines a small runtime protocol returning a normalized
single-animal pose: stable landmark ID, name, source-pixel coordinates, confidence,
visibility, bbox, provider/runtime metadata, and resolved device.

- ReefPose wraps `ReefPosePredictor` and checks native anatomy integrity separately
  from the ReefVision source-schema content hash.
- Ultralytics loads an explicitly registered local pose checkpoint, reads keypoints in
  source-image coordinates, and maps positional output through `PoseModelSchemaBinding`
  to the exact bound immutable ReefVision revision. Missing binding, count mismatch, or
  multiple detected animals is incompatible for this single-animal evaluator. Zero
  detections count as localization misses. Visibility metrics are marked unavailable
  because Ultralytics confidence is not silently reinterpreted as ReefVision visibility.
- SLEAP provider ID `sleap_nn` validates its registration and pinned optional runtime.
  The current environment lacks that runtime, so it produces a structured exclusion.
  Real still-frame execution is accepted only when a future/tested adapter can prove the
  same coordinate, identity, and visibility contract; no package is installed in Phase
  3B.

The scientific metric layer remains framework-neutral and unchanged except for any
test-proven alignment or missing-landmark fixes.

### Comparison and export

The comparison result includes child run IDs, model/checkpoint/provider identities,
dataset and schema identities, configuration, denominators, top-level and per-landmark
metrics, runtime, resolved hardware/software provenance, warnings, exclusions, and a
canonical SHA-256 over the report excluding volatile job timestamps.

Metric cells use a structured `{available, value, reason}` representation. Phase 3B also
persists deterministic normalized-error histogram bins, overflow, sample count, and
five-number quantiles so error-distribution and per-landmark views never invent data.
Models with different denominators are flagged rather than silently ranked.

JSON exports the complete report. CSV uses `aggregate`, `landmark`, and `exclusion` row
types with model/checkpoint/provider IDs, availability and reason columns, thresholds,
denominators, runtime, and report hash. Cancelled and failed jobs may export completed
partial results with an explicit terminal status and `partial=true`.

`GET /projects/{project_id}/pose-evaluation-comparisons` provides paginated durable job
discovery after reload. Detail and JSON/CSV export routes are keyed by comparison job ID.

## Workflow Builder

Add `pose_model_evaluation` with:

- input `dataset`: exactly one `pose_training_dataset`;
- input `models`: one or more `model_reference` artifacts with `multiple=True`;
- output `comparison`: one `pose_evaluation_comparison` artifact;
- persisted scientific thresholds, device, and optional OKS sigmas.

The adapter creates a child `pose_evaluation` job carrying `workflow_run_id`, runs the
production worker through the existing child-job mechanism, and emits job ID, child run
IDs, report hash, metrics, warnings, exclusions, and complete provenance. Parent workflow
cancellation propagates through the existing child-job cancellation mechanism using both
`workflow_run_id` and `workflow_node_run_id`. Saved
workflow replay uses the persisted model/dataset artifact identities and fails if their
checksums or schema compatibility changed.

This one node intentionally combines evaluation and comparison. A later report-export
node can consume its typed artifact without rerunning inference.

## Model Hub GUI

The existing ReefPose evaluation card becomes a comparison workspace rather than a new
top-level application. Users select multiple compatible pose models and one unused frozen
dataset, submit the async job, poll the existing job endpoint, cancel while active, and
inspect the consolidated result.

The result view contains:

- status and completed/total progress;
- provider/model/checkpoint identities and exclusions;
- comparative PCK, NME, localization coverage, visibility, latency, and throughput table;
- compact accessible SVG/bar views for per-landmark normalized error, matched-error
  distributions, and calibration threshold precision/recall;
- warnings and scientific limitations;
- JSON and CSV export actions.

Charts show persisted values only. Unsupported metrics display `Not available` with the
recorded reason.

## Error handling and integrity

- Reject schema mismatch, missing stable correspondence, leakage, changed manifests,
  item snapshots, missing or changed source-video bytes, and checkpoints before scoring.
- Reject duplicate model IDs and non-pose registrations.
- Preserve completed child results if a later provider fails.
- Never compare models with different reference denominators silently.
- Keep API errors structured and user-facing job failures concise; detailed causes remain
  in local logs and job result provenance.
- Prevent registered model deletion with a structured conflict while immutable pose
  evaluation runs still reference that model.

## Validation

- Hand-calculated provider-alignment and comparison aggregation tests.
- Async submission, duplicate suppression, progress, cancellation, recovery, partial
  failure, leakage, and export-integrity tests.
- ReefPose and fake Ultralytics adapter tests; SLEAP exclusion tests without installing it.
- Workflow validation, execution, cancellation, artifact, and replay tests.
- Model Hub selection, polling, cancellation, table/chart, exclusion, and export tests.
- Existing synchronous evaluation, Phase 2C, Ultralytics, Workflow, frontend, migration,
  type, lint, and build regressions.
- RTX 3090 execution using the available compatible environment, clearly labeled as a
  synthetic engineering fixture rather than biological validation.
- Logical local commits, roadmap/validation updates, final GUI/GPU evidence, limitations,
  and starting/final commit reporting.

## Phase 4 handoff

After Phase 3B validation, prepare—but do not implement—a design for pose-aware
multi-animal association, stable identities, occlusion/gap handling, IDF1, identity
switches, manual correction, and provenance-aware tracking review.
