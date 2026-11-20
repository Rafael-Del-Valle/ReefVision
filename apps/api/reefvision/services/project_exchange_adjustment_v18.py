"""Validate portable adjustment receipts and remap only live references."""

from collections.abc import Callable
from copy import deepcopy
from typing import Any

from pydantic import ValidationError as SchemaValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.db.models.image_adjustment import ImageAdjustmentRecipe
from reefvision.domain.errors import ConflictError, ValidationError
from reefvision.schemas.image_adjustments_v18 import ImageAdjustmentPin, ImageAdjustmentRecord
from reefvision.services.image_adjustments_v18 import (
    adjusted_input_provenance,
    image_adjustment_pin,
    verify_receipt,
)
from reefvision.services.workflow_image_adjustment_v18 import ARTIFACT, NODE
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.storage.image_adjustments_v18 import MAX_SOURCE_PIXELS, render_adjustment

SECTION = "image_adjustment_recipes"
SECTIONS = (SECTION,)
Rows = dict[str, list[dict[str, Any]]]


def has_adjustment_records(session: Session, project_id: str) -> bool:
    return (
        session.scalar(
            select(ImageAdjustmentRecipe.id)
            .where(ImageAdjustmentRecipe.project_id == project_id)
            .limit(1)
        )
        is not None
    )


def validate_adjustment_exchange(
    project_id: str,
    rows: Rows,
    *,
    origin_ids: dict[str, str] | None = None,
    read_image: Callable[[str], bytes | None] | None = None,
) -> None:
    """Check retained receipts and rerender when the original member is available."""
    origins = origin_ids or {}
    images = {row["id"]: row for row in rows.get("images", [])}
    models = {row["id"]: row for row in rows.get("models", [])}
    nodes = {row["id"]: row for row in rows.get("workflow_node_runs", [])}
    records: dict[str, ImageAdjustmentRecord] = {}
    job_recipes: dict[str, ImageAdjustmentRecord] = {}
    seen: set[tuple[str, str]] = set()

    def local(identifier: str) -> str:
        return origins.get(identifier, identifier)

    def matches(identifier: str, current: str) -> bool:
        return identifier == current or local(identifier) == current

    def match_pin(value: object, image_id: str) -> ImageAdjustmentRecord:
        pin = ImageAdjustmentPin.model_validate(value)
        recipe_id = str(pin.recipe_id)
        record = records.get(recipe_id) or records.get(local(recipe_id))
        if record is None or not matches(image_id, str(record.image_id)):
            raise ValidationError(
                "Adjusted evidence points to a different original image or recipe"
            )
        if pin.model_copy(update={"recipe_id": record.id}) != image_adjustment_pin(record):
            raise ValidationError("Adjusted evidence differs from its source and rendition pins")
        return record

    def check_model_input(body: object, record: ImageAdjustmentRecord) -> None:
        expected = adjusted_input_provenance(record)
        if not isinstance(body, dict) or not isinstance(body.get("recipe_id"), str):
            raise ValidationError("Adjusted inference is missing its model input provenance")
        if not matches(body["recipe_id"], str(record.id)):
            raise ValidationError("Adjusted inference points to a foreign recipe")
        if {**body, "recipe_id": str(record.id)} != expected:
            raise ValidationError(
                "Adjusted model input provenance differs from its verified recipe"
            )

    try:
        for row in rows.get(SECTION, []):
            receipt = verify_receipt(row["receipt_json"], row["content_sha256"])
            record = ImageAdjustmentRecord.model_validate({**row, "receipt": receipt})
            image_id = str(record.image_id)
            image = images[image_id]
            identity = (image_id, record.content_sha256)
            if (
                str(record.project_id) != project_id
                or image["project_id"] != project_id
                or not matches(str(receipt.project_id), project_id)
                or not matches(str(receipt.image_id), image_id)
                or (receipt.original_sha256, receipt.width_px, receipt.height_px)
                != (image["sha256"], image["width_px"], image["height_px"])
                or receipt.width_px * receipt.height_px > MAX_SOURCE_PIXELS
                or identity in seen
                or str(record.id) in records
            ):
                raise ValidationError(
                    "Adjustment receipt ownership, original hash or source grid differs"
                )
            seen.add(identity)
            records[str(record.id)] = record
            payload = read_image(image_id) if read_image else None
            if payload is not None:
                rendered = render_adjustment(
                    payload,
                    receipt.original_sha256,
                    receipt.width_px,
                    receipt.height_px,
                    receipt.parameters,
                )
                if (rendered.rendition_sha256, rendered.rgb_sha256) != (
                    receipt.rendition_sha256,
                    receipt.rgb_sha256,
                ):
                    raise ValidationError(
                        "The archived adjustment cannot reproduce its derived hashes"
                    )
        for row in rows.get("jobs", []):
            request = row.get("request_json") or {}
            if row.get("job_type") != "inference" or "image_adjustment" not in request:
                continue
            if row["project_id"] != project_id or len(request.get("image_ids", [])) != 1:
                raise ValidationError("Adjusted inference must be owned by one original image")
            model = models[request["model_id"]]
            if (
                model["project_id"] != project_id
                or request.get("checkpoint_sha256") != model["sha256"]
            ):
                raise ValidationError("Adjusted inference lost its registered checkpoint binding")
            record = match_pin(request["image_adjustment"], request["image_ids"][0])
            job_recipes[row["id"]] = record
            model_input = (row.get("result_json") or {}).get("model_input")
            if row["status"] == "succeeded" or model_input is not None:
                check_model_input(model_input, record)
        for row in rows.get("prediction_proposals", []):
            provenance = row.get("provenance_json") or {}
            record = job_recipes.get(row.get("inference_job_id", ""))
            if record is None:
                if "model_input" in provenance:
                    raise ValidationError(
                        "Adjusted prediction is missing its original inference job"
                    )
                continue
            if row["project_id"] != project_id or row["image_id"] != str(record.image_id):
                raise ValidationError(
                    "Adjusted prediction is bound to a different source pixel grid"
                )
            check_model_input(provenance.get("model_input"), record)
        for row in rows.get("workflow_artifacts", []):
            data_type = row.get("data_type")
            payload = row["payload_json"]
            if data_type in {"detection_proposals", "mask_proposals"}:
                observations = payload.get(
                    "detections" if data_type == "detection_proposals" else "masks", []
                )
                record = job_recipes.get(payload.get("inference_job_id", ""))
                for observation in observations:
                    model_input = (observation.get("provenance") or {}).get("model_input")
                    if record is not None:
                        check_model_input(model_input, record)
                    elif model_input is not None:
                        raise ValidationError(
                            "Adjusted workflow proposals are missing their inference job"
                        )
            if data_type != ARTIFACT:
                continue
            if not matches(payload["project_id"], project_id) or len(payload["image_ids"]) != 1:
                raise ValidationError(
                    "Adjusted workflow output is paired with a different project or image"
                )
            record = match_pin(payload["image_adjustment"], payload["image_ids"][0])
            producer = nodes[row["producer_node_run_id"]]
            parameters = dict(producer["parameters_json"])
            configured = match_pin(parameters, parameters.pop("image_id"))
            if (
                payload["receipt"] != record.receipt.model_dump(mode="json")
                or canonical_json_sha256(payload) != row["payload_sha256"]
                or producer["node_type"] != NODE
                or row["producer_port_id"] != "images"
                or configured.id != record.id
            ):
                raise ValidationError(
                    "Adjusted workflow output altered its original recipe receipt"
                )
    except (ConflictError, KeyError, TypeError, SchemaValidationError) as exc:
        raise ValidationError("Invalid portable image adjustment evidence") from exc


def remap_adjustment_parameters(
    parameters: dict[str, Any], id_map: dict[str, str]
) -> dict[str, Any]:
    result = deepcopy(parameters)
    for key in ("image_id", "recipe_id"):
        if isinstance(result.get(key), str):
            result[key] = id_map.get(result[key], result[key])
    return result


def restore_adjustment_row(
    name: str,
    original: dict[str, Any],
    values: dict[str, Any],
    id_map: dict[str, str],
) -> None:
    if name == SECTION:
        values["receipt_json"] = deepcopy(original["receipt_json"])
    elif name == "jobs":
        request = original.get("request_json") or {}
        if request.get("image_adjustment") is not None:
            values["request_json"]["image_adjustment"] = remap_adjustment_parameters(
                request["image_adjustment"], id_map
            )
            result = original.get("result_json") or {}
            if result.get("model_input") is not None:
                values["result_json"]["model_input"] = deepcopy(result["model_input"])
    elif name == "prediction_proposals":
        provenance = original.get("provenance_json") or {}
        if provenance.get("model_input") is not None:
            values["provenance_json"]["model_input"] = deepcopy(provenance["model_input"])
    elif name == "workflow_artifacts":
        payload = original.get("payload_json") or {}
        if original.get("data_type") == ARTIFACT:
            values["payload_json"] = deepcopy(payload)
        fields = {"detection_proposals": "detections", "mask_proposals": "masks"}
        field = fields.get(original.get("data_type", ""))
        if field and field in payload:
            for src, dst in zip(payload[field], values["payload_json"][field], strict=True):
                model_input = (src.get("provenance") or {}).get("model_input")
                if model_input is not None:
                    dst["provenance"]["model_input"] = deepcopy(model_input)
