"""Reviewable behavior-model inference and scientist acceptance."""

from __future__ import annotations

from math import isfinite
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.db.models import (
    BehaviorBoutRevision,
    BehaviorClassifierModel,
    BehaviorPrediction,
    BehaviorStateDefinition,
    VideoAsset,
    VideoTrack,
)
from reefvision.db.models.project import utc_now
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.schemas.behavior_classifier import (
    BehaviorPredictionResponse,
    BehaviorPredictionReviewRequest,
    BehaviorPredictionRunRequest,
    BehaviorPredictionRunResponse,
)
from reefvision.schemas.behavior_features import BehaviorFeatureRequest
from reefvision.services.behavior_dynamics import BehaviorDynamicsService
from reefvision.services.behavior_features import BehaviorFeatureService
from reefvision.services.behavior_model_common import (
    centroid_distances,
    feature_vector,
    standardize,
)


class BehaviorPredictionService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.features = BehaviorFeatureService(session)
        self.dynamics = BehaviorDynamicsService(session)

    def _track(self, track_id: str) -> VideoTrack:
        track = self.session.get(VideoTrack, track_id)
        if track is None or track.deleted_at is not None:
            raise NotFoundError("Video track not found")
        return track

    def _video(self, video_id: str) -> VideoAsset:
        video = self.session.get(VideoAsset, video_id)
        if video is None:
            raise NotFoundError("Video not found")
        return video

    def _model(self, model_id: str) -> BehaviorClassifierModel:
        model = self.session.get(BehaviorClassifierModel, model_id)
        if model is None:
            raise NotFoundError("Behavior model not found")
        return model

    def _state(self, state_id: str) -> BehaviorStateDefinition:
        state = self.session.get(BehaviorStateDefinition, state_id)
        if state is None:
            raise NotFoundError("Behavior state not found")
        return state

    @staticmethod
    def _feature_request(
        model: BehaviorClassifierModel,
        start_frame: int,
        end_frame: int,
    ) -> BehaviorFeatureRequest:
        options = dict(model.feature_request_json or {})
        minimum = options.get("minimum_landmark_confidence")
        return BehaviorFeatureRequest(
            start_frame=start_frame,
            end_frame=end_frame,
            include_predicted=bool(options.get("include_predicted", False)),
            include_uncertain=bool(options.get("include_uncertain", True)),
            minimum_landmark_confidence=(
                float(minimum) if isinstance(minimum, (int, float)) else None
            ),
        )

    def _response(
        self,
        prediction: BehaviorPrediction,
        track: VideoTrack | None = None,
    ) -> BehaviorPredictionResponse:
        track = track or self._track(prediction.video_track_id)
        state = self._state(prediction.behavior_state_id)
        return BehaviorPredictionResponse(
            id=prediction.id,
            video_track_id=prediction.video_track_id,
            model_id=prediction.classifier_id,
            ethogram_revision_id=prediction.ethogram_revision_id,
            behavior_state_id=state.id,
            behavior_code=state.code,
            behavior_label=state.label,
            channel=prediction.channel,
            start_frame=prediction.start_frame,
            end_frame=prediction.end_frame,
            prediction_score=prediction.prediction_score,
            scores=dict(prediction.scores_json),
            feature_vector=dict(prediction.feature_vector_json),
            feature_parameters_sha256=prediction.feature_parameters_sha256,
            source_track_revision=prediction.source_track_revision,
            stale_against_track=prediction.source_track_revision != track.revision,
            review_status=prediction.review_status,
            accepted_bout_series_id=prediction.accepted_bout_series_id,
            reviewed_at=prediction.reviewed_at,
            reviewed_by=prediction.reviewed_by,
            created_at=prediction.created_at,
        )

    def list_predictions(
        self,
        track_id: str,
        *,
        model_id: str | None = None,
        review_status: str | None = None,
    ) -> list[BehaviorPredictionResponse]:
        track = self._track(track_id)
        statement = select(BehaviorPrediction).where(
            BehaviorPrediction.video_track_id == track.id
        )
        if model_id is not None:
            statement = statement.where(BehaviorPrediction.classifier_id == model_id)
        if review_status is not None:
            statement = statement.where(
                BehaviorPrediction.review_status == review_status
            )
        statement = statement.order_by(
            BehaviorPrediction.start_frame,
            BehaviorPrediction.end_frame,
            BehaviorPrediction.created_at,
            BehaviorPrediction.id,
        )
        return [
            self._response(record, track)
            for record in self.session.scalars(statement)
        ]

    def run(
        self,
        track_id: str,
        payload: BehaviorPredictionRunRequest,
    ) -> BehaviorPredictionRunResponse:
        track = self._track(track_id)
        video = self._video(track.video_id)
        model = self._model(payload.model_id)
        if model.project_id != video.project_id:
            raise ValidationError("Behavior model belongs to a different project")

        first_frame, last_frame = self.dynamics._track_frame_bounds(track)
        start_frame = payload.start_frame if payload.start_frame is not None else first_frame
        end_frame = payload.end_frame if payload.end_frame is not None else last_frame
        if start_frame < first_frame or end_frame > last_frame:
            raise ValidationError(
                "Behavior prediction range must stay within the selected track"
            )

        feature_names = list(model.feature_names_json)
        scaler = dict(model.scaler_json)
        centroids = dict(model.centroids_json)
        states = {
            item.id: item
            for item in self.session.scalars(
                select(BehaviorStateDefinition).where(
                    BehaviorStateDefinition.ethogram_revision_id
                    == model.ethogram_revision_id,
                    BehaviorStateDefinition.channel == model.channel,
                )
            )
        }
        if set(centroids) - set(states):
            raise ValidationError(
                "Behavior model centroids reference missing ethogram states"
            )

        existing = {
            (item.start_frame, item.end_frame): item
            for item in self.session.scalars(
                select(BehaviorPrediction).where(
                    BehaviorPrediction.video_track_id == track.id,
                    BehaviorPrediction.classifier_id == model.id,
                    BehaviorPrediction.source_track_revision == track.revision,
                )
            )
        }

        created: list[BehaviorPrediction] = []
        window_start = start_frame
        while window_start <= end_frame:
            window_end = min(end_frame, window_start + payload.window_frames - 1)
            prior = existing.get((window_start, window_end))
            if prior is not None:
                created.append(prior)
                window_start += payload.stride_frames
                continue

            feature_response = self.features.extract(
                track.id,
                self._feature_request(model, window_start, window_end),
            )
            raw_vector = feature_vector(
                feature_response,
                feature_names,
                context=f"prediction window {window_start}-{window_end}",
            )
            standardized_vector = standardize(raw_vector, feature_names, scaler)
            distances = centroid_distances(standardized_vector, centroids)
            inverse = {
                state_id: 1.0 / (distance + 1e-9)
                for state_id, distance in distances.items()
            }
            denominator = sum(inverse.values())
            if not isfinite(denominator) or denominator <= 0:
                raise ValidationError("Behavior-model distance scores are invalid")
            normalized_scores = {
                state_id: value / denominator
                for state_id, value in inverse.items()
            }
            predicted_state_id = min(
                distances,
                key=lambda state_id: (distances[state_id], state_id),
            )
            prediction = BehaviorPrediction(
                video_track_id=track.id,
                classifier_id=model.id,
                ethogram_revision_id=model.ethogram_revision_id,
                behavior_state_id=predicted_state_id,
                channel=model.channel,
                start_frame=window_start,
                end_frame=window_end,
                prediction_score=normalized_scores[predicted_state_id],
                scores_json={
                    "score_semantics": "normalized_inverse_distance_not_calibrated",
                    "normalized_inverse_distance": normalized_scores,
                    "standardized_centroid_distance": distances,
                },
                feature_vector_json={
                    name: raw_vector[index]
                    for index, name in enumerate(feature_names)
                },
                feature_parameters_sha256=feature_response.parameters_sha256,
                source_track_revision=track.revision,
                review_status="pending",
            )
            self.session.add(prediction)
            created.append(prediction)
            window_start += payload.stride_frames

        self.session.commit()
        for item in created:
            self.session.refresh(item)
        return BehaviorPredictionRunResponse(
            track_id=track.id,
            model_id=model.id,
            source_track_revision=track.revision,
            prediction_count=len(created),
            predictions=[self._response(item, track) for item in created],
        )

    def review(
        self,
        prediction_id: str,
        payload: BehaviorPredictionReviewRequest,
    ) -> BehaviorPredictionResponse:
        prediction = self.session.get(BehaviorPrediction, prediction_id)
        if prediction is None:
            raise NotFoundError("Behavior prediction not found")
        track = self._track(prediction.video_track_id)
        if prediction.review_status != "pending":
            return self._response(prediction, track)

        if payload.action == "reject":
            prediction.review_status = "rejected"
            prediction.reviewed_at = utc_now()
            prediction.reviewed_by = "local_user"
            self.session.commit()
            self.session.refresh(prediction)
            return self._response(prediction, track)

        if prediction.source_track_revision != track.revision:
            raise ValidationError(
                "Behavior prediction is stale against the current video-track revision; "
                "rerun inference before acceptance"
            )

        target_state_id = payload.behavior_state_id or prediction.behavior_state_id
        state = self._state(target_state_id)
        if state.ethogram_revision_id != prediction.ethogram_revision_id:
            raise ValidationError(
                "Accepted behavior state must belong to the prediction ethogram revision"
            )
        if state.channel != prediction.channel:
            raise ValidationError(
                "Accepted behavior state must remain in the prediction channel"
            )

        start_frame = (
            payload.start_frame
            if payload.start_frame is not None
            else prediction.start_frame
        )
        end_frame = (
            payload.end_frame
            if payload.end_frame is not None
            else prediction.end_frame
        )
        first_frame, last_frame = self.dynamics._track_frame_bounds(track)
        if (
            start_frame < first_frame
            or end_frame > last_frame
            or end_frame < start_frame
        ):
            raise ValidationError(
                "Accepted prediction interval must stay within the current track"
            )

        for bout, bout_state in self.dynamics._effective_bouts(
            track.id,
            prediction.ethogram_revision_id,
        ):
            if bout_state.channel != prediction.channel:
                continue
            if not (end_frame < bout.start_frame or start_frame > bout.end_frame):
                raise ValidationError(
                    "Accepted behavior prediction overlaps an existing canonical "
                    "bout in the same behavior channel"
                )

        bout_series_id = str(uuid4())
        bout = BehaviorBoutRevision(
            bout_series_id=bout_series_id,
            revision=1,
            supersedes_bout_id=None,
            video_track_id=track.id,
            ethogram_revision_id=prediction.ethogram_revision_id,
            behavior_state_id=state.id,
            start_frame=start_frame,
            end_frame=end_frame,
            source="accepted_prediction",
            # The centroid score is not calibrated probability/confidence.
            # Preserve it on the linked prediction rather than relabeling it.
            confidence=None,
            review_status="verified",
            source_track_revision=track.revision,
            source_model_id=None,
            source_job_id=None,
            source_behavior_classifier_id=prediction.classifier_id,
            source_behavior_prediction_id=prediction.id,
            is_deleted=False,
            revision_reason=(
                "prediction_accept"
                if payload.action == "accept"
                else "prediction_edit_and_accept"
            ),
            note=payload.note,
            created_by="local_user",
        )
        self.session.add(bout)
        prediction.review_status = (
            "accepted"
            if payload.action == "accept"
            else "edited_and_accepted"
        )
        prediction.accepted_bout_series_id = bout_series_id
        prediction.reviewed_at = utc_now()
        prediction.reviewed_by = "local_user"
        self.session.commit()
        self.session.refresh(prediction)
        return self._response(prediction, track)
