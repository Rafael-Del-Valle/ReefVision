"""Versioned local inference settings, draft, and review receipt."""

from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    FiniteFloat,
    SerializerFunctionWrapHandler,
    model_serializer,
)

from reefvision.storage.datasets import canonical_json_sha256

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Probability = Annotated[FiniteFloat, Field(ge=0, le=1)]
Device = Literal["cpu", "cuda"]
_REVIEW_BINDINGS = frozenset({"class_mapping", "applied_image_settings"})


class ExecutionSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    device: Device
    confidence_threshold: Probability
    iou_threshold: Probability


class RuntimeDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_id: UUID
    runtime_id: str = Field(min_length=1, max_length=60)
    device: Device
    confidence_threshold: Probability | None = None
    iou_threshold: Probability | None = None
    prompt: str = Field(default="", max_length=500)


class RuntimeReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["reviewed-model-runtime-0001"] = "reviewed-model-runtime-0001"
    source_project_id: UUID
    source_model_id: UUID
    catalog_id: str
    display_name: str
    checkpoint_sha256: Digest
    file_size_bytes: int = Field(ge=1)
    task: str
    purpose: str
    labels: list[str]
    class_mapping: dict[str, UUID | None] = Field(default_factory=dict)
    applied_image_settings: list[Literal["device", "confidence_threshold", "iou_threshold"]] = (
        Field(
            default_factory=list,
        )
    )
    framework: str
    registered_provider_version: str
    provider_id: str
    provider_version: str
    runtime_id: str
    runtime_version: str
    settings: ExecutionSettings
    prompt: str

    @property
    def requires_re_review(self) -> bool:
        return not _REVIEW_BINDINGS.issubset(self.model_fields_set)

    @model_serializer(mode="wrap")
    def original_review_fields(self, serialize: SerializerFunctionWrapHandler) -> dict[str, Any]:
        body: dict[str, Any] = serialize(self)
        for omitted in _REVIEW_BINDINGS - self.model_fields_set:
            body.pop(omitted, None)
        return body

    def source_ids(self) -> set[str]:
        return {
            str(self.source_project_id),
            str(self.source_model_id),
            *(str(identifier) for identifier in self.class_mapping.values() if identifier),
        }


def read_runtime_receipt(raw: dict[str, Any], digest: str) -> RuntimeReceipt:
    if canonical_json_sha256(raw) != digest:
        raise ValueError("The original runtime receipt digest differs")
    receipt = RuntimeReceipt.model_validate(raw)
    if canonical_json_sha256(receipt.model_dump(mode="json")) != digest:
        raise ValueError("The model runtime receipt is not canonical")
    return receipt


def runtime_source_links_match(
    receipt: RuntimeReceipt,
    stored_ids: Mapping[str, str],
    origin_ids: Mapping[str, str],
    *,
    project_id: str,
    model_id: str,
) -> bool:
    identifiers = receipt.source_ids()
    original_project, original_model = str(receipt.source_project_id), str(receipt.source_model_id)
    return (
        receipt.catalog_id == f"registered-model/{original_model}"
        and not (stored_ids.keys() - identifiers)
        and all(stored_ids.get(key, key) == origin_ids.get(key, key) for key in identifiers)
        and stored_ids.get(original_project, original_project) == project_id
        and stored_ids.get(original_model, original_model) == model_id
    )


class RuntimePreview(BaseModel):
    snapshot: RuntimeReceipt
    content_sha256: Digest


class RuntimeConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    draft: RuntimeDraft
    reviewed_sha256: Digest


class RuntimeSelectionResponse(RuntimePreview):
    id: UUID
    project_id: UUID
    model_id: UUID
    created_at: datetime
    requires_re_review: bool = False
