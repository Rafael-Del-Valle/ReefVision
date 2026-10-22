"""Fail-closed checks for caller-declared ecological lineage and unit labels.

These checks prevent known forms of pseudoreplication; they do not verify that
any claimed biological identity or experimental design is authentic.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from reefvision.domain.errors import ValidationError


class DeclaredLineageRecord(Protocol):
    organism_id: str
    parent_colony_id: str | None
    experimental_unit_id: str | None


def validate_declared_lineage(
    records: Iterable[DeclaredLineageRecord], *, experimental_unit_type: str | None
) -> None:
    """Prevent conflicting organism, parent-colony, and independent-unit labels.

    Legacy records without parent-colony labels remain unverified, rather than
    being silently treated as source-confirmed colony membership. Once any
    parent is declared, the whole comparison must have lineage coverage.
    """
    rows = list(records)
    has_parent = any(row.parent_colony_id is not None for row in rows)
    if has_parent and any(row.parent_colony_id is None for row in rows):
        raise ValidationError(
            "Partial parent_colony_id coverage; declare lineage for every paired observation"
        )

    unit_type = (experimental_unit_type or "").strip().casefold().replace("-", "_")
    organism_units = {"organism", "individual", "fragment"}
    colony_units = {"colony", "parent_colony", "parent colony"}
    unit_to_organism: dict[str, str] = {}
    organism_to_parent: dict[str, str] = {}
    unit_to_parent: dict[str, str] = {}
    parent_to_unit: dict[str, str] = {}

    for row in rows:
        unit_id = row.experimental_unit_id
        if unit_type in organism_units and unit_id is not None:
            existing = unit_to_organism.setdefault(unit_id, row.organism_id)
            if existing != row.organism_id:
                raise ValidationError(
                    "One organism-level experimental unit cannot contain distinct organisms"
                )

        parent_id = row.parent_colony_id
        if parent_id is None:
            continue
        existing_parent = organism_to_parent.setdefault(row.organism_id, parent_id)
        if existing_parent != parent_id:
            raise ValidationError("An organism cannot change parent_colony_id")

        if unit_type in colony_units and unit_id is not None:
            existing_parent = unit_to_parent.setdefault(unit_id, parent_id)
            if existing_parent != parent_id:
                raise ValidationError(
                    "One colony-level experimental unit cannot contain different parent colonies"
                )
            existing_unit = parent_to_unit.setdefault(parent_id, unit_id)
            if existing_unit != unit_id:
                raise ValidationError(
                    "One parent colony cannot count as multiple independent colony units"
                )
