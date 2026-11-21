"""Public ABI, immutable package pins and local installation state."""

from __future__ import annotations

import base64
import binascii
from hashlib import sha256
from typing import Annotated, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field

from reefvision.domain.errors import ValidationError
from reefvision.storage.datasets import canonical_json_sha256

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
MAX_MODULE_BYTES = 256 * 1024
ABI = "reefvision.rgb-summary/1"


class PluginManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    manifest_version: Literal[2]
    abi: Literal["reefvision.rgb-summary/1"]
    plugin_id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,62}$")
    version: str = Field(
        pattern=r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$", max_length=48
    )
    display_name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=800)
    license: str = Field(min_length=1, max_length=150)
    permissions: list[Literal["read_image_rgb_summary"]] = Field(min_length=1, max_length=1)
    quantity: str = Field(pattern=r"^[a-z][a-z0-9_]{0,79}$")
    unit: Literal["1", "%"]
    module_sha256: Digest

    @property
    def record_id(self) -> UUID:
        return uuid5(NAMESPACE_URL, f"urn:reefvision:plugin:{self.plugin_id}:{self.version}")

    @property
    def package_sha256(self) -> str:
        return canonical_json_sha256(self.model_dump(mode="json"))


class PluginPackage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manifest: PluginManifest
    module_base64: str = Field(min_length=1, max_length=4 * ((MAX_MODULE_BYTES + 2) // 3))

    def module_bytes(self) -> bytes:
        try:
            module = base64.b64decode(self.module_base64, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValidationError("The plugin module must be base64-encoded WebAssembly.") from exc
        if len(module) > MAX_MODULE_BYTES or not module.startswith(b"\x00asm\x01\x00\x00\x00"):
            raise ValidationError("Choose a compiled WebAssembly module of at most 256 KiB.")
        if sha256(module).hexdigest() != self.manifest.module_sha256:
            raise ValidationError("The plugin module differs from its manifest checksum.")
        return module


class PluginRecord(BaseModel):
    id: UUID
    manifest: PluginManifest
    package_sha256: Digest
    enabled: bool
    available: bool
    reason: str | None


class PluginPage(BaseModel):
    items: list[PluginRecord]
    total: int


class PluginStateChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    package_sha256: Digest
    enabled: bool = Field(strict=True)


class PluginMeasurementPin(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    plugin_record_id: UUID
    package_sha256: Digest
    image_id: UUID
    image_sha256: Digest


class RGBSummary(BaseModel):
    red_mean: float = Field(ge=0, le=255)
    green_mean: float = Field(ge=0, le=255)
    blue_mean: float = Field(ge=0, le=255)
    pixel_count: int = Field(gt=0)
