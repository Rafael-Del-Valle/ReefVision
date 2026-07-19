"""Queue validated provider benchmark executions through the standard job system."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import ImageAsset, Job, ModelRegistration
from reefvision.domain.errors import ValidationError
from reefvision.schemas.jobs import JobResponse
from reefvision.schemas.provider_benchmark_jobs import (
    ProviderBenchmarkRunRequest,
    ProviderBenchmarkRunResponse,
)
from reefvision.services.provider_capabilities import ProviderCapabilityService

_PROVIDER_ALIASES = {
    "segment_anything": "efficientvit_sam",
    "depth_anything_v2_relative": "depth_anything_v2",
    "depth_anything_v2_metric": "depth_anything_v2",
}


class ProviderBenchmarkJobService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def queue(self, payload: ProviderBenchmarkRunRequest) -> ProviderBenchmarkRunResponse:
        capability_id = _PROVIDER_ALIASES.get(payload.provider_id, payload.provider_id)
        capability = ProviderCapabilityService(self.session, self.settings).get(capability_id)
        if capability.health == "unavailable":
            raise ValidationError(
                "The selected provider is unavailable. Resolve its dependency or device blockers first."
            )
        if payload.task not in capability.supported_tasks:
            aliases = {
                "detect": "detect",
                "segment": "segment",
                "classify": "classify",
                "track": "track",
                "prompt_segment": "prompt_segment",
                "automatic_mask": "automatic_mask",
                "video_mask_propagation": "video_mask_propagation",
                "depth": "depth",
                "embed": "embed",
            }
            if aliases.get(payload.task) not in capability.supported_tasks:
                raise ValidationError("The selected provider does not advertise the requested task")

        model: ModelRegistration | None = None
        project_id = payload.project_id
        if payload.model_id and payload.provider_id not in {
            "depth_anything_v2",
            "depth_anything_v2_relative",
            "depth_anything_v2_metric",
        }:
            model = self.session.get(ModelRegistration, payload.model_id)
            if model is None:
                raise ValidationError("The requested registered model does not exist")
            project_id = project_id or model.project_id
            if project_id != model.project_id:
                raise ValidationError("The registered model belongs to a different project")

        images = list(
            self.session.scalars(
                select(ImageAsset).where(ImageAsset.id.in_(payload.image_ids))
            )
        )
        if len(images) != len(set(payload.image_ids)):
            raise ValidationError("One or more benchmark images do not exist")
        image_project_ids = {image.project_id for image in images}
        if len(image_project_ids) > 1:
            raise ValidationError("Provider benchmarks cannot mix images from multiple projects")
        if image_project_ids:
            image_project_id = next(iter(image_project_ids))
            project_id = project_id or image_project_id
            if project_id != image_project_id:
                raise ValidationError("Benchmark images belong to a different project")

        compatible_devices = {
            device.device_id
            for device in capability.devices
            if device.available
            and (
                (device.kind == "cpu" and capability.supports_cpu)
                or (device.kind == "cuda" and capability.supports_cuda)
                or device.kind == "mps"
            )
        }
        requested_device = payload.device_id
        if requested_device not in {"auto", "cuda", "gpu"} and requested_device not in compatible_devices:
            raise ValidationError("The requested benchmark device is not available for this provider")

        minimum_vram = 0
        if requested_device.startswith("cuda") or requested_device in {"cuda", "gpu"}:
            minimum_vram = min(capability.estimated_vram_bytes.values(), default=0)
        job = Job(
            project_id=project_id,
            job_type="provider_benchmark",
            status="queued",
            progress_total=payload.warmup_count + payload.sample_count,
            max_retries=1,
            resume_supported=False,
            request_json=payload.model_dump(mode="json"),
            result_json={"stage": "queued"},
            resource_requirements_json={
                "device": requested_device,
                "gpu_required": requested_device.startswith("cuda")
                or requested_device in {"cuda", "gpu"},
                "minimum_vram_bytes": minimum_vram,
                "cpu_threads": int(payload.parameters.get("cpu_threads", 1)),
                "exclusive_gpu": bool(payload.parameters.get("exclusive_gpu", True)),
            },
        )
        self.session.add(job)
        self.session.commit()
        self.session.refresh(job)
        return ProviderBenchmarkRunResponse(job=JobResponse.model_validate(job))
