"""Deterministic audit of unverified registered design and lineage revisions."""

from __future__ import annotations

from reefvision.domain.ecology_lineage_policy import classify_ecological_unit_level
from reefvision.schemas.ecology_identity import (
    EcologyCrossUnitParentDetail,
    EcologyDesignChangedField,
    EcologyHistoricalCrossUnitParentDetail,
    EcologyHistoricalParentAssignment,
    EcologyDesignRevisionChange,
    EcologyIdentityRow,
)

DESIGN_FIELDS: tuple[EcologyDesignChangedField, ...] = (
    "kind",
    "parent_colony_key",
    "experimental_unit_type",
    "experimental_unit_id",
)


def derive_ecology_design_changes(
    history: list[EcologyIdentityRow],
) -> list[EcologyDesignRevisionChange]:
    """Report assignment changes, excluding reason-only revisions."""
    previous_by_key: dict[str, EcologyIdentityRow] = {}
    events: list[EcologyDesignRevisionChange] = []
    for current in sorted(history, key=lambda row: (row.organism_key, row.revision)):
        previous = previous_by_key.get(current.organism_key)
        if previous is not None:
            changed: list[EcologyDesignChangedField] = [
                field
                for field in DESIGN_FIELDS
                if getattr(previous, field) != getattr(current, field)
            ]
            if changed:
                events.append(
                    EcologyDesignRevisionChange(
                        organism_key=current.organism_key,
                        from_revision=previous.revision,
                        to_revision=current.revision,
                        changed_fields=changed,
                        previous_kind=previous.kind,
                        current_kind=current.kind,
                        previous_parent_colony_key=previous.parent_colony_key,
                        current_parent_colony_key=current.parent_colony_key,
                        previous_experimental_unit_type=previous.experimental_unit_type,
                        previous_experimental_unit_id=previous.experimental_unit_id,
                        current_experimental_unit_type=current.experimental_unit_type,
                        current_experimental_unit_id=current.experimental_unit_id,
                    )
                )
        previous_by_key[current.organism_key] = current
    return events


def derive_cross_unit_parent_details(
    identities: list[EcologyIdentityRow],
) -> list[EcologyCrossUnitParentDetail]:
    """Return auditable fragment and unit IDs without pooling sampling levels.

    These are unverified registrations, not proof of biological dependence.
    """
    grouped: dict[tuple[str, str], dict[str, set[str]]] = {}
    for row in identities:
        if row.kind != "fragment" or row.parent_colony_key is None:
            continue
        if row.experimental_unit_type is None or row.experimental_unit_id is None:
            continue
        level = (
            classify_ecological_unit_level(row.experimental_unit_type)
            or row.experimental_unit_type.casefold()
        )
        units = grouped.setdefault((row.parent_colony_key, level), {})
        units.setdefault(row.experimental_unit_id, set()).add(row.organism_key)
    return [
        EcologyCrossUnitParentDetail(
            parent_colony_key=parent,
            experimental_unit_level=level,
            experimental_unit_ids=sorted(units),
            fragment_keys=sorted({key for members in units.values() for key in members}),
        )
        for (parent, level), units in sorted(grouped.items())
        if len(units) > 1
    ]


def derive_cross_unit_shared_parent_colony_keys(
    identities: list[EcologyIdentityRow],
) -> list[str]:
    """Disclose shared parents, retaining the original backward-compatible field."""
    return sorted(
        {detail.parent_colony_key for detail in derive_cross_unit_parent_details(identities)}
    )


def derive_historical_cross_unit_parent_details(
    history: list[EcologyIdentityRow],
) -> list[EcologyHistoricalCrossUnitParentDetail]:
    """Find parents ever *registered* in multiple units at one sampling level.

    Revisions can be corrections rather than movements; do not infer occupancy
    overlap, actual transfers, or independent biological replication.
    """
    grouped: dict[
        tuple[str, str], list[EcologyHistoricalParentAssignment]
    ] = {}
    for row in history:
        if row.kind != "fragment" or row.parent_colony_key is None:
            continue
        if row.experimental_unit_type is None or row.experimental_unit_id is None:
            continue
        level = (
            classify_ecological_unit_level(row.experimental_unit_type)
            or row.experimental_unit_type.casefold()
        )
        grouped.setdefault((row.parent_colony_key, level), []).append(
            EcologyHistoricalParentAssignment(
                organism_key=row.organism_key,
                identity_revision=row.revision,
                experimental_unit_type=row.experimental_unit_type,
                experimental_unit_id=row.experimental_unit_id,
            )
        )
    details: list[EcologyHistoricalCrossUnitParentDetail] = []
    for (parent, level), assignments in sorted(grouped.items()):
        units = sorted({item.experimental_unit_id for item in assignments})
        if len(units) < 2:
            continue
        details.append(
            EcologyHistoricalCrossUnitParentDetail(
                parent_colony_key=parent,
                experimental_unit_level=level,
                experimental_unit_ids=units,
                assignments=sorted(
                    assignments,
                    key=lambda item: (
                        item.experimental_unit_id,
                        item.organism_key,
                        item.identity_revision,
                        item.experimental_unit_type,
                    ),
                ),
            )
        )
    return details
