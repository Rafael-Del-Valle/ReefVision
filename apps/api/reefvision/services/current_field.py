"""Build a provenance-compatible current grid from numeric scientific records."""

from __future__ import annotations

from sqlalchemy.orm import Session

from reefvision.db.models.scientific_record import ScientificRecord
from reefvision.domain.current_field import ALGORITHM_VERSION, CurrentField, integrate_streamline
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.schemas.current_field import (
    CurrentFieldPoint,
    CurrentFieldStreamline,
    CurrentFieldStreamlineRequest,
    CurrentFieldStreamlineResponse,
)
from reefvision.schemas.scientific_data import ScientificRecordResponse
from reefvision.services.scientific_data import ScientificDataService, content_hash

EAST = "current_eastward_velocity"
NORTH = "current_northward_velocity"


class CurrentFieldService:
    def __init__(self, session: Session) -> None:
        self.session = session

    @staticmethod
    def _identity(record: ScientificRecordResponse) -> tuple[object, ...]:
        provenance = record.provenance
        return (
            record.observed_at,
            record.source_kind,
            record.depth_m,
            record.depth_reference,
            provenance.source,
            provenance.dataset_id,
            provenance.model_version,
            record.environmental_cache_key,
        )

    def preview(
        self, project_id: str, request: CurrentFieldStreamlineRequest
    ) -> CurrentFieldStreamlineResponse:
        identifiers = [str(value) for value in request.scientific_record_ids]
        if len(set(identifiers)) != len(identifiers):
            raise ValidationError("Scientific record identifiers must be unique")
        data_service = ScientificDataService(self.session)
        records: list[ScientificRecordResponse] = []
        for identifier in identifiers:
            row = self.session.get(ScientificRecord, identifier)
            if row is None or row.project_id != project_id:
                raise NotFoundError("Project scientific record not found")
            records.append(data_service.response(row))
        if any(record.environmental_snapshot_current is False for record in records):
            raise ValidationError("Current fields cannot use an obsolete environmental snapshot")
        if any(record.calibration_current is False for record in records):
            raise ValidationError("Current fields cannot use an obsolete spatial calibration")
        if len({self._identity(record) for record in records}) != 1:
            raise ValidationError(
                "Current components must share UTC, depth, source, dataset, "
                "model, and cache identity"
            )
        if any(record.variable not in {EAST, NORTH} for record in records):
            raise ValidationError(
                "Current fields accept only eastward and northward velocity records"
            )
        if any(record.normalized_unit != "m/s" for record in records):
            raise ValidationError("Current velocity records must normalize to m/s")
        if any(record.location is None for record in records):
            raise ValidationError("Every current record requires an EPSG:4326 location")
        if any(record.qc in {"suspect", "rejected"} for record in records):
            raise ValidationError(
                "Suspect or rejected current records cannot define a streamline field"
            )

        latitudes = sorted({record.location.latitude for record in records if record.location})
        longitudes = sorted({record.location.longitude for record in records if record.location})
        if len(latitudes) < 2 or len(longitudes) < 2:
            raise ValidationError("Current field requires at least a 2 by 2 paired component grid")
        if any(right - left > 180.0 for left, right in zip(longitudes, longitudes[1:])):
            raise ValidationError(
                "Current longitude gap exceeds 180 degrees; "
                "antimeridian-spanning grids require regridding before integration"
            )
        indexed: dict[tuple[float, float, str], ScientificRecordResponse] = {}
        for record in records:
            assert record.location is not None
            key = (record.location.latitude, record.location.longitude, record.variable)
            if key in indexed:
                raise ValidationError("Current grid contains duplicate component records")
            indexed[key] = record
        required = {
            (latitude, longitude, variable)
            for latitude in latitudes
            for longitude in longitudes
            for variable in (EAST, NORTH)
        }
        if set(indexed) != required:
            raise ValidationError("Current field requires a complete paired component grid")
        east = tuple(
            tuple(indexed[(latitude, longitude, EAST)].normalized_value for longitude in longitudes)
            for latitude in latitudes
        )
        north = tuple(
            tuple(
                indexed[(latitude, longitude, NORTH)].normalized_value for longitude in longitudes
            )
            for latitude in latitudes
        )
        field = CurrentField(tuple(latitudes), tuple(longitudes), east, north)
        streamlines = []
        for seed in request.seeds:
            line = integrate_streamline(
                field,
                seed.latitude,
                seed.longitude,
                step_seconds=request.step_seconds,
                max_steps=request.max_steps,
                max_length_m=request.max_length_m,
                stagnation_m_s=request.stagnation_m_s,
            )
            streamlines.append(
                CurrentFieldStreamline(
                    points=[CurrentFieldPoint(**point.__dict__) for point in line.points],
                    termination=line.termination,
                    length_m=line.length_m,
                )
            )
        snapshot = [record.model_dump(mode="json") for record in records]
        first = records[0]
        return CurrentFieldStreamlineResponse(
            algorithm_version=ALGORITHM_VERSION,
            project_id=project_id,
            source_record_ids=identifiers,
            observed_at=first.observed_at,
            source_kind=first.source_kind,
            depth_m=first.depth_m,
            depth_reference=first.depth_reference,
            environmental_cache_key=first.environmental_cache_key,
            latitudes=latitudes,
            longitudes=longitudes,
            input_sha256=content_hash(snapshot),
            streamlines=streamlines,
            methodological_notes=[
                "Streamlines describe a frozen Eulerian current field; "
                "they are not organism trajectories.",
                "Bilinear interpolation requires four QC-compatible corners "
                "and never extrapolates.",
                "All source records share one UTC, depth, dataset/model, and cache identity.",
            ],
        )
