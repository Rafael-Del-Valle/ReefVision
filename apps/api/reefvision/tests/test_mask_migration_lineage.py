from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_mask_migrations_retain_the_common_lineage() -> None:
    api_root = Path(__file__).resolve().parents[2]
    config = Config(str(api_root / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)

    assert scripts.get_heads() == ["b20_integrated_0001"]
    combined = scripts.get_revision("b20_integrated_0001")
    assert combined is not None and set(combined.down_revision) == {
        "b20_compute_0001",
        "b20_multimodal_0002",
    }
    compute = scripts.get_revision("b20_compute_0001")
    assert compute is not None and compute.down_revision == "b20_appearance_0001"
    appearance = scripts.get_revision("b20_appearance_0001")
    assert appearance is not None and appearance.down_revision == "b19_registration_0001"
    registration = scripts.get_revision("b19_registration_0001")
    assert registration is not None and registration.down_revision == "b18_spectral_0002"
    spectral = scripts.get_revision("b18_spectral_0002")
    assert spectral is not None and spectral.down_revision == "b18_integrated_0001"
    research = scripts.get_revision("b18_integrated_0001")
    assert research is not None and set(research.down_revision) == {
        "b18_adjust_0001",
        "b18_taxon_0001",
        "b18_audio_0001",
    }
    monitoring = scripts.get_revision("b17_monitor_0003")
    assert monitoring is not None and monitoring.down_revision == "b17_acquire_0002"
    sources = scripts.get_revision("b17_acquire_0002")
    assert sources is not None and sources.down_revision == "b17_workflows_0001"
    schedules = scripts.get_revision("b17_workflows_0001")
    assert schedules is not None and schedules.down_revision == "b16_integrated_0001"
    integrated = scripts.get_revision("b16_integrated_0001")
    assert integrated is not None
    assert set(integrated.down_revision) == {"b15_integrated_0002", "reviewq_0041"}
    recovery = scripts.get_revision("b15_integrated_0002")
    assert recovery is not None and recovery.down_revision == "b15_integrated_0001"
    research = scripts.get_revision("b15_integrated_0001")
    assert research is not None and set(research.down_revision) == {
        "b15_model_0001",
        "b15_review_0001",
        "b15_study_0001",
        "b15_field_0001",
    }
    runtime = scripts.get_revision("b15_model_0001")
    assert runtime is not None and runtime.down_revision == "b14_condition_0041"
    spatial_condition = scripts.get_revision("b14_condition_0041")
    assert spatial_condition is not None
    assert spatial_condition.down_revision == "b14_spatial_0040"
    spatial_metadata = scripts.get_revision("b14_spatial_0040")
    assert spatial_metadata is not None
    assert spatial_metadata.down_revision == "b14_integration_0001"
    integration = scripts.get_revision("b14_integration_0001")
    assert integration is not None
    assert set(integration.down_revision) == {"b13_temporal_0001", "spatial_0039"}
    temporal = scripts.get_revision("b13_temporal_0001")
    assert temporal is not None
    assert temporal.down_revision == "b13_scientific_0001"
    study_assignments = scripts.get_revision("b13_scientific_0001")
    assert study_assignments is not None
    assert study_assignments.down_revision == "b12_integrated_0002"
    reviewed_science = scripts.get_revision("b12_integrated_0002")
    assert reviewed_science is not None
    assert reviewed_science.down_revision == "b12_integrated_0001"
    frozen_image_metadata = scripts.get_revision("b12_identity_0005")
    assert frozen_image_metadata is not None
    assert frozen_image_metadata.down_revision == "b12_identity_0004"
    calibration_evidence = scripts.get_revision("b12_identity_0004")
    assert calibration_evidence is not None
    assert calibration_evidence.down_revision == "b12_identity_0003"
    annotation_evidence = scripts.get_revision("b12_identity_0003")
    assert annotation_evidence is not None
    assert annotation_evidence.down_revision == "b12_identity_0002"
    image_evidence = scripts.get_revision("b12_identity_0002")
    assert image_evidence is not None
    assert image_evidence.down_revision == "b12_identity_0001"
    ecology_identity = scripts.get_revision("b12_identity_0001")
    assert ecology_identity is not None
    assert ecology_identity.down_revision == "0037"
    editable_masks = scripts.get_revision("0015")
    mask_datasets = scripts.get_revision("0016")
    segmentation_proposals = scripts.get_revision("0017")
    semantic_proposals = scripts.get_revision("0018")
    measurement_profiles = scripts.get_revision("0019")
    classification_workflows = scripts.get_revision("0020")
    video_tracking_workflows = scripts.get_revision("0021")
    active_learning_rounds = scripts.get_revision("0022")
    project_exchange_packages = scripts.get_revision("0023")
    srt_primary_georeferencing = scripts.get_revision("0029")
    projection_stability_georeferencing = scripts.get_revision("0030")
    temporal_pose_tracking = scripts.get_revision("0031")
    pose_landmark_schemas = scripts.get_revision("0032")
    skeleton_analysis_revisions = scripts.get_revision("0033")
    behavior_dynamics = scripts.get_revision("0034")
    behavior_models = scripts.get_revision("0035")
    pose_active_learning = scripts.get_revision("0036")
    pose_training_datasets = scripts.get_revision("0037")
    spatial_source_assets = scripts.get_revision("spatial_0038")
    spatial_calibration_reviews = scripts.get_revision("spatial_0039")
    assert editable_masks is not None
    assert editable_masks.down_revision == "53ba400993db"
    assert mask_datasets is not None
    assert mask_datasets.down_revision == "0015"
    assert segmentation_proposals is not None
    assert segmentation_proposals.down_revision == "0016"
    assert semantic_proposals is not None
    assert semantic_proposals.down_revision == "0017"
    assert measurement_profiles is not None
    assert measurement_profiles.down_revision == "0018"
    assert classification_workflows is not None
    assert classification_workflows.down_revision == "0019"
    assert video_tracking_workflows is not None
    assert video_tracking_workflows.down_revision == "0020"
    assert active_learning_rounds is not None
    assert active_learning_rounds.down_revision == "0021"
    assert project_exchange_packages is not None
    assert project_exchange_packages.down_revision == "0022"
    assert srt_primary_georeferencing is not None
    assert srt_primary_georeferencing.down_revision == "0028"
    assert projection_stability_georeferencing is not None
    assert projection_stability_georeferencing.down_revision == "0029"
    assert temporal_pose_tracking is not None
    assert temporal_pose_tracking.down_revision == "0030"
    assert pose_landmark_schemas is not None
    assert pose_landmark_schemas.down_revision == "0031"
    assert skeleton_analysis_revisions is not None
    assert skeleton_analysis_revisions.down_revision == "0032"
    assert behavior_dynamics is not None
    assert behavior_dynamics.down_revision == "0033"
    assert behavior_models is not None
    assert behavior_models.down_revision == "0034"
    assert pose_active_learning is not None
    assert pose_active_learning.down_revision == "0035"
    assert pose_training_datasets is not None
    assert pose_training_datasets.down_revision == "0036"
    assert spatial_source_assets is not None
    assert spatial_source_assets.down_revision == "0037"
    assert spatial_calibration_reviews is not None
    assert spatial_calibration_reviews.down_revision == "spatial_0038"
