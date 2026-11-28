"""Reviewed assignments within the organism registry."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Annotated, Literal, Protocol

from pydantic import AwareDatetime, BaseModel, ConfigDict, StringConstraints, model_validator

from reefvision.domain.ecology_lineage_policy import classify_ecological_unit_level

StudyCode = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
StudyUnitType = Literal[
    "individual", "fragment", "colony", "quadrat", "transect", "sample", "quadrant"
]


class EcologyStudyAssignmentFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tank_code: StudyCode | None = None
    site_code: StudyCode | None = None
    treatment_code: StudyCode | None = None
    sampling_unit_type: StudyUnitType | None = None
    sampling_unit_id: StudyCode | None = None
    reviewer: StudyCode
    notes: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] = ""

    @model_validator(mode="after")
    def validate_assignment(self) -> EcologyStudyAssignmentFields:
        if not any((self.tank_code, self.site_code, self.treatment_code, self.sampling_unit_id)):
            raise ValueError("Record at least one study assignment")
        if (self.sampling_unit_type is None) != (self.sampling_unit_id is None):
            raise ValueError("Sampling unit type and ID are required together")
        return self


class EcologyStudyAssignmentCreate(EcologyStudyAssignmentFields):
    confirm_review: Literal[True]


class EcologyStudyAssignmentRead(EcologyStudyAssignmentFields):
    review_status: Literal["reviewed"] = "reviewed"
    reviewed_at: AwareDatetime


class StudyIdentity(Protocol):
    @property
    def experimental_unit_id(self) -> str | None: ...

    @property
    def experimental_unit_type(self) -> str | None: ...


def validate_study_assignments(
    rows: Iterable[tuple[StudyIdentity, EcologyStudyAssignmentFields | None]],
) -> None:
    """Keep each declared experimental or sampling unit in one design context."""
    labels: dict[tuple[str, str], str] = {}
    tanks: dict[str, dict[str, str]] = {}
    units: dict[tuple[str, str], dict[str, str]] = {}
    sampling_parents: dict[tuple[str, str], dict[str, str]] = {}

    for identity, assignment in rows:
        if assignment is None:
            continue
        unit_type, unit_id = identity.experimental_unit_type, identity.experimental_unit_id
        if unit_type is None or unit_id is None:
            raise ValueError("Reviewed study assignments require an experimental unit")
        level = classify_ecological_unit_level(unit_type) or unit_type.casefold()
        tank = assignment.tank_code
        site = assignment.site_code
        treatment = assignment.treatment_code
        if level == "tank" and tank != unit_id:
            raise ValueError("A tank-based experimental unit must use its tank ID")

        for field in ("tank_code", "site_code", "treatment_code", "sampling_unit_id"):
            value = getattr(assignment, field)
            if value is not None:
                key = (field, value.casefold())
                if labels.setdefault(key, value) != value:
                    raise ValueError(f"Use a single spelling for {field}")

        experimental = units.setdefault((level, unit_id), {})
        _check_context(experimental, "tank", tank)
        _check_context(experimental, "site", site)
        _check_context(experimental, "treatment", treatment)
        if tank:
            declared_tank = tanks.setdefault(tank, {})
            _check_context(declared_tank, "site", site)
            _check_context(declared_tank, "treatment", treatment)
        if assignment.sampling_unit_type and assignment.sampling_unit_id:
            sampling = sampling_parents.setdefault(
                (assignment.sampling_unit_type, assignment.sampling_unit_id), {}
            )
            _check_context(sampling, "experimental unit", f"{level}/{unit_id}")
            _check_context(sampling, "tank", tank)
            _check_context(sampling, "site", site)


def _check_context(context: dict[str, str], field: str, value: str | None) -> None:
    if value is not None and context.setdefault(field, value) != value:
        raise ValueError(
            f"One experimental or sampling unit cannot span conflicting {field} records"
        )


def study_assignment_signature(
    assignment: EcologyStudyAssignmentRead | None,
) -> dict[str, str | None] | None:
    if assignment is None:
        return None
    return {
        "tank_code": assignment.tank_code,
        "site_code": assignment.site_code,
        "treatment_code": assignment.treatment_code,
        "sampling_unit_type": assignment.sampling_unit_type,
        "sampling_unit_id": assignment.sampling_unit_id,
    }


def save_reviewed_study(
    assignment: EcologyStudyAssignmentCreate, reviewed_at: datetime
) -> dict[str, object]:
    return EcologyStudyAssignmentRead(
        **assignment.model_dump(exclude={"confirm_review"}), reviewed_at=reviewed_at
    ).model_dump(mode="json")
