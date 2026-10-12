"""Fail-closed scientific eligibility policy for segmentation candidate comparisons.

This pure policy does not activate models or replace audited persistence.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class SegmentationCandidateScore:
    model_id: str
    project_id: str
    dataset_version_id: str
    split_digest: str
    mask_map50: float
    mean_absolute_count_error: float
    evaluated_images: int

    def __post_init__(self) -> None:
        identity = (self.model_id, self.project_id, self.dataset_version_id, self.split_digest)
        if not all(identity):
            raise ValueError(
                "Segmentation evaluation identity and split digest are required"
            )
        if self.evaluated_images < 1:
            raise ValueError("Segmentation evaluation needs held-out images")
        if not isfinite(self.mask_map50) or not 0 <= self.mask_map50 <= 1:
            raise ValueError("Invalid mask AP50")
        if not isfinite(self.mean_absolute_count_error) or self.mean_absolute_count_error < 0:
            raise ValueError("Invalid segmentation count error")


def candidate_meets_segmentation_guardrails(
    candidate: SegmentationCandidateScore,
    incumbent: SegmentationCandidateScore | None,
    *,
    minimum_mask_map50: float,
    minimum_gain: float = 0.0,
    maximum_count_error_increase: float = 0.0,
) -> bool:
    """Eligibility prerequisite only; never authorizes automatic promotion.

    Both models must be evaluated on the exact same immutable held-out split.
    A missing incumbent is allowed only for initial activation and still
    requires the absolute quality floor. Deployment must independently check
    model digest, task, project, lineage, and audit requirements.
    """
    thresholds = (minimum_mask_map50, minimum_gain, maximum_count_error_increase)
    if not all(isfinite(value) for value in thresholds):
        raise ValueError("Nonfinite promotion threshold")
    if (
        not 0 <= minimum_mask_map50 <= 1
        or minimum_gain < 0
        or maximum_count_error_increase < 0
    ):
        raise ValueError("Invalid promotion threshold")
    if candidate.mask_map50 < minimum_mask_map50:
        return False
    if incumbent is None:
        return True
    if (
        candidate.project_id != incumbent.project_id
        or candidate.dataset_version_id != incumbent.dataset_version_id
        or candidate.split_digest != incumbent.split_digest
        or candidate.evaluated_images != incumbent.evaluated_images
    ):
        raise ValueError("Candidate and incumbent require the same immutable evaluation split")
    return (
        candidate.mask_map50 >= incumbent.mask_map50 + minimum_gain
        and candidate.mean_absolute_count_error
        <= incumbent.mean_absolute_count_error + maximum_count_error_increase
    )
