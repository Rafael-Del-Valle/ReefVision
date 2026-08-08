"""Queue project-scoped Depth Anything V2 inference jobs."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import ImageAsset, Job, ModelRegistration, Project
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.schemas.advanced_providers import (
    AdvancedDepthJobCreateRequest,
    AdvancedProviderPreflightRequest,
)
from reefvision.schemas.jobs import JobResponse
from reefvision.services.advanced_providers import AdvancedProviderService


class AdvancedDepthService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def create_job(
        self,
        project_id: str,
        request: AdvancedDepthJobCreateRequest,
    ) -> JobResponse:
        project = self.session.get(Project, project_id)
        if project is None:
            raise NotFoundError("Project not found")
        model = self.session.get(ModelRegistration, request.model_id)
        if (
            model is None
            or model.project_id != project_id
            or model.purpose != "depth"
            or model.provider_name != "depth_anything_v2"
            or model.task != "relative_depth"
        ):
            raise ValidationError(
                "Depth inference requires a registered Depth Anything V2 model from this project"
            )

        image_ids = list(dict.fromkeys(request.image_ids))
        images = list(
            self.session.scalars(
                select(ImageAsset).where(
                    ImageAsset.project_id == project_id,
                    ImageAsset.id.in_(image_ids),
                )
            )
        )
        if len(images) != len(image_ids):
            raise ValidationError("One or more depth-inference images do not belong to the project")

        first_image_id = image_ids[0]
        preflight = AdvancedProviderService(self.session, self.settings).preflight(
            project_id,
            "depth_anything_v2",
            AdvancedProviderPreflightRequest(
                task="relative_depth",
                device=request.device,
                model_id=model.id,
                prompt_fields={"image_id": first_image_id},
            ),
        )
        if not preflight.ready:
            raise ValidationError("; ".join(preflight.blockers))

        job = Job(
            project_id=project_id,
            job_type="advanced_depth",
            status="queued",
            progress_current=0,
            progress_total=len(image_ids),
            request_json={
                "provider_id": "depth_anything_v2",
                "model_id": model.id,
                "model_sha256": model.sha256,
                "image_ids": image_ids,
                "device": request.device,
            },
            result_json={"stage": "queued", "outputs": []},
        )
        self.session.add(job)
        self.session.commit()
        self.session.refresh(job)
        return JobResponse.model_validate(job)
