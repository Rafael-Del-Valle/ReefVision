"""Validated local current-grid adapter for offline researcher datasets."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.db.models import EnvironmentalCacheEntry
from reefvision.domain.errors import ValidationError
from reefvision.schemas.environmental_context import (
    EnvironmentalImportResponse,
    LocalCurrentGridImport,
)
from reefvision.schemas.scientific_data import ScientificRecordCreate
from reefvision.services.environmental_context import EnvironmentalContextService
from reefvision.services.scientific_data import content_hash


class LocalCurrentGridService:
    def __init__(self, session: Session) -> None:
        self.environment = EnvironmentalContextService(session)
        self.session = session

    def import_grid(
        self, project_id: str, request: LocalCurrentGridImport
    ) -> EnvironmentalImportResponse:
        self.environment.science.require_project(project_id)
        identity = {
            "provider": "local_current_grid",
            "dataset_id": request.dataset_id,
            "dataset_version": request.dataset_version,
        }
        key = content_hash(identity)
        existing = self.session.scalar(
            select(EnvironmentalCacheEntry).where(
                EnvironmentalCacheEntry.project_id == project_id,
                EnvironmentalCacheEntry.cache_key == key,
            )
        )
        if existing is not None:
            raise ValidationError(
                "This local dataset ID and version already exists; use a new explicit version"
            )
        records: list[ScientificRecordCreate] = []
        missing = 0
        seen: set[tuple[object, ...]] = set()
        for sample in request.samples:
            sample_key = (
                sample.observed_at,
                sample.depth_m,
                sample.latitude,
                sample.longitude,
            )
            if sample_key in seen:
                raise ValidationError("Local current grid contains a duplicate coordinate sample")
            seen.add(sample_key)
            for variable, value in (
                ("current_eastward_velocity", sample.eastward_velocity_m_s),
                ("current_northward_velocity", sample.northward_velocity_m_s),
            ):
                if value is None:
                    missing += 1
                    continue
                records.append(
                    ScientificRecordCreate.model_validate(
                        {
                            "variable": variable,
                            "value": value,
                            "unit": "m/s",
                            "observed_at": sample.observed_at,
                            "source_kind": request.source_kind,
                            "location": {
                                "crs": "EPSG:4326",
                                "latitude": sample.latitude,
                                "longitude": sample.longitude,
                            },
                            "depth_m": sample.depth_m,
                            "depth_reference": "sea_surface",
                            "qc": "unassessed",
                            "provenance": {
                                "source": request.source,
                                "dataset_id": request.dataset_id,
                                "model_version": request.dataset_version,
                                "acquired_at": request.acquired_at,
                                "method": "local_rectilinear_or_point_grid_no_interpolation",
                                "processing_parameters": {},
                                "source_metadata": {
                                    "component_semantics": "geographic_east_north",
                                    "coordinate_reference": "EPSG:4326",
                                },
                            },
                        }
                    )
                )
        if not records:
            raise ValidationError("Local current grid contains no available velocity components")
        raw = request.model_dump(mode="json")
        response = self.environment.store_dataset(
            project_id,
            identity=identity,
            source_url=f"local://current-grid/{request.dataset_id}/{request.dataset_version}",
            raw=raw,
            items=records,
            missing=missing,
            entry=None,
        )
        return response.model_copy(update={"cache_status": "imported"})
