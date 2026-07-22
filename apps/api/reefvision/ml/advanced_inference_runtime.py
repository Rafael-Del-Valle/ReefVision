"""Thread-local prompt propagation for queued Transformers inference jobs."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from reefvision.db.models import Job, PredictionProposal
from reefvision.ml.transformers_provider import (
    reset_transformers_text_prompt,
    set_transformers_text_prompt,
)

_APPLIED = False
_TRANSFORMERS_PROVIDERS = {"grounding_dino", "owlv2", "florence2"}


def apply_advanced_inference_runtime_patch() -> None:
    global _APPLIED
    if _APPLIED:
        return
    from reefvision.jobs import worker

    original = worker.process_inference_job

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

    worker.process_inference_job = process_with_prompt
    _APPLIED = True
