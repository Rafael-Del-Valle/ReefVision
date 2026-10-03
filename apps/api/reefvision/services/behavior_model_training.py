"""Training for transparent behavior feature models."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from statistics import fmean, pstdev
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.db.models import (
    BehaviorClassifierModel,
    BehaviorEthogramRevision,
    VideoAsset,
    VideoTrack,
)
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.schemas.behavior_classifier import (
    BehaviorModelResponse,
    BehaviorModelTrainRequest,
)
from reefvision.schemas.behavior_features import BehaviorFeatureRequest
from reefvision.services.behavior_dynamics import BehaviorDynamicsService
from reefvision.services.behavior_features import BehaviorFeatureService
from reefvision.services.behavior_model_common import (
    ALGORITHM,
    ALGORITHM_VERSION,
    FEATURE_PRESETS,
    feature_request,
    feature_vector,
)


class BehaviorModelTrainingService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.dynamics = BehaviorDynamicsService(session)
        self.features = BehaviorFeatureService(session)

    def _ethogram(self, ethogram_revision_id: str) -> BehaviorEthogramRevision:
        record = self.session.get(BehaviorEthogramRevision, ethogram_revision_id)
        if record is None:
            raise NotFoundError("Behavior ethogram revision not found")
        return record

    def _project_tracks(
        self,
        project_id: str,
        requested_track_ids: list[str],
    ) -> list[VideoTrack]:
        statement = (
            select(VideoTrack)
            .join(VideoAsset, VideoAsset.id == VideoTrack.video_id)
            .where(
                VideoAsset.project_id == project_id,
                VideoTrack.deleted_at.is_(None),
            )
            .order_by(VideoTrack.video_id, VideoTrack.track_number, VideoTrack.id)
        )
        if requested_track_ids:
            statement = statement.where(VideoTrack.id.in_(requested_track_ids))
        tracks = list(self.session.scalars(statement))
        if requested_track_ids and {item.id for item in tracks} != set(requested_track_ids):
            raise ValidationError("All behavior-model training tracks must belong to the project")
        return tracks

    def train(
        self,
        project_id: str,
        payload: BehaviorModelTrainRequest,
    ) -> BehaviorModelResponse:
        ethogram = self._ethogram(payload.ethogram_revision_id)
        if ethogram.project_id != project_id:
            raise ValidationError("Behavior ethogram belongs to a different project")
        display_name = payload.display_name.strip()
        duplicate_name = self.session.scalar(
            select(BehaviorClassifierModel.id).where(
                BehaviorClassifierModel.project_id == project_id,
                BehaviorClassifierModel.display_name == display_name,
            )
        )
        if duplicate_name is not None:
            raise ValidationError(
                "A behavior model with this display name already exists in the project"
            )

        feature_names = FEATURE_PRESETS[payload.feature_preset]
        request_options = feature_request()
        tracks = self._project_tracks(project_id, payload.track_ids)
        if not tracks:
            raise ValidationError("Behavior-model training requires at least one video track")

        samples: list[dict[str, Any]] = []
        class_counts: Counter[str] = Counter()
        for track in tracks:
            for bout, state in self.dynamics._effective_bouts(
                track.id,
                ethogram.id,
            ):
                if state.channel != payload.channel:
                    continue
                if bout.review_status != "verified" or bout.source != "manual":
                    continue
                if bout.source_track_revision != track.revision:
                    continue
                response = self.features.extract(
                    track.id,
                    BehaviorFeatureRequest(
                        start_frame=bout.start_frame,
                        end_frame=bout.end_frame,
                        include_predicted=False,
                        include_uncertain=True,
                        minimum_landmark_confidence=None,
                    ),
                )
                vector = feature_vector(
                    response,
                    feature_names,
                    context=f"verified bout {bout.id}",
                )
                samples.append(
                    {
                        "bout_id": bout.id,
                        "track_id": track.id,
                        "track_revision": track.revision,
                        "state_id": state.id,
                        "parameters_sha256": response.parameters_sha256,
                        "values": vector,
                    }
                )
                class_counts[state.id] += 1

        if len(class_counts) < 2:
            raise ValidationError(
                "Behavior-model training requires verified manual bouts from at "
                "least two behavior states in the selected channel"
            )
        if any(count < 2 for count in class_counts.values()):
            raise ValidationError(
                "Behavior-model training requires at least two verified manual "
                "bouts per represented behavior state"
            )

        columns = list(zip(*(item["values"] for item in samples), strict=True))
        means = [fmean(column) for column in columns]
        raw_stds = [pstdev(column) if len(column) > 1 else 0.0 for column in columns]
        safe_stds = [value if value > 1e-12 else 1.0 for value in raw_stds]
        scaler = {
            name: {
                "mean": means[index],
                "std": safe_stds[index],
                "constant_feature": raw_stds[index] <= 1e-12,
            }
            for index, name in enumerate(feature_names)
        }

        standardized: dict[str, list[list[float]]] = defaultdict(list)
        for item in samples:
            vector = [
                (float(value) - means[index]) / safe_stds[index]
                for index, value in enumerate(item["values"])
            ]
            standardized[str(item["state_id"])].append(vector)

        centroids = {
            state_id: [
                fmean(vector[index] for vector in vectors) for index in range(len(feature_names))
            ]
            for state_id, vectors in standardized.items()
        }
        manifest = {
            "algorithm": ALGORITHM,
            "algorithm_version": ALGORITHM_VERSION,
            "ethogram_revision_id": ethogram.id,
            "ethogram_definition_sha256": ethogram.definition_sha256,
            "channel": payload.channel,
            "feature_set_version": "reefvision-behavior-features-0001",
            "feature_preset": payload.feature_preset,
            "feature_names": list(feature_names),
            "feature_request": request_options,
            "samples": samples,
        }
        manifest_sha256 = hashlib.sha256(
            json.dumps(
                manifest,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

        model = BehaviorClassifierModel(
            project_id=project_id,
            ethogram_revision_id=ethogram.id,
            channel=payload.channel.strip(),
            display_name=display_name,
            algorithm=ALGORITHM,
            algorithm_version=ALGORITHM_VERSION,
            feature_set_version="reefvision-behavior-features-0001",
            feature_preset=payload.feature_preset,
            feature_names_json=list(feature_names),
            feature_request_json=request_options,
            scaler_json=scaler,
            centroids_json=centroids,
            class_counts_json=dict(class_counts),
            training_track_ids_json=sorted({str(item["track_id"]) for item in samples}),
            training_bout_ids_json=[str(item["bout_id"]) for item in samples],
            training_sample_count=len(samples),
            training_manifest_sha256=manifest_sha256,
            created_by="local_user",
        )
        self.session.add(model)
        self.session.commit()
        self.session.refresh(model)
        return behavior_model_response(model)

    def list_models(
        self,
        project_id: str,
        ethogram_revision_id: str | None = None,
    ) -> list[BehaviorModelResponse]:
        statement = select(BehaviorClassifierModel).where(
            BehaviorClassifierModel.project_id == project_id
        )
        if ethogram_revision_id is not None:
            statement = statement.where(
                BehaviorClassifierModel.ethogram_revision_id == ethogram_revision_id
            )
        statement = statement.order_by(
            BehaviorClassifierModel.created_at.desc(),
            BehaviorClassifierModel.id,
        )
        return [behavior_model_response(record) for record in self.session.scalars(statement)]


def behavior_model_response(
    record: BehaviorClassifierModel,
) -> BehaviorModelResponse:
    return BehaviorModelResponse(
        id=record.id,
        project_id=record.project_id,
        ethogram_revision_id=record.ethogram_revision_id,
        channel=record.channel,
        display_name=record.display_name,
        algorithm=record.algorithm,
        algorithm_version=record.algorithm_version,
        feature_set_version=record.feature_set_version,
        feature_preset=record.feature_preset,
        feature_names=list(record.feature_names_json),
        feature_request=dict(record.feature_request_json),
        scaler=dict(record.scaler_json),
        centroids=dict(record.centroids_json),
        class_counts=dict(record.class_counts_json),
        training_track_ids=list(record.training_track_ids_json),
        training_bout_ids=list(record.training_bout_ids_json),
        training_sample_count=record.training_sample_count,
        training_manifest_sha256=record.training_manifest_sha256,
        created_by=record.created_by,
        created_at=record.created_at,
    )
