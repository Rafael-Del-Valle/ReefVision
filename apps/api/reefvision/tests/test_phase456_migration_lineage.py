from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_phase456_migrations_form_one_linear_head() -> None:
    api_root = Path(__file__).resolve().parents[2]
    configuration = Config()
    configuration.set_main_option(
        "script_location",
        str(api_root / "migrations"),
    )
    scripts = ScriptDirectory.from_config(configuration)

    assert scripts.get_heads() == ["0024"]
    assert scripts.get_revision("0020").down_revision == "0019"
    assert scripts.get_revision("0021").down_revision == "0020"
    assert scripts.get_revision("0022").down_revision == "0021"
    assert scripts.get_revision("0023").down_revision == "0022"
    assert scripts.get_revision("0024").down_revision == "0023"
