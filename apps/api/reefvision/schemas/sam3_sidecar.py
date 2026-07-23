"""SAM 3 localhost sidecar registration schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class Sam3SidecarRegistrationRequest(BaseModel):
    display_name: str = Field(default="SAM 3 concept segmenter", min_length=1, max_length=200)
    endpoint: str = Field(default="http://127.0.0.1:8765", min_length=1, max_length=500)
    concept_prompt: str = Field(min_length=1, max_length=500)
    label_class_id: str = Field(min_length=1, max_length=36)
    score_threshold: float = Field(default=0.35, ge=0, le=1)
    token_env: str = Field(
        default="REEFVISION_SAM3_SIDECAR_TOKEN",
        min_length=1,
        max_length=100,
        pattern=r"^[A-Z][A-Z0-9_]*$",
    )
    notes: str | None = Field(default=None, max_length=5000)

    @field_validator("display_name", "concept_prompt")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Value may not be blank")
        return cleaned
