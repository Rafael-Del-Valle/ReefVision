"""Queue class-agnostic SAM proposals without starting inference on the API thread."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import ImageAsset, Job
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.ml.sam_image_proposals import tile_boxes
from reefvision.schemas.sam_image_proposals import SamImageProposalsRequest
from reefvision.services.sam2_install import sam2_status


class SamImageProposalsService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def create(self, project_id: str, request: SamImageProposalsRequest) -> Job:
        image = self.session.get(ImageAsset, str(request.image_id))
        if image is None or image.project_id != project_id:
            raise NotFoundError("Image not found in this project")
        boxes = tile_boxes(image.width_px, image.height_px, request.tile_size)
        points = len(boxes) * request.points_per_side**2
        if points > 256:
            raise ValidationError("SAM point budget exceeds 256; reduce points per side")
        active = self.session.scalars(
            select(Job).where(
                Job.project_id == project_id,
                Job.job_type == "sam_image_proposals",
                Job.status.in_(("queued", "running", "cancel_requested")),
            )
        )
        if any(job.request_json.get("image_id") == str(request.image_id) for job in active):
            raise ConflictError("A SAM proposal job is already active for this image")
        installed = sam2_status(self.settings, request.variant)
        if not installed["ready"]:
            raise ValidationError(
                f"Choose/download SAM 2.1 {request.variant} in Model Hub first. "
                f"{installed['reason']}"
            )
        job = Job(
            project_id=project_id,
            job_type="sam_image_proposals",
            status="queued",
            progress_current=0,
            progress_total=points,
            request_json=request.model_dump(mode="json"),
            result_json={"stage": "queued", "image_id": str(request.image_id)},
        )
        self.session.add(job)
        self.session.commit()
        self.session.refresh(job)
        return job
