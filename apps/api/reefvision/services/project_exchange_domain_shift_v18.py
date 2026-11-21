"""Verify portable domain analyses against recorded workers and frozen references."""

from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime
from hashlib import sha256
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from reefvision.db.models import Job
from reefvision.domain.errors import NotFoundError, ReefVisionError, ValidationError
from reefvision.schemas.domain_shift_v18 import DomainShiftDraft
from reefvision.schemas.image_adjustments_v18 import ImageAdjustmentPin, ImageAdjustmentRecord
from reefvision.schemas.model_runtime import RuntimeReceipt
from reefvision.schemas.paired_models_v15 import ComparisonEvidence, ComparisonRequest
from reefvision.services.domain_shift_metrics_v18 import summarize_domain_shift
from reefvision.services.domain_shift_v18 import JOB_TYPE, VERSION, remap_domain_declaration
from reefvision.services.image_adjustments_v18 import image_adjustment_pin, verify_receipt
from reefvision.services.model_comparison_stills_v15 import (
    ComparisonLineageOverlap,
    RecordedImageRuns,
    compare_image_models,
)
from reefvision.services.project_exchange_paired_models_v15 import (
    RasterReader,
    _add_raster,
    _archive_session,
    _groups,
    _lineage,
    paired_comparison_raster_paths,
)
from reefvision.services.workflow_domain_shift_v18 import NODE
from reefvision.storage.datasets import canonical_json_sha256

Rows = dict[str, list[dict[str, Any]]]


def _reports(sections: Rows) -> list[dict[str, Any]]:
    return [
        row
        for row in sections.get("jobs", [])
        if row.get("job_type") == JOB_TYPE and row.get("status") == "succeeded"
    ]


def domain_shift_raster_paths(sections: Rows) -> dict[str, str]:
    paths: dict[str, str] = {}
    child_ids: set[str] = set()
    for row in _reports(sections):
        result = row.get("result_json") or {}
        body = result.get("snapshot") or {}
        if body.get("preprocessing_executed") == "adjusted":
            aliases = result.get("source_id_map", {})
            child_ids.update(
                aliases.get(value, value)
                for value in body["observed_evidence"]["inference_job_ids"]
            )
    for prediction in sections.get("prediction_proposals", []):
        if prediction["inference_job_id"] in child_ids:
            _add_raster(paths, prediction)
    return paths


def _links(snapshot: dict[str, Any]) -> set[str]:
    evidence = snapshot["observed_evidence"]
    links = {
        snapshot["project_id"],
        snapshot["declaration"]["comparison_id"],
        snapshot["reference"]["id"],
        *evidence["inference_job_ids"],
        *(item["id"] for item in snapshot["models"]),
        *(item["runtime_id"] for item in snapshot["models"]),
        *(row["media_id"] for group in evidence["groups"] for row in group["observations"]),
        *(
            item[key]
            for item in snapshot["declaration"]["adjustments"]
            for key in ("recipe_id", "image_id")
        ),
    }
    for source in evidence["lineage"]:
        links.update(source["training_run_ids"])
        links.update(source["model_selection_job_ids"])
        links.update(source["checkpoint_dependencies"])
        links.update(row["id"] for row in source["datasets"])
        links.update(source["overlapping_image_ids"])
    return links


def restore_domain_shift_row(
    name: str, original: dict[str, Any], values: dict[str, Any], id_map: dict[str, str]
) -> None:
    if name != "jobs" or original.get("job_type") != JOB_TYPE:
        return
    values["request_json"] = remap_domain_declaration(original["request_json"], id_map)
    if original["status"] != "succeeded":
        return
    body = deepcopy(original["result_json"])
    aliases = body.get("source_id_map", {})
    body["source_id_map"] = {
        key: id_map.get(aliases.get(key, key), aliases.get(key, key))
        for key in _links(body["snapshot"])
    }
    values["result_json"] = body


def remap_domain_shift_parameters(
    parameters: dict[str, Any], id_map: dict[str, str]
) -> dict[str, Any]:
    report_id = parameters.get("report_id")
    if not isinstance(report_id, str):
        return parameters
    return {**parameters, "report_id": id_map.get(report_id, report_id)}


def _validate_report(
    session: Session,
    row: dict[str, Any],
    project_id: str,
    sections: Rows,
    origin_ids: Mapping[str, str],
    read_raster: RasterReader,
) -> None:
    result = row["result_json"]
    snapshot, aliases = result["snapshot"], result.get("source_id_map", {})
    links = _links(snapshot)
    if (
        snapshot["schema_version"] != VERSION
        or row["project_id"] != project_id
        or aliases.get(snapshot["project_id"], snapshot["project_id"]) != project_id
        or canonical_json_sha256(snapshot) != result["content_sha256"]
        or set(aliases) - links
        or any(aliases.get(key, key) != origin_ids.get(key, key) for key in links)
        or len({aliases.get(key, key) for key in links}) != len(links)
        or remap_domain_declaration(snapshot["declaration"], aliases) != row["request_json"]
    ):
        raise ValidationError(
            "Domain report source or declaration does not match its frozen receipt"
        )
    reverse = {value: key for key, value in aliases.items()}
    draft = DomainShiftDraft.model_validate(row["request_json"])
    frozen = DomainShiftDraft.model_validate(snapshot["declaration"])
    paired = session.get(Job, str(draft.comparison_id))
    if (
        paired is None
        or paired.project_id != project_id
        or paired.job_type != "paired_model_comparison"
        or paired.status != "succeeded"
        or not paired.result_json
        or paired.result_json.get("content_sha256") != draft.comparison_sha256
    ):
        raise ValidationError("The prerequisite paired model evidence is missing or foreign")
    paired_snapshot = paired.result_json["snapshot"]
    paired_evidence = paired_snapshot["evidence"]
    paired_aliases = paired.result_json.get("source_id_map", {})
    live = ComparisonRequest.model_validate(paired.request_json)
    observed_raw = snapshot["observed_evidence"]
    observed = ComparisonEvidence.model_validate(observed_raw).model_dump(mode="json")
    source = snapshot["reference"]
    if (
        live.task not in {"detector", "mask"}
        or source["split"] != "test"
        or source["id"] != observed["reference_id"]
        or aliases.get(source["id"], source["id"]) != str(live.sources[0].id)
        or source["original_manifest_sha256"] != paired_evidence["reference_sha256"]
        or source["manifest_sha256"] != observed["reference_sha256"]
        or (not aliases and source["manifest_sha256"] != live.sources[0].sha256)
        or snapshot["summary"]
        != summarize_domain_shift(frozen, observed["groups"], snapshot["summary"]["lineage"])
    ):
        raise ValidationError(
            "Domain report does not match the frozen test reference and grouped estimates"
        )
    picks = []
    for info, selected, original in zip(
        snapshot["models"], (live.left, live.right), paired_snapshot["models"], strict=True
    ):
        receipt = RuntimeReceipt.model_validate(original["receipt"])
        model_id = aliases.get(info["id"], info["id"])
        if (
            model_id != paired_aliases.get(original["model_id"], original["model_id"])
            or aliases.get(info["runtime_id"], info["runtime_id"]) != str(selected.id)
            or info["runtime_sha256"] != selected.sha256
            or info["checkpoint_sha256"] != receipt.checkpoint_sha256
            or info["class_mapping"] != receipt.model_dump(mode="json")["class_mapping"]
            or info["label"] != receipt.display_name
        ):
            raise ValidationError("Both domain shifts must use the frozen model and class-map pins")
        picks.append(
            {
                "model_id": model_id,
                "runtime_selection_id": str(selected.id),
                "runtime_selection_sha256": selected.sha256,
                "checkpoint_sha256": receipt.checkpoint_sha256,
                **receipt.settings.model_dump(),
            }
        )
    completed = (
        datetime.fromisoformat(row["completed_at"])
        if isinstance(row["completed_at"], str)
        else row["completed_at"]
    )
    scope = {"dataset_version_id": str(live.sources[0].id)}
    prepared: dict[str, ImageAdjustmentPin] | None = None
    archived: RecordedImageRuns
    execution = snapshot["preprocessing_executed"]
    if execution == "adjusted":
        if frozen.preprocessing != "adjusted" or snapshot["summary"]["lineage"] != "held_out":
            raise ValidationError(
                "Archived preprocessing differs from the declared eligible domain plan"
            )
        recipes = {item["id"]: item for item in sections.get("image_adjustment_recipes", [])}
        prepared, input_records = {}, {}
        for item in draft.adjustments:
            recipe = recipes[str(item.recipe_id)]
            record = ImageAdjustmentRecord.model_validate(
                {
                    **recipe,
                    "receipt": verify_receipt(recipe["receipt_json"], recipe["content_sha256"]),
                }
            )
            pin = ImageAdjustmentPin.model_validate(item.model_dump(exclude={"image_id"}))
            if str(record.project_id) != project_id:
                raise ValidationError("Archived domain recipe is foreign")
            if record.image_id != item.image_id or image_adjustment_pin(record) != pin:
                raise ValidationError("Archived domain recipe differs from the frozen model input")
            prepared[str(item.image_id)] = pin
            input_records[str(item.image_id)] = record
        children: tuple[dict[str, str], dict[str, str]] = ({}, {})
        output_ids = observed["inference_job_ids"]
        if len(output_ids) != 2 * len(prepared) or len(output_ids) != len(set(output_ids)):
            raise ValidationError("Each model and adjusted image needs one actual evaluation job")
        for old_job in output_ids:
            child_id = aliases.get(old_job, old_job)
            child = session.get(Job, child_id)
            if child is None or child.request_json.get("paired_owner_run_id") != row["id"]:
                raise ValidationError(
                    "An adjusted evaluation job belongs to a different domain report"
                )
            [image_id] = child.request_json["image_ids"]
            [side] = [
                index
                for index, pick in enumerate(picks)
                if pick["model_id"] == child.request_json["model_id"]
            ]
            if image_id in children[side]:
                raise ValidationError("The archived domain counts a model and image twice")
            children[side][image_id] = child_id
        archived = RecordedImageRuns(
            None,
            read_raster,
            reverse,
            completed,
            adjusted_jobs=children,
            adjusted_records=input_records,
        )
    elif execution in {"original", "unscored"}:
        local_children = [
            paired_aliases.get(key, key) for key in paired_evidence["inference_job_ids"]
        ]
        [left, right] = local_children
        archived = RecordedImageRuns(
            (left, right),
            read_raster,
            {value: key for key, value in paired_aliases.items()},
            completed,
        )
    else:
        raise ValidationError("Unknown executed domain input mode")
    try:
        expected = compare_image_models(
            session,
            None,
            project_id,
            live.task,
            scope,
            picks,
            recorded=archived,
            adjusted_inputs=prepared,
        )
    except ComparisonLineageOverlap as exc:
        if (
            snapshot["summary"]["lineage"] == "overlap"
            and execution == "unscored"
            and snapshot["lineage_reasons"] == [str(exc)]
            and _groups(observed, aliases) == _groups(paired_evidence, paired_aliases)
            and observed["source_sha256"] == paired_evidence["source_sha256"]
            and [aliases.get(key, key) for key in observed["inference_job_ids"]] == local_children
            and all(
                observed[key] == paired_evidence[key]
                for key in ("method", "limitations", "evaluation_status")
            )
            and _lineage(observed, aliases, include_digests=False)
            == _lineage(paired_evidence, paired_aliases, include_digests=False)
        ):
            return
        raise
    expected = ComparisonEvidence.model_validate(expected).model_dump(mode="json")
    lineage = (
        "held_out"
        if expected["evaluation_status"] == paired_evidence["evaluation_status"] == "held_out"
        else "exploratory"
    )
    if (
        lineage != snapshot["summary"]["lineage"]
        or execution != (frozen.preprocessing if lineage == "held_out" else "unscored")
        or _groups(expected, {}) != _groups(observed, aliases)
        or expected["source_sha256"] != observed["source_sha256"]
        or any(
            expected[key] != observed[key] for key in ("method", "limitations", "evaluation_status")
        )
        or _lineage(expected, {}, include_digests=not aliases)
        != _lineage(observed, aliases, include_digests=not aliases)
        or expected["inference_job_ids"]
        != [aliases.get(key, key) for key in observed["inference_job_ids"]]
    ):
        raise ValidationError("Domain scores no longer match their frozen evaluation jobs")


def validate_domain_shift_exchange(
    project_id: str,
    sections: Rows,
    origin_ids: Mapping[str, str],
    *,
    read_raster: RasterReader | None = None,
) -> None:
    reports = _reports(sections)
    artifacts = [
        row for row in sections.get("workflow_artifacts", []) if row.get("data_type") == NODE
    ]
    if not reports and not artifacts:
        return
    records = {row["id"]: row for row in reports}
    try:
        paths = {**paired_comparison_raster_paths(sections), **domain_shift_raster_paths(sections)}

        def checked_raster(path: str) -> bytes:
            if read_raster is None or path not in paths:
                raise NotFoundError("An archived domain comparison raster is unavailable")
            data = read_raster(path)
            if sha256(data).hexdigest() != paths[path]:
                raise ValidationError("Archived domain comparison raster digest differs")
            return data

        for path in domain_shift_raster_paths(sections):
            checked_raster(path)
        with _archive_session(sections) as session:
            for report in reports:
                _validate_report(session, report, project_id, sections, origin_ids, checked_raster)
        nodes = {row["id"]: row for row in sections.get("workflow_node_runs", [])}
        for artifact in artifacts:
            node = nodes[artifact["producer_node_run_id"]]
            params = node["parameters_json"]
            stored = records[params["report_id"]]["result_json"]
            payload = {key: stored[key] for key in ("snapshot", "content_sha256")}
            if (
                node["node_type"] != NODE
                or node["status"] != "succeeded"
                or node["workflow_run_id"] != artifact["workflow_run_id"]
                or artifact["producer_port_id"] != "report"
                or artifact["payload_json"] != payload
                or params["content_sha256"] != payload["content_sha256"]
                or artifact["payload_sha256"] != canonical_json_sha256(payload)
            ):
                raise ValidationError(
                    "Archived domain workflow does not produce its declared frozen report"
                )
    except (
        ReefVisionError,
        SQLAlchemyError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        IndexError,
    ) as exc:
        raise ValidationError(
            f"Domain shift Exchange could not verify its evidence. {exc}"
        ) from exc
