"""Dataset and job lifecycle for learned ReefPose temporal refinement."""

from __future__ import annotations

from collections import Counter
from typing import Any, cast

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from reefvision.db.models import (
    Job,
    ModelRegistration,
    PoseAnimalIdentity,
    PoseIdentityAssociationRun,
    Project,
    TemporalReefPoseDataset,
    TemporalReefPoseFrame,
    TemporalReefPoseRun,
    VideoAsset,
    VideoTrack,
)
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.schemas.temporal_reefpose import (
    TemporalDatasetCreate,
    TemporalDatasetDetail,
    TemporalDatasetRead,
    TemporalEvaluationCreate,
    TemporalFrameModelChoice,
    TemporalFramePage,
    TemporalFrameRead,
    TemporalIdentityChoice,
    TemporalInferenceCreate,
    TemporalInputsRead,
    TemporalKind,
    TemporalLandmarkChoice,
    TemporalModelChoice,
    TemporalRunCreate,
    TemporalRunRead,
    TemporalTrackChoice,
    TemporalTrainingCreate,
)
from reefvision.services.temporal_reefpose_sources import (
    REVIEWED,
    TEMPORAL_METHOD,
    frame_training_lineage,
    freeze_source,
    source_model,
    track_binding,
)
from reefvision.storage.datasets import canonical_json_sha256

TEMPORAL_JOB = "temporal_reefpose"
TEMPORAL_PROVIDER = "reefpose_temporal"
TEMPORAL_DATASET_FORMAT = "reefpose-temporal-dataset-0001"


def _check_checksum(payload: dict[str, Any], sha256: str, label: str) -> None:
    if canonical_json_sha256(payload) != sha256:
        raise ConflictError(f"{label} integrity check failed")


def _group_sources(sources: list[dict[str, Any]]) -> None:
    """Unify transitively related recordings before any temporal windows exist."""
    groups: dict[str, set[str]] = {}
    splits: dict[str, str] = {}
    for source in sources:
        keys = set(source["groups"])
        split = source["split"]
        for key in keys:
            if key in splits and splits[key] != split:
                raise ValidationError("Related recordings or animals cannot cross dataset splits")
        connected = keys.union(*(groups[key] for key in keys if key in groups))
        for key in connected:
            groups[key] = connected
            splits[key] = split
    for source in sources:
        source["group_key"] = min(groups[source["groups"][0]])


def _lineage_state(lineage: dict[str, Any], sources: list[dict[str, Any]]) -> str:
    exposed_hashes = {item["sha256"] for item in lineage["recordings"]}
    exposed_groups = {group for item in lineage["recordings"] for group in item["groups"]}
    if any(
        source["recording"]["sha256"] in exposed_hashes
        or bool(exposed_groups.intersection(source["groups"]))
        for source in sources
    ):
        return "exposed"
    grouped = all(any(key.startswith("group:") for key in source["groups"]) for source in sources)
    return "held_out" if lineage["complete"] and sources and grouped else "unverified"


def _compatible(data: dict[str, Any], model: ModelRegistration) -> dict[str, Any]:
    metadata = model.metadata_json or {}
    if model.provider_name != TEMPORAL_PROVIDER or model.task != "pose_temporal":
        raise ValidationError("Select a registered temporal ReefPose checkpoint")
    if (
        metadata.get("schema_hash") != data["schema"]["content_hash"]
        or metadata.get("frame_model_sha256") != data["frame_model"]["checkpoint_sha256"]
    ):
        raise ValidationError("Temporal checkpoint requires the same anatomy and frame checkpoint")
    if not metadata.get("training_group_keys") or not metadata.get("training_recording_hashes"):
        raise ValidationError("Temporal checkpoint training and selection lineage is unavailable")
    return metadata


class TemporalReefPoseService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _project(self, project_id: str) -> None:
        if self.session.get(Project, project_id) is None:
            raise NotFoundError("Project not found")

    def dataset(self, project_id: str, dataset_id: str) -> TemporalReefPoseDataset:
        dataset = self.session.get(TemporalReefPoseDataset, dataset_id)
        if dataset is None or dataset.project_id != project_id:
            raise NotFoundError("Temporal dataset was not found in this project")
        _check_checksum(dataset.manifest_json, dataset.manifest_sha256, "Frozen dataset")
        return dataset

    def run(self, project_id: str, run_id: str) -> TemporalReefPoseRun:
        run = self.session.get(TemporalReefPoseRun, run_id)
        if run is None or run.project_id != project_id:
            raise NotFoundError("Temporal run was not found in this project")
        _check_checksum(run.input_manifest_json, run.input_manifest_sha256, "Temporal run input")
        return run

    def freeze(self, project_id: str, payload: TemporalDatasetCreate) -> TemporalReefPoseDataset:
        # Serialize split checks across competing freeze requests.
        project = self.session.scalar(
            update(Project)
            .where(Project.id == project_id)
            .values(id=Project.id)
            .returning(Project.id)
        )
        if project is None:
            raise NotFoundError("Project not found")
        sources: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        seen_targets: set[str] = set()
        previous = list(
            self.session.scalars(
                select(TemporalReefPoseDataset).where(
                    TemporalReefPoseDataset.project_id == project_id
                )
            )
        )
        prior_splits = {
            key: source["split"]
            for dataset in previous
            for source in dataset.manifest_json["sources"]
            for key in source["groups"]
        }
        for selection in payload.sources:
            source = freeze_source(self.session, project_id, selection)
            source["split"] = selection.split
            scope = (source["recording"]["sha256"], source["animal_id"])
            if scope in seen:
                raise ValidationError("Include only one frame sequence per recording and animal")
            seen.add(scope)
            reviewed_track = source.get("reviewed_track")
            if reviewed_track:
                if reviewed_track["id"] in seen_targets:
                    raise ValidationError("A reviewed track may supervise only one sequence")
                seen_targets.add(reviewed_track["id"])
            if not any(
                point is not None and point["x"] is not None and point["visibility"] == "visible"
                for row in source["frames"]
                for point in (row["target_points"] or [])
            ):
                raise ValidationError(
                    "Each sequence needs a visible human-reviewed landmark target"
                )
            if any(
                prior_splits.get(key, selection.split) != selection.split
                for key in source["groups"]
            ):
                raise ValidationError(
                    "Recording or animal group already belongs to a different split"
                )
            if sources and (
                source["schema"] != sources[0]["schema"]
                or source["frame_model"]["checkpoint_sha256"]
                != sources[0]["frame_model"]["checkpoint_sha256"]
            ):
                raise ValidationError(
                    "A temporal dataset requires one anatomy and frame checkpoint"
                )
            sources.append(source)
        _group_sources(sources)
        prototype = sources[0]
        model = source_model(self.session, project_id, prototype["frame_model"]["id"])
        lineage = frame_training_lineage(self.session, model)
        lineage["state"] = _lineage_state(
            lineage, [item for item in sources if item["split"] == "test"]
        )
        manifest = {
            "format": TEMPORAL_DATASET_FORMAT,
            "schema": prototype["schema"],
            "frame_model": prototype["frame_model"],
            "frame_lineage": lineage,
            "sources": sources,
        }
        digest = canonical_json_sha256(manifest)
        existing = self.session.scalar(
            select(TemporalReefPoseDataset)
            .where(
                TemporalReefPoseDataset.project_id == project_id,
                TemporalReefPoseDataset.name == payload.name,
                TemporalReefPoseDataset.manifest_sha256 == digest,
            )
            .limit(1)
        )
        if existing is not None:
            self.session.commit()
            return existing
        dataset = TemporalReefPoseDataset(
            project_id=project_id,
            name=payload.name,
            manifest_json=manifest,
            manifest_sha256=digest,
        )
        self.session.add(dataset)
        self.session.commit()
        return dataset

    @staticmethod
    def dataset_summary(dataset: TemporalReefPoseDataset) -> TemporalDatasetRead:
        manifest = dataset.manifest_json
        return TemporalDatasetRead(
            id=dataset.id,
            name=dataset.name,
            created_at=dataset.created_at,
            manifest_sha256=dataset.manifest_sha256,
            schema_hash=manifest["schema"]["content_hash"],
            frame_model_sha256=manifest["frame_model"]["checkpoint_sha256"],
            source_count=len(manifest["sources"]),
            split_counts=dict(Counter(source["split"] for source in manifest["sources"])),
            frame_lineage_state=manifest["frame_lineage"]["state"],
            landmarks=[
                TemporalLandmarkChoice(id=item["id"], name=item["name"])
                for item in manifest["schema"]["landmarks"]
            ],
        )

    def dataset_detail(self, project_id: str, dataset_id: str) -> TemporalDatasetDetail:
        dataset = self.dataset(project_id, dataset_id)
        return TemporalDatasetDetail(
            **self.dataset_summary(dataset).model_dump(), manifest=dataset.manifest_json
        )

    def datasets(self, project_id: str, limit: int, offset: int) -> list[TemporalDatasetRead]:
        self._project(project_id)
        return [
            self.dataset_summary(row)
            for row in self.session.scalars(
                select(TemporalReefPoseDataset)
                .where(TemporalReefPoseDataset.project_id == project_id)
                .order_by(TemporalReefPoseDataset.created_at.desc(), TemporalReefPoseDataset.id)
                .limit(limit)
                .offset(offset)
            )
        ]

    def submit(
        self,
        project_id: str,
        payload: TemporalRunCreate,
        *,
        workflow_run_id: str | None = None,
        workflow_node_run_id: str | None = None,
    ) -> TemporalReefPoseRun:
        self._project(project_id)
        dataset = None
        manifest: dict[str, Any] = {"format": "reefpose-temporal-run-0001"}
        if isinstance(payload, (TemporalTrainingCreate, TemporalEvaluationCreate)):
            dataset = self.dataset(project_id, str(payload.dataset_id))
            manifest["dataset_id"] = dataset.id
            manifest["dataset_sha256"] = dataset.manifest_sha256
        if isinstance(payload, TemporalTrainingCreate) and dataset is not None:
            if not any(item["split"] == "train" for item in dataset.manifest_json["sources"]):
                raise ValidationError("The temporal dataset needs a training partition")
            total = payload.epochs
        elif isinstance(payload, TemporalInferenceCreate):
            source = freeze_source(self.session, project_id, payload.source)
            model = source_model(self.session, project_id, str(payload.temporal_model_id))
            _compatible(source, model)
            manifest["source"] = source
            manifest["temporal_model_sha256"] = model.sha256
            total = len(source["frames"])
        elif isinstance(payload, TemporalEvaluationCreate) and dataset is not None:
            model = source_model(self.session, project_id, str(payload.temporal_model_id))
            metadata = _compatible(dataset.manifest_json, model)
            test = [item for item in dataset.manifest_json["sources"] if item["split"] == "test"]
            if not test:
                raise ValidationError("The temporal dataset needs a test partition for evaluation")
            if payload.anatomical_events is not None and not {
                payload.anatomical_events.landmark_a_id,
                payload.anatomical_events.landmark_b_id,
            } <= {item["id"] for item in dataset.manifest_json["schema"]["landmarks"]}:
                raise ValidationError("Anatomical event landmarks do not match the frozen schema")
            if any(
                source["recording"]["sha256"] in metadata["training_recording_hashes"]
                or not set(source["groups"]).isdisjoint(metadata["training_group_keys"])
                for source in test
            ):
                raise ValidationError(
                    "Test recordings overlap temporal training or model selection"
                )
            manifest["temporal_model_sha256"] = model.sha256
            total = sum(len(item["frames"]) for item in test)
        else:
            raise ValidationError("Temporal run configuration is incompatible")
        configuration = payload.model_dump(mode="json")
        manifest["configuration"] = configuration
        row = TemporalReefPoseRun(
            project_id=project_id,
            kind=payload.kind,
            dataset_id=dataset.id if dataset is not None else None,
            configuration_json=configuration,
            input_manifest_json=manifest,
            input_manifest_sha256=canonical_json_sha256(manifest),
        )
        self.session.add(row)
        self.session.flush()
        job = Job(
            project_id=project_id,
            job_type=TEMPORAL_JOB,
            progress_total=total,
            request_json={
                "temporal_run_id": row.id,
                "input_manifest_sha256": row.input_manifest_sha256,
                **({"workflow_run_id": workflow_run_id} if workflow_run_id else {}),
                **({"workflow_node_run_id": workflow_node_run_id} if workflow_node_run_id else {}),
            },
            result_json={"stage": "queued"},
        )
        self.session.add(job)
        self.session.flush()
        row.job_id = job.id
        self.session.commit()
        return row

    def source_stale(self, row: TemporalReefPoseRun) -> bool:
        source = row.input_manifest_json.get("source")
        if not source:
            return False
        recording = source["recording"]
        video = self.session.get(VideoAsset, recording["id"])
        if (
            video is None
            or recording["sha256"] != video.sha256
            or recording["calibration"] != (video.metadata_json or {}).get("spatial_calibration")
        ):
            return True
        for item in (source["frame_track"], source.get("reviewed_track")):
            if item is None:
                continue
            track = self.session.get(VideoTrack, item["id"])
            if (
                track is None
                or track.deleted_at is not None
                or track.revision != item["revision"]
                or canonical_json_sha256(track.keyframes_json) != item["keyframes_sha256"]
            ):
                return True
        identity = source.get("identity")
        if identity:
            run = self.session.get(PoseIdentityAssociationRun, identity["run_id"])
            if run is None or run.revision != identity["run_revision"]:
                return True
        return False

    def run_summary(self, row: TemporalReefPoseRun) -> TemporalRunRead:
        job = self.session.get(Job, row.job_id) if row.job_id else None
        return TemporalRunRead(
            id=row.id,
            kind=cast(TemporalKind, row.kind),
            job_id=row.job_id,
            status=job.status
            if job is not None
            else "succeeded"
            if row.result_json
            else "unavailable",
            result=row.result_json or (job.result_json if job is not None else None),
            error=job.error_message if job is not None else None,
            progress_current=job.progress_current if job is not None else 0,
            progress_total=job.progress_total if job is not None else 0,
            created_at=row.created_at,
            configuration=row.configuration_json,
            review_revision=row.review_revision,
            identity_run_id=row.identity_run_id,
            identity_id=row.identity_id,
            source_stale=self.source_stale(row),
        )

    def runs(self, project_id: str, limit: int, offset: int) -> list[TemporalRunRead]:
        self._project(project_id)
        return [
            self.run_summary(row)
            for row in self.session.scalars(
                select(TemporalReefPoseRun)
                .where(TemporalReefPoseRun.project_id == project_id)
                .order_by(TemporalReefPoseRun.created_at.desc(), TemporalReefPoseRun.id)
                .limit(limit)
                .offset(offset)
            )
        ]

    def frames(self, project_id: str, run_id: str, limit: int, offset: int) -> TemporalFramePage:
        run = self.run(project_id, run_id)
        if run.kind != "inference" or run.result_json is None:
            raise ValidationError(
                "A completed refinement run is required to inspect frame evidence"
            )
        statement = select(TemporalReefPoseFrame).where(TemporalReefPoseFrame.run_id == run.id)
        total = self.session.scalar(select(func.count()).select_from(statement.subquery())) or 0
        items = []
        for row in self.session.scalars(
            statement.order_by(TemporalReefPoseFrame.frame_index).limit(limit).offset(offset)
        ):
            _check_checksum(row.evidence_json, row.evidence_sha256, "Frame prediction")
            items.append(
                TemporalFrameRead.model_validate(
                    {**row.evidence_json, "review_source": row.review_source}
                )
            )
        return TemporalFramePage(items=items, offset=offset, limit=limit, total=total)

    def inputs(self, project_id: str, limit: int, offset: int) -> TemporalInputsRead:
        self._project(project_id)
        frame_tracks: list[TemporalTrackChoice] = []
        reviewed_tracks: list[TemporalTrackChoice] = []
        temporal_models: list[TemporalModelChoice] = []
        frame_models: list[TemporalFrameModelChoice] = []
        track_rows = list(
            self.session.execute(
                select(VideoTrack, VideoAsset)
                .join(VideoAsset, VideoTrack.video_id == VideoAsset.id)
                .where(
                    VideoAsset.project_id == project_id,
                    VideoTrack.deleted_at.is_(None),
                    VideoTrack.metadata_json["pose_landmark_schema"]["content_hash"]
                    .as_string()
                    .is_not(None),
                )
                .order_by(VideoAsset.original_filename, VideoTrack.track_number, VideoTrack.id)
                .limit(limit + 1)
                .offset(offset)
            )
        )
        for track, video in track_rows[:limit]:
            binding = track_binding(track)
            option = TemporalTrackChoice(
                id=track.id,
                video_id=video.id,
                video_name=video.original_filename,
                track_number=track.track_number,
                revision=track.revision,
                model_id=track.source_model_id,
                schema_hash=binding["content_hash"],
            )
            if track.status in {"verified", "reviewed"}:
                reviewed_tracks.append(option)
            if track.source_model_id and track.source_job_id:
                job = self.session.get(Job, track.source_job_id)
                model = self.session.get(ModelRegistration, track.source_model_id)
                if (
                    model is not None
                    and model.provider_name == "reefpose"
                    and model.task == "pose"
                    and job is not None
                    and job.status == "succeeded"
                    and (job.result_json or {}).get("pose_inference_protocol")
                    and track.id in (job.result_json or {}).get("pose_track_hashes", {})
                ):
                    frame_tracks.append(option)
        model_rows = list(
            self.session.scalars(
                select(ModelRegistration)
                .where(
                    ModelRegistration.project_id == project_id,
                    ModelRegistration.provider_name.in_(("reefpose", TEMPORAL_PROVIDER)),
                )
                .order_by(ModelRegistration.display_name, ModelRegistration.id)
                .limit(limit + 1)
                .offset(offset)
            )
        )
        for model in model_rows[:limit]:
            metadata = model.metadata_json or {}
            if model.provider_name == TEMPORAL_PROVIDER and model.task == "pose_temporal":
                temporal_models.append(
                    TemporalModelChoice(
                        id=model.id,
                        name=model.display_name,
                        sha256=model.sha256,
                        schema_hash=metadata["schema_hash"],
                        frame_model_sha256=metadata["frame_model_sha256"],
                        window_length=metadata["window_length"],
                        context_mode=metadata["context_mode"],
                    )
                )
            if model.provider_name == "reefpose" and model.task == "pose":
                schema_hash = (metadata.get("pose_landmark_schema") or {}).get("content_hash")
                if schema_hash:
                    frame_models.append(
                        TemporalFrameModelChoice(
                            id=model.id,
                            name=model.display_name,
                            sha256=model.sha256,
                            schema_hash=schema_hash,
                        )
                    )
        identity_rows = list(
            self.session.execute(
                select(PoseAnimalIdentity, PoseIdentityAssociationRun)
                .join(PoseIdentityAssociationRun)
                .where(
                    PoseIdentityAssociationRun.project_id == project_id,
                    PoseIdentityAssociationRun.status == "completed",
                    PoseIdentityAssociationRun.algorithm != TEMPORAL_METHOD,
                    PoseAnimalIdentity.verification_state.in_(REVIEWED),
                )
                .order_by(PoseAnimalIdentity.created_at, PoseAnimalIdentity.id)
                .limit(limit + 1)
                .offset(offset)
            )
        )
        identities = [
            TemporalIdentityChoice(
                id=identity.id,
                run_id=run.id,
                video_id=run.video_id,
                name=identity.display_name or identity.stable_identity_key,
                revision=identity.revision,
            )
            for identity, run in identity_rows[:limit]
        ]
        return TemporalInputsRead(
            frame_tracks=frame_tracks,
            reviewed_tracks=reviewed_tracks,
            frame_models=frame_models,
            temporal_models=temporal_models,
            identities=identities,
            offset=offset,
            limit=limit,
            has_more=max(len(track_rows), len(model_rows), len(identity_rows)) > limit,
        )
