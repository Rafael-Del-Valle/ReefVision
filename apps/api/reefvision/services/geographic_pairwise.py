"""Immutable WGS84 pairwise measurements from persisted geographic observations."""

from __future__ import annotations

import csv
import io
import math
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from geographiclib.geodesic import Geodesic
from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.db.models import GeoReferencedObservation
from reefvision.db.models.computed_metric import ComputedMetricDefinition, ComputedMetricResult
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.schemas.geographic_pairwise import (
    GeographicPairwiseCalculateRequest,
    GeographicPairwiseMeasurement,
    GeographicPairwiseSavedResponse,
    GeographicPairwiseValidationResponse,
)
from reefvision.services.georeferenced_observations import GeoReferencedObservationService
from reefvision.services.scientific_data import content_hash

DEFINITION_KIND = "geographic_pairwise"
RESULT_KIND = "geographic_pairwise"
FORMULA_VERSION = "reefvision.geographic-pairwise.v1"
ALGORITHM = "reefvision.wgs84-pairwise-geodesic.v1"
EXPRESSION = "wgs84_inverse(endpoint_a, endpoint_b)"


def _definition_payload(row: ComputedMetricDefinition) -> dict[str, Any]:
    return {
        "name": row.name,
        "expression": row.expression,
        "formula_version": row.formula_version,
        "output_unit": row.output_unit,
        "configuration": row.configuration_json,
    }


class GeographicPairwiseService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _endpoint(
        self, project_id: str, observation_id: str, *, require_current: bool = True
    ) -> tuple[GeoReferencedObservation, dict[str, Any]]:
        row = self.session.get(GeoReferencedObservation, observation_id)
        if row is None or row.project_id != project_id:
            raise NotFoundError("Georeferenced observation not found in project")
        if require_current and row.is_stale:
            raise ValidationError(
                "Pairwise measurement requires current georeferenced observations"
            )
        response = GeoReferencedObservationService.to_response(row)
        snapshot = {
            "observation": response.model_dump(mode="json"),
            "configuration_hash": row.configuration_hash,
            "is_stale": row.is_stale,
            "stale_reason": row.stale_reason,
            "stale_at": row.stale_at.isoformat() if row.stale_at is not None else None,
        }
        return row, snapshot

    def _measurement(
        self,
        project_id: str,
        start_id: str,
        end_id: str,
    ) -> GeographicPairwiseMeasurement:
        start_row, start_snapshot = self._endpoint(project_id, start_id)
        end_row, end_snapshot = self._endpoint(project_id, end_id)
        if start_row.crs.strip().upper() != "EPSG:4326" or end_row.crs.strip().upper() != (
            "EPSG:4326"
        ):
            raise ValidationError("Pairwise geographic measurements require EPSG:4326 endpoints")
        inverse = Geodesic.WGS84.Inverse(
            start_row.latitude_deg,
            start_row.longitude_deg,
            end_row.latitude_deg,
            end_row.longitude_deg,
        )
        distance_m = float(inverse["s12"])
        initial_bearing = float(inverse["azi1"]) % 360.0 if distance_m > 0 else None
        bearing_reason = None if initial_bearing is not None else "coincident_locations"

        start_observation = GeoReferencedObservationService.to_response(start_row)
        end_observation = GeoReferencedObservationService.to_response(end_row)
        start_utc = start_observation.timestamp.utc
        end_utc = end_observation.timestamp.utc
        if (
            start_utc is not None
            and end_utc is not None
            and start_utc.utcoffset() is not None
            and end_utc.utcoffset() is not None
        ):
            signed_time_delta_s = (
                end_utc.astimezone(UTC) - start_utc.astimezone(UTC)
            ).total_seconds()
            time_basis = "utc"
            time_reason = None
        elif start_row.video_id == end_row.video_id:
            signed_time_delta_s = end_row.frame_time_s - start_row.frame_time_s
            time_basis = "same_video_frame_time"
            time_reason = None
        else:
            signed_time_delta_s = None
            time_basis = "unavailable"
            time_reason = "no_common_absolute_time_basis"

        start_uncertainty = start_observation.uncertainty
        end_uncertainty = end_observation.uncertainty
        distance_uncertainty: float | None = None
        bearing_uncertainty: float | None = None
        uncertainty_method = None
        uncertainty_reason: str | None = None
        if (
            start_uncertainty.horizontal_sigma_m is None
            or end_uncertainty.horizontal_sigma_m is None
        ):
            uncertainty_reason = "missing_endpoint_standard_uncertainty"
        elif (
            not start_uncertainty.correlation_group_id
            or not end_uncertainty.correlation_group_id
            or start_uncertainty.correlation_group_id == end_uncertainty.correlation_group_id
        ):
            uncertainty_reason = "unknown_or_shared_endpoint_correlation"
        else:
            distance_uncertainty = math.hypot(
                start_uncertainty.horizontal_sigma_m,
                end_uncertainty.horizontal_sigma_m,
            )
            uncertainty_method = "independent_isotropic_first_order"
            if distance_m == 0:
                uncertainty_reason = "coincident_locations"
            elif distance_m > 5.0 * distance_uncertainty:
                bearing_uncertainty = math.degrees(distance_uncertainty / distance_m)
            else:
                uncertainty_reason = "bearing_geometry_ill_conditioned"

        payload = {
            "schema_version": "1.1.0",
            "algorithm": ALGORITHM,
            "project_id": project_id,
            "start_observation_id": start_id,
            "end_observation_id": end_id,
            "start_snapshot": start_snapshot,
            "end_snapshot": end_snapshot,
            "start_snapshot_sha256": content_hash(start_snapshot),
            "end_snapshot_sha256": content_hash(end_snapshot),
            "coordinate_reference_system": "EPSG:4326",
            "distance_m": distance_m,
            "initial_bearing_deg": initial_bearing,
            "bearing_unavailable_reason": bearing_reason,
            "signed_time_delta_s": signed_time_delta_s,
            "absolute_time_delta_s": (
                abs(signed_time_delta_s) if signed_time_delta_s is not None else None
            ),
            "time_basis": time_basis,
            "time_unavailable_reason": time_reason,
            "distance_standard_uncertainty_m": distance_uncertainty,
            "bearing_standard_uncertainty_deg": bearing_uncertainty,
            "uncertainty_method": uncertainty_method,
            "uncertainty_unavailable_reason": uncertainty_reason,
            "methodological_notes": [
                "Distance and initial bearing use the WGS84 ellipsoidal inverse solution.",
                "Initial bearing describes endpoint displacement, not organism orientation "
                "or path.",
                "A pair is one descriptive measurement and is not an independent replicate claim.",
                "Uncertainty is propagated only for explicit independent isotropic one-sigma "
                "endpoints.",
            ],
        }
        return GeographicPairwiseMeasurement(**payload, content_sha256=content_hash(payload))

    def calculate(
        self,
        project_id: str,
        request: GeographicPairwiseCalculateRequest,
        *,
        workflow_run_id: str | None = None,
        workflow_node_run_id: str | None = None,
    ) -> GeographicPairwiseSavedResponse:
        configuration = {
            "schema_version": "1.1.0",
            "start_observation_id": str(request.start_observation_id),
            "end_observation_id": str(request.end_observation_id),
        }
        if workflow_node_run_id is not None:
            existing = self.session.scalar(
                select(ComputedMetricResult).where(
                    ComputedMetricResult.workflow_node_run_id == workflow_node_run_id
                )
            )
            if existing is not None:
                definition = self.session.get(ComputedMetricDefinition, existing.definition_id)
                if (
                    existing.project_id != project_id
                    or existing.result_kind != RESULT_KIND
                    or definition is None
                    or definition.configuration_json != configuration
                    or definition.name != request.name
                ):
                    raise ConflictError("Workflow node replay conflicts with saved pairwise result")
                return self._saved_response(project_id, existing.id)

        measurement = self._measurement(
            project_id, str(request.start_observation_id), str(request.end_observation_id)
        )
        definition = ComputedMetricDefinition(
            id=str(uuid4()),
            project_id=project_id,
            definition_kind=DEFINITION_KIND,
            name=request.name,
            expression=EXPRESSION,
            formula_version=FORMULA_VERSION,
            input_spec_json=[],
            configuration_json=configuration,
            output_unit="m",
            definition_sha256="",
        )
        definition.definition_sha256 = content_hash(_definition_payload(definition))
        self.session.add(definition)
        self.session.flush()
        result_payload = {
            "definition_id": definition.id,
            "definition_name": definition.name,
            "definition_sha256": definition.definition_sha256,
            "expression": definition.expression,
            "formula_version": definition.formula_version,
            "output_unit": definition.output_unit,
            "measurement": measurement.model_dump(mode="json"),
        }
        start_row = self.session.get(GeoReferencedObservation, str(request.start_observation_id))
        end_row = self.session.get(GeoReferencedObservation, str(request.end_observation_id))
        if start_row is None or end_row is None:
            raise NotFoundError("Georeferenced observation not found in project")
        result = ComputedMetricResult(
            id=str(uuid4()),
            project_id=project_id,
            result_kind=RESULT_KIND,
            definition_id=definition.id,
            observed_at=max(start_row.created_at, end_row.created_at),
            payload_json=result_payload,
            content_sha256=content_hash(result_payload),
            workflow_run_id=workflow_run_id,
            workflow_node_run_id=workflow_node_run_id,
        )
        self.session.add(result)
        self.session.commit()
        return self._saved_response(project_id, result.id)

    def _saved_response(self, project_id: str, result_id: str) -> GeographicPairwiseSavedResponse:
        result = self.session.get(ComputedMetricResult, result_id)
        if result is None or result.project_id != project_id or result.result_kind != RESULT_KIND:
            raise NotFoundError("Geographic pairwise result not found")
        if content_hash(result.payload_json) != result.content_sha256:
            raise ConflictError("Geographic pairwise result checksum mismatch")
        definition = self.session.get(ComputedMetricDefinition, result.definition_id)
        if (
            definition is None
            or definition.project_id != project_id
            or definition.definition_kind != DEFINITION_KIND
            or content_hash(_definition_payload(definition)) != definition.definition_sha256
        ):
            raise ConflictError("Geographic pairwise definition checksum mismatch")
        measurement = GeographicPairwiseMeasurement.model_validate(
            result.payload_json.get("measurement")
        )
        measurement_content = measurement.model_dump(mode="json", exclude={"content_sha256"})
        if content_hash(measurement_content) != measurement.content_sha256:
            raise ConflictError("Geographic pairwise measurement checksum mismatch")
        return GeographicPairwiseSavedResponse(
            definition_id=definition.id,
            result_id=result.id,
            definition_sha256=definition.definition_sha256,
            result_sha256=result.content_sha256,
            workflow_run_id=result.workflow_run_id,
            workflow_node_run_id=result.workflow_node_run_id,
            measurement=measurement,
        )

    def get_result(self, project_id: str, result_id: str) -> GeographicPairwiseSavedResponse:
        return self._saved_response(project_id, result_id)

    def validate_result(
        self, project_id: str, result_id: str
    ) -> GeographicPairwiseValidationResponse:
        saved = self._saved_response(project_id, result_id)
        reasons: list[str] = []
        current_hash: str | None = None
        try:
            current = self._measurement(
                project_id,
                str(saved.measurement.start_observation_id),
                str(saved.measurement.end_observation_id),
            )
            current_hash = current.content_sha256
            if current_hash != saved.measurement.content_sha256:
                reasons.append("endpoint_snapshot_changed")
        except (NotFoundError, ValidationError, ValueError):
            reasons.append("endpoint_unavailable_or_stale")
        return GeographicPairwiseValidationResponse(
            result_id=result_id,
            is_current=not reasons,
            reasons=reasons,
            stored_measurement_sha256=saved.measurement.content_sha256,
            current_measurement_sha256=current_hash,
            validated_at=datetime.now(UTC),
        )

    def result_csv(self, project_id: str, result_id: str) -> str:
        saved = self._saved_response(project_id, result_id)
        value = saved.measurement
        output = io.StringIO(newline="")
        writer = csv.DictWriter(
            output,
            fieldnames=[
                "result_id",
                "start_observation_id",
                "end_observation_id",
                "distance_m",
                "initial_bearing_deg_true_north",
                "signed_time_delta_s",
                "time_basis",
                "distance_standard_uncertainty_m",
                "bearing_standard_uncertainty_deg",
                "uncertainty_method",
                "measurement_sha256",
            ],
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerow(
            {
                "result_id": result_id,
                "start_observation_id": value.start_observation_id,
                "end_observation_id": value.end_observation_id,
                "distance_m": value.distance_m,
                "initial_bearing_deg_true_north": value.initial_bearing_deg,
                "signed_time_delta_s": value.signed_time_delta_s,
                "time_basis": value.time_basis,
                "distance_standard_uncertainty_m": value.distance_standard_uncertainty_m,
                "bearing_standard_uncertainty_deg": value.bearing_standard_uncertainty_deg,
                "uncertainty_method": value.uncertainty_method,
                "measurement_sha256": value.content_sha256,
            }
        )
        return output.getvalue()
