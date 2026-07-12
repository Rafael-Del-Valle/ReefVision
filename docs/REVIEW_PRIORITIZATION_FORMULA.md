# Review Prioritization Formula

Current formula ID: `review_priority_v1`  
Current formula version: `1.0.0`

## Determinism

For a fixed:

- project or dataset-version scope;
- formula version;
- weight configuration;
- QC source run;
- annotation and prediction state; and
- item input checksums;

ReefVision produces the same ranking and score breakdown.

The implementation avoids wall-clock drift by deriving the review-time reference timestamp from the scoped image records instead of using the current time during queue generation.

## Severity mapping

When unresolved QC issues contribute to ranking, the current formula maps severities as:

| Severity | Numeric value |
|---|---:|
| `error` | `1.0` |
| `warning` | `0.6` |
| `info` | `0.3` |

## Raw signals and normalization

| Signal ID | Raw value | Normalization |
|---|---|---|
| `low_mean_confidence` | `max(0, 1 - mean(pending confidences))` | Clamp to `[0, 1]`. |
| `low_min_confidence` | `max(0, 1 - min(pending confidences))` | Clamp to `[0, 1]`. |
| `pending_proposals` | Count of pending proposals. | `min(count / 10, 1)`. |
| `rejection_rate` | `rejected / reviewed_predictions` when reviewed predictions exist. | Clamp to `[0, 1]`. |
| `count_disagreement` | `abs(annotation_count - proposal_count) / max(annotation_count, proposal_count, 1)` | Clamp to `[0, 1]`. |
| `unresolved_qc_severity` | Highest unresolved QC severity numeric value for the image. | Clamp to `[0, 1]`. |
| `rare_class_presence` | `max(1 - class_count / max_class_count)` across classes present on the image. | Clamp to `[0, 1]`. |
| `edited_acceptance_rate` | Accepted predictions that were edited before acceptance divided by accepted predictions. | Clamp to `[0, 1]`. |
| `unreviewed_state` | `1` when the image status is not `reviewed`, else `0`. | Already in `[0, 1]`. |
| `missing_group_metadata` | `1` when `group_key` is blank or missing, else `0`. | Already in `[0, 1]`. |
| `incomplete_provenance` | Missing provenance records divided by provenance-bearing items. | Clamp to `[0, 1]`. |
| `recent_import` | `max(0, 1 - age_days / 7)` from image creation time. | Clamp to `[0, 1]`. |
| `stale_review_state` | `min(age_days / 30, 1)` when the image is not reviewed. | Clamp to `[0, 1]`. |

## Current default weights

| Signal ID | Default weight |
|---|---:|
| `low_mean_confidence` | `24` |
| `low_min_confidence` | `12` |
| `pending_proposals` | `14` |
| `rejection_rate` | `8` |
| `count_disagreement` | `12` |
| `unresolved_qc_severity` | `18` |
| `rare_class_presence` | `5` |
| `edited_acceptance_rate` | `6` |
| `unreviewed_state` | `10` |
| `missing_group_metadata` | `4` |
| `incomplete_provenance` | `5` |
| `recent_import` | `4` |
| `stale_review_state` | `6` |

## Score calculation

For each signal:

`contribution = (normalized_value * weight / total_weight) * 100`

The final review score is the sum of all contributions, rounded to two decimal places.

Each queue item stores:

- the raw signal values;
- normalized values;
- the weights used;
- the contribution list;
- the final score; and
- a short human-readable reason summary built from the top positive contributors.

## Ranking order

Queue items are sorted by:

1. descending final score;
2. ascending image ID as a deterministic tie-breaker.

The contribution list is sorted by descending contribution and then by signal ID.

## Historical behavior

Changing weights or selecting a different QC source run produces a new queue record with its own configuration metadata. Older queues remain inspectable and are never rewritten.
