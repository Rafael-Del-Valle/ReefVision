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

    assert scripts.get_heads() == ["0034"]
    assert scripts.get_revision("0020").down_revision == "0019"
    assert scripts.get_revision("0021").down_revision == "0020"
    assert scripts.get_revision("0022").down_revision == "0021"
    assert scripts.get_revision("0023").down_revision == "0022"
    assert scripts.get_revision("0024").down_revision == "0023"
    assert scripts.get_revision("0025").down_revision == "0024"
    assert scripts.get_revision("0026").down_revision == "0025"
    assert scripts.get_revision("0027").down_revision == "0026"
    assert scripts.get_revision("0028").down_revision == "0027"
    assert scripts.get_revision("0029").down_revision == "0028"
    assert scripts.get_revision("0030").down_revision == "0029"
    assert scripts.get_revision("0031").down_revision == "0030"
    assert scripts.get_revision("0032").down_revision == "0031"
    assert scripts.get_revision("0033").down_revision == "0032"
    assert scripts.get_revision("0034").down_revision == "0033"
