# Phase 7 — Active Learning

## Scope

Phase 7 turns ReefVision's explainable review ranking into reproducible acquisition rounds. A model may prioritize images for human attention, but it cannot promote its own predictions directly into verified annotations.

The completed software loop is:

```text
immutable dataset / project candidates
            ↓
      train or register model
            ↓
          inference
            ↓
 explainable acquisition ranking
            ↓
        review queue
            ↓
 human annotation / correction / review
            ↓
 immutable reviewed feedback dataset
            ↓
 subsequent export / training / inference round
```

## Implemented architecture

- `ActiveLearningRound` freezes selected images, scores, input checksums, acquisition strategy, model scope, review budget, and a stable selection SHA-256.
- Every round links to a normal ReefVision review queue. Existing queue-item start, complete, skip, return, and image-review behavior remains the source of truth.
- Stable selection hashes exclude generated database IDs, so equivalent acquisition inputs resolve to the same historical round.
- Four deterministic strategies are available:
  - `hybrid`
  - `uncertainty`
  - `rare_class`
  - `quality`
- Optional dataset-version scoping limits the acquisition candidate universe to an immutable ReefVision dataset.
- Optional model scoping limits acquisition to images carrying signals from selected registered models.
- The frozen selection manifest stores a human-readable `reason_summary`, score breakdown, and raw signal values for every selected image.
- Feedback summaries report pending, in-progress, completed, and skipped selections plus detection and classification prediction-review counts.
- A round can close only after every selected queue item is completed or skipped.
- Any queue item marked `completed` must also have underlying image annotation status `reviewed` before round completion.
- Completing a round with reviewed items creates an immutable mask-aware ReefVision dataset version containing current reviewed annotations.
- When the acquisition round started from a dataset version, the feedback version records that version as its parent and reuses parent split assignments while deterministically assigning newly eligible reviewed images.
- The feedback dataset ID and manifest checksum are persisted in `feedback_summary_json` and returned through the feedback API.
- Round completion is idempotent: re-closing an already completed round does not create a second feedback dataset.

## Desktop workflow

The Active Learning workspace exposes:

- input dataset selection (`Current project state` or a complete immutable dataset version)
- Hybrid, Uncertainty, Rare class, and Quality strategies
- a concise explanation of what the selected strategy prioritizes
- review budget
- optional registered-model filters
- frozen round identity, input dataset, model scope, review queue, and selection manifest checksum
- a ranked `Why these images?` view with the human-readable reason and acquisition score for every selected image
- direct handoff to the normal Review Queue workspace
- feedback progress
- feedback dataset version ID and manifest checksum after successful completion

The round-completion control explicitly states that queue completion and scientific annotation review are separate requirements.

## Acquisition signals and interpretation

ReefVision active learning reuses the explainable review-ranking signals rather than introducing a hidden acquisition model. Depending on strategy weights these may include:

- low mean model confidence
- low minimum confidence
- pending proposal burden
- prediction rejection history
- count disagreement
- unresolved quality-control severity
- rare-class presence
- edited-acceptance history
- unreviewed annotation state
- missing group metadata
- incomplete provenance
- recent import state
- stale review state

`uncertainty` puts most weight on confidence/disagreement-related signals. `rare_class` strongly increases rare-class presence. `quality` emphasizes unresolved QC/provenance/review risk. `hybrid` balances the available signals.

These are acquisition heuristics, not calibrated probabilities that an image is scientifically wrong or biologically important. The manifest preserves the individual signal values so a researcher can audit why a sample entered a round.

## Feedback dataset contract

A completed review item is eligible for feedback only after its underlying image has been explicitly marked `reviewed` in the annotation workspace. This prevents a queue-state click from being mistaken for scientific verification.

The post-round snapshot uses ReefVision's mask-aware immutable dataset service, so verified bounding-box annotations and verified polygon/raster masks are preserved using the existing dataset checksum/provenance contract. Pixel data remain managed project assets; the dataset version freezes image/annotation membership and metadata rather than mutating the sources.

If every selected item is skipped, the round may close without a new feedback dataset because no reviewed sample was contributed.

The feedback dataset is intended to be an input to later export/training workflows. It is not automatically retrained. Training remains an explicit researcher action so model lineage, hyperparameters, validation splits, and scientific interpretation stay reviewable.

## Automated acceptance gate

The permanent Milestone 7 workflow is required to verify:

1. Ruff lint and formatting for the M7 migration, models, schemas, service, routes, and focused tests
2. first-class model/inference/prediction records drive uncertainty acquisition
3. lower-confidence model output outranks a higher-confidence peer under the uncertainty strategy
4. Hybrid, Uncertainty, Rare class, and Quality rounds all emit explainable manifests
5. stable selection identity reuses an equivalent historical round
6. model scoping rejects invalid/foreign models
7. queue completion alone cannot close a round until completed images are scientifically marked Reviewed
8. reviewed feedback creates a complete immutable dataset with the expected image/annotation counts and manifest SHA-256
9. round completion is idempotent and does not duplicate feedback datasets
10. migration upgrade through `0022`, downgrade to `0021`, and re-upgrade
11. frontend Prettier and TypeScript checks
12. focused Active Learning workspace tests for strategy guidance, selection explanations, and feedback-dataset lineage

As of August 8, 2026, GitHub-hosted Actions jobs remain blocked before checkout by the account/repository Actions billing or spending-limit state. A two-second no-run check is not evidence that this gate passed or failed at the code level.

## Required real-data and packaged-desktop validation

Automated tests do not establish scientific active-learning efficiency. Before M7 promotion, validate on representative coral data:

1. annotation → immutable dataset → training/registered model → inference → acquisition → review → feedback dataset as a complete user workflow
2. Uncertainty selection against genuinely varying model confidence/disagreement
3. Rare class selection on an intentionally imbalanced biological dataset
4. Quality selection with representative QC/provenance problems
5. Hybrid selection across mixed signal types
6. model-scoped and dataset-scoped rounds
7. reviewed feedback retained in a later export/training run
8. restart/reopen persistence
9. packaged Windows desktop acceptance
10. selection efficiency against a defensible baseline such as random sampling or existing review order

Useful scientific comparisons include labels corrected per reviewed image, error discovery rate, class-balance improvement, validation-performance change after a fixed annotation budget, and annotation time per useful correction. These should be reported separately from software acceptance.

## Safety and reproducibility constraints

- Active learning selects work for a human; it does not silently verify predictions.
- Predictions remain governed by the normal proposal-review flow.
- Queue state and image annotation status remain separate concepts.
- Acquisition manifests preserve model scope, queue formula/version, weights, scores, image IDs, reasons, signal values, and input checksums.
- Dataset-version-scoped rounds retain the immutable source version ID.
- Feedback datasets preserve their own immutable manifest checksum and parent dataset lineage when applicable.
- No embeddings or novelty model are silently generated.
- No automatic retraining occurs when a round completes.

## Remaining extensions beyond the M7 release gate

- embedding-based diversity and core-set selection
- synchronized ensemble disagreement from multiple model runs
- per-class acquisition quotas
- cost-aware acquisition using historical annotation time
- automatic experiment comparison before versus after a round
- adaptive strategy-weight optimization

Those extensions can improve research efficiency later, but they are not required to establish a safe, reproducible M7 active-learning loop.