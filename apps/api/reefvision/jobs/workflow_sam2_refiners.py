"""Select in-process or sidecar SAM 2 refinement for exact consensus Workflows."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import ModelRegistration
from reefvision.domain.errors import ValidationError
from reefvision.jobs import workflow_consensus
from reefvision.ml.sam2_sidecar import SAM2SidecarAssistProvider
from reefvision.services.independent_segmentation_auto_labeling import VLMBoxDetection
from reefvision.services.mask_consensus import IndependentMaskCandidate
from reefvision.storage.models import resolve_verified_model_path

_ORIGINAL_PIPELINE = workflow_consensus.run_independent_segmentation_pipeline


def _mask_bounds(mask: np.ndarray) -> tuple[float, float, float, float]:
    rows, columns = np.where(mask)
    if rows.size == 0 or columns.size == 0:
        raise ValidationError("SAM 2 sidecar produced an empty refinement mask")
    return (
        float(columns.min()),
        float(rows.min()),
        float(columns.max() + 1),
        float(rows.max() + 1),
    )


class SidecarSAM2BoxRefiner:
    def __init__(
        self,
        settings: Settings,
        model: ModelRegistration,
        *,
        device: str,
    ) -> None:
        if model.provider_name.strip().casefold() != "sam2_sidecar":
            raise ValidationError("Sidecar refiner requires a sam2_sidecar model")
        self.settings = settings
        self.model_id = model.id
        self.model_checksum = model.sha256
        self.provider = SAM2SidecarAssistProvider()
        self.provider.load_model(
            resolve_verified_model_path(
                settings,
                model.managed_path,
                expected_sha256=model.sha256,
            ),
            device,
        )

    def refine(
        self,
        *,
        image_id: str,
        image_path: Path,
        class_key: str,
        detections: list[VLMBoxDetection],
    ) -> list[IndependentMaskCandidate]:
        prepared = self.provider.prepare_image(image_path)
        candidates: list[IndependentMaskCandidate] = []
        for detection in detections:
            prediction = self.provider.predict_from_box(prepared, detection.box)
            mask = np.asarray(prediction.mask, dtype=bool)
            x_min, y_min, x_max, y_max = _mask_bounds(mask)
            candidates.append(
                IndependentMaskCandidate(
                    candidate_id=f"{detection.detection_id}:sam2",
                    branch_id=detection.branch_id,
                    image_id=image_id,
                    class_key=class_key,
                    confidence=float(min(detection.confidence, prediction.score)),
                    mask=mask,
                    provenance={
                        "detector_model": detection.model_name,
                        "detector_confidence": detection.confidence,
                        "detector_box": [
                            detection.box.x_min,
                            detection.box.y_min,
                            detection.box.x_max,
                            detection.box.y_max,
                        ],
                        "sam2_model_id": self.model_id,
                        "sam2_model_checksum": self.model_checksum,
                        "sam2_provider": "sam2_sidecar",
                        "sam2_provider_version": self.provider.provider_version,
                        "sam2_score": prediction.score,
                        "refined_bounds": [x_min, y_min, x_max, y_max],
                    },
                )
            )
        return candidates

    def close(self) -> None:
        self.provider.unload_model()


def run_pipeline_with_registered_sam2(
    settings: Settings,
    factory: sessionmaker[Session],
    **kwargs: Any,
):
    """Inject a sidecar refiner only when the selected registration requires it."""

    sam2_model_id = str(kwargs.get("sam2_model_id", ""))
    with factory() as session:
        model = session.get(ModelRegistration, sam2_model_id)
        if model is None:
            raise ValidationError("The selected SAM 2 refinement model no longer exists")
        provider_name = model.provider_name.strip().casefold()
    if provider_name != "sam2_sidecar":
        return _ORIGINAL_PIPELINE(settings, factory, **kwargs)

    refiner = SidecarSAM2BoxRefiner(
        settings,
        model,
        device=str(kwargs.get("device", "auto")),
    )
    try:
        return _ORIGINAL_PIPELINE(
            settings,
            factory,
            **{**kwargs, "refiner": refiner},
        )
    finally:
        refiner.close()


workflow_consensus.run_independent_segmentation_pipeline = run_pipeline_with_registered_sam2

# Worker startup imports these modules for workflow definition/runtime extensions. Install
# typed ports first, then the full science bridge. Depth-artifact enrichment wraps the base
# depth node before downstream measurement wrappers. Ordering remains part of the contract:
# behavior configuration precedes windowing; video 3D precedes the metric coral-surface
# wrapper; canonical depth-source aliases load before both physical-depth workflows execute.
from reefvision.services import (  # noqa: E402,F401
    workflow_definition_extensions as _workflow_definition_extensions,
)
from reefvision.jobs import workflow_science_runtime as _workflow_science_runtime  # noqa: E402,F401
from reefvision.jobs import (  # noqa: E402,F401
    workflow_depth_artifact_runtime as _workflow_depth_artifact_runtime,
)
from reefvision.jobs import workflow_behavior_runtime as _workflow_behavior_runtime  # noqa: E402,F401
from reefvision.jobs import (  # noqa: E402,F401
    workflow_behavior_window_runtime as _workflow_behavior_window_runtime,
)
from reefvision.jobs import (  # noqa: E402,F401
    workflow_active_learning_runtime as _workflow_active_learning_runtime,
)
from reefvision.jobs import (  # noqa: E402,F401
    workflow_probability_only_active_learning as _workflow_probability_only_active_learning,
)
from reefvision.jobs import (  # noqa: E402,F401
    workflow_video_depth_3d_runtime as _workflow_video_depth_3d_runtime,
)
from reefvision.jobs import (  # noqa: E402,F401
    workflow_depth_source_compat as _workflow_depth_source_compat,
)
from reefvision.jobs import (  # noqa: E402,F401
    workflow_metric_coral_surface_runtime as _workflow_metric_coral_surface_runtime,
)
