# ReefVision feature reference

This is a technical inventory of the features described on the repository's default branch. Specific behavior and available providers can vary by release. For an introduction, return to the [README](../README.md).

## Images and annotations

- Create blank projects or start from the six-class octocoral template.
- Create, rename, reorder, recolor, deactivate, and manage visibility for annotation classes.
- Import JPEG, PNG, TIFF, and WebP images into managed storage, with duplicate detection and background thumbnails.
- Browse by filename, annotation state, or leakage-prevention group.
- Annotate with bounding boxes, rotated boxes, polygons, raster brush editing, and deterministic Fill.
- Edit model-generated polygons and masks before accepting them as research annotations.
- Draw coral centerlines and use image scale or calibration information for measurements.
- Calculate mask-aware and calibration-aware measurements and view measurement summaries.

## Models and datasets

- Register trusted local checkpoints through the Model Hub.
- Run detection and segmentation inference, keeping proposed predictions separate from verified annotations.
- Run supported classification workflows with image-level labels and crop-based datasets.
- Train supported detection and segmentation models with persisted training runs and results packages.
- Create immutable dataset versions with frozen annotation state, leakage-aware splits, manifests, comparisons, and exports.
- Run explainable project and dataset quality-control checks, including historical comparisons.
- Generate ranked review queues and open the corresponding images in the annotation editor.
- Create active-learning rounds using uncertainty, rarity, quality-risk, or combined selection methods.
- Use advanced provider adapters where the relevant runtime is installed and supported. These can include SAM2, Grounding DINO, Depth Anything, OCR, and vision-language providers.

## Video and analysis

- Import video, run ByteTrack or BoT-SORT tracking, inspect run histories, and exchange tracks.
- Export annotated review videos from saved tracking observations without rerunning detection.
- Work with activity and occupancy analysis and the supported depth and 3D workflows.

## Projects and reproducibility

- Build and execute versioned workflow graphs, including human-review gates and artifact lineage.
- Export and inspect checksummed project-exchange ZIP files. Original imagery, models, and generated artifacts are explicit options.
- Import supported project-exchange packages into managed projects with identifier remapping.
- Create and verify managed backups, restore into recovery locations, and export redacted diagnostic bundles.
- Archive projects without deleting the underlying managed files.

For setup, release packaging, and checks, see the [developer guide](DEVELOPMENT.md).
