# Phase 7: Diversity-aware active learning

## Status

Implemented as a backend-and-desktop first release on top of ReefVision's existing explainable review queues.

This implementation does not automatically accept model predictions or modify verified annotations. It creates a compact, reproducible list of images for human review.

## What it adds

- Project-scoped active-learning queues.
- Immutable-dataset-version-scoped active-learning queues.
- Existing review-priority signals, including prediction confidence, proposal state, model-versus-human count disagreement, quality-control severity, rare classes, provenance gaps, and review state.
- Greedy diversity selection across label classes, model registrations, image groups, dataset splits, and quality-control severities.
- Configurable batch size, minimum priority score, diversity weight, per-group cap, and reviewed-image inclusion.
- Deterministic ranking and checksums for reproducibility.
- Human-readable score explanations stored on each selected item.
- Score components scaled so their displayed contributions reconstruct the blended active-learning score within rounding tolerance.
- Queue regeneration that preserves the original active-learning configuration.
- Compatibility with the existing Review Queue list, item viewer, state transitions, filters, and Regenerate button.
- Desktop controls for switching between ordinary priority rankings and active-learning batches.
- Desktop summary metrics for candidate count, reviewed-image exclusions, diversity, and final score.

## Desktop workflow

1. Open **Review Queue**.
2. Choose **Priority ranking** or **Active-learning batch**.
3. Select the entire project or an immutable dataset version.
4. Optionally choose a completed quality-control run.
5. For active learning, configure:
   - maximum images;
   - minimum priority score;
   - diversity weight from `0` to `1`;
   - optional maximum images per group;
   - whether already-reviewed images may be included.
6. Adjust the explainable review-signal weights when needed.
7. Generate the queue and review the ranked images through the existing item workflow.
8. Regenerate later to produce a new immutable queue using the same configuration and current project state.

## Selection behavior

ReefVision first creates the normal explainable review-priority ranking. It then removes reviewed images unless they are explicitly requested, applies the minimum score threshold, and greedily selects a compact batch.

For each selection step, the final score blends:

- the existing review-priority score; and
- the candidate's novelty relative to images already selected in the batch.

A higher diversity weight favors coverage of new classes, models, groups, splits, and QC severities. A weight of `0` preserves priority-only selection. A weight of `1` emphasizes diversity while using priority and prior rank as deterministic tie breakers.

## API

### Shared Review Queue creation route

The desktop interface uses the existing routes with `queue_kind` set to `priority` or `active_learning`:

- `POST /api/v1/projects/{project_id}/review-queues`
- `POST /api/v1/dataset-versions/{version_id}/review-queues`

Ordinary clients that omit `queue_kind` remain backward compatible and create `review_priority_v1` queues.

### Dedicated active-learning routes

The original dedicated routes remain available:

- `POST /api/v1/projects/{project_id}/active-learning-queues`
- `POST /api/v1/dataset-versions/{version_id}/active-learning-queues`

### Regenerate while preserving settings

Either endpoint is supported:

- `POST /api/v1/active-learning-queues/{queue_id}/regenerate`
- `POST /api/v1/review-queues/{queue_id}/regenerate`

The second route keeps the existing Review Queue desktop workflow compatible.

## Shared-route request example

```json
{
  "queue_kind": "active_learning",
  "source_quality_control_run_id": null,
  "max_items": 100,
  "min_priority_score": 15.0,
  "diversity_weight": 0.35,
  "max_items_per_group": 5,
  "include_reviewed": false,
  "signal_weights": {
    "low_mean_confidence": 24,
    "low_min_confidence": 12,
    "pending_proposals": 14,
    "rejection_rate": 8,
    "count_disagreement": 12,
    "unresolved_qc_severity": 18,
    "rare_class_presence": 5,
    "edited_acceptance_rate": 6,
    "unreviewed_state": 10,
    "missing_group_metadata": 4,
    "incomplete_provenance": 5,
    "recent_import": 4,
    "stale_review_state": 6
  }
}
```

## Persisted provenance

Each queue records:

- formula ID and version;
- full active-learning configuration;
- candidate and selected counts;
- exclusion counts;
- average selection and diversity scores;
- selected counts by image group;
- a checksum of the final ranked selection.

Each item records:

- its original review-priority score;
- its diversity score at the moment it was selected;
- its blended selection score;
- a human-readable reason summary;
- a checksum derived from the source review item and final active-learning rank.

## Validation included

- Priority/diversity selection behavior.
- Per-group batch limits.
- Review-score explanation arithmetic.
- Reviewed-image exclusion.
- Maximum batch size.
- Active-learning metadata persistence.
- Shared-route active-learning dispatch.
- Backward-compatible default priority-queue creation.
- Regeneration through the existing Review Queue route.

## Remaining Phase 7 work

- Add optional embedding-based visual novelty once a stable feature provider is available.
- Add model-ensemble disagreement when multiple compatible inference runs exist.
- Add a retraining-cycle workflow that converts reviewed items into a new immutable dataset version and launches an explicitly approved training run.
- Add before-and-after model evaluation that measures whether the reviewed batch improved performance.
- Validate batch quality on a real coral dataset and tune the default diversity weight.
- Complete full frontend and packaged-desktop acceptance once GitHub Actions can start jobs again.
