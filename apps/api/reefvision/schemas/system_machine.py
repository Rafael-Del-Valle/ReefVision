"""Public, non-identifying compatibility facts about the API host."""

from pydantic import BaseModel


class SystemMachineCompatibilityResponse(BaseModel):
    operating_system: str
    os_release: str
    os_version: str
    architecture: str
    packaged_backend: bool
