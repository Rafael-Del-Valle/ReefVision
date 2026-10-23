"""Fail-closed checks for caller-declared ecological lineage and unit labels.

These checks prevent known forms of pseudoreplication; they do not verify that
any claimed biological identity or experimental design is authentic.
"""

from __future__ import annotations

import re
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

    # Recognize common plural and "-level" designations without conflating
    # parent colonies with the fragments that belong to them.
    words = [
        word
        for word in re.findall(r"[a-z0-9]+", (experimental_unit_type or "").casefold())
        if word not in {"experimental", "independent", "biological", "unit", "units", "level"}
    ]
    organism_units = {
        "organism",
        "organisms",
        "individual",
        "individuals",
        "fragment",
        "fragments",
    }
    colony_units = {"colony", "colonies"}
    organism_level = len(words) == 1 and words[0] in organism_units
    colony_level = (len(words) == 1 and words[0] in colony_units) or (
        len(words) == 2 and words[0] == "parent" and words[1] in colony_units
    )
    unit_to_organism: dict[str, str] = {}
    organism_to_parent: dict[str, str] = {}
    unit_to_parent: dict[str, str] = {}
    parent_to_unit: dict[str, str] = {}

    for row in rows:
        unit_id = row.experimental_unit_id
        if organism_level and unit_id is not None:
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

        if colony_level and unit_id is not None:
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



def cross_unit_shared_parent_colony_ids(
    records: Iterable[DeclaredLineageRecord],
) -> list[str]:
    """Flag declared parent colonies represented in multiple sampling units.

    This is a study-design review signal, not proof that tanks are dependent.
    Biological parentage and experimental-unit labels remain unauthenticated.
    """
    units_by_parent: dict[str, set[str]] = {}
    for record in records:
        if record.parent_colony_id is None or record.experimental_unit_id is None:
            continue
        units_by_parent.setdefault(record.parent_colony_id, set()).add(
            record.experimental_unit_id
        )
    return sorted(parent for parent, units in units_by_parent.items() if len(units) > 1)
