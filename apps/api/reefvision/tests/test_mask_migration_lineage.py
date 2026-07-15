from alembic.config import Config
from alembic.script import ScriptDirectory


def test_mask_migrations_form_one_linear_head() -> None:
    config = Config("apps/api/alembic.ini")
    scripts = ScriptDirectory.from_config(config)

    assert scripts.get_heads() == ["0016"]
    editable_masks = scripts.get_revision("0015")
    assert editable_masks is not None
    assert editable_masks.down_revision == "53ba400993db"
