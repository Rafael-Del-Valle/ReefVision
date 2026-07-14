"""Capability API schemas."""

from pydantic import BaseModel


class TaskCapabilityResponse(BaseModel):
    task_id: str
    display_name: str
    media: tuple[str, ...]
    annotation_kinds: tuple[str, ...]
    providers: tuple[str, ...]
    supports_training: bool
    supports_inference: bool
    state: str
    notes: str
