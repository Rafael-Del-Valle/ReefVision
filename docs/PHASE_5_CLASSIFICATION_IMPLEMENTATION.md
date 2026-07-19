# Phase 5: Coral crop classification

## Status

Feature-complete first release in code. Real-model performance, migration, restart, and packaged-Windows acceptance remain release gates.

## Supported classification targets

- **Multiclass:** project classes such as species/state combinations.
- **Binary state:** open versus closed, using each project class's `state_name` metadata.
- **Image labels:** optional verified image-level labels stored separately from crop predictions.

## Immutable dataset workflow

Classification crops are produced only from frozen `DatasetVersionItem.annotation_snapshot_json` records. Source images are never modified.

The exporter writes an Ultralytics classification directory:

```text
train/<class>/...
val/<class>/...
test/<class>/...
```

Every crop records:

- source image and annotation IDs;
- source and crop bounding boxes;
- image and dataset snapshot checksums;
- crop checksum;
- split and group metadata;
- source class, scientific name, and state.

Crops smaller than the configured minimum are **removed during preprocessing** and reported in the preview, export manifest, training preflight, and job result. The default minimum is 10×10 pixels.

## Training

The desktop workspace supports:

- scratch Ultralytics classification training from an installed `*-cls.yaml` architecture;
- transfer learning from a locally registered classifier;
- immutable dataset and split checksums;
- configurable epochs, patience, batch size, image size, device, and precision;
- background jobs, progress, cancellation, logs, metrics, checkpoints, and experiment lineage.

Automatic checkpoint downloads are not used. A pretrained checkpoint must already be a trusted local registered classifier.

## Registration and import

A completed ReefVision classification run can be registered as purpose `classifier`, task `classify`.

Trusted external Ultralytics classification checkpoints can also be imported. ReefVision inspects the local file and rejects checkpoints whose actual task is not `classify`. The import records whether the model is multiclass or binary-state.

## Inference and review

Classification runs against the current verified bounding-box annotations in selected images. Each annotation is cropped without modifying the source image.

A prediction stores:

- model ID and checksum;
- inference job and settings;
- source annotation and bounding box;
- predicted label and class index;
- top confidence and complete probability distribution;
- preprocessing provenance;
- pending review status.

Predictions do not change annotations automatically.

Accepting a prediction:

- optionally maps or overrides the project class;
- changes the source annotation class;
- increments annotation and image revisions;
- records source model and prediction provenance;
- creates an append-only `class_changed` audit event.

Rejecting a prediction leaves the verified annotation unchanged.

## Desktop workflow

The Classification tab provides:

1. immutable dataset selection;
2. six-class or binary-state selection;
3. crop preview and undersized-crop reporting;
4. classification export;
5. scratch or local-pretrained training;
6. run status and classifier registration;
7. image selection and crop inference;
8. prediction confidence, class override, accept, and reject.

## Validation included

- multiclass and binary crop preview;
- minimum crop removal and manifest wording;
- Ultralytics-compatible split folders;
- immutable training-run provenance;
- prediction acceptance and audit events;
- image-level label CRUD;
- model-purpose and task separation.

## Remaining release validation

- Alembic upgrade/downgrade through revision `0020`;
- full Ruff, mypy, pytest, TypeScript, Vitest, Playwright, and production build;
- one-epoch six-class training and inference;
- one-epoch binary-state training and inference;
- confusion matrices, per-class precision/recall/F1, calibration, and scientific performance review;
- restart persistence and packaged-Windows smoke testing.
