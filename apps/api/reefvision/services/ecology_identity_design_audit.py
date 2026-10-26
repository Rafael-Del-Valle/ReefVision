"""Deterministic audit of unverified registered design and lineage revisions."""

from __future__ import annotations

from reefvision.schemas.ecology_identity import (
    EcologyDesignChangedField,
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
