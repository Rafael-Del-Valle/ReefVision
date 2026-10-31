"""Stable input fingerprints for exploratory ecological workflow artifacts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from typing import Any

from pydantic import BaseModel

from reefvision.schemas.scientific_provenance import ScientificInputProvenance


def scientific_input_provenance(
    *,
    algorithm_version: str,
    records: Iterable[BaseModel],
    parameters: Mapping[str, Any],
    source_record_ids: Iterable[str],
) -> ScientificInputProvenance:
    """Hash canonical, normalized *inputs*, independent of record ordering.

    Pydantic JSON mode normalizes timezone-aware datetimes before encoding.
    A SHA-256 fingerprint detects changed inputs but does not verify that
    caller-supplied records, organism identities or calibrations are genuine.
    """
    normalized = [record.model_dump(mode="json") for record in records]
    encoded_rows = [
        json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False)
        for row in normalized
    ]
    canonical = json.dumps(
        {
            "algorithm_version": algorithm_version,
            "parameters": dict(parameters),
            "records": sorted(encoded_rows),
        },
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return ScientificInputProvenance(
        algorithm_version=algorithm_version,
        canonical_input_sha256=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        source_record_ids=sorted(source_record_ids),
    )
