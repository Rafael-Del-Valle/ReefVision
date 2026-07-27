"""Thread-local prompt propagation for queued Transformers inference jobs."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from reefvision.db.models import Job, PredictionProposal
from reefvision.ml.transformers_provider import (
    reset_transformers_text_prompt,
    set_transformers_text_prompt,
)
from reefvision.schemas.jobs import JobResponse

_APPLIED = False
_TRANSFORMERS_PROVIDERS = {"grounding_dino", "owlv2", "florence2"}


def _patch_registered_model_job_creation() -> None:
    from reefvision.services.semantic_models import SemanticModelService

    original = SemanticModelService.create_inference_job

    def create_with_prompt(self: Any, project_id: str, payload: Any) -> JobResponse:
        response = original(self, project_id, payload)
        prompt = getattr(payload, "text_prompt", None)
        normalized = prompt.strip() if isinstance(prompt, str) and prompt.strip() else None
        if normalized is None:
            return response
        job = self.session.get(Job, response.id)
        if job is None:
            return response
        request = dict(job.request_json or {})
        request["text_prompt"] = normalized
        job.request_json = request
        self.session.commit()
        self.session.refresh(job)
        return JobResponse.model_validate(job)

    SemanticModelService.create_inference_job = create_with_prompt  # type: ignore[method-assign]


def _patch_worker_prompt_context() -> None:
    from reefvision.jobs import worker

    original = worker.process_inference_job  # type: ignore[attr-defined]

    def process_with_prompt(settings: Any, factory: Any, job_id: str) -> bool:
        prompt: str | None = None
        provider_name: str | None = None
        with factory() as session:
            job = session.get(Job, job_id)
            if job is not None:
                request = dict(job.request_json or {})
                value = request.get("text_prompt")
                prompt = value.strip() if isinstance(value, str) and value.strip() else None
                model_id = str(request.get("model_id") or "")
                if model_id:
                    from reefvision.db.models import ModelRegistration

                    model = session.get(ModelRegistration, model_id)
                    provider_name = model.provider_name if model is not None else None
        token = set_transformers_text_prompt(
            prompt if provider_name in _TRANSFORMERS_PROVIDERS else None
        )
        try:
            result = original(settings, factory, job_id)
        finally:
            reset_transformers_text_prompt(token)
        if prompt and provider_name in _TRANSFORMERS_PROVIDERS:
            with factory() as session:
                proposals = list(
                    session.scalars(
                        select(PredictionProposal).where(
                            PredictionProposal.inference_job_id == job_id
                        )
                    )
                )
                for proposal in proposals:
                    provenance = dict(proposal.provenance_json or {})
                    provenance["text_prompt"] = prompt
                    proposal.provenance_json = provenance
                    inference_settings = dict(proposal.inference_settings_json or {})
                    inference_settings["text_prompt"] = prompt
                    proposal.inference_settings_json = inference_settings
                if proposals:
                    session.commit()
        return result

    worker.process_inference_job = process_with_prompt  # type: ignore[attr-defined]


def apply_advanced_inference_runtime_patch() -> None:
    global _APPLIED
    if _APPLIED:
        return
    _patch_registered_model_job_creation()
    _patch_worker_prompt_context()
    _APPLIED = True
