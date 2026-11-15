"""Pure replay of reviewed coral correspondence and projected measurements."""

from math import isfinite

from reefvision.domain.errors import ValidationError
from reefvision.schemas.coral_graph import (
    CorrespondenceMatch,
    CorrespondenceSnapshot,
    GraphSnapshot,
    GrowthBranch,
    GrowthChange,
    GrowthSnapshot,
)


def validate_branch_correspondence(
    earlier: GraphSnapshot, later: GraphSnapshot, matches: list[CorrespondenceMatch]
) -> None:
    if earlier.organism_key != later.organism_key:
        raise ValidationError("Both observations must be of the same registered colony")
    if earlier.image_sha256 == later.image_sha256 or earlier.observed_at >= later.observed_at:
        raise ValidationError("Use distinct source images in chronological order")
    for branch_field, graph in (("earlier_branch_ids", earlier), ("later_branch_ids", later)):
        selected = [identifier for match in matches for identifier in getattr(match, branch_field)]
        if len(set(selected)) != len(selected) or set(selected) != {
            edge.id for edge in graph.edges
        }:
            raise ValidationError(
                "Review each branch exactly once, including missing or ambiguous observations"
            )


def calculate_pinned_growth(
    earlier: GraphSnapshot,
    later: GraphSnapshot,
    correspondence: CorrespondenceSnapshot,
    correspondence_sha256: str,
) -> GrowthSnapshot:
    validate_branch_correspondence(earlier, later, correspondence.matches)
    if (
        earlier.calibration is None
        or later.calibration is None
        or not (earlier.eligible_for_growth and later.eligible_for_growth)
    ):
        raise ValidationError(
            "Growth requires calibrated, connected observations with reviewed visibility"
        )
    if earlier.calibration.unit.casefold() != later.calibration.unit.casefold() or (
        (earlier.calibration.perspective_homography is None)
        != (later.calibration.perspective_homography is None)
    ):
        raise ValidationError("Growth requires the same physical unit and reference-plane method")
    elapsed = (later.observed_at - earlier.observed_at).total_seconds() / 86400
    if elapsed <= 0:
        raise ValidationError("Later observation must follow earlier observation")

    def change(before: float | None, after: float | None) -> GrowthChange:
        if before is None or after is None:
            raise ValidationError("A referenced branch has no calibrated length")
        difference = after - before
        rate = difference / elapsed
        if not all(isfinite(value) for value in (difference, rate)):
            raise ValidationError("Growth change is outside supported numeric precision")
        return GrowthChange(
            earlier_length=before,
            later_length=after,
            absolute_change=difference,
            change_per_day=rate,
        )

    old = {edge.id: edge.length_physical for edge in earlier.edges}
    new = {edge.id: edge.length_physical for edge in later.edges}
    limitations = [
        "Projected centerline lengths in a common reference-plane method; no depth correction.",
        "Imaging orientation and visibility can affect measured change.",
        "Calibration and tracing uncertainty were not quantified.",
    ]
    complete = not any(
        match.status in {"missing", "ambiguous", "occluded"} for match in correspondence.matches
    )
    if not complete:
        limitations.append("Colony total change withheld because some branches were unresolved.")
    return GrowthSnapshot(
        organism_key=earlier.organism_key,
        correspondence_sha256=correspondence_sha256,
        earlier_graph_sha256=correspondence.earlier_graph_sha256,
        later_graph_sha256=correspondence.later_graph_sha256,
        earlier_observed_at=earlier.observed_at,
        later_observed_at=later.observed_at,
        elapsed_days=elapsed,
        unit=earlier.calibration.unit,
        total=change(earlier.total_physical, later.total_physical) if complete else None,
        branches=[
            GrowthBranch(
                status=match.status,
                earlier_branch_ids=match.earlier_branch_ids,
                later_branch_ids=match.later_branch_ids,
                change=change(old[match.earlier_branch_ids[0]], new[match.later_branch_ids[0]])
                if match.status == "matched"
                else None,
                reason=match.reason,
            )
            for match in correspondence.matches
        ],
        limitations=limitations,
    )
