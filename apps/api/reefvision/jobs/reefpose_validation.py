"""Queue and execute immutable ReefPose validation reports."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import (
    Job,
    ModelRegistration,
    PoseIdentityAssociationRun,
    PoseIdentityObservation,
    PoseTrainingDataset,
    PoseTrainingDatasetItem,
    VideoAsset,
    VideoTrack,
)
from reefvision.db.models.reefpose_validation import ReefPoseHeldoutLock
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.schemas.reefpose_validation import ValidationConfiguration, ValidationRequest
from reefvision.services.reefpose_validation import ReferenceService, frozen_recording
from reefvision.services.reefpose_validation_analysis import analyze
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.storage.results_packages import sha256_file

JOB_TYPE = "reefpose_validation"


def completed_report(session: Session, project_id: str, job_id: str) -> dict[str, Any]:
    job = session.get(Job, job_id)
    if job is None or job.project_id != project_id or job.job_type != JOB_TYPE:
        raise NotFoundError("Scientific validation job was not found")
    if job.status != "succeeded":
        raise ValidationError("Scientific validation has no completed report")
    report = dict(job.result_json or {})
    digest = report.pop("result_sha256", None)
    if digest != canonical_json_sha256(report):
        raise ValidationError("Scientific validation result hash does not match")
    return {**report, "result_sha256": digest}


def _model_snapshot(
    session: Session,
    model_id: str,
    video_hashes: set[str],
    *,
    biological: bool,
    ancestors: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    if model_id in ancestors or len(ancestors) >= 32:
        raise ValidationError("Source model initialization lineage is cyclic or too deep")
    model = session.get(ModelRegistration, model_id)
    if model is None:
        raise ValidationError("Source model registration is missing")
    metadata = model.metadata_json or {}
    lineage = []
    for purpose in ("training", "validation"):
        dataset_id = metadata.get(f"source_pose_{purpose}_dataset_id")
        if not dataset_id:
            continue
        dataset = session.get(PoseTrainingDataset, str(dataset_id))
        if dataset is None or (
            metadata.get(f"source_pose_{purpose}_dataset_manifest_sha256")
            != dataset.manifest_sha256
        ):
            raise ValidationError("Source model dataset lineage is missing or inconsistent")
        hashes = set(
            session.scalars(
                select(PoseTrainingDatasetItem.video_sha256).where(
                    PoseTrainingDatasetItem.dataset_id == dataset.id
                )
            )
        )
        if hashes & video_hashes:
            raise ValidationError(
                "Training or model-selection video overlaps the scientific reference"
            )
        if not hashes:
            raise ValidationError("Source model dataset has no verifiable video lineage")
        lineage.append(
            {
                "purpose": purpose,
                "id": dataset.id,
                "sha256": dataset.manifest_sha256,
                "video_sha256": sorted(hashes),
            }
        )
    if biological and not any(item["purpose"] == "training" for item in lineage):
        raise ValidationError("Biological scoring requires verifiable model training lineage")
    initial_id = metadata.get("source_initial_pose_model_id")
    initial_hash = metadata.get("source_initial_pose_model_sha256")
    initial_model = None
    if initial_id:
        initial_model = _model_snapshot(
            session,
            str(initial_id),
            video_hashes,
            biological=biological,
            ancestors=ancestors | {model_id},
        )
        if initial_model["checkpoint_sha256"] != initial_hash:
            raise ValidationError("Initialization checkpoint hash does not match model lineage")
    elif biological and initial_hash:
        raise ValidationError("Biological scoring requires verifiable initialization lineage")
    return {
        "id": model.id,
        "name": model.display_name,
        "provider": model.provider_name,
        "provider_version": model.provider_version,
        "checkpoint_sha256": model.sha256,
        "lineage": lineage,
        "initialization_model": initial_model,
    }


def _inputs(
    session: Session,
    settings: Settings,
    project_id: str,
    request: ValidationRequest,
) -> tuple[dict[str, Any], list[Any], list[ValidationConfiguration]]:
    frozen = ReferenceService(session).get(project_id, str(request.reference_id))
    biological = frozen.data_kind == "biological"
    recordings = [row for row in frozen.manifest["recordings"] if row["split"] == request.split]
    video_hashes = {row["video_sha256"] for row in frozen.manifest["recordings"]}
    if not recordings or {row["video_id"] for row in recordings} != {
        str(key) for key in request.source_runs.keys() | request.zero_detection_jobs.keys()
    }:
        raise ValidationError(
            "Provide one original identity run for each video in the selected split"
        )
    sources = []
    records = []
    models: dict[str, dict[str, Any]] = {}
    for row in sorted(recordings, key=lambda item: item["video_id"]):
        record = frozen_recording(row)
        annotation = next(
            (item for item in record.annotations if item.rater_id == request.rater_id), None
        )
        if annotation is None:
            raise ValidationError("Selected rater does not cover every recording in the split")
        if biological and request.split == "test" and not annotation.adjudicates:
            raise ValidationError("Biological test scoring requires an adjudicated reference")
        if biological and any(
            not item.blinded for item in record.annotations if not item.adjudicates
        ):
            raise ValidationError(
                "Biological scoring requires a blinding attestation from each rater"
            )
        video = session.get(VideoAsset, str(record.video_id))
        if (
            video is None
            or video.project_id != project_id
            or video.sha256 != record.video_sha256
            or video.frame_count != row["video_geometry"]["frames"]
            or video.fps != row["video_geometry"]["fps"]
            or video.duration_seconds != row["video_geometry"]["duration_s"]
            or video.width_px != row["video_geometry"]["width"]
            or video.height_px != row["video_geometry"]["height"]
            or not video.fps
            or video.fps <= 0
        ):
            raise ValidationError(
                "Source video does not match the frozen reference geometry and content"
            )
        if biological:
            try:
                actual_hash = sha256_file(
                    resolve_managed_project_path(settings, video.managed_path)
                )
            except OSError as exc:
                raise ValidationError("Reference source video is unavailable") from exc
            if actual_hash != record.video_sha256:
                raise ValidationError("Reference source video bytes do not match the frozen hash")
        upstream_protocol = None
        names = {point["id"]: point["name"] for point in row["schema"]["landmarks"]}
        if zero_id := request.zero_detection_jobs.get(record.video_id):
            zero = session.get(Job, str(zero_id))
            result = (zero.result_json or {}) if zero else {}
            schema = result.get("pose_landmark_schema") or {}
            model_id = str(result.get("model_id") or "")
            if (
                zero is None
                or zero.project_id != project_id
                or zero.status != "succeeded"
                or zero.job_type != "video_tracking"
                or result.get("video_id") != video.id
                or result.get("pose_track_hashes") != {}
                or result.get("detection_count") != 0
                or not model_id
                or schema.get("schema_id") != str(record.schema_id)
                or schema.get("schema_revision") != record.schema_revision
                or schema.get("content_hash") != record.schema_sha256
            ):
                raise ValidationError("Expected a complete zero-detection pose tracking job")
            model = _model_snapshot(session, model_id, video_hashes, biological=biological)
            models[model_id] = model
            if result.get("pose_input_hashes") != {
                "model_sha256": model["checkpoint_sha256"],
                "video_sha256": record.video_sha256,
            }:
                raise ValidationError("Zero-detection source hashes do not match")
            source: dict[str, Any] = {
                "id": zero.id,
                "video_id": video.id,
                "model_id": model_id,
                "algorithm": None,
                "algorithm_version": None,
                "parameters_sha256": None,
                "upstream_protocol": result.get("pose_inference_protocol"),
                "fps": video.fps,
                "observations": [],
            }
            sources.append(
                {
                    **{key: value for key, value in source.items() if key != "observations"},
                    "observations_sha256": canonical_json_sha256([]),
                }
            )
            records.append((record, annotation, source, names))
            continue
        run = session.get(PoseIdentityAssociationRun, str(request.source_runs[record.video_id]))
        if (
            run is None
            or run.project_id != project_id
            or run.status != "completed"
            or run.video_id != video.id
            or run.pose_schema_id != str(record.schema_id)
            or run.pose_schema_revision != record.schema_revision
            or run.pose_schema_content_hash != record.schema_sha256
            or run.source_coordinate_space != "source_pixels"
            or (run.source_width, run.source_height) != (video.width_px, video.height_px)
        ):
            raise ValidationError("Source run does not match the frozen anatomy schema and video")
        if run.source_model_id:
            if run.source_model_id not in models:
                models[run.source_model_id] = _model_snapshot(
                    session,
                    run.source_model_id,
                    video_hashes,
                    biological=biological,
                )
            if biological:
                source_job = session.get(Job, run.source_job_id) if run.source_job_id else None
                # The identity job must bind the original tracking inputs before review.
                if source_job is None or source_job.status not in {"completed", "succeeded"}:
                    raise ValidationError(
                        "Biological scoring requires completed association job provenance"
                    )
                original = source_job.request_json.get("input_manifest") or {}
                if canonical_json_sha256(original) != run.input_manifest_sha256:
                    raise ValidationError("Original association manifest integrity check failed")
                track_hashes = {
                    entry["id"]: entry["keyframes_sha256"] for entry in original.get("tracks", [])
                }
                upstream_ids: set[str] = set()
                for entry in original.get("tracks", []):
                    track = session.get(VideoTrack, entry["id"])
                    tracking_job = (
                        session.get(Job, track.source_job_id)
                        if track is not None and track.source_job_id
                        else None
                    )
                    if (
                        track is None
                        or track.source_model_id != run.source_model_id
                        or track.revision != 1
                        or entry["revision"] != 1
                        or canonical_json_sha256(track.keyframes_json) != entry["keyframes_sha256"]
                        or tracking_job is None
                        or tracking_job.job_type != "video_tracking"
                        or tracking_job.status != "succeeded"
                    ):
                        raise ValidationError(
                            "Scientific comparison requires original model track lineage"
                        )
                    upstream_ids.add(tracking_job.id)
                if len(upstream_ids) != 1:
                    raise ValidationError(
                        "Scientific comparison requires one complete tracking output"
                    )
                upstream = session.get(Job, next(iter(upstream_ids)))
                assert upstream is not None
                upstream_result = upstream.result_json or {}
                if upstream_result.get("pose_track_hashes") != track_hashes or upstream_result.get(
                    "pose_input_hashes"
                ) != {
                    "model_sha256": models[run.source_model_id]["checkpoint_sha256"],
                    "video_sha256": record.video_sha256,
                }:
                    raise ValidationError(
                        "Tracking output is incomplete or its input hashes differ"
                    )
                upstream_protocol = upstream_result.get("pose_inference_protocol")
                if not isinstance(upstream_protocol, dict):
                    raise ValidationError("Tracking inference protocol is missing")
        elif biological:
            raise ValidationError("Biological scoring requires a registered source model")
        observations = [
            {
                "id": obs.id,
                "identity_id": obs.animal_identity_id,
                "frame": obs.frame_index,
                "time_s": obs.time_s,
                "bbox": obs.bbox_json,
                "landmarks": obs.landmarks_json,
                "association_confidence": obs.association_confidence,
                "detection_key": obs.source_detection_key,
                "source_track_id": obs.source_video_track_id,
            }
            for obs in session.scalars(
                select(PoseIdentityObservation)
                .where(
                    PoseIdentityObservation.association_run_id == run.id,
                    PoseIdentityObservation.revision == 1,
                    PoseIdentityObservation.assignment_source == "model",
                )
                .order_by(PoseIdentityObservation.frame_index, PoseIdentityObservation.id)
            )
        ]
        source = {
            "id": run.id,
            "video_id": run.video_id,
            "model_id": run.source_model_id,
            "input_manifest_sha256": run.input_manifest_sha256,
            "algorithm": run.algorithm,
            "algorithm_version": run.algorithm_version,
            "parameters": run.parameters_json,
            "upstream_protocol": upstream_protocol,
            "parameters_sha256": run.parameters_sha256,
            "fps": video.fps,
            "video_revision_at_scoring": video.revision,
            "observations": observations,
        }
        sources.append(
            {
                **{k: v for k, v in source.items() if k != "observations"},
                "observations_sha256": canonical_json_sha256(observations),
            }
        )
        records.append((record, annotation, source, names))
    configurations = request.configurations
    lock_hash = None
    tracker_protocol = sorted(
        {
            (
                item["algorithm"],
                item["algorithm_version"],
                item["parameters_sha256"],
                canonical_json_sha256(item["upstream_protocol"]),
            )
            for item in sources
            if item["algorithm"] is not None
        }
    )
    if request.development_job_id:
        lock = completed_report(session, project_id, str(request.development_job_id))
        if (
            lock["split"] != "development"
            or lock["reference_sha256"] != frozen.manifest_sha256
            or lock["models"] != models
            or not set(tracker_protocol) <= {tuple(row) for row in lock["tracker_protocol"]}
            or not {canonical_json_sha256(item["upstream_protocol"]) for item in sources}
            <= {
                canonical_json_sha256(item["upstream_protocol"])
                for item in lock["prediction_sources"]
            }
            or lock["schema_version"] != "reefpose-scientific-validation-1"
        ):
            raise ValidationError(
                "Development lock does not match the reference, model and tracker"
            )
        lock_hash = lock["result_sha256"]
        configurations = [ValidationConfiguration.model_validate(lock["selected_configuration"])]
    for config in configurations:
        for record, annotation, _, names in records:
            if any(not set(item.landmark_ids) <= names.keys() for item in config.definitions):
                raise ValidationError(
                    f"Measurement definition uses an unknown landmark for {record.video_id}"
                )
            labels = {cycle.label for cycle in config.events}
            if labels != {window.label for window in record.event_windows}:
                raise ValidationError(
                    "Every configuration must score the same declared event labels"
                )
            defined = {item.id for item in config.definitions}
            frozen_definitions = {item.id: item for item in record.measurement_protocol}
            if frozen_definitions and (
                defined != frozen_definitions.keys()
                or any(
                    (item.kind, item.landmark_ids, item.options)
                    != (
                        frozen_definitions[item.id].kind,
                        frozen_definitions[item.id].landmark_ids,
                        frozen_definitions[item.id].options,
                    )
                    for item in config.definitions
                )
            ):
                raise ValidationError("Configuration changes the frozen measurement protocol")
            if any(sample.definition_id not in defined for sample in annotation.measurements):
                raise ValidationError("Configuration omits a declared reference measurement")
    if configurations:
        protocol = configurations[0]
        for config in configurations[1:]:
            if (
                config.definitions != protocol.definitions
                or config.onset_tolerance_s != protocol.onset_tolerance_s
                or config.offset_tolerance_s != protocol.offset_tolerance_s
                or config.iou_threshold != protocol.iou_threshold
                or config.pck_thresholds != protocol.pck_thresholds
                or {(row.label, row.definition_id, row.unit) for row in config.events}
                != {(row.label, row.definition_id, row.unit) for row in protocol.events}
            ):
                raise ValidationError(
                    "Sensitivity configurations must use the same scoring protocol"
                )
        if len(configurations) > 1 and not any(
            event.quality == "scored" and event.state == "complete"
            for _, annotation, _, _ in records
            for event in annotation.events
        ):
            raise ValidationError("Threshold selection requires scored complete development events")
    manifest = {
        "schema_version": "reefpose-scientific-validation-1",
        "reference_id": frozen.id,
        "reference_sha256": frozen.manifest_sha256,
        "scored_reference_manifest": {**frozen.manifest, "recordings": recordings},
        "data_kind": frozen.data_kind,
        "split": request.split,
        "rater_id": request.rater_id,
        "models": models,
        "prediction_sources": sources,
        "tracker_protocol": [list(row) for row in tracker_protocol],
        "development_lock_sha256": lock_hash,
        "configurations": [config.model_dump(mode="json") for config in configurations],
        "bootstrap_seed": request.bootstrap_seed,
    }
    return manifest, records, configurations


def _pin_test_protocol(
    session: Session,
    project_id: str,
    manifest: dict[str, Any],
) -> None:
    if manifest["split"] != "test":
        return
    sources = {item["video_id"]: item for item in manifest["prediction_sources"]}
    for recording in manifest["scored_reference_manifest"]["recordings"]:
        source = sources[recording["video_id"]]
        model = manifest["models"].get(source["model_id"], {})
        scope = canonical_json_sha256(
            {
                "project": project_id,
                "video": recording["video_sha256"],
                "checkpoint": model.get("checkpoint_sha256"),
            }
        )
        protocol = canonical_json_sha256(
            {
                "development_lock": manifest["development_lock_sha256"],
                "tracker_protocol": manifest["tracker_protocol"],
                "reference": manifest["reference_sha256"],
                "rater": manifest["rater_id"],
                "bootstrap_seed": manifest["bootstrap_seed"],
                "observations_sha256": source["observations_sha256"],
            }
        )
        lock = session.get(ReefPoseHeldoutLock, scope)
        if lock is not None:
            if lock.protocol_sha256 != protocol:
                raise ConflictError(
                    "Held-out protocol is already locked for this video and checkpoint"
                )
        else:
            session.add(
                ReefPoseHeldoutLock(
                    scope_sha256=scope,
                    project_id=project_id,
                    protocol_sha256=protocol,
                )
            )


def submit_validation(
    session: Session,
    settings: Settings,
    project_id: str,
    request: ValidationRequest,
    *,
    workflow_context: dict[str, str] | None = None,
) -> Job:
    manifest, records, configurations = _inputs(session, settings, project_id, request)
    _pin_test_protocol(session, project_id, manifest)
    input_hash = canonical_json_sha256(manifest)
    if workflow_context and all(workflow_context.values()):
        existing = session.scalar(
            select(Job)
            .where(
                Job.job_type == JOB_TYPE,
                Job.project_id == project_id,
                Job.status.in_(("queued", "running", "succeeded")),
                Job.request_json["input_sha256"].as_string() == input_hash,
                Job.request_json["workflow_run_id"].as_string()
                == workflow_context["workflow_run_id"],
                Job.request_json["workflow_node_run_id"].as_string()
                == workflow_context["workflow_node_run_id"],
            )
            .order_by(Job.created_at, Job.id)
            .limit(1)
        )
        if existing is not None:
            session.commit()
            return existing
    job = Job(
        project_id=project_id,
        job_type=JOB_TYPE,
        status="queued",
        progress_total=len(records) * len(configurations),
        request_json={
            "payload": request.model_dump(mode="json"),
            "input_sha256": input_hash,
            **(workflow_context or {}),
        },
    )
    session.add(job)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError("Concurrent held-out protocol submission. Retry the request.") from exc
    session.refresh(job)
    return job


class _Cancelled(Exception):
    pass


def process_reefpose_validation_job(
    settings: Settings,
    factory: sessionmaker[Session],
    job_id: str,
) -> bool:
    with factory() as session:
        claimed = session.execute(
            update(Job)
            .where(
                Job.id == job_id,
                Job.job_type == JOB_TYPE,
                Job.status == "queued",
            )
            .values(status="running", started_at=datetime.now(UTC), progress_current=0)
        )
        session.commit()
        if not cast(CursorResult[Any], claimed).rowcount:
            return False
        job = session.get(Job, job_id)
        assert job is not None and job.project_id is not None
        project_id = job.project_id
        try:
            request = ValidationRequest.model_validate(job.request_json["payload"])
            manifest, records, configurations = _inputs(session, settings, project_id, request)
            if canonical_json_sha256(manifest) != job.request_json["input_sha256"]:
                raise ValidationError("Validation inputs changed after submission")

            def progress() -> None:
                advanced = session.execute(
                    update(Job)
                    .where(
                        Job.id == job_id,
                        Job.status == "running",
                    )
                    .values(progress_current=Job.progress_current + 1)
                )
                session.commit()
                if not cast(CursorResult[Any], advanced).rowcount:
                    raise _Cancelled

            analysis = analyze(records, configurations, request.bootstrap_seed, progress)
            report = {
                **manifest,
                **analysis,
                "input_sha256": job.request_json["input_sha256"],
                "selected_configuration": manifest["configurations"][
                    analysis["selected_configuration_index"]
                ],
                "warnings": [
                    "Two-dimensional image projection only.",
                    "Uncertainty intervals require at least five independent recording groups.",
                    "Event precision is conditional on the declared windows and identity coverage.",
                    "Synthetic engineering data."
                    if manifest["data_kind"] == "synthetic"
                    else "Scientific results depend on the reference and blinding attestations.",
                ],
            }
            report["result_sha256"] = canonical_json_sha256(report)
            written = session.execute(
                update(Job)
                .where(
                    Job.id == job_id,
                    Job.status == "running",
                )
                .values(status="succeeded", completed_at=datetime.now(UTC), result_json=report)
            )
            if not cast(CursorResult[Any], written).rowcount:
                raise _Cancelled
        except Exception as exc:
            session.rollback()
            session.refresh(job)
            cancelled = isinstance(exc, _Cancelled) or job.status == "cancel_requested"
            job.status = "cancelled" if cancelled else "failed"
            job.error_message = None if cancelled else str(exc)
            job.result_json = None
            job.completed_at = datetime.now(UTC)
        session.commit()
        return True
