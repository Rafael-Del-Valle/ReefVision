"""NOAA CO-OPS water-temperature adapter. Never invent missing sensor values."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
from pydantic import ValidationError as SchemaError

from reefvision.domain.errors import ValidationError
from reefvision.schemas.environmental_context import NOAAImportRequest
from reefvision.schemas.scientific_data import ScientificRecordCreate

NOAA_URL = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"


def noaa_request_url(request: NOAAImportRequest) -> str:
    return str(
        httpx.URL(
            NOAA_URL,
            params={
                "station": request.station_id,
                "begin_date": request.day.strftime("%Y%m%d"),
                "end_date": request.day.strftime("%Y%m%d"),
                "product": "water_temperature",
                "time_zone": "gmt",
                "units": "metric",
                "format": "json",
                "application": "ReefVision",
            },
        )
    )


def fetch_noaa(http: httpx.Client, url: str) -> dict[str, Any]:
    try:
        response = http.get(url, timeout=20, follow_redirects=False)
        response.raise_for_status()
        if len(response.content) > 2_000_000:
            raise ValidationError("NOAA response exceeds the bounded daily dataset size")
        raw = response.json()
        if not isinstance(raw, dict):
            raise ValueError("Expected a NOAA JSON object")
        return raw
    except (httpx.HTTPError, ValueError) as exc:
        raise ValidationError(
            "NOAA data could not be acquired; use offline mode for an existing cache"
        ) from exc


def parse_noaa(
    raw: dict[str, Any], request: NOAAImportRequest, acquired_at: datetime, source_url: str
) -> tuple[list[ScientificRecordCreate], int]:
    if "error" in raw:
        raise ValidationError("NOAA reports unavailable observations for this station and day")
    records = []
    missing = 0
    try:
        metadata = raw["metadata"]
        if str(metadata["id"]) != request.station_id:
            raise ValueError("NOAA response station does not match the request")
        data = raw["data"]
        if not isinstance(data, list) or len(data) > 5000:
            raise ValueError("Invalid daily NOAA response size")
        for item in data:
            timestamp = datetime.strptime(item["t"], "%Y-%m-%d %H:%M").replace(tzinfo=UTC)
            if timestamp.date() != request.day:
                raise ValueError("NOAA response time lies outside the requested day")
            if item.get("v") in (None, ""):
                missing += 1
                continue
            flags = str(item.get("f", ""))
            flagged = any(flag.strip() not in ("", "0") for flag in flags.split(","))
            records.append(
                ScientificRecordCreate.model_validate(
                    {
                        "variable": "water_temperature",
                        "value": float(item["v"]),
                        "unit": "degC",
                        "observed_at": timestamp,
                        "source_kind": "observed",
                        "subject": request.subject.model_dump(mode="json"),
                        "location": {
                            "latitude": float(metadata["lat"]),
                            "longitude": float(metadata["lon"]),
                        },
                        "qc": "suspect" if flagged else "unassessed",
                        "qc_flags": [f"noaa_flags:{flags}"] if flags else [],
                        "provenance": {
                            "source": "NOAA CO-OPS",
                            "source_url": source_url,
                            "dataset_id": (
                                f"noaa-coops:{request.station_id}:water_temperature:{request.day}"
                            ),
                            "acquired_at": acquired_at,
                            "temporal_resolution_s": 360,
                            "source_metadata": {**item, "station": metadata},
                            "processing_parameters": {
                                "units": "metric",
                                "time_zone": "gmt",
                                "parser_version": "1.1.0",
                            },
                        },
                    }
                )
            )
    except (KeyError, TypeError, ValueError, SchemaError) as exc:
        raise ValidationError(f"Invalid NOAA observations: {exc}") from exc
    if not records:
        raise ValidationError("NOAA returned no usable observations; no values were fabricated")
    return records, missing
