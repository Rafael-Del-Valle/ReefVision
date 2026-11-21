from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from reefvision.domain.pose_appearance import calibration, rank, rates


def test_appearance_migration_adds_and_removes_only_its_study_tables(tmp_path, monkeypatch):
    monkeypatch.setenv("REEFVISION_DATA_DIR", str(tmp_path))
    from reefvision.config import Settings

    url = Settings(data_dir=tmp_path).resolved_database_url
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "b19_registration_0001")
    engine = create_engine(url)
    try:
        original = set(inspect(engine).get_table_names())
        command.upgrade(config, "b20_appearance_0001")
        assert set(inspect(engine).get_table_names()) - original == {
            "pose_appearance_studies",
            "pose_appearance_decisions",
        }
        command.downgrade(config, "b19_registration_0001")
        assert set(inspect(engine).get_table_names()) == original
    finally:
        engine.dispose()


def test_threshold_is_fit_on_development_and_a_close_runner_up_requires_review():
    threshold = calibration([0.95, 0.85], [0.32, 0.70], maximum_false_rate=0)
    assert 0.70 < threshold <= 0.85
    assert rank([("a", 0.96), ("b", 0.95)], threshold, 0.02)["state"] == "ambiguous"
    assert rank([("a", 0.62)], threshold, 0.02)["state"] == "abstained"
    assert rank([("a", 0.93), ("b", 0.61)], threshold, 0.02)["selected"] == "a"
    assert rank([("a", 0.95), ("b", 0.95)], threshold, 0)["selected"] is None
    with pytest.raises(ValueError):
        calibration([], [0.1], maximum_false_rate=0)


def test_false_and_missed_link_denominators_include_abstentions_and_wrong_winners():
    scored = rates(
        [
            ({"a"}, {"a", "b"}, "a"),
            ({"a"}, {"a", "b"}, "b"),
            ({"a"}, {"a", "b"}, None),
            (set(), {"a", "b"}, "b"),
        ]
    )
    assert scored["impostor_pairs"] == 5
    assert scored["false_links"] == 2
    assert scored["false_match_rate"] == pytest.approx(2 / 5)
    assert scored["genuine_pairs"] == 3
    assert scored["missed_links"] == 2
    assert scored["missed_match_rate"] == pytest.approx(2 / 3)
    assert rates([])["false_match_rate"] is None
