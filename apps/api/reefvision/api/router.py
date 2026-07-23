"""Top-level API router."""

from fastapi import APIRouter

from reefvision.api.routes.active_learning import router as active_learning_router
from reefvision.api.routes.active_learning_cycles import router as active_learning_cycles_router
from reefvision.api.routes.annotations import router as annotations_router
from reefvision.api.routes.artifacts import router as artifacts_router
from reefvision.api.routes.assist import router as assist_router
from reefvision.api.routes.backups import router as backups_router
from reefvision.api.routes.capabilities import router as capabilities_router
from reefvision.api.routes.catalog_inference import router as catalog_inference_router
from reefvision.api.routes.class_operations import router as class_operations_router
from reefvision.api.routes.class_visibility import router as class_visibility_router
from reefvision.api.routes.classification import router as classification_router
from reefvision.api.routes.classification_datasets import (
    router as classification_datasets_router,
)
from reefvision.api.routes.classification_evaluation import (
    router as classification_evaluation_router,
)
from reefvision.api.routes.classification_management import (
    router as classification_management_router,
)
from reefvision.api.routes.classification_qa import router as classification_qa_router
from reefvision.api.routes.dataset_versions import router as dataset_versions_router
from reefvision.api.routes.depth import router as depth_router
from reefvision.api.routes.health import router as health_router
from reefvision.api.routes.image_embeddings import router as image_embeddings_router
from reefvision.api.routes.images import router as images_router
from reefvision.api.routes.interchange import router as interchange_router
from reefvision.api.routes.jobs import router as jobs_router
from reefvision.api.routes.mask_conversion import router as mask_conversion_router
from reefvision.api.routes.measurements import router as measurements_router
from reefvision.api.routes.model_catalog import router as model_catalog_router
from reefvision.api.routes.models import router as models_router
from reefvision.api.routes.predictions import router as predictions_router
from reefvision.api.routes.project_archives import router as project_archives_router
from reefvision.api.routes.project_integrity import router as project_integrity_router
from reefvision.api.routes.project_recovery import router as project_recovery_router
from reefvision.api.routes.projects import router as projects_router
from reefvision.api.routes.provider_capabilities import (
    router as provider_capabilities_router,
)
from reefvision.api.routes.provider_lifecycle import router as provider_lifecycle_router
from reefvision.api.routes.quality_control import router as quality_control_router
from reefvision.api.routes.raster_edits import router as raster_edits_router
from reefvision.api.routes.review_queues import router as review_queues_router
from reefvision.api.routes.sam2_video import router as sam2_video_router
from reefvision.api.routes.scientific_validation import (
    router as scientific_validation_router,
)
from reefvision.api.routes.segmentation_evaluation import (
    router as segmentation_evaluation_router,
)
from reefvision.api.routes.system import router as system_router
from reefvision.api.routes.tracking_evaluation import router as tracking_evaluation_router
from reefvision.api.routes.training import router as training_router
from reefvision.api.routes.training_reports import router as training_reports_router
from reefvision.api.routes.validation_dashboard import router as validation_dashboard_router
from reefvision.api.routes.video_exports import router as video_exports_router
from reefvision.api.routes.videos import router as videos_router
from reefvision.api.routes.workflow_persistence import router as workflow_persistence_router
from reefvision.api.routes.workflows import router as workflows_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health_router)
api_router.include_router(capabilities_router)
api_router.include_router(system_router)
api_router.include_router(provider_capabilities_router)
api_router.include_router(provider_lifecycle_router)
api_router.include_router(active_learning_cycles_router)
api_router.include_router(training_router)
api_router.include_router(training_reports_router)
api_router.include_router(classification_router)
api_router.include_router(classification_datasets_router)
api_router.include_router(classification_management_router)
api_router.include_router(classification_evaluation_router)
api_router.include_router(classification_qa_router)
api_router.include_router(videos_router)
api_router.include_router(video_exports_router)
api_router.include_router(tracking_evaluation_router)
api_router.include_router(sam2_video_router)
api_router.include_router(backups_router)
api_router.include_router(projects_router)
api_router.include_router(project_archives_router)
api_router.include_router(project_integrity_router)
api_router.include_router(project_recovery_router)
api_router.include_router(validation_dashboard_router)
api_router.include_router(artifacts_router)
api_router.include_router(class_operations_router)
api_router.include_router(class_visibility_router)
api_router.include_router(images_router)
api_router.include_router(image_embeddings_router)
api_router.include_router(depth_router)
api_router.include_router(annotations_router)
api_router.include_router(raster_edits_router)
api_router.include_router(mask_conversion_router)
api_router.include_router(measurements_router)
api_router.include_router(scientific_validation_router)
api_router.include_router(dataset_versions_router)
api_router.include_router(interchange_router)
api_router.include_router(jobs_router)
api_router.include_router(model_catalog_router)
api_router.include_router(models_router)
api_router.include_router(catalog_inference_router)
api_router.include_router(predictions_router)
api_router.include_router(assist_router)
api_router.include_router(segmentation_evaluation_router)
api_router.include_router(quality_control_router)
api_router.include_router(review_queues_router)
api_router.include_router(active_learning_router)
api_router.include_router(workflows_router)
api_router.include_router(workflow_persistence_router)
