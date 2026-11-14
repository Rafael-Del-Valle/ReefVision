"""Validate and relink integrated scientific-comparison jobs across project exchange."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from pydantic import ValidationError as ContractError
from sqlalchemy.orm import Session

from reefvision.db.models import Job
from reefvision.domain.errors import ValidationError
from reefvision.schemas.scientific_comparison import ComparisonRecord
from reefvision.services.scientific_comparison import (
    JOB_TYPE,
    agreement_statistics,
    paired_model_difference,
    read_comparison,
    scored_pairs,
)
from reefvision.services.workflow_scientific_comparison import comparison_artifact
from reefvision.storage.datasets import canonical_json_sha256


def validate_comparison_exchange(sections: dict[str, list[dict[str, Any]]]) -> None:
    jobs = {row["id"]: row for row in sections.get("jobs", [])}
    references = {row["id"]: row for row in sections.get("reefpose_references", [])}
    comparison_ids = {identifier for identifier, row in jobs.items() if row["job_type"] == JOB_TYPE}
    for identifier in comparison_ids:
        row = jobs[identifier]
        try:
            record = ComparisonRecord.model_validate(
                {**row["result_json"], "id": identifier, "project_id": row["project_id"]}
            )
        except (ContractError, TypeError) as exc:
            raise ValidationError("Scientific comparison exchange record is malformed") from exc
        snapshot = record.snapshot
        if (
            row["status"] != "succeeded"
            or canonical_json_sha256(snapshot.model_dump(mode="json")) != record.content_sha256
            or len(snapshot.models) != len(record.local_sources)
            or [model.source_job_id for model in snapshot.models] != snapshot.options.source_job_ids
        ):
            raise ValidationError(
                "Scientific comparison exchange snapshot checksum or lineage mismatch"
            )
        mapping = record.source_id_map
        resolved_reference_id = mapping.get(str(snapshot.reference_id), str(snapshot.reference_id))
        reference = references.get(resolved_reference_id)
        if reference is None or reference.get("project_id") != row["project_id"]:
            raise ValidationError("Scientific comparison has no project-owned reference")
        shared: list[set[tuple[str, str, float]]] = []
        for model, source in zip(snapshot.models, record.local_sources, strict=True):
            resolved_id = mapping.get(str(model.source_job_id), str(model.source_job_id))
            report = jobs.get(str(source.job_id))
            if (
                resolved_id != str(source.job_id)
                or report is None
                or report["project_id"] != row["project_id"]
                or report["job_type"] != "reefpose_validation"
                or report["status"] != "succeeded"
                or report["result_json"]["result_sha256"] != source.result_sha256
                or report["result_json"]["reference_id"] != resolved_reference_id
            ):
                raise ValidationError("Scientific comparison source report lineage is inconsistent")
            source_report = report["result_json"]
            if (
                source_report["split"] != "test"
                or source_report["rater_id"] != snapshot.rater_id
                or source_report["data_kind"] != snapshot.data_kind
                or canonical_json_sha256(source_report["selected_configuration"])
                != snapshot.configuration_sha256
            ):
                raise ValidationError("Scientific comparison uses different held-out evidence")
            local_model = mapping.get(str(model.model_id), str(model.model_id))
            if {row["model_id"] for row in source_report["prediction_sources"]} != {
                local_model
            } or source_report["models"].get(local_model, {}).get(
                "checkpoint_sha256"
            ) != model.checkpoint_sha256:
                raise ValidationError("Scientific comparison checkpoint lineage is inconsistent")
            available, _ = scored_pairs(
                source_report, reference["manifest"], snapshot.options, str(source.job_id)
            )
            shared.append(set(available))
            row_keys = set()
            for pair in model.pairs:
                original_video = str(pair.video_id)
                local_video = mapping.get(original_video, original_video)
                key = (
                    local_video,
                    pair.individual_id,
                    float(pair.frame if pair.frame is not None else pair.start_s or 0),
                )
                observed = available.get(key)
                if observed is None or observed != pair.model_copy(
                    update={"video_id": observed.video_id}
                ):
                    raise ValidationError("Scientific comparison pair disagrees with its source")
                row_keys.add(key)
            if len(row_keys) != len(model.pairs):
                raise ValidationError("Scientific comparison contains duplicate pairs")
            if model.statistics != agreement_statistics(model.pairs, snapshot.options):
                raise ValidationError("Scientific comparison statistics do not replay")
        common = set.intersection(*shared)
        for model in snapshot.models:
            keys = {
                (
                    mapping.get(str(pair.video_id), str(pair.video_id)),
                    pair.individual_id,
                    float(pair.frame if pair.frame is not None else pair.start_s or 0),
                )
                for pair in model.pairs
            }
            if keys != common:
                raise ValidationError("Scientific comparison omits shared held-out observations")
        if snapshot.pairing != paired_model_difference(snapshot.models, snapshot.options):
            raise ValidationError("Scientific comparison model difference does not replay")
    for artifact in sections.get("workflow_artifacts", []):
        if artifact["data_type"] == "scientific_comparison_report":
            payload = artifact["payload_json"]
            identifier = payload.get("comparison_id")
            if (
                identifier not in comparison_ids
                or jobs[identifier]["project_id"] != payload.get("project_id")
                or jobs[identifier]["result_json"]["content_sha256"]
                != payload.get("content_sha256")
            ):
                raise ValidationError("Workflow artifact disagrees with its scientific comparison")


def restore_comparison_jobs(
    session: Session,
    project_id: str,
    sections: dict[str, list[dict[str, Any]]],
    id_map: dict[str, str],
    digest_map: dict[str, str],
) -> None:
    for row in sections.get("jobs", []):
        if row["job_type"] != JOB_TYPE:
            continue
        job = session.get(Job, id_map[row["id"]])
        if job is None or job.project_id != project_id:
            raise ValidationError("Scientific comparison job was lost during import")
        previous = row["result_json"]
        snapshot = deepcopy(previous["snapshot"])
        known_ids = {
            snapshot["reference_id"],
            *[model["source_job_id"] for model in snapshot["models"]],
            *[model["model_id"] for model in snapshot["models"]],
            *[pair["video_id"] for model in snapshot["models"] for pair in model["pairs"]],
            *[excluded["video_id"] for excluded in snapshot["exclusions"]],
        }
        old_map = previous.get("source_id_map", {})
        resolved = {origin: id_map[old_map.get(origin, origin)] for origin in sorted(known_ids)}
        job.result_json = {
            "snapshot": snapshot,
            "content_sha256": previous["content_sha256"],
            "local_sources": [
                {
                    "job_id": id_map[source["job_id"]],
                    "result_sha256": digest_map.get(
                        source["result_sha256"], source["result_sha256"]
                    ),
                }
                for source in previous["local_sources"]
            ],
            "source_id_map": resolved,
        }
    session.flush()


def restore_comparison_artifact(
    session: Session, project_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    report = read_comparison(session, project_id, payload["comparison_id"])
    if report.content_sha256 != payload.get("content_sha256"):
        raise ValidationError("Imported workflow artifact disagrees with its scientific comparison")
    return comparison_artifact(report)
