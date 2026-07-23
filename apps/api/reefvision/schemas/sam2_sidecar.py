"""SAM 2 sidecar registration and health-check contracts."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class _Sam2SidecarConnectionRequest(BaseModel):
    endpoint: str = Field(min_length=1, max_length=500)
    token_env: str = Field(
        default="REEFVISION_SAM2_SIDECAR_TOKEN",
        min_length=1,
        max_length=100,
    )
    timeout_seconds: float = Field(default=120.0, ge=1, le=600)

    @field_validator("endpoint", "token_env")
    @classmethod
    def strip_required(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Value cannot be blank")
        return normalized

    @field_validator("token_env")
    @classmethod
    def validate_token_env(cls, value: str) -> str:
        if not value.replace("_", "").isalnum() or not value[0].isalpha():
            raise ValueError("token_env must be an environment variable name")
        return value


class Sam2SidecarRegistrationRequest(_Sam2SidecarConnectionRequest):
    display_name: str = Field(min_length=1, max_length=200)
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("display_name")
    @classmethod
    def strip_display_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Value cannot be blank")
        return normalized


class Sam2SidecarHealthRequest(_Sam2SidecarConnectionRequest):
    pass


class Sam2SidecarHealthResponse(BaseModel):
    status: str
    provider: str
    model_version: str | None
    device: str
    endpoint: str
    token_configured: bool
