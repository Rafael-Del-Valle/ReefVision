# Phase 5 — Classification Workflows

## Scope

Phase 5 adds reproducible image-level and crop-level classification without changing the existing detection or segmentation data model.

## Implemented vertical slice

- revisioned image labels organized by named label sets
- human and accepted-prediction provenance
- immutable classification datasets derived from an existing dataset version
- whole-image samples
- bounding-box crops
- mask-bounds crops
- frozen class mapping, source image checksums, split assignment, crop bounds, and source snapshot checksums
- downloadable dataset ZIPs using the folder structure expected by Ultralytics classification
- provider-neutral classification interface
- Ultralytics classification training
- automatic classifier registration after successful training
- top-k image inference
- accept and reject review actions
- accepted predictions converted to verified image labels
- project Classification workspace in the desktop UI

## Dataset rules

Whole-image classification requires exactly one verified image label in the requested label set for every included image. Crop classification uses the class attached to each frozen box or mask snapshot. Mask crops currently use the mask bounding extent; background removal is deferred.

## Model rules

Classification training currently supports an Ultralytics classification checkpoint or architecture identifier. Completed training jobs automatically register a managed model with:

- purpose `classifier`
- task `classify`
- provider and provider version
- immutable classification dataset checksum
- training metrics
- folder-to-ReefVision class mapping

## Review rules

Top-k results are persisted independently. Accepting a result creates or restores a verified `ImageLabel` with source model and source prediction provenance. Rejecting a result preserves the prediction and records the review decision.

## Deferred validation

The branch is not considered complete until a later validation day confirms:

1. migration upgrade through `0020` and downgrade to `0019`
2. Ruff formatting and lint
3. strict mypy
4. focused Phase 5 backend tests
5. full backend regression suite
6. Prettier and TypeScript
7. frontend unit tests
8. production build and MSI packaging
9. one-epoch real Ultralytics classification run
10. installed-app label, dataset, inference, and review persistence

## Known limitations

- image labels currently support multiple labels per label set, while whole-image training requires exactly one
- mask crops use rectangular mask bounds rather than masked pixels
- classifier upload through the generic model-import form is not yet implemented; Phase 5 training auto-registers checkpoints
- prediction review is image-level and does not yet feed the general active-learning queue
- architecture identifiers can trigger Ultralytics weight retrieval when the checkpoint is not already installed
