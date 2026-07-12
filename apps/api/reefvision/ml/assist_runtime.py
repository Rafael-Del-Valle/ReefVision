"""In-memory prepared-image cache and Smart Mask session manager."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from reefvision.config import Settings
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.ml.provider_hub import assist_provider_for_name
from reefvision.ml.providers import (
    AnnotationAssistProvider,
    AssistPrediction,
    BrushStroke,
    PixelBox,
    mask_to_png_base64,
    resample_stroke_points,
    stroke_bounds,
)


@dataclass
class PreparedAssistEntry:
    cache_key: str
    model_id: str
    model_checksum: str
    provider_name: str
    provider_version: str
    provider: AnnotationAssistProvider
    prepared_image: Any
    created_at: datetime
    last_used_at: datetime


@dataclass
class AssistSessionState:
    session_id: str
    project_id: str
    image_id: str
    model_id: str
    model_display_name: str
    model_checksum: str
    provider_name: str
    provider_version: str
    prepared_cache_key: str
    created_at: datetime
    last_used_at: datetime
    expires_at: datetime
    brush_radius: float | None = None
    add_strokes: list[BrushStroke] = field(default_factory=list)
    subtract_strokes: list[BrushStroke] = field(default_factory=list)
    candidate_prediction: AssistPrediction | None = None
    candidate_mask_png_base64: str | None = None
    source_prediction_id: str | None = None
    prompt_type: str | None = None
    prompt_box: PixelBox | None = None


class AssistRuntime:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._prepared: dict[str, PreparedAssistEntry] = {}
        self._sessions: dict[str, AssistSessionState] = {}

    def _now(self) -> datetime:
        return datetime.now(UTC)

    def _provider_for_model(self, provider_name: str) -> AnnotationAssistProvider:
        return assist_provider_for_name(provider_name)

    def _cache_key(
        self,
        *,
        image_sha256: str,
        model_checksum: str,
        provider_version: str,
        device: str,
    ) -> str:
        return f"{image_sha256}:{model_checksum}:{provider_version}:{device.lower()}"

    def _expire_sessions(self) -> None:
        now = self._now()
        expired = [
            session_id
            for session_id, session in self._sessions.items()
            if session.expires_at <= now
        ]
        for session_id in expired:
            self._sessions.pop(session_id, None)
        self._trim_cache()

    def _trim_cache(self) -> None:
        referenced = {session.prepared_cache_key for session in self._sessions.values()}
        unreferenced = sorted(
            (entry for key, entry in self._prepared.items() if key not in referenced),
            key=lambda entry: (entry.last_used_at, entry.created_at, entry.cache_key),
        )
        while len(self._prepared) > self.settings.assist_cache_max_items and unreferenced:
            entry = unreferenced.pop(0)
            self._prepared.pop(entry.cache_key, None)
            entry.provider.unload_model()

    def _entry(self, cache_key: str) -> PreparedAssistEntry:
        entry = self._prepared.get(cache_key)
        if entry is None:
            raise ValidationError("The prepared assist image is no longer available")
        entry.last_used_at = self._now()
        return entry

    def _session(self, session_id: str) -> AssistSessionState:
        self._expire_sessions()
        session = self._sessions.get(session_id)
        if session is None:
            raise NotFoundError("Assist session not found")
        session.last_used_at = self._now()
        session.expires_at = session.last_used_at + timedelta(
            seconds=self.settings.assist_session_ttl_seconds
        )
        return session

    def create_session(
        self,
        *,
        project_id: str,
        image_id: str,
        image_sha256: str,
        image_path: Path,
        model_id: str,
        model_display_name: str,
        model_checksum: str,
        model_path: Path,
        provider_name: str,
        provider_version: str,
        device: str,
        source_prediction_id: str | None = None,
    ) -> AssistSessionState:
        self._expire_sessions()
        cache_key = self._cache_key(
            image_sha256=image_sha256,
            model_checksum=model_checksum,
            provider_version=provider_version,
            device=device,
        )
        entry = self._prepared.get(cache_key)
        now = self._now()
        if entry is None:
            provider = self._provider_for_model(provider_name)
            provider.load_model(model_path, device)
            entry = PreparedAssistEntry(
                cache_key=cache_key,
                model_id=model_id,
                model_checksum=model_checksum,
                provider_name=provider_name,
                provider_version=provider_version,
                provider=provider,
                prepared_image=provider.prepare_image(image_path),
                created_at=now,
                last_used_at=now,
            )
            self._prepared[cache_key] = entry
            self._trim_cache()
        session = AssistSessionState(
            session_id=str(uuid4()),
            project_id=project_id,
            image_id=image_id,
            model_id=model_id,
            model_display_name=model_display_name,
            model_checksum=model_checksum,
            provider_name=provider_name,
            provider_version=provider_version,
            prepared_cache_key=cache_key,
            created_at=now,
            last_used_at=now,
            expires_at=now + timedelta(seconds=self.settings.assist_session_ttl_seconds),
            source_prediction_id=source_prediction_id,
        )
        self._sessions[session.session_id] = session
        return session

    def _validate_points(
        self,
        *,
        strokes: list[BrushStroke],
        image_width: int,
        image_height: int,
    ) -> None:
        for stroke in strokes:
            if stroke.brush_radius <= 0:
                raise ValidationError("Brush radius must be positive")
            if not stroke.points:
                raise ValidationError("Brush strokes must contain at least one point")
            for point in stroke.points:
                if point.x != point.x or point.y != point.y:
                    raise ValidationError("Brush points must be finite")
                if point.x < 0 or point.y < 0 or point.x > image_width or point.y > image_height:
                    raise ValidationError("Brush points must remain inside the image bounds")

    def _update_candidate(self, session: AssistSessionState, prediction: AssistPrediction) -> None:
        session.candidate_prediction = prediction
        session.candidate_mask_png_base64 = mask_to_png_base64(prediction.mask)

    def apply_box_prompt(
        self,
        *,
        session_id: str,
        box: PixelBox,
    ) -> AssistSessionState:
        session = self._session(session_id)
        entry = self._entry(session.prepared_cache_key)
        prediction = entry.provider.predict_from_box(entry.prepared_image, box)
        session.prompt_type = "box_to_mask"
        session.prompt_box = box
        self._update_candidate(session, prediction)
        return session

    def apply_brush_prompts(
        self,
        *,
        session_id: str,
        strokes: list[BrushStroke],
        mode: str,
        image_width: int,
        image_height: int,
    ) -> AssistSessionState:
        session = self._session(session_id)
        self._validate_points(strokes=strokes, image_width=image_width, image_height=image_height)
        if mode == "add":
            session.add_strokes.extend(strokes)
        else:
            session.subtract_strokes.extend(strokes)
        session.brush_radius = strokes[-1].brush_radius
        positive_points = [
            point
            for stroke in session.add_strokes
            for point in resample_stroke_points(
                stroke.points,
                max(self.settings.smart_mask_sample_spacing, stroke.brush_radius),
            )
        ]
        negative_points = [
            point
            for stroke in session.subtract_strokes
            for point in resample_stroke_points(
                stroke.points,
                max(self.settings.smart_mask_sample_spacing, stroke.brush_radius),
            )
        ]
        if not positive_points:
            raise ValidationError("Smart Mask needs at least one Add stroke before refinement")
        context_box = stroke_bounds(session.add_strokes)
        entry = self._entry(session.prepared_cache_key)
        prediction = entry.provider.predict_from_points(
            entry.prepared_image,
            positive_points=positive_points,
            negative_points=negative_points,
            context_box=context_box,
        )
        session.prompt_type = "smart_mask"
        session.prompt_box = context_box
        self._update_candidate(session, prediction)
        return session

    def reset_session(self, session_id: str) -> AssistSessionState:
        session = self._session(session_id)
        session.add_strokes.clear()
        session.subtract_strokes.clear()
        session.candidate_prediction = None
        session.candidate_mask_png_base64 = None
        session.brush_radius = None
        session.prompt_type = None
        session.prompt_box = None
        return session

    def delete_session(self, session_id: str) -> None:
        session = self._sessions.pop(session_id, None)
        if session is None:
            raise NotFoundError("Assist session not found")
        self._trim_cache()

    def accept_session(
        self, session_id: str
    ) -> tuple[AssistSessionState, PixelBox, dict[str, Any]]:
        session = self._session(session_id)
        if session.candidate_prediction is None:
            raise ValidationError("There is no current Smart Mask candidate to accept")
        box = session.candidate_prediction.box
        provenance = {
            "source_type": "assist_mask",
            "model_checksum": session.model_checksum,
            "provider_name": session.provider_name,
            "provider_version": session.provider_version,
            "prompt_type": session.prompt_type or "smart_mask",
            "source_prediction_id": session.source_prediction_id,
            "add_strokes": [
                {
                    "brush_radius": stroke.brush_radius,
                    "points": [{"x": point.x, "y": point.y} for point in stroke.points],
                }
                for stroke in session.add_strokes
            ],
            "subtract_strokes": [
                {
                    "brush_radius": stroke.brush_radius,
                    "points": [{"x": point.x, "y": point.y} for point in stroke.points],
                }
                for stroke in session.subtract_strokes
            ],
            "prompt_box": (
                {
                    "x_min": session.prompt_box.x_min,
                    "y_min": session.prompt_box.y_min,
                    "x_max": session.prompt_box.x_max,
                    "y_max": session.prompt_box.y_max,
                }
                if session.prompt_box is not None
                else None
            ),
            "accepted_box": {
                "x_min": box.x_min,
                "y_min": box.y_min,
                "x_max": box.x_max,
                "y_max": box.y_max,
            },
            "accepted_at": self._now().isoformat(),
        }
        return session, box, provenance
