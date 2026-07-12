# Quality Control Threshold Reference

All geometry thresholds use canonical source-image pixels, not display pixels and not normalized YOLO coordinates.

## Current configurable thresholds

| Threshold | Default | Used by | Meaning |
|---|---:|---|---|
| `small_box_min_width_px` | `6.0` | `small_box` | Minimum width below which a box is flagged as unusually small. |
| `small_box_min_height_px` | `6.0` | `small_box` | Minimum height below which a box is flagged as unusually small. |
| `near_duplicate_iou_threshold` | `0.9` | `near_duplicate_box` | IoU at or above this value is treated as a likely duplicate. |
| `same_class_overlap_iou_threshold` | `0.75` | `same_class_overlap` | IoU at or above this value becomes suspicious for same-class boxes unless already treated as a near duplicate. |
| `different_class_overlap_iou_threshold` | `0.8` | `different_class_overlap` | IoU at or above this value becomes suspicious for different-class boxes. |
| `boundary_touch_margin_px` | `0.0` | `boundary_touching_box` | Margin from the image edge that still counts as touching the boundary. |
| `annotation_count_mad_multiplier` | `3.5` | `annotation_count_outlier` | Robust outlier cutoff in median-absolute-deviation units. |
| `class_imbalance_majority_ratio` | `0.85` | `class_imbalance` | Majority-class fraction that triggers a skew warning. |
| `suspicious_bulk_acceptance_min_count` | `12` | `suspicious_bulk_acceptance` | Minimum accepted-prediction count before a short review burst is flagged. |
| `suspicious_bulk_acceptance_window_minutes` | `10` | `suspicious_bulk_acceptance` | Time window used with the bulk-acceptance count threshold. |
| `overlap_spatial_cell_px` | `128` | duplicate and overlap rules | Spatial bucket size used to keep pairwise comparisons bounded on dense images. |

## Statistical method

`annotation_count_outlier` uses one consistent robust method:

- compute the per-image annotation count;
- compute the median count;
- compute the median absolute deviation, or `1.0` when the MAD is zero;
- calculate `mad_score = (count - median) / scale`;
- flag high or low outliers when the absolute score crosses `annotation_count_mad_multiplier`.

The issue record stores the annotation count, median, MAD, MAD score, and direction so the warning remains explainable later.

## Tuning guidance

Smaller `small_box_*` values reduce sensitivity for dense tiny-object projects.

Higher overlap thresholds reduce duplicate warnings but may also hide true duplicate boxes.

Higher `annotation_count_mad_multiplier` values make outlier detection less sensitive.

Lower `class_imbalance_majority_ratio` values make class skew warnings less common.

Larger `overlap_spatial_cell_px` values increase candidate pairing breadth, while smaller values reduce comparisons but can miss far-apart overlaps if chosen too aggressively.

## Historical behavior

Thresholds are copied into every run record and every issue record that uses them. Changing thresholds for a new run does not rewrite older QC history.
