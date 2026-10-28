from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_mask_migrations_form_one_linear_head() -> None:
    api_root = Path(__file__).resolve().parents[2]
    config = Config(str(api_root / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)

    assert scripts.get_heads() == ["0039"]
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
    computed_metrics = scripts.get_revision("0039")
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
    assert computed_metrics.down_revision == "0038"
