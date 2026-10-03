"""Reproducible behavior-dynamics and prediction exports."""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from reefvision.db.models import BehaviorClassifierModel
from reefvision.domain.errors import ValidationError
from reefvision.schemas.behavior_classifier import BehaviorExportFormat
from reefvision.schemas.behavior_dynamics import BehaviorDynamicsRequest
from reefvision.services.behavior_dynamics import BehaviorDynamicsService
from reefvision.services.behavior_model_training import behavior_model_response
from reefvision.services.behavior_predictions import BehaviorPredictionService


@dataclass(frozen=True)
class BehaviorExportPayload:
    filename: str
    media_type: str
    content: str


class BehaviorExportService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.dynamics = BehaviorDynamicsService(session)
        self.predictions = BehaviorPredictionService(session)

    def export(
        self,
        track_id: str,
        ethogram_revision_id: str,
        export_format: BehaviorExportFormat,
        *,
        model_id: str | None = None,
    ) -> BehaviorExportPayload:
        bouts = self.dynamics.list_bouts(track_id, ethogram_revision_id)
        predictions = self.predictions.list_predictions(
            track_id,
            model_id=model_id,
        )
        dynamics = self.dynamics.analyze(
            track_id,
            BehaviorDynamicsRequest(
                ethogram_revision_id=ethogram_revision_id,
                include_unreviewed=False,
            ),
        )

        track = self.dynamics._track(track_id)
        provenance: dict[str, Any] = {
            "export_schema_version": "reefvision-behavior-export-0001",
            "track_id": track_id,
            "source_track_revision": track.revision,
            "ethogram_revision_id": ethogram_revision_id,
            "ethogram_definition_sha256": dynamics.ethogram_definition_sha256,
            "annotation_policy": dynamics.annotation_policy,
            "transition_policy": dynamics.transition_policy,
            "interval_policy": dynamics.interval_policy,
        }
        if model_id is not None:
            model = self.session.get(BehaviorClassifierModel, model_id)
            if model is None:
                raise ValidationError("Behavior model not found for export")
            provenance["model"] = behavior_model_response(model).model_dump(
                mode="json"
            )

        if export_format == "json":
            document = {
                "provenance": provenance,
                "dynamics": dynamics.model_dump(mode="json"),
                "bouts": [item.model_dump(mode="json") for item in bouts],
                "predictions": [
                    item.model_dump(mode="json")
                    for item in predictions
                ],
            }
            return BehaviorExportPayload(
                filename=f"reefvision-behavior-{track_id}.json",
                media_type="application/json",
                content=json.dumps(document, indent=2, sort_keys=True),
            )

        buffer = io.StringIO()
        writer: csv.DictWriter[str]
        if export_format == "bouts_csv":
            fields = [
                "video_track_id",
                "source_track_revision",
                "ethogram_revision_id",
                "behavior_state_id",
                "behavior_code",
                "behavior_label",
                "channel",
                "start_frame",
                "end_frame",
                "start_time_seconds",
                "end_time_seconds",
                "duration_seconds",
                "source",
                "confidence",
                "review_status",
                "stale_against_track",
                "revision_reason",
                "source_behavior_classifier_id",
                "source_behavior_prediction_id",
            ]
            writer = csv.DictWriter(buffer, fieldnames=fields)
            writer.writeheader()
            for item in bouts:
                writer.writerow(
                    {
                        field: getattr(item, field)
                        for field in fields
                    }
                )
            return BehaviorExportPayload(
                filename=f"reefvision-behavior-bouts-{track_id}.csv",
                media_type="text/csv",
                content=buffer.getvalue(),
            )

        if export_format == "predictions_csv":
            fields = [
                "id",
                "video_track_id",
                "model_id",
                "ethogram_revision_id",
                "behavior_state_id",
                "behavior_code",
                "behavior_label",
                "channel",
                "start_frame",
                "end_frame",
                "prediction_score",
                "score_semantics",
                "scores_json",
                "feature_vector_json",
                "feature_parameters_sha256",
                "source_track_revision",
                "stale_against_track",
                "review_status",
                "accepted_bout_series_id",
                "reviewed_at",
                "reviewed_by",
            ]
            writer = csv.DictWriter(buffer, fieldnames=fields)
            writer.writeheader()
            for item in predictions:
                row = item.model_dump(mode="json")
                row["scores_json"] = json.dumps(
                    item.scores,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                row["feature_vector_json"] = json.dumps(
                    item.feature_vector,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                writer.writerow({field: row.get(field) for field in fields})
            return BehaviorExportPayload(
                filename=f"reefvision-behavior-predictions-{track_id}.csv",
                media_type="text/csv",
                content=buffer.getvalue(),
            )

        raise ValidationError("Unsupported behavior export format")
