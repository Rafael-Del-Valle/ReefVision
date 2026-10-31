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


def classify_ecological_unit_level(experimental_unit_type: str | None) -> str | None:
    """Interpret common biological-unit aliases without claiming independence.

    Unknown study-specific units remain caller-declared and unverified.
    Ambiguous mixed-level labels fail closed for both analyses and registries.
    """
    # A CamelCase label can otherwise hide mixed biological levels (TankColony).
    # Keep the original declaration in provenance; normalize only for classification.
    split_label = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", experimental_unit_type or "")
    words = {
        word
        for word in re.findall(r"[a-z0-9]+", split_label.casefold())
        if word not in {"experimental", "independent", "biological", "unit", "units", "level"}
    }
    declared_levels = {
        level
        for level, vocabulary in (
            (
                "organism",
                {"organism", "organisms", "individual", "individuals", "fragment", "fragments"},
            ),
            ("colony", {"colony", "colonies"}),
            ("tank", {"tank", "tanks", "aquarium", "aquaria"}),
            ("site", {"site", "sites", "plot", "plots", "transect", "transects"}),
        )
        if words & vocabulary
    }
    if len(declared_levels) > 1:
        raise ValidationError(
            "Ambiguous experimental_unit_type mixes biological sampling levels; "
            "declare one independent experimental unit"
        )
    return next(iter(declared_levels), None)


def ecological_unit_types_equivalent(left: str, right: str) -> bool:
    """Compare declared sampling levels without authenticating study design.

    Known biological aliases (tank/aquarium, colony/colonies, etc.) are
    equivalent. Unknown study-specific labels must match exactly; mixed
    biological levels still fail closed.
    """
    left_level = classify_ecological_unit_level(left)
    right_level = classify_ecological_unit_level(right)
    return left == right or (left_level is not None and left_level == right_level)


def canonical_declared_unit_type(labels: Iterable[str]) -> str | None:
    """Choose a deterministic display level for compatible declarations.

    Preserve the original label for homogeneous inputs to avoid changing
    existing output contracts. Mixed known aliases use the canonical level;
    None signals conflicting or unrecognized mixed declarations.
    """
    unique = sorted(set(labels))
    if not unique:
        return None
    if any(not ecological_unit_types_equivalent(unique[0], label) for label in unique[1:]):
        return None
    return unique[0] if len(unique) == 1 else classify_ecological_unit_level(unique[0])


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

    level = classify_ecological_unit_level(experimental_unit_type)
    organism_level = level == "organism"
    colony_level = level == "colony"

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
        units_by_parent.setdefault(record.parent_colony_id, set()).add(record.experimental_unit_id)
    return sorted(parent for parent, units in units_by_parent.items() if len(units) > 1)
