"""Relink frozen ReefPose provenance to the imported project."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.db.models import (
    Job,
    ModelRegistration,
    PoseEvaluationRun,
    PoseLandmarkSchemaRevision,
    PoseTrainingDataset,
)
from reefvision.domain.errors import ValidationError
from reefvision.services.pose_evaluation import pose_evaluation_result_sha256
from reefvision.services.pose_schemas import definition_for_revision
from reefvision.services.project_exchange_validation_report import validate_reefpose_report
from reefvision.services.reefpose_validation import frozen_recording
from reefvision.storage.datasets import canonical_json_sha256

_JSON_HASHES = {
    "pose_identity_association_runs": {"parameters_sha256": "parameters_json"},
    "pose_identity_corrections": {"before_sha256": "before_json", "after_sha256": "after_json"},
    "pose_identity_truth_datasets": {"manifest_sha256": "manifest_json"},
    "pose_measurement_runs": {"input_manifest_sha256": "input_manifest_json"},
    "pose_event_detection_runs": {"configuration_sha256": "configuration_json"},
    "reefpose_references": {"manifest_sha256": "manifest"},
}


def _update_keys(row: dict[str, Any], keys: tuple[str, ...], mapping: dict[str, str]) -> None:
    for key in keys:
        value = row.get(key)
        if isinstance(value, str) and value in mapping:
            row[key] = mapping[value]


def _remap_reference_manifest(manifest: dict[str, Any], id_map: dict[str, str]) -> None:
    for recording in manifest["recordings"]:
        _update_keys(recording, ("video_id", "schema_id"), id_map)


def remap_phase6_job(row: dict[str, Any], values: dict[str, Any], mapping: dict[str, str]) -> None:
    if row["job_type"] == "video_tracking":
        result = values.get("result_json")
        if isinstance(result, dict) and isinstance(result.get("pose_track_hashes"), dict):
            result["pose_track_hashes"] = {
                mapping.get(identifier, identifier): digest
                for identifier, digest in result["pose_track_hashes"].items()
            }
    if row["job_type"] == "reefpose_validation":
        payload = values["request_json"].get("payload")
        if isinstance(payload, dict):
            for name in ("source_runs", "zero_detection_jobs"):
                sources = payload.get(name)
                if isinstance(sources, dict):
                    payload[name] = {
                        mapping.get(identifier, identifier): source
                        for identifier, source in sources.items()
                    }


def _identity_manifest(
    manifest: dict[str, Any],
    mapping: dict[str, str],
    track_digests: dict[str, tuple[str, str]],
) -> dict[str, Any]:
    value = deepcopy(manifest)
    _update_keys(value, ("video_id",), mapping)
    _update_keys(value["pose_schema"], ("id",), mapping)
    for track in value["tracks"]:
        if (pair := track_digests.get(track["id"])) and track["keyframes_sha256"] == pair[0]:
            track["keyframes_sha256"] = pair[1]
        _update_keys(track, ("id",), mapping)
        _update_keys(track["schema_binding"], ("id", "schema_id"), mapping)
    return value


def _evaluation_summary(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "configuration": row["configuration_json"],
        "metrics": row["metrics_json"],
        "warnings": row["warnings_json"],
        "provenance": row["provenance_json"],
    }


def _measurement_series_hash(
    series: dict[str, Any], run: dict[str, Any], samples: list[dict[str, Any]]
) -> str:
    definitions = {item["id"]: item for item in run["definitions_json"]}
    definition = definitions[series["definition_id"]]
    fields = ("frame_index", "time_s", "pixel_value", "physical_value", "confidence", "valid")
    return canonical_json_sha256(
        {
            "definition": {
                "definition_id": definition["id"],
                "kind": definition["kind"],
                "landmark_ids": definition["landmark_ids"],
                "options": definition.get("options") or {},
            },
            "identity_id": series["animal_identity_id"],
            "samples": [
                {
                    **{name: row[name] for name in fields},
                    "quality_flags": row["quality_flags_json"],
                    "source_observation_ids": row["source_observation_ids_json"],
                    "source_observation_revisions": row["source_observation_revisions_json"],
                }
                for row in sorted(samples, key=lambda row: row["frame_index"])
            ],
            "summary": series["summary_json"],
        }
    )


def remap_measurement_digests(
    sections: dict[str, list[dict[str, Any]]], id_map: dict[str, str]
) -> dict[str, str]:
    runs = {row["id"]: row for row in sections.get("pose_measurement_runs", [])}
    samples_by_series: dict[str, list[dict[str, Any]]] = {}
    for sample in sections.get("pose_measurement_samples", []):
        samples_by_series.setdefault(sample["series_id"], []).append(sample)
    hashes_by_run: dict[str, dict[tuple[str, str], str]] = {}
    digests: dict[str, str] = {}
    for series in sections.get("pose_measurement_series", []):
        run = runs[series["measurement_run_id"]]
        samples = samples_by_series.get(series["id"], [])
        if _measurement_series_hash(series, run, samples) != series["series_sha256"]:
            raise ValidationError("Exchange measurement sample or series checksum does not match")
        if not id_map:
            continue
        remapped = {**series, "animal_identity_id": id_map[series["animal_identity_id"]]}
        remapped_samples = [
            {
                **sample,
                "source_observation_ids_json": [
                    id_map[identifier] for identifier in sample["source_observation_ids_json"]
                ],
            }
            for sample in samples
        ]
        digest = _measurement_series_hash(remapped, run, remapped_samples)
        digests[series["series_sha256"]] = digest
        hashes_by_run.setdefault(run["id"], {})[
            (remapped["animal_identity_id"], series["definition_id"])
        ] = digest
    for run_id, hashes in hashes_by_run.items():
        run = runs[run_id]
        if run["status"] != "completed" or not run["result_sha256"]:
            continue
        ordered = [
            hashes[(identity, definition["id"])]
            for identity in sorted(id_map[key] for key in run["configuration_json"]["identity_ids"])
            for definition in run["definitions_json"]
        ]
        digests[run["result_sha256"]] = canonical_json_sha256(ordered)
    return digests


def validate_pose_rows(sections: dict[str, list[dict[str, Any]]]) -> None:
    remap_measurement_digests(sections, {})
    for name, fields in _JSON_HASHES.items():
        for row in sections.get(name, []):
            for digest_name, json_name in fields.items():
                if canonical_json_sha256(row[json_name]) != row[digest_name]:
                    raise ValidationError(f"Exchange checksum does not match {name}.{json_name}")
    for row in sections.get("pose_identity_evaluation_runs", []):
        if canonical_json_sha256(_evaluation_summary(row)) != row["result_sha256"]:
            raise ValidationError("Exchange pose identity evaluation checksum does not match")
    for row in sections.get("pose_evaluation_runs", []):
        if pose_evaluation_result_sha256(PoseEvaluationRun(**row)) != row["result_sha256"]:
            raise ValidationError("Exchange pose evaluation checksum does not match")

    schema_revisions = {
        (row["schema_id"], row["revision"]): row
        for row in sections.get("pose_landmark_schema_revisions", [])
    }
    videos = {row["id"]: row for row in sections.get("videos", [])}
    references = {row["id"]: row for row in sections.get("reefpose_references", [])}
    partitions: dict[tuple[str, str], str] = {}
    for row in references.values():
        manifest = row["manifest"]
        parent = references.get(row["parent_id"])
        if (
            manifest["schema_version"] != "reefpose-reference-1"
            or manifest["name"] != row["name"]
            or manifest["data_kind"] != row["data_kind"]
            or manifest["revision"] != row["revision"]
            or (parent and parent["data_kind"] != row["data_kind"])
            or row["revision"] != (parent["revision"] + 1 if parent else 1)
            or manifest["parent_sha256"] != (parent["manifest_sha256"] if parent else None)
        ):
            raise ValidationError("Exchange ReefPose reference ancestry is inconsistent")
        recording_ids: set[str] = set()
        recording_hashes: set[str] = set()
        if not manifest["recordings"]:
            raise ValidationError("Exchange ReefPose reference does not contain recordings")
        for recording in manifest["recordings"]:
            frozen_recording(recording)
            for key in ("video_sha256", "group_id"):
                identity = (key, recording[key])
                partition = partitions.setdefault(identity, recording["split"])
                if partition != recording["split"]:
                    raise ValidationError(
                        "Exchange ReefPose reference uses a video or group in another split"
                    )
            video = videos.get(recording["video_id"])
            annotations = recording["annotations"]
            schema = schema_revisions.get((recording["schema_id"], recording["schema_revision"]))
            if (
                video is None
                or video["sha256"] != recording["video_sha256"]
                or recording["video_id"] in recording_ids
                or recording["video_sha256"] in recording_hashes
                or schema is None
                or schema["content_hash"] != recording["schema_sha256"]
                or definition_for_revision(PoseLandmarkSchemaRevision(**schema))
                != recording["schema"]
                or recording["annotation_sha256"]
                != {item["rater_id"]: canonical_json_sha256(item) for item in annotations}
            ):
                raise ValidationError("Exchange ReefPose reference source or checksum is invalid")
            recording_ids.add(recording["video_id"])
            recording_hashes.add(recording["video_sha256"])

    for job in sections.get("jobs", []):
        if job["job_type"] == "pose_evaluation" and job.get("result_json"):
            report = dict(job["result_json"])
            digest = report.pop("report_sha256", None)
            if digest is not None and digest != canonical_json_sha256(report):
                raise ValidationError("Exchange pose comparison report checksum does not match")
        if job["job_type"] != "reefpose_validation" or job["status"] != "succeeded":
            continue
        report = dict(job["result_json"])
        checksum = report.pop("result_sha256", None)
        if checksum != canonical_json_sha256(report):
            raise ValidationError("Exchange ReefPose validation report checksum does not match")
        validate_reefpose_report(report, references.get(report["reference_id"]))
    locks = {
        row["scope_sha256"]: row["protocol_sha256"]
        for row in sections.get("reefpose_heldout_locks", [])
    }
    for job in sections.get("jobs", []):
        if job["job_type"] != "reefpose_validation":
            continue
        request = job["request_json"]
        pending = request.get("heldout_input_manifest")
        if pending is None:
            continue  # Older jobs persisted only an opaque lock digest.
        reference = references.get(pending["reference_id"])
        if (
            pending["split"] != "test"
            or reference is None
            or reference["manifest_sha256"] != pending["reference_sha256"]
            or canonical_json_sha256(pending) != request["input_sha256"]
            or any(
                locks.get(scope) != digest
                for scope, digest in _heldout_locks(job["project_id"], pending).items()
            )
        ):
            raise ValidationError("Exchange held-out job does not match its pinned protocol")


def validate_frozen_pose_frames(sections: dict[str, list[dict[str, Any]]]) -> None:
    for row in sections.get("pose_training_dataset_items", []):
        frame = row.get("canonical_pose_json")
        if not isinstance(frame, dict):
            raise ValidationError("Exchange frozen pose training frame is missing")
        payload = {
            "schema_version": "pose-active-learning-verified-pose-0001",
            "video_track_id": row.get("video_track_id"),
            "track_revision": row.get("verified_track_revision"),
            "focus_frame": row.get("frame_index"),
            "pose_schema_id": row.get("pose_schema_id"),
            "pose_schema_revision": row.get("pose_schema_revision"),
            "pose_observations": frame.get("pose_observations") or [],
            "keypoints": frame.get("keypoints") or [],
        }
        if frame.get("frame_index") != row.get("frame_index") or canonical_json_sha256(
            payload
        ) != row.get("verified_pose_sha256"):
            raise ValidationError("Exchange frozen pose training frame checksum does not match")


def remap_pose_row(
    session: Session,
    name: str,
    row: dict[str, Any],
    values: dict[str, Any],
    mapping: dict[str, str],
    digests: dict[str, str],
    source_jobs: dict[str, dict[str, Any]],
    track_digests: dict[str, tuple[str, str]],
) -> None:
    """Rehash canonical projections while leaving original evidence in the source archive."""
    for key, json_field in _JSON_HASHES.get(name, {}).items():
        if name == "pose_identity_truth_datasets":
            manifest = deepcopy(row[json_field])
            _update_keys(manifest, ("project_id", "video_id"), mapping)
            _update_keys(manifest["pose_schema"], ("id",), mapping)
            values[json_field] = manifest
        elif name == "pose_measurement_runs":
            manifest = values[json_field]
            manifest["observations"].sort(
                key=lambda item: (item["animal_identity_id"], item["frame_index"], item["id"])
            )
            manifest["identity_ids"].sort()
        elif name == "reefpose_references":
            manifest = deepcopy(row[json_field])
            _remap_reference_manifest(manifest, mapping)
            if manifest["parent_sha256"] is not None:
                manifest["parent_sha256"] = digests[manifest["parent_sha256"]]
            values[json_field] = manifest
        replacement = canonical_json_sha256(values[json_field])
        digests[row[key]] = values[key] = replacement

    if name == "pose_identity_association_runs" and (job := source_jobs.get(row["source_job_id"])):
        original = job["request_json"].get("input_manifest")
        if isinstance(original, dict):
            if canonical_json_sha256(original) != row["input_manifest_sha256"]:
                raise ValidationError(
                    "Exchange identity association source manifest is inconsistent"
                )
            remapped = _identity_manifest(original, mapping, track_digests)
            target_job = session.get(Job, mapping[job["id"]])
            if target_job is not None:
                target_job.request_json = {**target_job.request_json, "input_manifest": remapped}
            replacement = canonical_json_sha256(remapped)
            digests[row["input_manifest_sha256"]] = values["input_manifest_sha256"] = replacement
    if name == "pose_identity_evaluation_runs":
        provenance = values["provenance_json"]
        _update_keys(
            provenance, ("association_input_manifest_sha256", "truth_manifest_sha256"), digests
        )
        replacement = canonical_json_sha256(_evaluation_summary(values))
        digests[row["result_sha256"]] = values["result_sha256"] = replacement
    if name == "pose_evaluation_runs":
        provenance = values["provenance_json"]
        dataset = session.get(PoseTrainingDataset, values["evaluation_dataset_id"])
        if dataset is not None:
            provenance["dataset_manifest_sha256"] = dataset.manifest_sha256
        replacement = pose_evaluation_result_sha256(PoseEvaluationRun(**values))
        digests[row["result_sha256"]] = values["result_sha256"] = replacement
    if name == "pose_measurement_runs":
        values["configuration_json"]["identity_ids"].sort()
        _update_keys(values, ("result_sha256",), digests)
        target_job = session.get(Job, values["source_job_id"]) if values["source_job_id"] else None
        if target_job is not None:
            target_job.request_json = {
                **target_job.request_json,
                "input_manifest_sha256": values["input_manifest_sha256"],
            }
            result = dict(target_job.result_json or {})
            _update_keys(result, ("input_manifest_sha256", "result_sha256"), digests)
            target_job.result_json = result
    if name == "pose_measurement_series":
        _update_keys(values, ("series_sha256",), digests)
    if name == "pose_event_detection_runs":
        _update_keys(values["provenance_json"], ("measurement_result_sha256",), digests)


def restore_pose_reports(
    session: Session,
    sections: dict[str, list[dict[str, Any]]],
    id_map: dict[str, str],
    digests: dict[str, str],
    map_values: Callable[[Any, dict[str, str]], Any],
) -> dict[str, str]:
    """Restore completed report links and preserve the archived observations digest."""
    old_reports = [
        row
        for row in sections.get("jobs", [])
        if row["job_type"] == "reefpose_validation" and row["status"] == "succeeded"
    ]
    locks: dict[str, str] = {}
    observations: dict[str, list[dict[str, Any]]] = {}
    for row in sections.get("pose_identity_observations", []):
        if row["revision"] == 1 and row["assignment_source"] == "model":
            observations.setdefault(row["association_run_id"], []).append(
                {
                    "id": row["id"],
                    "identity_id": row["animal_identity_id"],
                    "frame": row["frame_index"],
                    "time_s": row["time_s"],
                    "bbox": row["bbox_json"],
                    "landmarks": row["landmarks_json"],
                    "association_confidence": row["association_confidence"],
                    "detection_key": row["source_detection_key"],
                    "source_track_id": row["source_video_track_id"],
                }
            )

    def remap_manifest(original: dict[str, Any]) -> dict[str, Any]:
        report: dict[str, Any] = map_values(original, {**id_map, **digests})
        report["models"] = {
            id_map[key]: map_values(value, {**id_map, **digests})
            for key, value in original["models"].items()
        }
        manifest = deepcopy(original["scored_reference_manifest"])
        _remap_reference_manifest(manifest, id_map)
        _update_keys(manifest, ("parent_sha256",), digests)
        report["scored_reference_manifest"] = manifest
        for old_entry, entry in zip(
            original["prediction_sources"], report["prediction_sources"], strict=True
        ):
            source_observations = observations.get(old_entry.get("id"), [])
            old_hash = old_entry["observations_sha256"]
            original_order = sorted(source_observations, key=lambda row: (row["frame"], row["id"]))
            if canonical_json_sha256(original_order) == old_hash:
                copied = deepcopy(source_observations)
                for observation in copied:
                    _update_keys(observation, ("id", "identity_id", "source_track_id"), id_map)
                copied.sort(key=lambda row: (row["frame"], row["id"]))
                entry["observations_sha256"] = canonical_json_sha256(copied)
        report["prediction_sources"].sort(key=lambda item: item["video_id"])
        return report

    waiting: dict[str, list[dict[str, Any]]] = {}
    for row in old_reports:
        waiting.setdefault(row["result_json"]["result_sha256"], []).append(row)
    while waiting:
        ready = [
            digest
            for digest, rows in waiting.items()
            if rows[0]["result_json"]["development_lock_sha256"] not in waiting
        ]
        if not ready:
            raise ValidationError("Exchange ReefPose validation reports form a dependency cycle")
        for digest in ready:
            report_jobs = waiting.pop(digest)
            source = report_jobs[0]
            old_report = source["result_json"]
            report = remap_manifest(old_report)
            if report["split"] == "test":
                locks.update(_heldout_locks(source["project_id"], report))
            manifest_keys = (
                "schema_version",
                "reference_id",
                "reference_sha256",
                "scored_reference_manifest",
                "data_kind",
                "split",
                "rater_id",
                "models",
                "prediction_sources",
                "tracker_protocol",
                "development_lock_sha256",
                "configurations",
                "bootstrap_seed",
            )
            report["input_sha256"] = canonical_json_sha256(
                {key: report[key] for key in manifest_keys}
            )
            report.pop("result_sha256")
            report["result_sha256"] = canonical_json_sha256(report)
            digests[digest] = report["result_sha256"]
            for row in report_jobs:
                job = session.get(Job, id_map[row["id"]])
                if job is not None:
                    job.result_json = report
                    request = dict(job.request_json)
                    request["input_sha256"] = report["input_sha256"]
                    job.request_json = request
    for source in sections.get("jobs", []):
        if source["job_type"] != "reefpose_validation":
            continue
        original = source["request_json"].get("heldout_input_manifest")
        if original is None:
            continue
        updated = remap_manifest(original)
        locks.update(_heldout_locks(source["project_id"], updated))
        job = session.get(Job, id_map[source["id"]])
        if job is not None:
            job.request_json = {
                **job.request_json,
                "heldout_input_manifest": updated,
                "input_sha256": canonical_json_sha256(updated),
            }
    return locks


def restore_pose_model_lineage(
    session: Session,
    project_id: str,
    sections: dict[str, list[dict[str, Any]]],
    mapping: dict[str, str],
    digests: dict[str, str],
) -> None:
    source_datasets = {
        row["id"]: row["manifest_sha256"] for row in sections.get("pose_training_datasets", [])
    }
    datasets = {
        row.id: row.manifest_sha256
        for row in session.scalars(
            select(PoseTrainingDataset).where(PoseTrainingDataset.project_id == project_id)
        )
    }
    digests.update(
        {digest: datasets[mapping[identifier]] for identifier, digest in source_datasets.items()}
    )
    for row in sections.get("models", []):
        source = row.get("metadata_json") or {}
        model = session.get(ModelRegistration, mapping[row["id"]])
        if model is None:
            continue
        metadata = dict(model.metadata_json or {})
        for purpose in ("training", "validation"):
            field = f"source_pose_{purpose}_dataset"
            original_id = source.get(f"{field}_id")
            old_digest = source.get(f"{field}_manifest_sha256")
            if (
                isinstance(original_id, str)
                and original_id in source_datasets
                and old_digest == source_datasets[original_id]
            ):
                metadata[f"{field}_manifest_sha256"] = datasets[mapping[original_id]]
        if metadata != model.metadata_json:
            model.metadata_json = metadata


def restore_phase6_track_digests(
    session: Session,
    project_id: str,
    mapping: dict[str, str],
    track_digests: dict[str, tuple[str, str]],
) -> None:
    if not track_digests:
        return
    imported_track_digests = {
        mapping[identifier]: pair for identifier, pair in track_digests.items()
    }
    for job in session.scalars(
        select(Job).where(Job.project_id == project_id, Job.job_type == "video_tracking")
    ):
        result = dict(job.result_json or {})
        inventory = result.get("pose_track_hashes")
        if isinstance(inventory, dict):
            result["pose_track_hashes"] = {
                identifier: pair[1]
                if (pair := imported_track_digests.get(identifier)) and digest == pair[0]
                else digest
                for identifier, digest in inventory.items()
            }
            job.result_json = result


def restore_pose_comparisons(session: Session, project_id: str, digests: dict[str, str]) -> None:
    """Rebind evaluation results after the importer has rebuilt training manifests."""
    datasets = {
        row.id: row
        for row in session.scalars(
            select(PoseTrainingDataset).where(PoseTrainingDataset.project_id == project_id)
        )
    }
    for run in session.scalars(
        select(PoseEvaluationRun).where(PoseEvaluationRun.project_id == project_id)
    ):
        dataset = datasets[run.evaluation_dataset_id]
        previous = dict(run.provenance_json)
        if previous.get("dataset_manifest_sha256") != dataset.manifest_sha256:
            run.provenance_json = {**previous, "dataset_manifest_sha256": dataset.manifest_sha256}
            after = pose_evaluation_result_sha256(run)
            for before, current in list(digests.items()):
                if current == run.result_sha256:
                    digests[before] = after
            digests[run.result_sha256] = after
            run.result_sha256 = after
    for job in session.scalars(
        select(Job).where(Job.project_id == project_id, Job.job_type == "pose_evaluation")
    ):
        report = deepcopy(job.result_json or {})
        old_report_hash = report.pop("report_sha256", None)
        request = deepcopy(job.request_json)
        job_dataset = datasets.get(request.get("evaluation_dataset_id", ""))
        if job_dataset is None:
            continue
        request["dataset_manifest_sha256"] = job_dataset.manifest_sha256
        if old_report_hash is None:
            job.request_json = request
            continue
        report["dataset_manifest_sha256"] = job_dataset.manifest_sha256
        for model in report.get("models", []):
            _update_keys(model, ("result_sha256",), digests)
            model["provenance"]["dataset_manifest_sha256"] = job_dataset.manifest_sha256
        request_hash = canonical_json_sha256(
            {
                "schema_version": "pose-evaluation-comparison-request-0001",
                "project_id": project_id,
                "models": sorted(request["model_identities"], key=lambda row: row["model_id"]),
                "dataset_id": job_dataset.id,
                "dataset_manifest_sha256": job_dataset.manifest_sha256,
                "configuration": {
                    **report["configuration"],
                    "evaluation_dataset_id": job_dataset.id,
                },
                "submission_context": {
                    key: request[key]
                    for key in ("workflow_run_id", "workflow_node_run_id")
                    if key in request
                },
            }
        )
        old_request_hash = request.get("request_sha256")
        if old_request_hash:
            digests[old_request_hash] = request_hash
        report["request_sha256"] = request["request_sha256"] = request_hash
        report_hash = canonical_json_sha256(report)
        report["report_sha256"] = digests[old_report_hash] = report_hash
        job.result_json = report
        job.request_json = request


def heldout_scope(project_id: str, video_checksum: str, model_checksum: str | None) -> str:
    return canonical_json_sha256(
        {"project": project_id, "video": video_checksum, "checkpoint": model_checksum}
    )


def _heldout_locks(project_id: str, manifest: dict[str, Any]) -> dict[str, str]:
    sources = {entry["video_id"]: entry for entry in manifest["prediction_sources"]}
    locks = {}
    for recording in manifest["scored_reference_manifest"]["recordings"]:
        source = sources[recording["video_id"]]
        checkpoint = manifest["models"].get(source["model_id"], {}).get("checkpoint_sha256")
        scope = heldout_scope(project_id, recording["video_sha256"], checkpoint)
        locks[scope] = canonical_json_sha256(
            {
                "development_lock": manifest["development_lock_sha256"],
                "tracker_protocol": manifest["tracker_protocol"],
                "reference": manifest["reference_sha256"],
                "rater": manifest["rater_id"],
                "bootstrap_seed": manifest["bootstrap_seed"],
                "observations_sha256": source["observations_sha256"],
            }
        )
    return locks
