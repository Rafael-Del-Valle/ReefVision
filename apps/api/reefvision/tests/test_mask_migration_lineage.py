from alembic.config import Config
from alembic.script import ScriptDirectory


def test_mask_migrations_remain_in_the_single_linear_head() -> None:
    config = Config("apps/api/alembic.ini")
    scripts = ScriptDirectory.from_config(config)

    assert scripts.get_heads() == ["0032"]
    editable_masks = scripts.get_revision("0015")
    mask_datasets = scripts.get_revision("0016")
    segmentation_proposals = scripts.get_revision("0017")
    semantic_proposals = scripts.get_revision("0018")
    measurement_profiles = scripts.get_revision("0019")
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
