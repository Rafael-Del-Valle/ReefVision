# ReefVision Data Model

## Foundational entities

### Projects

A project is the root container for research images, annotation classes, models, dataset versions, and derived exports. Public IDs are UUID strings. The stored `storage_root` is relative to the configured ReefVision data directory so a project can be moved or backed up without embedding a machine-specific absolute path.

Projects are archived instead of deleted. Archiving does not remove their database records or managed files.

### Label classes

Label classes belong to exactly one project. Both `class_index` and `name` are unique within that project. The class index is the stable external identifier used by YOLO imports and exports. `display_order` controls interface ordering without changing that stable index.

Classes are deactivated instead of deleted so future annotation and dataset lineage cannot be silently invalidated.

## Current operational entities

### Images

An image belongs to one project and stores its managed original path, SHA-256 checksum, dimensions, mutable image-level `annotation_status`, and optional `group_key`. Source-image pixel coordinates are the canonical geometry system for current and frozen image annotations.

### Annotations

Current verified annotations store canonical source-pixel bounding boxes linked to an image and
label class. Mask annotations preserve editable polygons or source-aligned raster masks alongside
their derived boxes. Annotation events preserve change history, while each annotation row tracks
the latest geometry, provenance, soft-delete state, and revision.

Prompt-assisted candidates remain unverified until explicit acceptance. Acceptance preserves the
native editable mask where available and records the provider, checkpoint checksum, prompts,
candidate ranking, accepted geometry, and any originating proposal.

### Dataset versions

`dataset_versions` stores project-local sequential version numbers plus immutable snapshot metadata for one version:

- requested and resolved split methods;
- eligible image statuses;
- requested and achieved split ratios;
- optional parent-version linkage;
- warning text;
- frozen class map;
- manifest checksum;
- total image and annotation counts.

### Dataset-version items

`dataset_version_items` freezes one image membership record inside a dataset version:

- original filename and image checksum;
- frozen image dimensions and image-level annotation status;
- split assignment and group key;
- full annotation snapshot JSON for active annotations;
- per-class counts for that image;
- stable snapshot checksum.

### Exports

`exports` stores derived artifact metadata for immutable-version exports. Each export records:

- the source dataset version;
- the queued background job ID;
- managed relative paths for the export directory, export manifest, and zip archive;
- status and error state;
- request and result metadata.

### Quality-control runs

`quality_control_runs` stores one historical QC execution for a project or dataset version. Each run preserves:

- the scope type and optional dataset-version linkage;
- the background job ID when execution is queued;
- selected rule categories and explicit rule IDs;
- threshold configuration and ruleset metadata;
- practical input checksums;
- summary counts, timestamps, status, cancellation state, and error text.

Runs are append-only historical records. Re-running after a correction creates a new run instead of rewriting the old one.

### Quality-control issues

`quality_control_issues` stores the findings emitted by one QC run. Each issue records:

- the parent run ID plus project and optional dataset-version scope;
- optional image, annotation, prediction, and class linkage;
- rule ID, rule version, severity, and fingerprint;
- title, explanation, measured values, and thresholds;
- status and lifecycle metadata for acknowledgement, dismissal, or later resolution.

Issue status is separate from annotation state. Viewing an issue does not resolve it, and correcting the underlying data only changes future runs.

### Review queues

`review_queues` stores one persisted prioritization run for a project or dataset version. Each queue records:

- the scope and optional dataset-version linkage;
- the selected source QC run, if any;
- the deterministic formula ID and version;
- weight configuration, ruleset metadata, and input checksums;
- summary statistics, completion timestamp, and any error message.

### Review-queue items

`review_queue_items` stores the ranked images for one queue. Each item records:

- the linked queue, project, optional dataset version, and image;
- split metadata where available;
- current workflow state (`pending`, `in_progress`, `completed`, `skipped`);
- final score, rank position, and highest related QC severity;
- related class IDs, model IDs, and QC issue IDs;
- raw and normalized signal values, weights, score breakdown, reason summary, and input checksum;
- workflow timestamps plus an optional skip reason.

### Model registrations

`model_registrations` remains the project-scoped local checkpoint registry. The current schema stores purpose, provider, framework, task, class-map metadata, input-size metadata, and freeform model metadata JSON. ReefVision now complements those rows with a separate provider-hub API so architecture family, runtime availability, and blocked provider states do not have to be inferred from one checkpoint row alone.

### Provider model assets and acceptance records

`provider_model_assets` is the restart-safe, project-independent lifecycle registry for managed and
trusted external checkpoints. It stores provider and model identity, architecture, task,
capabilities, checkpoint verification metadata, dependency/device requirements, state, health
results, and last successful load/inference timestamps. A trusted external registration keeps its
absolute source path and does not imply an import into managed storage.

`provider_acceptance_records` is append-only evidence from deterministic software acceptance. Each
row records the provider/model/checksum, device and runtime versions, load/inference/unload result,
execution time, optional peak memory, warnings, failure, test input, and timestamp. These rows do
not assert coral or fish accuracy.

### Image embeddings and active-learning cycles

`image_embeddings` stores image- or crop-level feature vectors under a versioned embedding key.
The key incorporates provider, model, checkpoint checksum, preprocessing, source-image checksum,
crop, dimension, and normalization so a new model or changed source cannot silently replace an
older vector.

Active-learning queue revisions preserve selection configuration, embedding identity, input
checksums, explanations, manual includes/excludes, duplicate decisions, and promotion linkage.
`active_learning_cycles` links the source model, embedding model, selected/reviewed image IDs,
accepted/rejected records, immutable dataset version, optional training run, candidate/result
model, compatible evaluation summaries, warnings, status history, and timestamps.

## Current relationships

```text
Project 1 --- * LabelClass
Project 1 --- * Image
Project 1 --- * DatasetVersion
Project 1 --- * Export
Project 1 --- * QualityControlRun
Project 1 --- * ReviewQueue
Image 1 --- * Annotation
Image 1 --- * QualityControlIssue
Image 1 --- * ReviewQueueItem
DatasetVersion 1 --- * DatasetVersionItem
DatasetVersion 1 --- * Export
DatasetVersion 1 --- * QualityControlRun (optional scope)
DatasetVersion 1 --- * ReviewQueue (optional scope)
QualityControlRun 1 --- * QualityControlIssue
ReviewQueue 1 --- * ReviewQueueItem
Image 1 --- * ImageEmbedding
ReviewQueue 0..1 --- 1 ActiveLearningCycle
DatasetVersion 0..1 --- * ActiveLearningCycle
ProviderModelAsset 1 --- * ProviderAcceptanceRecord
```

Deleting a project at the database level cascades to dependent rows, but the public application API currently exposes archive-only behavior rather than destructive deletion.
