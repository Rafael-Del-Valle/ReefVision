# Phase 3E: Semantic Segmentation with nnU-Net v2

## Status

Implementation is present on `feat/semantic-segmentation-nnunet`; automated and installed-app validation remain pending.

This branch is stacked on the validated Phase 3 instance-segmentation branch. It does not replace or merge the existing detection and YOLO polygon-segmentation workflows.

## User workflow

1. Install the optional nnU-Net provider with `scripts/install-nnunet-provider.ps1`.
2. Create or select a complete immutable dataset version containing polygon masks, raster masks, or both.
3. Open Training and choose **Semantic segmentation**.
4. Select **nnU-Net v2 2D**.
5. Keep ReefVision tiling and tuning disabled. nnU-Net plans its own patches.
6. Choose a supported trainer length. `1` epoch is intended for smoke testing; longer trainers are required for scientific use.
7. Launch the background run.
8. Review the exported semantic dataset, nnU-Net logs, validation metrics, and resulting `semantic-model.zip`.
9. Register the completed run. The model is recorded as purpose `semantic_segmenter`, task `semantic_segment`, provider `nnunet`.
10. Open an image, select the semantic model in the annotation toolbar, and run segmentation.
11. Review the per-class raster proposals. Accepting one creates a normal verified ReefVision raster `MaskAnnotation` with revision and provenance history.

## Dataset boundary

ReefVision first writes its existing immutable semantic-mask export:

- `images/train`, `images/validation`, `images/test`
- `masks/train`, `masks/validation`, `masks/test`
- indexed lossless PNG masks
- background pixel value `0`
- foreground values `1..N`
- frozen raster-mask checksum validation
- deterministic polygon/raster overlap policy
- immutable dataset and split checksums

The nnU-Net provider then creates one isolated per-run native dataset:

```text
nnUNet_raw/
  DatasetXXX_ReefVision_<run>/
    dataset.json
    imagesTr/
      <case>_0000.png
    labelsTr/
      <case>.png
    imagesTs/
      <case>_0000.png
```

Source images are converted to RGB PNG. Semantic labels are copied as single-channel indexed PNG. A supplied validation split becomes an explicit `splits_final.json`; when no validation split exists and at least two training cases are available, ReefVision creates a deterministic one-case holdout.

## Training execution

The provider uses the installed nnU-Net v2 command-line interface:

```text
nnUNetv2_plan_and_preprocess
nnUNetv2_train
nnUNetv2_predict
```

Each run receives isolated `nnUNet_raw`, `nnUNet_preprocessed`, and `nnUNet_results` directories. The first slice supports:

- configuration: `2d`
- plans: `nnUNetPlans`
- scratch training
- CPU, CUDA, or MPS selection
- packaged nnU-Net trainer lengths: 1, 5, 10, 20, 50, 100, 250, 500, 750, 2000, 4000, and 8000 epochs
- validation summary metric capture
- experiment lineage and package-version capture
- a complete portable ReefVision nnU-Net ZIP bundle

## Model bundle

A successful run creates `semantic-model.zip`. The ZIP contains the complete nnU-Net result configuration and:

```text
reefvision-semantic-model.json
```

The metadata records:

- bundle format and provider version
- nnU-Net dataset name and numeric ID
- trainer, plans, configuration, and fold
- checkpoint name
- ReefVision semantic class indices, names, and pixel values

Registration verifies the ZIP, copies it into the project model store, calculates its checksum, maps semantic class names to project class IDs, and stores dataset/run/experiment provenance.

## Inference and review

nnU-Net prediction produces one indexed PNG label map. ReefVision splits every foreground class present in that map into a separate immutable binary PNG proposal.

Each proposal stores:

- geometry kind `raster_mask`
- model and inference-job IDs
- model checksum and provider version
- predicted class/index/pixel value
- managed PNG path and SHA-256 checksum
- source-image bounds and area
- hard-label confidence metadata

The annotation editor serves each proposal through a checked API endpoint and renders it inside the existing transformed SVG group, preserving pan/zoom alignment.

Accepting a semantic proposal:

- verifies the proposal PNG checksum
- allows a project-class override
- copies the PNG through the standard mask-storage service
- creates a verified raster `MaskAnnotation`
- increments the image annotation revision
- records a `MaskAnnotationEvent`
- preserves source model, prediction, class, checksum, and acceptance provenance

Reject and mixed bulk-review paths use the existing prediction-review API.

## Phase 3 acceptance harness

Run:

```powershell
.\scripts\phase3-acceptance.ps1 -SkipBuild
```

The harness launches the packaged executable and records PASS/FAIL/BLOCKED results for:

- instance-segmentation preflight and raster warning
- one-epoch YOLO segmentation training and mask metrics
- segmenter registration
- polygon proposal alignment
- accept/reject/bulk review
- restart persistence
- detection regression

Reports are written under `.desktop/acceptance` and tied to the tested Git commit.

## Validation gates for Phase 3E

Before the branch is considered usable:

1. Run Ruff lint and formatting.
2. Run strict mypy.
3. Run the complete backend test suite, including semantic contract, migration, dispatch, and raster proposal tests.
4. Run Alembic upgrade and downgrade.
5. Run Prettier, TypeScript, Vitest, and Playwright.
6. Build the packaged backend, Tauri executable, and MSI.
7. Install the optional nnU-Net provider in the development environment.
8. Perform a real one-epoch semantic run on a small immutable dataset.
9. Register the ZIP and run real semantic inference.
10. Verify raster proposal alignment, accept/reject/bulk review, and restart persistence.
11. Verify detection and YOLO instance segmentation still work.

## Known limitations

- nnU-Net remains optional and is not bundled into the base MSI in this slice.
- The optional provider must be installed into the Python environment used by the ReefVision backend.
- The first implementation supports `2d` scratch training only.
- Resume, pretrained semantic checkpoints, ensembles, cross-validation orchestration, cascades, and semantic hyperparameter tuning are not exposed yet.
- Cancellation is checked between ReefVision stages; an active nnU-Net subprocess is not yet terminated immediately.
- Training progress is stage-level until subprocess output is streamed into per-epoch progress.
- Semantic predictions are hard class labels; calibrated pixel probabilities and uncertainty maps are not yet stored.
- Proposal PNG cleanup and retention policies need a later maintenance slice.
- The Training Models panel retains legacy detector-oriented wording in places; backend registration is task-aware, and the annotation launcher recognizes semantic models.
- Scientific performance remains unvalidated until a real coral dataset is trained and evaluated.
