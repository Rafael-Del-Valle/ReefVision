"""Fail-closed checks for caller-declared ecological lineage and unit labels.

These checks prevent known forms of pseudoreplication; they do not verify that
any claimed biological identity or experimental design is authentic.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from datetime import UTC, datetime
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
    normalized = unicodedata.normalize("NFKC", experimental_unit_type or "")
    split_label = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", normalized)
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


class RegisteredEcologicalUnit(Protocol):
    experimental_unit_type: str | None
    experimental_unit_id: str | None


def require_unique_ecological_unit_spellings(
    records: Iterable[RegisteredEcologicalUnit],
    *,
    default_unit_type: str | None = None,
) -> None:
    """Reject case-only aliases of one registered physical sampling unit.

    The same exact ID may be shared by organisms in one unit. Known sampling
    labels such as tank/aquarium are equivalent, but different sampling levels
    have separate namespaces. Request-level unit types apply when individual
    rows omit their type. Do not rewrite source IDs or claim independence.
    """
    spellings: dict[tuple[str, str], str] = {}
    for record in records:
        unit_type = record.experimental_unit_type or default_unit_type
        unit_id = record.experimental_unit_id
        if unit_type is None or unit_id is None:
            continue
        level = classify_ecological_unit_level(unit_type) or unit_type.casefold()
        key = (level, unit_id.casefold())
        prior = spellings.setdefault(key, unit_id)
        if prior != unit_id:
            raise ValueError(
                "Ecological experimental unit IDs differ only by case at the same sampling level"
            )


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


def require_unique_ecological_organism_key_spellings(keys: Iterable[str]) -> None:
    """Reject case and Unicode-compatibility aliases of biological identities.

    Imported records can bypass the ASCII-only registration schema; fullwidth
    or other compatibility spellings must not create independent organisms.
    Preserve original identifiers and repeated exact-key revisions. This
    does not prove that differently named organisms are biologically distinct.
    """
    spellings: dict[str, str] = {}
    for key in keys:
        canonical = unicodedata.normalize("NFKC", key).casefold()
        prior = spellings.setdefault(canonical, key)
        if prior != key:
            raise ValueError(
                "Ecological organism keys differ only by case or Unicode compatibility"
            )


class CurrentEcologicalParentRecord(Protocol):
    """Latest registered identity used to check current parent relationships."""

    organism_key: str
    kind: str
    parent_colony_key: str | None


def require_current_ecological_parent_registration(
    records: Iterable[CurrentEcologicalParentRecord],
) -> None:
    """Reject latest fragment links to absent or reclassified parent colonies.

    A historically valid parent can later be reclassified in an imported
    revision. Both project reads and saved-workflow replay must reject the
    resulting inconsistent *current* lineage, even with recomputed digests.
    This is identity consistency, not verification of biological parentage.
    """
    latest = {record.organism_key: record for record in records}
    for record in latest.values():
        if record.parent_colony_key is None:
            continue
        parent = latest.get(record.parent_colony_key)
        if record.kind != "fragment" or parent is None or parent.kind != "colony":
            raise ValueError("Ecological identity registry contains an invalid parent-colony link")


class ChronologicalEcologicalIdentityRevision(Protocol):
    """Identity revision carrying its recorded audit timestamp."""

    organism_key: str
    revision: int
    created_at: datetime


def _identity_revision_utc(value: datetime) -> datetime:
    """Normalize application UTC timestamps and offset-aware imports."""
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class HistoricalEcologicalParentRevision(ChronologicalEcologicalIdentityRevision, Protocol):
    kind: str
    parent_colony_key: str | None


def require_historical_ecological_parent_registration(
    records: Iterable[HistoricalEcologicalParentRevision],
) -> None:
    """Fail closed if a fragment predates its registered parent-colony identity.

    The append-only API requires a parent to be registered as a colony before
    linking a fragment. Imported histories and re-signed workflow artifacts
    must honor that same provenance ordering. This checks recorded identity
    chronology, not biological parentage or timestamp authorship.
    """
    rows = list(records)
    by_key: dict[str, list[HistoricalEcologicalParentRevision]] = {}
    for row in rows:
        by_key.setdefault(row.organism_key, []).append(row)

    for row in rows:
        parent_key = row.parent_colony_key
        if parent_key is None:
            continue
        if row.kind != "fragment" or parent_key == row.organism_key:
            raise ValueError("Historical ecological parent links require a distinct fragment")
        child_time = _identity_revision_utc(row.created_at)
        eligible = [
            parent
            for parent in by_key.get(parent_key, [])
            if _identity_revision_utc(parent.created_at) <= child_time
        ]
        if not eligible:
            raise ValueError(
                "Ecological fragment parent colony was not registered before fragment revision"
            )
        parent_at_link = max(
            eligible,
            key=lambda parent: (_identity_revision_utc(parent.created_at), parent.revision),
        )
        if parent_at_link.kind != "colony":
            raise ValueError("Ecological fragment parent was not a colony at fragment revision")


def require_chronological_ecological_identity_revisions(
    records: Iterable[ChronologicalEcologicalIdentityRevision],
) -> None:
    """Reject backwards identity history, normalizing offsets to UTC.

    SQLite returns naive UTC timestamps for some database backends. Treat
    those as UTC and permit equal timestamps when storage precision differs.
    This is chronology QC, not proof of audit record authorship.
    """
    previous_by_key: dict[str, datetime] = {}
    for row in sorted(records, key=lambda item: (item.organism_key, item.revision)):
        recorded_utc = _identity_revision_utc(row.created_at)
        previous = previous_by_key.get(row.organism_key)
        if previous is not None and recorded_utc < previous:
            raise ValueError("Ecological identity revision timestamps are not chronological")
        previous_by_key[row.organism_key] = recorded_utc
