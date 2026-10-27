"""Top-level API router."""

from fastapi import APIRouter

from reefvision.api.routes.active_learning import router as active_learning_router
from reefvision.api.routes.advanced_provider_execution import (
    router as advanced_provider_execution_router,
)
from reefvision.api.routes.advanced_providers import router as advanced_providers_router
from reefvision.api.routes.annotation_imports import router as annotation_imports_router
from reefvision.api.routes.annotations import router as annotations_router
from reefvision.api.routes.assist import router as assist_router
from reefvision.api.routes.backups import router as backups_router
from reefvision.api.routes.behavior_dynamics import router as behavior_dynamics_router
from reefvision.api.routes.capabilities import router as capabilities_router
from reefvision.api.routes.class_operations import router as class_operations_router
from reefvision.api.routes.class_visibility import router as class_visibility_router
from reefvision.api.routes.classification import router as classification_router
from reefvision.api.routes.coral_structure import router as coral_structure_router
from reefvision.api.routes.dataset_versions import router as dataset_versions_router
from reefvision.api.routes.geographic_movement_analytics import (
    router as geographic_movement_analytics_router,
)
from reefvision.api.routes.georeferenced_observations import (
    router as georeferenced_observations_router,
)
from reefvision.api.routes.health import router as health_router
from reefvision.api.routes.images import router as images_router
from reefvision.api.routes.jobs import router as jobs_router
from reefvision.api.routes.learning_evaluation import router as learning_evaluation_router
from reefvision.api.routes.mask_refinements import router as mask_refinements_router
from reefvision.api.routes.measurements import router as measurements_router
from reefvision.api.routes.model_catalog import router as model_catalog_router
from reefvision.api.routes.models import router as models_router
from reefvision.api.routes.pose_active_learning import router as pose_active_learning_router
from reefvision.api.routes.pose_training_datasets import (
    router as pose_training_datasets_router,
)
from reefvision.api.routes.predictions import router as predictions_router
from reefvision.api.routes.project_exchange import router as project_exchange_router
from reefvision.api.routes.project_learning import router as project_learning_router
from reefvision.api.routes.projects import router as projects_router
from reefvision.api.routes.quality_control import router as quality_control_router
from reefvision.api.routes.raster_edits import router as raster_edits_router
from reefvision.api.routes.review_queue_events import router as review_queue_events_router
from reefvision.api.routes.review_queues import router as review_queues_router
from reefvision.api.routes.sam2_models import router as sam2_models_router
from reefvision.api.routes.sam_image_proposals import router as sam_image_proposals_router
from reefvision.api.routes.scale_label_ocr import router as scale_label_ocr_router
from reefvision.api.routes.segmentation_deployment import router as segmentation_deployment_router
from reefvision.api.routes.segmentation_evaluation_queue import (
    router as segmentation_evaluation_queue_router,
)
from reefvision.api.routes.segmentation_learning_evaluation import (
    router as segmentation_learning_evaluation_router,
)
from reefvision.api.routes.skeleton_records import router as skeleton_records_router
from reefvision.api.routes.system import router as system_router
from reefvision.api.routes.training import router as training_router
from reefvision.api.routes.video_science import router as video_science_router
from reefvision.api.routes.videos import router as videos_router
from reefvision.api.routes.workflow_graphs import router as workflow_graphs_router
from reefvision.services.workflow_v1_install import install_workflow_v1_extensions

install_workflow_v1_extensions()

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(geographic_movement_analytics_router)
api_router.include_router(health_router)
api_router.include_router(capabilities_router)
api_router.include_router(system_router)
api_router.include_router(training_router)
api_router.include_router(classification_router)
api_router.include_router(coral_structure_router)
api_router.include_router(skeleton_records_router)
api_router.include_router(videos_router)
api_router.include_router(georeferenced_observations_router)
api_router.include_router(video_science_router)
api_router.include_router(behavior_dynamics_router)
api_router.include_router(backups_router)
api_router.include_router(projects_router)
api_router.include_router(project_exchange_router)
api_router.include_router(class_operations_router)
api_router.include_router(class_visibility_router)
api_router.include_router(images_router)
api_router.include_router(annotation_imports_router)
api_router.include_router(annotations_router)
api_router.include_router(raster_edits_router)
api_router.include_router(measurements_router)
api_router.include_router(scale_label_ocr_router)
api_router.include_router(dataset_versions_router)
api_router.include_router(jobs_router)
api_router.include_router(model_catalog_router)
api_router.include_router(sam2_models_router)
api_router.include_router(models_router)
api_router.include_router(predictions_router)
api_router.include_router(assist_router)
api_router.include_router(quality_control_router)
api_router.include_router(review_queues_router)
api_router.include_router(review_queue_events_router)
api_router.include_router(active_learning_router)
api_router.include_router(pose_active_learning_router)
api_router.include_router(pose_training_datasets_router)
api_router.include_router(advanced_providers_router)
api_router.include_router(advanced_provider_execution_router)
api_router.include_router(workflow_graphs_router)
api_router.include_router(learning_evaluation_router)
api_router.include_router(segmentation_learning_evaluation_router)
api_router.include_router(segmentation_deployment_router)
api_router.include_router(segmentation_evaluation_queue_router)

api_router.include_router(mask_refinements_router)

api_router.include_router(sam_image_proposals_router)

api_router.include_router(project_learning_router)
