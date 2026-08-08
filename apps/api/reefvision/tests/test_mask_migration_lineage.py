from alembic.config import Config
from alembic.script import ScriptDirectory


def test_mask_migrations_form_one_linear_head() -> None:
    config = Config("apps/api/alembic.ini")
    scripts = ScriptDirectory.from_config(config)

    assert scripts.get_heads() == ["0023"]
    editable_masks = scripts.get_revision("0015")
    mask_datasets = scripts.get_revision("0016")
    segmentation_proposals = scripts.get_revision("0017")
    semantic_proposals = scripts.get_revision("0018")
    measurement_profiles = scripts.get_revision("0019")
    classification_workflows = scripts.get_revision("0020")
    video_tracking_workflows = scripts.get_revision("0021")
    active_learning_rounds = scripts.get_revision("0022")
    project_exchange_packages = scripts.get_revision("0023")
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
