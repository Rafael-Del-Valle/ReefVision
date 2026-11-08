# ReefPose Phase 2C Anatomical Skeleton Designer Design

## Intent

Researchers need to define arbitrary animal anatomy, annotate it, freeze verified truth, and train ReefPose without editing JSON or losing landmark identity. Phase 2C extends ReefVision's existing immutable pose schemas, video pose editor, scientist-verification flow, frozen datasets, and native trainer.

## Goals

- Project-scoped named skeleton templates with immutable revisions.
- Stable landmark IDs independent of display names or ordering.
- Descriptions, groups, repeated structures, symmetry, and visual edges.
- A graphical designer integrated with existing pose review controls.
- Annotation observations bound to stable landmark IDs and exact schema revisions.
- Exact schema definitions and hashes retained through dataset freezing, training, registration, and inference.
- Synthetic browser and RTX 3090 evidence without biological accuracy claims.

## Non-goals

- Predefined species or human skeleton catalogs.
- A second annotation or dataset subsystem.
- Multi-animal association, biological validation, or automatic pretrained weights.
- Reinterpreting existing checkpoints after display-name or structural changes.

## Existing foundations

`PoseLandmarkSchema` and `PoseLandmarkSchemaRevision` already provide project identity, immutable revisions, ordering, repeated labels, and integrity hashes. Pose Active Learning freezes only scientist-verified canonical track keyframes and rejects mixed schema revisions. ReefPose registration and inference already validate dataset/checkpoint schema identity. `PoseAnnotationEditor` already supports repeated labels, source-coordinate placement, dragging, deletion, visibility states, zoom/pan, and revision pinning.

## Approaches considered

1. Store designer-only documents in a new parallel table. This isolates the UI but creates two competing schema authorities and risks dataset/checkpoint drift.
2. Overload model-bound schema assignment. This reuses an endpoint but makes schema creation depend on a model and cannot support annotation-first research.
3. Extend canonical pose schema revisions with a full normalized definition and expose project-level CRUD/revision APIs. This preserves one authority and naturally feeds annotation, freezing, training, and Model Hub. **Selected.**

## Architecture

Add a JSON definition to immutable schema revisions while retaining the legacy `groups_json` and `expanded_labels_json` projections used by existing providers. The normalized definition contains ordered landmarks with stable IDs, display names, descriptions, groups, occurrence metadata, optional symmetry partners, and edges that reference stable IDs. Its canonical JSON is the revision integrity hash.

Project APIs create templates, list their revision history, and append revisions. Reordering or renaming creates a new revision; it never mutates existing rows. Validation rejects duplicate IDs, dangling/self edges, invalid symmetry, and ambiguous repeated instances. Existing legacy revisions are serialized into compatible definitions on read.

The React designer uses the existing card/form language and an SVG preview. It edits a draft, shows integrity/revision state, and saves an explicit new revision. The video pose editor consumes the selected exact revision and records `landmark_id` alongside the legacy label/occurrence projection. Existing observations remain readable through deterministic legacy slot resolution.

Dataset freezing embeds the complete immutable definition and its hash. Existing scientist-verification checks remain the truth gate. Training continues consuming the frozen projection/order while checkpoint metadata retains the schema identity and full definition.

## Compatibility and failure handling

- Existing legacy schemas remain readable and trainable.
- Existing annotations are not rewritten.
- Display-name changes cannot change a stable landmark ID within the same conceptual landmark.
- Structural edits produce a new revision and are incompatible with old checkpoints unless the exact hash matches.
- Failed revision creation leaves no partial schema revision.
- Unreviewed predictions remain excluded from frozen training data.

## Validation

Backend API/integrity tests, frontend designer/editor tests, frozen-dataset and training compatibility tests, live browser workflow, and explicit RTX 3090 training/inference. Synthetic fixtures are engineering evidence only.

