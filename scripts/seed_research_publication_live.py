"""Seed a disposable 1.3 profile for the held-out comparison publication browser test."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pytest import MonkeyPatch


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data_dir", type=Path, help="A new directory for the synthetic fixture.")
    args = parser.parse_args()
    data_dir = args.data_dir.resolve()
    data_dir.mkdir(parents=True, exist_ok=False)
    os.environ.update(
        REEFVISION_ENV="test",
        REEFVISION_DATA_DIR=str(data_dir),
        REEFVISION_DATABASE_URL=f"sqlite:///{(data_dir / 'reefvision.db').as_posix()}",
        REEFVISION_BACKGROUND_WORKER_ENABLED="false",
    )

    from reefvision.config import clear_settings_cache
    from reefvision.main import create_app
    from reefvision.tests.test_scientific_comparison_1_3 import seed_comparison_fixture

    config = Config(str(Path(__file__).resolve().parents[1] / "apps" / "api" / "alembic.ini"))
    command.upgrade(config, "head")
    clear_settings_cache()
    with TestClient(create_app()) as client, MonkeyPatch.context() as patch:
        project_id, first, second = seed_comparison_fixture(client, patch)
    output = data_dir / "research-report-fixture.json"
    output.write_text(
        json.dumps({"project_id": project_id, "report_ids": [first, second]}),
        encoding="utf-8",
    )
    print(output)


if __name__ == "__main__":
    main()
