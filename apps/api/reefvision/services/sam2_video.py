"""Queue validated SAM 2 video-mask propagation jobs."""

from __future__ import annotations

from sqlalchemy.orm import Session

from reefvision.db.models import Job, ModelRegistration, VideoAsset
from reefvision.domain.errors import ValidationError
from reefvision.schemas.jobs import JobResponse
from reefvision.schemas.sam2_video import (
    SAM2VideoPropagationRequest,
    SAM2VideoPropagationResponse,
)


class SAM2VideoPropagationService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def queue(
        self,
        video_id: str,
        payload: SAM2VideoPropagationRequest,
    ) -> SAM2VideoPropagationResponse:
        video = self.session.get(VideoAsset, video_id)
        if video is None:
            raise ValidationError("Video not found")
        model = self.session.get(ModelRegistration, payload.model_id)
        if model is None:
            raise ValidationError("Registered SAM 2 model not found")
        if model.project_id != video.project_id:
            raise ValidationError("The SAM 2 model belongs to a different project")
        provider_name = model.provider_name.strip().casefold().replace("-", "_")
        if provider_name not in {"sam2", "sam_2"}:
            raise ValidationError("Video-mask propagation requires a registered SAM 2 checkpoint")
        if payload.seed_frame_index >= video.frame_count:
            raise ValidationError("The seed frame is outside the managed video")
        for point in [*payload.positive_points, *payload.negative_points]:
            if point.x > video.width_px or point.y > video.height_px:
                raise ValidationError("Prompt points must remain inside video-frame bounds")
        if payload.prompt_box is not None and (
            payload.prompt_box.x_max > video.width_px or payload.prompt_box.y_max > video.height_px
        ):
            raise ValidationError("The prompt box must remain inside video-frame bounds")

        maximum_frames = payload.maximum_frames or video.frame_count
        total_frames = min(
            maximum_frames,
            max(1, (video.frame_count + payload.every_n_frames - 1) // payload.every_n_frames),
        )
        job = Job(
            project_id=video.project_id,
            job_type="sam2_video_propagation",
            status="queued",
            progress_total=total_frames,
            max_retries=1,
            resume_supported=False,
            request_json={
                "video_id": video.id,
                **payload.model_dump(mode="json"),
            },
            result_json={"stage": "queued"},
            resource_requirements_json={
                "device": payload.device,
                "gpu_required": payload.device != "cpu",
                "minimum_vram_bytes": int(
                    model.metadata_json.get("recommended_vram_bytes", 4 * 1024**3)
                ),
                "exclusive_gpu": True,
            },
        )
        self.session.add(job)
        self.session.commit()
        self.session.refresh(job)
        return SAM2VideoPropagationResponse(job=JobResponse.model_validate(job))
