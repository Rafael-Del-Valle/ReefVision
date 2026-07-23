"""Register localhost SAM 2 sidecars as managed Prompt Assist models."""

from __future__ import annotations

import json
from io import BytesIO

from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import ModelRegistration
from reefvision.domain.errors import NotFoundError
from reefvision.schemas.models import ModelRegistrationResponse
from reefvision.schemas.sam2_sidecar import Sam2SidecarRegistrationRequest
from reefvision.services.models import ModelService


class Sam2SidecarModelService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def register(
        self,
        project_id: str,
        request: Sam2SidecarRegistrationRequest,
    ) -> ModelRegistrationResponse:
        descriptor = {
            "schema": "reefvision-sam2-sidecar-v1",
            "endpoint": request.endpoint,
            "token_env": request.token_env,
            "timeout_seconds": request.timeout_seconds,
            "sam2_version": "sam2-sidecar",
        }
        payload = json.dumps(
            descriptor,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        registered = ModelService(self.session, self.settings).register_model_upload(
            project_id,
            purpose="assist",
            provider_name="sam2_sidecar",
            upload_filename="sam2-sidecar.sam2.json",
            upload_stream=BytesIO(payload),
            display_name=request.display_name,
            notes=request.notes,
        )
        model = self.session.get(ModelRegistration, registered.id)
        if model is None:
            raise NotFoundError("Registered SAM 2 sidecar model could not be reloaded")
        model.framework = "sam2-sidecar"
        model.task = "assist_segmentation"
        model.provider_name = "sam2_sidecar"
        model.provider_version = "1"
        model.input_size_json = None
        model.class_map_json = {}
        model.metadata_json = {
            **dict(model.metadata_json or {}),
            "registration_kind": "sam2_sidecar",
            "endpoint": request.endpoint,
            "token_env": request.token_env,
            "timeout_seconds": request.timeout_seconds,
            "remote_host_policy": "localhost_only",
            "checkpoint_location": "sidecar_process",
        }
        self.session.commit()
        self.session.refresh(model)
        return ModelRegistrationResponse.model_validate(model)
