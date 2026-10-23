"""Conservative coverage checks for caller-declared organism rosters.

This is not a verified experimental-design registry or a survival estimator.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Protocol

from reefvision.domain.errors import ValidationError


class RosterObservation(Protocol):
    organism_id: str
    experimental_unit_id: str | None


def validate_expected_roster(
    observations: Iterable[RosterObservation],
    expected_by_unit: Mapping[str, Sequence[str]] | None,
    *,
    experimental_unit_type: str | None,
) -> dict[str, list[str]]:
    """Return canonical rosters or fail closed on inconsistent unit membership.

    Every declared unit must be represented in the observations; every observed
    organism must be in that unit's roster. Missing roster organisms remain
    explicitly missing, never silently classified as deaths or zero counts.
    """
    if expected_by_unit is None:
        return {}
    if not expected_by_unit:
        raise ValidationError("Expected organism roster cannot be empty")
    if experimental_unit_type is None:
        raise ValidationError("Expected organism roster requires experimental_unit_type")

    rows = list(observations)
    observed_units = {row.experimental_unit_id for row in rows}
    if None in observed_units:
        raise ValidationError("Expected organism roster requires unit IDs on all observations")
    if set(expected_by_unit) != observed_units:
        raise ValidationError("Expected organism roster must cover exactly the observed units")

    canonical: dict[str, list[str]] = {}
    assigned: set[str] = set()
    total = 0
    for unit_id, organism_ids in sorted(expected_by_unit.items()):
        if not isinstance(unit_id, str) or not unit_id or unit_id.strip() != unit_id:
            raise ValidationError("Expected roster unit IDs must be canonical nonempty strings")
        if not organism_ids:
            raise ValidationError("Expected organism roster cannot contain an empty unit")
        if len(organism_ids) != len(set(organism_ids)):
            raise ValidationError("Expected organism roster contains duplicate organism IDs")
        if any(
            not isinstance(organism_id, str)
            or not organism_id
            or organism_id.strip() != organism_id
            or len(organism_id) > 150
            for organism_id in organism_ids
        ):
            raise ValidationError("Expected organism IDs must be canonical nonempty strings")
        if assigned.intersection(organism_ids):
            raise ValidationError("An expected organism cannot belong to multiple units")
        assigned.update(organism_ids)
        total += len(organism_ids)
        if total > 10000:
            raise ValidationError("Expected organism roster exceeds 10000 organisms")
        canonical[unit_id] = sorted(organism_ids)

    for row in rows:
        observed_unit_id = row.experimental_unit_id
        if observed_unit_id is None:
            raise ValidationError("Expected organism roster requires unit IDs on all observations")
        if row.organism_id not in canonical[observed_unit_id]:
            raise ValidationError("Observed organism is absent from its expected unit roster")
    return canonical
