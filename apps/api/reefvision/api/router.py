"""Top-level API router."""

from fastapi import APIRouter

from reefvision.api.routes.acquisition_sources import router as acquisition_sources_router
from reefvision.api.routes.active_learning import router as active_learning_router
from reefvision.api.routes.advanced_provider_execution import (
    router as advanced_provider_execution_router,
)
from reefvision.api.routes.advanced_providers import router as advanced_providers_router
from reefvision.api.routes.annotation_aggregates import router as annotation_aggregates_router
from reefvision.api.routes.annotation_comparison import router as annotation_comparison_router
from reefvision.api.routes.annotation_imports import router as annotation_imports_router
from reefvision.api.routes.annotations import router as annotations_router
from reefvision.api.routes.assist import router as assist_router
from reefvision.api.routes.backups import router as backups_router
from reefvision.api.routes.behavior_dynamics import router as behavior_dynamics_router
from reefvision.api.routes.bioacoustics import router as bioacoustics_router
from reefvision.api.routes.capabilities import router as capabilities_router
from reefvision.api.routes.class_operations import router as class_operations_router
from reefvision.api.routes.class_visibility import router as class_visibility_router
from reefvision.api.routes.classification import router as classification_router
from reefvision.api.routes.computed_aggregate_metrics import (
    router as computed_aggregate_metrics_router,
)
from reefvision.api.routes.computed_mask_coverage import router as computed_mask_coverage_router
from reefvision.api.routes.computed_metrics import router as computed_metrics_router
from reefvision.api.routes.coral_graph import router as coral_graph_router
from reefvision.api.routes.coral_structure import router as coral_structure_router
from reefvision.api.routes.current_field import router as current_field_router
from reefvision.api.routes.dataset_versions import router as dataset_versions_router
from reefvision.api.routes.domain_shift_v18 import router as domain_shift_router
from reefvision.api.routes.ecology_analysis import router as ecology_analysis_router
from reefvision.api.routes.ecology_event_summary import router as ecology_event_summary_router
from reefvision.api.routes.ecology_identity import router as ecology_identity_router
from reefvision.api.routes.ecology_pose_links import router as ecology_pose_links_router
from reefvision.api.routes.environmental_analysis import router as environmental_analysis_router
from reefvision.api.routes.environmental_context import router as environmental_context_router
from reefvision.api.routes.field_capture import router as field_capture_router
from reefvision.api.routes.geographic_movement_analytics import (
    router as geographic_movement_analytics_router,
)
from reefvision.api.routes.geographic_pairwise import router as geographic_pairwise_router
from reefvision.api.routes.georeferenced_observations import (
    router as georeferenced_observations_router,
)
from reefvision.api.routes.health import router as health_router
from reefvision.api.routes.image_adjustments_v18 import router as image_adjustments_router
from reefvision.api.routes.images import router as images_router
from reefvision.api.routes.jobs import router as jobs_router
from reefvision.api.routes.learning_evaluation import router as learning_evaluation_router
from reefvision.api.routes.longitudinal_monitoring import router as longitudinal_monitoring_router
from reefvision.api.routes.lunar_context import router as lunar_context_router
from reefvision.api.routes.mask_refinements import router as mask_refinements_router
from reefvision.api.routes.measurements import router as measurements_router
from reefvision.api.routes.model_agreement import router as model_agreement_router
from reefvision.api.routes.model_catalog import router as model_catalog_router
from reefvision.api.routes.model_runtime import router as model_runtime_router
from reefvision.api.routes.models import router as models_router
from reefvision.api.routes.monitoring import router as monitoring_router
from reefvision.api.routes.monitoring_summaries import router as monitoring_summaries_router
from reefvision.api.routes.multimodal import router as multimodal_router
from reefvision.api.routes.multispectral import router as multispectral_router
from reefvision.api.routes.paired_models_v15 import router as paired_models_router
from reefvision.api.routes.plugins import router as plugins_router
from reefvision.api.routes.pose_active_learning import router as pose_active_learning_router
from reefvision.api.routes.pose_appearance import router as pose_appearance_router
from reefvision.api.routes.pose_biological_measurement import (
    router as pose_biological_measurement_router,
)
from reefvision.api.routes.pose_evaluation import router as pose_evaluation_router
from reefvision.api.routes.pose_identity_tracking import router as pose_identity_tracking_router
from reefvision.api.routes.pose_schemas import router as pose_schemas_router
from reefvision.api.routes.pose_training_datasets import (
    router as pose_training_datasets_router,
)
from reefvision.api.routes.predictions import router as predictions_router
from reefvision.api.routes.project_exchange import router as project_exchange_router
from reefvision.api.routes.project_learning import router as project_learning_router
from reefvision.api.routes.projects import router as projects_router
from reefvision.api.routes.quality_control import router as quality_control_router
from reefvision.api.routes.raster_edits import router as raster_edits_router
from reefvision.api.routes.reefpose_validation import router as reefpose_validation_router
from reefvision.api.routes.reproducibility_v15 import router as reproducibility_router
from reefvision.api.routes.research_reports import router as research_reports_router
from reefvision.api.routes.review_queue_events import router as review_queue_events_router
from reefvision.api.routes.review_queues import router as review_queues_router
from reefvision.api.routes.reviewer_lab_v15 import router as reviewer_lab_router
from reefvision.api.routes.sam2_models import router as sam2_models_router
from reefvision.api.routes.sam_image_proposals import router as sam_image_proposals_router
from reefvision.api.routes.scale_label_ocr import router as scale_label_ocr_router
from reefvision.api.routes.scientific_comparison import router as scientific_comparison_router
from reefvision.api.routes.scientific_data import router as scientific_data_router
from reefvision.api.routes.scientific_heatmaps import router as scientific_heatmaps_router
from reefvision.api.routes.segmentation_deployment import router as segmentation_deployment_router
from reefvision.api.routes.segmentation_evaluation_queue import (
    router as segmentation_evaluation_queue_router,
)
from reefvision.api.routes.segmentation_learning_evaluation import (
    router as segmentation_learning_evaluation_router,
)
from reefvision.api.routes.skeleton_records import router as skeleton_records_router
from reefvision.api.routes.spatial_condition_v14 import router as spatial_condition_router
from reefvision.api.routes.spatial_source_assets_v14 import (
    router as spatial_source_assets_router,
)
from reefvision.api.routes.static_comparison import router as static_comparison_router
from reefvision.api.routes.study_design import router as study_design_router
from reefvision.api.routes.system import router as system_router
from reefvision.api.routes.taxonomy import router as taxonomy_router
from reefvision.api.routes.temporal_reefpose import router as temporal_reefpose_router
from reefvision.api.routes.training import router as training_router
from reefvision.api.routes.video_science import router as video_science_router
from reefvision.api.routes.videos import router as videos_router
from reefvision.api.routes.workflow_graphs import router as workflow_graphs_router
from reefvision.api.routes.workflow_schedule_receipts import (
    router as workflow_schedule_receipt_router,
)
from reefvision.api.routes.workflow_schedules import router as workflow_schedules_router
from reefvision.services.workflow_v1_install import install_workflow_v1_extensions

install_workflow_v1_extensions()

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(acquisition_sources_router)
api_router.include_router(taxonomy_router)
api_router.include_router(monitoring_router)
api_router.include_router(monitoring_summaries_router)
api_router.include_router(environmental_analysis_router)
api_router.include_router(environmental_context_router)
api_router.include_router(field_capture_router)
api_router.include_router(lunar_context_router)
api_router.include_router(scientific_data_router)
api_router.include_router(scientific_heatmaps_router)
api_router.include_router(annotation_comparison_router)
api_router.include_router(current_field_router)
api_router.include_router(computed_aggregate_metrics_router)
api_router.include_router(computed_mask_coverage_router)
api_router.include_router(computed_metrics_router)
api_router.include_router(geographic_movement_analytics_router)
api_router.include_router(geographic_pairwise_router)
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
api_router.include_router(bioacoustics_router)
api_router.include_router(backups_router)
api_router.include_router(projects_router)
api_router.include_router(project_exchange_router)
api_router.include_router(class_operations_router)
api_router.include_router(class_visibility_router)
api_router.include_router(images_router)
api_router.include_router(image_adjustments_router)
api_router.include_router(multispectral_router)
api_router.include_router(domain_shift_router)
api_router.include_router(annotation_imports_router)
api_router.include_router(annotations_router)
api_router.include_router(annotation_aggregates_router)
api_router.include_router(raster_edits_router)
api_router.include_router(measurements_router)
api_router.include_router(scale_label_ocr_router)
api_router.include_router(dataset_versions_router)
api_router.include_router(jobs_router)
api_router.include_router(model_catalog_router)
api_router.include_router(model_runtime_router)
api_router.include_router(paired_models_router)
api_router.include_router(sam2_models_router)
api_router.include_router(models_router)
api_router.include_router(predictions_router)
api_router.include_router(assist_router)
api_router.include_router(quality_control_router)
api_router.include_router(review_queues_router)
api_router.include_router(review_queue_events_router)
api_router.include_router(active_learning_router)
api_router.include_router(pose_active_learning_router)
api_router.include_router(pose_evaluation_router)
api_router.include_router(reefpose_validation_router)
api_router.include_router(temporal_reefpose_router)
api_router.include_router(pose_appearance_router)
api_router.include_router(multimodal_router)
api_router.include_router(pose_identity_tracking_router)
api_router.include_router(pose_biological_measurement_router)
api_router.include_router(pose_schemas_router)
api_router.include_router(pose_training_datasets_router)
api_router.include_router(advanced_providers_router)
api_router.include_router(plugins_router)
api_router.include_router(advanced_provider_execution_router)
api_router.include_router(workflow_graphs_router)
api_router.include_router(workflow_schedule_receipt_router)
api_router.include_router(workflow_schedules_router)
api_router.include_router(spatial_source_assets_router)
api_router.include_router(spatial_condition_router)
api_router.include_router(reviewer_lab_router)
api_router.include_router(reproducibility_router)
api_router.include_router(learning_evaluation_router)
api_router.include_router(longitudinal_monitoring_router)
api_router.include_router(ecology_identity_router)
api_router.include_router(coral_graph_router)
api_router.include_router(ecology_analysis_router)
api_router.include_router(study_design_router)
api_router.include_router(ecology_event_summary_router)
api_router.include_router(scientific_comparison_router)
api_router.include_router(static_comparison_router)
api_router.include_router(research_reports_router)
api_router.include_router(ecology_pose_links_router)
api_router.include_router(model_agreement_router)
api_router.include_router(segmentation_learning_evaluation_router)
api_router.include_router(segmentation_deployment_router)
api_router.include_router(segmentation_evaluation_queue_router)

api_router.include_router(mask_refinements_router)

api_router.include_router(sam_image_proposals_router)

api_router.include_router(project_learning_router)
