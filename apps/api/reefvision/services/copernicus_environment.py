"""Bounded optional Copernicus acquisition into the existing scientific cache."""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError as SchemaError
from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import EnvironmentalCacheEntry
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.schemas.copernicus import CopernicusRequest
from reefvision.schemas.environmental_context import EnvironmentalImportResponse
from reefvision.schemas.scientific_data import ScientificRecordCreate, utc_timestamp
from reefvision.services.environmental_context import EnvironmentalContextService, _utc
from reefvision.services.scientific_data import content_hash

SOURCE_URL = "https://data.marine.copernicus.eu/"
MAX_SAMPLES = 5000


def fetch_copernicus(request: CopernicusRequest, settings: Settings) -> dict[str, Any]:
    if not settings.copernicus_username or not settings.copernicus_password:
        raise ValidationError(
            "Copernicus credentials are not configured in the backend environment"
        )
    executable = settings.copernicus_python_executable
    if executable is None:
        if getattr(sys, "frozen", False):
            raise ValidationError(
                "Configure the optional Copernicus Python runtime; cached "
                "data remains available offline"
            )
        executable = Path(sys.executable)
    if not executable.is_absolute() or not executable.is_file():
        raise ValidationError(
            "Copernicus Python runtime must be an existing absolute executable path"
        )
    environment = {
        **os.environ,
        "COPERNICUSMARINE_SERVICE_USERNAME": settings.copernicus_username.get_secret_value(),
        "COPERNICUSMARINE_SERVICE_PASSWORD": settings.copernicus_password.get_secret_value(),
    }
    try:
        result = subprocess.run(
            [str(executable), str(Path(__file__).with_name("copernicus_worker.py"))],
            input=request.model_dump_json(exclude={"offline", "refresh"}),
            text=True,
            capture_output=True,
            timeout=90,
            check=False,
            env=environment,
        )
        if result.returncode != 0 or len(result.stdout.encode()) > 8_000_000:
            raise ValueError("Worker failed or exceeded response limit")
        raw = json.loads(result.stdout)
        if not isinstance(raw, dict) or "error" in raw:
            raise ValueError("Invalid provider response")
        return raw
    except (OSError, subprocess.TimeoutExpired, ValueError):
        raise ValidationError(
            "Copernicus acquisition failed or timed out. Verify the optional "
            "Toolbox runtime, credentials, dataset/version and bounds; "
            "the previous cache is unchanged."
        ) from None


def _quantity(variable: str, unit: str, standard_name: str) -> tuple[str, str]:
    if variable in ("uo", "vo"):
        expected = (
            "eastward_sea_water_velocity" if variable == "uo" else "northward_sea_water_velocity"
        )
        if standard_name != expected or unit not in {"m s-1", "m/s", "m s^-1"}:
            raise ValidationError(
                "Currents require geographic east/north components in m/s; "
                "grid-relative velocities are unsupported"
            )
        return (
            "current_eastward_velocity" if variable == "uo" else "current_northward_velocity",
            "m/s",
        )
    if variable == "thetao" and standard_name == "sea_water_potential_temperature":
        units = {"degrees_C": "degC", "degree_Celsius": "degC", "degC": "degC", "K": "K"}
        if unit in units:
            return "water_potential_temperature", units[unit]
    if (
        variable == "so"
        and (unit.lower() in {"psu", "1e-3"})
        and standard_name == "sea_water_practical_salinity"
    ):
        return "practical_salinity", "PSU"
    raise ValidationError(
        "Unsupported or ambiguous Copernicus unit/standard_name; do not "
        "infer salinity scale or in-situ temperature"
    )


def _finite_number(value: Any) -> bool:
    """Reject non-finite and nonnumeric provider values before scientific persistence."""
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def parse_copernicus(
    raw: dict[str, Any], request: CopernicusRequest, acquired_at: datetime
) -> tuple[list[ScientificRecordCreate], int]:
    if (
        raw.get("dataset_id") != request.dataset_id
        or raw.get("dataset_version") != request.dataset_version
    ):
        raise ValidationError(
            "Copernicus dataset/version differs from the requested pinned dataset"
        )
    samples = raw.get("samples")
    if not isinstance(samples, list) or not 1 <= len(samples) <= MAX_SAMPLES:
        raise ValidationError("Copernicus response must contain 1 to 5000 samples")
    records = []
    missing = 0
    seen = set()
    for sample in samples:
        try:
            variable = sample["variable"]
            if variable not in request.variables:
                raise ValueError("Unexpected variable")
            name, unit = _quantity(variable, sample["unit"], sample["standard_name"])
            time = utc_timestamp(
                datetime.fromisoformat(sample["observed_at"].replace("Z", "+00:00"))
            )
            if not all(
                _finite_number(sample[field])
                for field in ("longitude", "latitude", "depth_m")
            ):
                raise ValueError("Non-finite or nonnumeric Copernicus grid coordinates")
            if sample["value"] is not None and not _finite_number(sample["value"]):
                raise ValueError("Non-finite or nonnumeric Copernicus grid value")
            if not (
                request.start_datetime <= time <= request.end_datetime
                and request.minimum_longitude <= sample["longitude"] <= request.maximum_longitude
                and request.minimum_latitude <= sample["latitude"] <= request.maximum_latitude
                and request.minimum_depth <= sample["depth_m"] <= request.maximum_depth
            ):
                raise ValueError("Sample outside requested extent, time or depth")
            identity = (variable, time, sample["depth_m"], sample["latitude"], sample["longitude"])
            if identity in seen:
                raise ValueError("Duplicate grid sample")
            seen.add(identity)
            if sample["value"] is None:
                missing += 1
                continue
            records.append(
                ScientificRecordCreate.model_validate(
                    {
                        "variable": name,
                        "value": sample["value"],
                        "unit": unit,
                        "observed_at": time,
                        "source_kind": "modeled",
                        "depth_m": sample["depth_m"],
                        "depth_reference": "sea_surface",
                        "location": {
                            "latitude": sample["latitude"],
                            "longitude": sample["longitude"],
                        },
                        "qc": "unassessed",
                        "qc_flags": ["model_value_not_observation"],
                        "provenance": {
                            "source": "Copernicus Marine",
                            "source_url": SOURCE_URL,
                            "dataset_id": request.dataset_id,
                            "model_version": request.dataset_version,
                            "acquired_at": acquired_at,
                            "method": "copernicus_rectilinear_grid_no_interpolation",
                            "temporal_resolution_s": raw.get("coordinate_resolution", {}).get(
                                "time"
                            ),
                            "processing_parameters": request.model_dump(
                                mode="json", exclude={"offline", "refresh"}
                            ),
                            "source_metadata": {
                                "provider_variable": variable,
                                "provider_unit": sample["unit"],
                                "standard_name": sample["standard_name"],
                                "toolbox_version": raw.get("toolbox_version"),
                                "dataset": raw.get("dataset_metadata", {}),
                                "coordinate_resolution": raw.get("coordinate_resolution", {}),
                            },
                        },
                    }
                )
            )
        except (KeyError, TypeError, ValueError, SchemaError) as exc:
            raise ValidationError(f"Invalid Copernicus grid sample: {exc}") from exc
    if not records:
        raise ValidationError("Copernicus subset contains no available ocean values")
    return records, missing


class CopernicusEnvironmentService:
    def __init__(
        self,
        session: Session,
        settings: Settings,
        *,
        fetch: Callable[[CopernicusRequest, Settings], dict[str, Any]] = fetch_copernicus,
        now: datetime | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.fetch = fetch
        self.environment = EnvironmentalContextService(session, now=now)

    def acquire(self, project_id: str, request: CopernicusRequest) -> EnvironmentalImportResponse:
        env = self.environment
        env.science.require_project(project_id)
        identity = {
            "provider": "copernicus_marine",
            "request": request.model_dump(mode="json", exclude={"offline", "refresh"}),
        }
        key = content_hash(identity)
        entry = self.session.scalar(
            select(EnvironmentalCacheEntry).where(
                EnvironmentalCacheEntry.project_id == project_id,
                EnvironmentalCacheEntry.cache_key == key,
            )
        )
        if entry is not None:
            env._cache_response(entry, "integrity_check")
            if request.offline or (not request.refresh and env.now < _utc(entry.expires_at)):
                return env._cache_response(
                    entry, "fresh" if env.now < _utc(entry.expires_at) else "stale_offline"
                )
        elif request.offline:
            raise NotFoundError("No cached Copernicus subset matches these exact parameters")
        raw = self.fetch(request, self.settings)
        records, missing = parse_copernicus(raw, request, env.now)
        return env.store_dataset(
            project_id,
            identity=identity,
            source_url=SOURCE_URL,
            raw=raw,
            items=records,
            missing=missing,
            entry=entry,
        )
