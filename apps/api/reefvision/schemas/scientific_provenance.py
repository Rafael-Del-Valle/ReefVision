"""Immutable-description metadata for caller-supplied ecological analyses."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ScientificInputProvenance(BaseModel):
    """A reproducibility fingerprint, NOT evidence of authenticated sources."""

    algorithm_version: str
    canonicalization: Literal["normalized_sorted_json_v1"] = "normalized_sorted_json_v1"
    canonical_input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_record_ids: list[str]
    source_verification: Literal["caller_supplied_unverified"] = "caller_supplied_unverified"
