# Quality Control Rule Reference

Current QC ruleset version: `1.0.0`

All rules in the Milestone 7 implementation currently use rule version `1.0.0`. The ruleset is intentionally versioned so later geometry types such as polygons or masks can add new logic without rewriting historical runs.

## Geometry rules

| Rule ID | Category | What it checks | Interpretation |
|---|---|---|---|
| `invalid_bounding_box` | `annotation_geometry` | Non-finite or otherwise invalid bounding-box coordinates. | Strong data-integrity signal. |
| `zero_area_box` | `annotation_geometry` | Boxes with zero width or zero height. | Strong data-integrity signal. |
| `small_box` | `annotation_geometry` | Boxes smaller than the configured width or height threshold in source-image pixels. | Heuristic warning. |
| `out_of_bounds_box` | `annotation_geometry` | Boxes that extend outside image bounds. | Strong data-integrity signal. |
| `boundary_touching_box` | `annotation_geometry` | Boxes that touch the image border within the configured pixel margin. | Heuristic warning. |
| `exact_duplicate_box` | `annotation_geometry` | Two annotations with identical geometry and class on one image. | Strong duplicate signal. |
| `near_duplicate_box` | `annotation_geometry` | Two annotations with IoU at or above the near-duplicate threshold. | Heuristic duplicate warning. |
| `same_class_overlap` | `annotation_geometry` | Same-class annotations whose IoU is high enough to be suspicious but below the near-duplicate threshold. | Heuristic overlap warning. |
| `different_class_overlap` | `annotation_geometry` | Different-class annotations whose overlap is unusually high. | Heuristic semantic warning. |

## Annotation semantics

| Rule ID | Category | What it checks | Interpretation |
|---|---|---|---|
| `missing_or_invalid_class` | `annotation_semantics` | An annotation refers to no class or to a class not present in the current class map. | Strong integrity signal. |
| `annotation_unavailable_image` | `annotation_semantics` | An annotation points at an image that is unavailable in the evaluated scope. | Strong integrity signal. |
| `reviewed_without_annotations` | `annotation_semantics` | An image is marked `reviewed` but contains zero verified annotations in scope. | Heuristic review warning. |

## Statistics

| Rule ID | Category | What it checks | Interpretation |
|---|---|---|---|
| `annotation_count_outlier` | `statistics` | Image-level annotation counts that are unusually high or low by deterministic MAD scoring. | Heuristic warning. |
| `class_imbalance` | `statistics` | Scope-wide annotation counts that are dominated by one class or missing classes entirely. | Heuristic warning. |
| `missing_group_key` | `statistics` | Images with no usable `group_key`, which can weaken leakage-aware split behavior. | Workflow warning. |

## Prediction and provenance rules

| Rule ID | Category | What it checks | Interpretation |
|---|---|---|---|
| `prediction_unmapped_class` | `predictions` | Prediction proposals whose class mapping does not land on a valid project class. | Review warning. |
| `accepted_prediction_missing_provenance` | `predictions` | Accepted or edited-and-accepted prediction-derived results that lack provenance metadata. | Provenance integrity warning. |
| `suspicious_bulk_acceptance` | `predictions` | Many accepted predictions in a short time window, which may indicate over-aggressive review. | Heuristic warning. |

## Dataset-version rules

| Rule ID | Category | What it checks | Interpretation |
|---|---|---|---|
| `dataset_manifest_inconsistency` | `dataset_versions` | Dataset-version manifest counts or checksums that do not match the frozen snapshot contents. | Strong integrity signal. |
| `inconsistent_split_metadata` | `dataset_versions` | Split metadata conflicts such as invalid split labels or one non-null group key crossing multiple splits. | Strong integrity signal. |

## Image-integrity rules

| Rule ID | Category | What it checks | Interpretation |
|---|---|---|---|
| `missing_image_checksum` | `image_integrity` | Images or dataset-version items that are missing expected SHA-256 checksums. | Strong integrity signal. |
| `broken_managed_file_reference` | `image_integrity` | Managed original or thumbnail paths that no longer resolve beneath project storage. | Strong integrity signal. |

## Performance notes

Duplicate and overlap checks avoid naive unbounded all-pairs processing. The current implementation uses deterministic spatial bucketing through `overlap_spatial_cell_px` so dense images remain practical to process in background jobs.

## Interpretation notes

These rules intentionally mix strong integrity signals with heuristic warnings. A warning is not proof that an annotation is wrong. ReefVision stores the measured values and thresholds with each issue so reviewers can decide whether the finding matters for the project.
