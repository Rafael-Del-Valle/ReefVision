"""The offline Windows installer media preflight contract."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field

Digest = Annotated[str, Field(pattern=r"^[0-9a-fA-F]{64}$")]


class OfflineUpdateRequest(BaseModel):
    directory: str = Field(min_length=1, max_length=4096)
    manifest_sha256: Digest


class MediaFileResult(BaseModel):
    name: str
    status: Literal["matched", "changed", "missing", "unexpected", "unreadable"]


class OfflineUpdateReport(BaseModel):
    status: Literal["verified", "incomplete"]
    version: str
    installer: str
    source_commit: str
    manifest_sha256: str
    total_verified_bytes: int
    files: list[MediaFileResult]
