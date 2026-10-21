"""Versioned calculations over immutable scientific record snapshots."""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from reefvision.db.models.scientific_record import ScientificRecord
from reefvision.domain.errors import ValidationError
from reefvision.domain.scientific_units import UNITS
from reefvision.schemas.scientific_calculations import ScientificCalculationRequest
from reefvision.schemas.scientific_data import ScientificRecordCreate, ScientificRecordResponse
from reefvision.services.scientific_data import ScientificDataService

CALCULATION_SOURCE = "ReefVision scientific calculation engine"
CALCULATION_QC_FLAG = "derived_requires_scientific_review"


@dataclass(frozen=True)
class CalculatedQuantity:
    variable: str
    value: float
    unit: str
    observed_at: datetime


def evaluate_calculation(
    request: ScientificCalculationRequest,
    inputs: list[ScientificRecordResponse],
) -> CalculatedQuantity:
    if any(item.qc in {"suspect", "rejected"} for item in inputs):
        raise ValidationError("Calculation inputs must pass scientific QC")
    scopes = {
        (
            item.subject.model_dump_json(),
            item.location.model_dump_json() if item.location is not None else None,
            item.pixel.model_dump_json() if item.pixel is not None else None,
            item.observed_at,
            item.depth_m,
            item.depth_reference,
            item.calibration_sha256,
        )
        for item in inputs
    }
    if len(scopes) != 1:
        raise ValidationError(
            "Calculation inputs must share one observation scope, including subject, "
            "location, time, depth, coordinate frame, and calibration"
        )
    formula = request.formula_id
    if formula == "count_records":
        value, unit, variable = float(len(inputs)), "count", "calculated_count"
    elif formula == "rectangular_area":
        if len(inputs) != 2 or any(UNITS[item.normalized_unit][0] != "length" for item in inputs):
            raise ValidationError("rectangular_area requires exactly two length records")
        if any(item.normalized_value <= 0 for item in inputs):
            raise ValidationError("rectangular_area requires positive length records")
        value = inputs[0].normalized_value * inputs[1].normalized_value
        unit, variable = "m2", "calculated_area"
    else:
        count = [item for item in inputs if item.normalized_unit == "count"]
        area = [item for item in inputs if item.normalized_unit == "m2"]
        if (
            len(inputs) != 2
            or len(count) != 1
            or len(area) != 1
            or count[0].normalized_value < 0
            or not count[0].normalized_value.is_integer()
            or area[0].normalized_value <= 0
        ):
            raise ValidationError(
                "density requires one nonnegative integer count record and one positive area record"
            )
        value = count[0].normalized_value / area[0].normalized_value
        unit, variable = "count/m2", "calculated_density"
    return CalculatedQuantity(
        variable=variable,
        value=value,
        unit=unit,
        observed_at=max(item.observed_at for item in inputs),
    )


class ScientificCalculationService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.science = ScientificDataService(session)

    def calculate(
        self, project_id: str, request: ScientificCalculationRequest
    ) -> ScientificRecordResponse:
        self.science.require_project(project_id)
        if len(set(request.input_record_ids)) != len(request.input_record_ids):
            raise ValidationError("Calculation input record IDs must be unique")
        rows = [
            self.session.get(ScientificRecord, str(record_id))
            for record_id in request.input_record_ids
        ]
        if any(row is None or row.project_id != project_id for row in rows):
            raise ValidationError("Every calculation input must belong to this project")
        inputs = [self.science.response(row) for row in rows if row is not None]
        if any(item.environmental_snapshot_current is False for item in inputs):
            raise ValidationError("Calculation inputs cannot use superseded environmental data")
        if any(item.calibration_current is False for item in inputs):
            raise ValidationError("Calculation inputs cannot use stale calibration snapshots")
        result = evaluate_calculation(request, inputs)
        formula = request.formula_id
        now = datetime.now(UTC)
        record = ScientificRecordCreate.model_validate(
            {
                "variable": result.variable,
                "value": result.value,
                "unit": result.unit,
                "observed_at": result.observed_at,
                "source_kind": "derived",
                "subject": inputs[0].subject,
                "location": inputs[0].location,
                "pixel": inputs[0].pixel,
                "depth_m": inputs[0].depth_m,
                "depth_reference": inputs[0].depth_reference,
                "qc": "unassessed",
                "qc_flags": [CALCULATION_QC_FLAG],
                "provenance": {
                    "source": CALCULATION_SOURCE,
                    "acquired_at": now,
                    "method": f"{formula}@{request.formula_version}",
                    "processing_parameters": {
                        "formula_id": formula,
                        "formula_version": request.formula_version,
                        "input_record_ids": [str(value) for value in request.input_record_ids],
                    },
                    "source_metadata": {
                        "input_content_sha256": [item.content_sha256 for item in inputs],
                        "input_calibration_sha256": [item.calibration_sha256 for item in inputs],
                    },
                },
            }
        )
        row = self.science.add_records(
            project_id,
            [record],
            calibration_snapshot=inputs[0].calibration_snapshot,
            use_subject_calibration=False,
        )[0]
        self.session.commit()
        return self.science.response(row)
