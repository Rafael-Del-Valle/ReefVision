"""Recoverable queued execution of learned ReefPose temporal refinement."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from dataclasses import asdict
from time import perf_counter
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import Job, ModelRegistration, Project, TemporalReefPoseFrame
from reefvision.db.models.project import utc_now
from reefvision.db.models.temporal_reefpose import TemporalReefPoseRun
from reefvision.domain.errors import ReefVisionError, ValidationError
from reefvision.domain.pose_biological_events import CycleDefinition
from reefvision.ml.reefpose.errors import ReefPoseCancelledError, ReefPoseError
from reefvision.schemas.temporal_reefpose import (
    TEMPORAL_RUN_ADAPTER,
    TemporalEvaluationCreate,
    TemporalInferenceCreate,
    TemporalTrainingCreate,
)
from reefvision.services.temporal_reefpose import (
    TEMPORAL_JOB,
    TEMPORAL_PROVIDER,
    TemporalReefPoseService,
    _compatible,
)
from reefvision.services.temporal_reefpose_sources import TEMPORAL_METHOD, source_model
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.storage.temporal_reefpose import read_temporal_checkpoint, save_temporal_checkpoint

LOGGER = logging.getLogger(__name__)
RunProgress = Callable[[int, dict[str, Any]], None]
Cancelled = Callable[[], bool]


def _sequence(source: dict[str, Any]) -> Any:
    from reefvision.ml.reefpose.temporal_data import TemporalFrame, TemporalPoint, TemporalSequence

    def point(value: dict[str, Any]) -> TemporalPoint:
        return TemporalPoint(value["x"], value["y"], value["confidence"], value["visibility"])

    recording = source["recording"]
    identity = source.get("identity")
    return TemporalSequence(
        recording_id=recording["sha256"],
        animal_id=source["animal_id"],
        group_key=source.get("group_key", source["groups"][0]),
        schema_hash=source["schema"]["content_hash"],
        width=recording["width"],
        height=recording["height"],
        frames=tuple(
            TemporalFrame(
                frame_index=frame["frame_index"],
                timestamp_seconds=frame["timestamp_seconds"],
                observations=(
                    tuple(point(item) for item in frame["frame_points"])
                    if frame["frame_points"] is not None
                    else None
                ),
                targets=(
                    tuple(
                        point(item) if item is not None else None for item in frame["target_points"]
                    )
                    if frame["target_points"] is not None
                    else None
                ),
                discontinuity=frame["discontinuity"],
            )
            for frame in source["frames"]
        ),
        identity_revision=f"{identity['run_id']}:{identity['run_revision']}" if identity else None,
        calibration_id=recording["calibration_sha256"],
    )


def _training(
    session: Session,
    settings: Settings,
    row: TemporalReefPoseRun,
    configuration: TemporalTrainingCreate,
    manifest: dict[str, Any],
    progress: RunProgress,
    cancelled: Cancelled,
) -> dict[str, Any]:
    from reefvision.ml.reefpose.temporal import (
        TemporalConfig,
        TemporalTrainingConfig,
        train_temporal,
    )

    project = session.get(Project, row.project_id)
    if project is None:
        raise ValidationError("Temporal training project is unavailable")
    storage_root = project.storage_root
    source_dataset_sha256 = row.input_manifest_json["dataset_sha256"]
    frame_model_sha256 = manifest["frame_model"]["checkpoint_sha256"]
    sources = manifest["sources"]
    landmark_ids = [item["id"] for item in manifest["schema"]["landmarks"]]
    development = [source for source in sources if source["split"] != "test"]
    lineage = {
        "source_temporal_dataset_id": row.dataset_id,
        "source_temporal_dataset_sha256": source_dataset_sha256,
        "frame_model_id": manifest["frame_model"]["id"],
        "frame_model_sha256": frame_model_sha256,
        "landmark_ids": landmark_ids,
        "training_group_keys": sorted(
            {group for source in development for group in source["groups"]}
        ),
        "training_recording_hashes": sorted(
            {source["recording"]["sha256"] for source in development}
        ),
        "training_groups_complete": all(
            any(group.startswith("group:") for group in source["groups"]) for source in development
        ),
    }
    if any(source.get("source_grouping") for source in development):
        lineage["training_declared_groups_complete"] = all(
            source.get("source_grouping") for source in development
        )
    recovery_path = f"{storage_root}/training/temporal/{row.id}/last.pt"
    registered_path = f"{storage_root}/models/{row.id}-temporal.pt"
    resume = read_temporal_checkpoint(settings, recovery_path)
    if resume is not None and resume.get("provenance") != lineage:
        raise ValidationError(
            "Recovery checkpoint does not match frozen temporal training evidence"
        )

    model_config = TemporalConfig(
        num_keypoints=len(landmark_ids),
        window_length=configuration.window_length,
        context_mode=configuration.context_mode,
        channels=configuration.channels,
        max_gap_seconds=configuration.max_gap_seconds,
    )
    training_config = TemporalTrainingConfig(
        epochs=configuration.epochs,
        batch_size=configuration.batch_size,
        learning_rate=configuration.learning_rate,
        loss=configuration.loss,
        seed=configuration.seed,
        device=configuration.device,
    )

    def epoch(epoch_number: int, metrics: dict[str, float], state: dict[str, Any]) -> None:
        save_temporal_checkpoint(settings, recovery_path, {**state, "provenance": lineage})
        progress(epoch_number, {"stage": "training", "metrics": metrics, "resumable": True})

    if resume is not None:
        progress(resume["epoch"], {"stage": "resuming", "resumable": True})
    trained = train_temporal(
        [_sequence(item) for item in sources],
        {item["group_key"]: item["split"] for item in sources},
        model_config,
        training_config,
        resume=resume,
        on_epoch=epoch,
        cancelled=cancelled,
    )
    if cancelled():
        raise ReefPoseCancelledError("Temporal training cancelled")
    checkpoint = {
        key: value for key, value in trained.state.items() if key != "optimizer_state"
    } | {"provenance": lineage}
    sha256, file_size = save_temporal_checkpoint(settings, registered_path, checkpoint)
    metadata = {
        **lineage,
        "architecture": checkpoint["architecture"],
        "architecture_version": checkpoint["architecture_version"],
        "schema_hash": checkpoint["schema_hash"],
        "pose_landmark_schema": manifest["schema"],
        "normalization": checkpoint["normalization"],
        "timing_policy": checkpoint["timing_policy"],
        "window_length": model_config.window_length,
        "context_mode": model_config.context_mode,
        "max_future_frames": model_config.future_frames,
        "source_workflow": TEMPORAL_METHOD,
        "source_temporal_run_id": row.id,
        "model_configuration": asdict(model_config),
        "training_configuration": asdict(training_config),
        "metrics_history": trained.metrics_history,
    }
    model = ModelRegistration(
        project_id=row.project_id,
        purpose="pose_temporal",
        display_name=f"{configuration.name[:174]} · {row.id[:8]}",
        source_filename=f"{row.id}-temporal.pt",
        managed_path=registered_path,
        sha256=sha256,
        file_size_bytes=file_size,
        framework="reefpose",
        task="pose_temporal",
        provider_name=TEMPORAL_PROVIDER,
        provider_version="1",
        metadata_json=metadata,
    )
    session.add(model)
    session.flush()
    return {
        "model_id": model.id,
        "checkpoint_sha256": sha256,
        "metrics_history": trained.metrics_history,
        "architecture": metadata["architecture"],
        "context_mode": model_config.context_mode,
        "window_length": model_config.window_length,
        "maximum_future_frames": model_config.future_frames,
        "normalization": metadata["normalization"],
        "timing_policy": metadata["timing_policy"],
    }


def _loaded_model(
    session: Session,
    settings: Settings,
    row: TemporalReefPoseRun,
    configuration: TemporalEvaluationCreate | TemporalInferenceCreate,
    source: dict[str, Any],
) -> tuple[ModelRegistration, Any]:
    from reefvision.ml.reefpose.temporal import load_temporal_model

    model = source_model(session, row.project_id, str(configuration.temporal_model_id))
    metadata = _compatible(source, model)
    if model.sha256 != row.input_manifest_json["temporal_model_sha256"]:
        raise ValidationError("Temporal model checkpoint changed after the run was submitted")
    state = read_temporal_checkpoint(settings, model.managed_path, model.sha256)
    assert state is not None  # A required checkpoint never returns None.
    provenance = state.get("provenance") or {}
    if state.get("schema_hash") != source["schema"]["content_hash"] or any(
        provenance.get(key) != metadata.get(key)
        for key in (
            "frame_model_sha256",
            "training_group_keys",
            "training_recording_hashes",
            "training_groups_complete",
            "training_declared_groups_complete",
            "landmark_ids",
        )
    ):
        raise ValidationError("Temporal checkpoint provenance does not agree with its registration")
    return model, load_temporal_model(state, device=configuration.device)


def _predictions(
    model: Any, source: dict[str, Any], chunk_size: int, cancelled: Cancelled
) -> Iterator[dict[str, Any]]:
    from reefvision.ml.reefpose.temporal import iter_refined

    ids = [item["id"] for item in source["schema"]["landmarks"]]
    for frame, result in zip(
        source["frames"],
        iter_refined(model, _sequence(source), chunk_size=chunk_size, cancelled=cancelled),
        strict=True,
    ):
        yield {
            "frame_index": result.frame_index,
            "timestamp_seconds": result.timestamp_seconds,
            "timestamp_source": frame["timestamp_source"],
            "discontinuity": frame["discontinuity"],
            "frame_points": frame["frame_points"],
            "bbox": frame["bbox"],
            "refined_points": [
                {"landmark_id": identifier, **asdict(point)} if point is not None else None
                for identifier, point in zip(ids, result.points, strict=True)
            ],
            "future_frames": result.future_frames,
            "future_seconds": result.future_seconds,
        }


def _inference(
    session: Session,
    factory: sessionmaker[Session],
    settings: Settings,
    row: TemporalReefPoseRun,
    configuration: TemporalInferenceCreate,
    progress: RunProgress,
    cancelled: Cancelled,
) -> dict[str, Any]:
    source = row.input_manifest_json["source"]
    registration, model = _loaded_model(session, settings, row, configuration, source)
    run_id = row.id
    session.commit()
    # Frame batches are transactional individually. Evidence becomes public only on success.
    with factory() as frames:
        frames.execute(delete(TemporalReefPoseFrame).where(TemporalReefPoseFrame.run_id == run_id))
        frames.commit()
    maximum_future_seconds = 0.0
    total = 0
    batch: list[TemporalReefPoseFrame] = []
    started = perf_counter()
    for evidence in _predictions(model, source, configuration.chunk_size, cancelled):
        maximum_future_seconds = max(maximum_future_seconds, evidence["future_seconds"])
        total += 1
        batch.append(
            TemporalReefPoseFrame(
                run_id=run_id,
                frame_index=evidence["frame_index"],
                evidence_json=evidence,
                evidence_sha256=canonical_json_sha256(evidence),
            )
        )
        if len(batch) >= configuration.chunk_size:
            with factory() as frames:
                frames.add_all(batch)
                frames.commit()
            batch.clear()
            progress(total, {"stage": "refining"})
    if batch:
        with factory() as frames:
            frames.add_all(batch)
            frames.commit()
    return {
        "model_id": registration.id,
        "temporal_model_sha256": registration.sha256,
        "frame_model_id": source["frame_model"]["id"],
        "frame_model_sha256": source["frame_model"]["checkpoint_sha256"],
        "source_video_id": source["recording"]["id"],
        "source_frame_track_id": source["frame_track"]["id"],
        "frame_count": total,
        "context_mode": model.config.context_mode,
        "window_length": model.config.window_length,
        "maximum_future_frames": model.config.future_frames,
        "maximum_future_seconds": maximum_future_seconds,
        "elapsed_seconds": perf_counter() - started,
        "time_source": source["recording"]["time_source"],
    }


def _evaluation(
    session: Session,
    settings: Settings,
    row: TemporalReefPoseRun,
    configuration: TemporalEvaluationCreate,
    manifest: dict[str, Any],
    progress: RunProgress,
    cancelled: Cancelled,
) -> dict[str, Any]:
    import torch

    from reefvision.ml.reefpose.temporal import iter_refined
    from reefvision.ml.reefpose.temporal_metrics import evaluate_temporal_predictions

    registration, model = _loaded_model(session, settings, row, configuration, manifest)
    test = [item for item in manifest["sources"] if item["split"] == "test"]
    sequences = [_sequence(item) for item in test]
    landmark_indices = {
        item["id"]: index for index, item in enumerate(manifest["schema"]["landmarks"])
    }
    edges = [
        (landmark_indices[item["from_id"]], landmark_indices[item["to_id"]])
        for item in manifest["schema"]["edges"]
    ]
    anatomy = None
    if event := configuration.anatomical_events:
        from reefvision.ml.reefpose.temporal_events import AnatomicalEventConfig

        anatomy = AnatomicalEventConfig(
            landmark_ids=(event.landmark_a_id, event.landmark_b_id),
            landmark_slots=(
                landmark_indices[event.landmark_a_id],
                landmark_indices[event.landmark_b_id],
            ),
            definition=CycleDefinition(
                open_threshold=event.open_threshold_px,
                close_threshold=event.close_threshold_px,
                minimum_amplitude=event.minimum_amplitude_px,
                minimum_duration_s=event.minimum_duration_seconds,
                maximum_gap_s=event.maximum_gap_seconds,
            ),
            onset_tolerance_seconds=event.onset_tolerance_seconds,
            offset_tolerance_seconds=event.offset_tolerance_seconds,
        )
    state = manifest["frame_lineage"]["state"]
    grouped_test = all(any(group.startswith("group:") for group in item["groups"]) for item in test)
    typed_test = [bool(item.get("source_grouping")) for item in test]
    typed_training = registration.metadata_json.get("training_declared_groups_complete")
    compatible_grouping = (
        all(typed_test) and typed_training is True
        if any(typed_test) or typed_training is not None
        else grouped_test and registration.metadata_json.get("training_groups_complete")
    )
    temporal_state = "held_out" if compatible_grouping else "recording_disjoint_group_unverified"
    device = next(model.parameters()).device
    if device.type == "cuda":
        torch.cuda.reset_peak_memory_stats(device)
    try:
        import psutil

        process = psutil.Process()
    except (ImportError, OSError):
        process = None
    rss_start = process.memory_info().rss if process is not None else None
    rss_peak = rss_start
    runtime_seconds = 0.0
    completed = 0
    effective_batch = model.config.effective_batch_size(configuration.chunk_size)

    def audited_predictions(sequence: Any) -> Iterator[Any]:
        nonlocal completed, runtime_seconds, rss_peak
        frames = iter_refined(
            model, sequence, chunk_size=configuration.chunk_size, cancelled=cancelled
        )
        while True:
            before = perf_counter()
            result = next(frames, None)
            runtime_seconds += perf_counter() - before
            if result is None:
                return
            completed += 1
            if process is not None and (completed == 1 or completed % effective_batch == 0):
                rss_peak = max(rss_peak or 0, process.memory_info().rss)
            if completed % effective_batch == 0:
                progress(completed, {"stage": "comparing_test_frames"})
            yield result

    metrics = evaluate_temporal_predictions(
        sequences,
        {
            (sequence.recording_id, sequence.animal_id): audited_predictions(sequence)
            for sequence in sequences
        },
        skeleton_edges=edges,
        movement_threshold_px_per_second=configuration.movement_threshold_px_per_second,
        bootstrap_samples=configuration.bootstrap_samples if grouped_test else 0,
        max_gap_seconds=model.config.max_gap_seconds,
        anatomical_events=anatomy,
    )
    return {
        "model_id": registration.id,
        "temporal_model_sha256": registration.sha256,
        "evaluation_status": (
            "held_out" if state == temporal_state == "held_out" else "exploratory"
        ),
        "frame_lineage_state": state,
        "temporal_lineage_state": temporal_state,
        "metrics": metrics,
        "runtime": {
            "refinement_seconds": runtime_seconds,
            "device": str(device),
            "cuda_peak_allocated_bytes": int(torch.cuda.max_memory_allocated(device))
            if device.type == "cuda"
            else None,
            "configured_chunk_frames": configuration.chunk_size,
            "effective_batch_frames": effective_batch,
            "working_batch_input_tensor_byte_bound": model.config.input_tensor_byte_bound(
                configuration.chunk_size
            ),
            "process_rss_bytes_at_start": rss_start,
            "sampled_process_rss_peak_bytes": rss_peak,
            "memory_sampling_scope": "whole_local_worker_process",
            "frame_model_runtime_seconds": [
                item["frame_model"].get("runtime_seconds") for item in test
            ],
        },
    }


def process_temporal_reefpose_job(
    settings: Settings, factory: sessionmaker[Session], job_id: str
) -> bool:
    with factory() as session:
        claimed = session.scalar(
            update(Job)
            .where(Job.id == job_id, Job.job_type == TEMPORAL_JOB, Job.status == "queued")
            .values(status="running", started_at=utc_now(), error_message=None)
            .returning(Job.id)
        )
        session.commit()
    if not claimed:
        return False

    def cancelled() -> bool:
        with factory() as state:
            status = state.scalar(select(Job.status).where(Job.id == job_id))
            return status in {"cancel_requested", "cancelled"} or status is None

    def progress(current: int, result: dict[str, Any]) -> None:
        with factory() as state:
            status = state.scalar(
                update(Job)
                .where(Job.id == job_id, Job.status == "running")
                .values(progress_current=current, result_json=result)
                .returning(Job.id)
            )
            state.commit()
            if not status:
                raise ReefPoseCancelledError("Temporal ReefPose operation cancelled")

    try:
        with factory() as session:
            job = session.get(Job, job_id)
            if job is None or job.project_id is None:
                return False
            service = TemporalReefPoseService(session)
            row = service.run(job.project_id, job.request_json["temporal_run_id"])
            if (
                row.job_id != job.id
                or row.input_manifest_sha256 != job.request_json["input_manifest_sha256"]
            ):
                raise ValidationError("Queued temporal job input does not match the frozen run")
            payload = TEMPORAL_RUN_ADAPTER.validate_python(row.configuration_json)
            if row.configuration_json != row.input_manifest_json.get("configuration"):
                raise ValidationError("Temporal run configuration changed before execution")
            manifest = {}
            if row.dataset_id is not None:
                dataset = service.dataset(row.project_id, row.dataset_id)
                if dataset.manifest_sha256 != row.input_manifest_json["dataset_sha256"]:
                    raise ValidationError("Temporal dataset changed before execution")
                manifest = dataset.manifest_json
            if isinstance(payload, TemporalTrainingCreate):
                result = _training(session, settings, row, payload, manifest, progress, cancelled)
            elif isinstance(payload, TemporalInferenceCreate):
                if service.source_stale(row):
                    raise ValidationError("Source pose changed. Submit a new refinement run.")
                result = _inference(session, factory, settings, row, payload, progress, cancelled)
            else:
                result = _evaluation(session, settings, row, payload, manifest, progress, cancelled)
            changed = session.scalar(
                update(Job)
                .where(Job.id == job.id, Job.status == "running")
                .values(
                    status="succeeded",
                    progress_current=Job.progress_total,
                    completed_at=utc_now(),
                    result_json={"stage": "completed", **result},
                )
                .returning(Job.id)
            )
            if not changed:
                raise ReefPoseCancelledError("Temporal ReefPose operation cancelled")
            row.result_json = result
            session.commit()
    except Exception as exc:
        is_cancelled = isinstance(exc, ReefPoseCancelledError) or cancelled()
        message = (
            str(exc)
            if isinstance(exc, (ReefVisionError, ReefPoseError, ValueError))
            else ("Temporal ReefPose execution failed. See the local application log.")
        )
        if not is_cancelled:
            LOGGER.exception("Temporal ReefPose job %s failed", job_id)
        with factory() as session:
            job = session.get(Job, job_id)
            if job is not None and job.status in {"running", "cancel_requested"}:
                job.status = "cancelled" if is_cancelled else "failed"
                job.completed_at = utc_now()
                job.error_message = message
                job.result_json = {**(job.result_json or {}), "stage": job.status}
                session.commit()
    return True
