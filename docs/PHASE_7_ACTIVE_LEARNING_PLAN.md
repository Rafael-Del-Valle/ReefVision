# Phase 7 — Active Learning

## Scope

Phase 7 turns ReefVision's explainable review ranking into reproducible acquisition rounds. It does not allow a model to promote its own predictions directly into verified annotations.

## Implemented architecture

- `ActiveLearningRound` freezes the selected images, scores, input checksums, acquisition strategy, model scope, and review budget.
- Every round links to a normal ReefVision review queue. Existing queue-item start, complete, skip, return, and image-review behavior remains the source of truth.
- Stable selection hashes exclude generated database IDs, so equivalent acquisition inputs resolve to the same historical round.
- Four deterministic strategies are available:
  - `hybrid`
  - `uncertainty`
  - `rare_class`
  - `quality`
- Optional model scoping limits acquisition to images carrying proposals from selected registered models.
- Feedback summaries report pending, in-progress, completed, and skipped selections plus detection and classification prediction-review counts.
- A round can close only after every selected item is completed or skipped.

## Safety and scientific constraints

- Active learning only selects work for a human.
- Predictions remain pending until accepted through the normal review flow.
- Acquisition manifests preserve model IDs, queue formula/version, weights, scores, image IDs, and input checksums.
- Dataset-version-scoped rounds retain the immutable source version ID.
- No embeddings or novelty model are silently generated. The existing conservative ranking primitive remains available for future embedding-backed novelty scoring.

## Deferred work

- Embedding-based diversity and core-set selection.
- Ensemble disagreement using synchronized inference from multiple models.
- Per-class acquisition quotas.
- Cost-aware acquisition using historical annotation time.
- Automatic creation of a new immutable dataset version after a round closes.
- Training-run comparison before and after a round.
- Installed desktop and real-model validation.
