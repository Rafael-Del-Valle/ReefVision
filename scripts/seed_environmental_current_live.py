"""Export an offline current-field fixture for the environmental browser test.

Run from the repository root with apps/api on PYTHONPATH and pass a new
scratch directory. The test's REEFVISION_CURRENT_FIELD_FIXTURE should point to
its environmental-current.reefvision.zip. No credentials or remote data are used.
"""

from __future__ import annotations

import argparse
import os
from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_dir", type=Path, help="New scratch directory for the fixture")
    output_dir = parser.parse_args().output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=False)
    data_dir = output_dir / "source-profile"
    os.environ.update(
        REEFVISION_ENV="test",
        REEFVISION_DATA_DIR=str(data_dir),
        REEFVISION_DATABASE_URL=f"sqlite:///{(data_dir / 'reefvision.db').as_posix()}",
        REEFVISION_BACKGROUND_WORKER_ENABLED="false",
    )

    from reefvision.main import app
    from reefvision.schemas.copernicus import CopernicusRequest
    from reefvision.services.copernicus_environment import CopernicusEnvironmentService
    from reefvision.tests.test_scientific_project_exchange import export_archive

    config = Config(str(Path(__file__).resolve().parents[1] / "apps" / "api" / "alembic.ini"))
    command.upgrade(config, "head")
    observed_at = "2026-04-03T00:00:00Z"
    request = CopernicusRequest.model_validate(
        {
            "dataset_id": "cmems_mod_synthetic_reefvision_current_qa",
            "dataset_version": "fixture",
            "variables": ["uo", "vo"],
            "minimum_longitude": -79.5,
            "maximum_longitude": -79.4,
            "minimum_latitude": 32.5,
            "maximum_latitude": 32.6,
            "minimum_depth": 5,
            "maximum_depth": 5,
            "start_datetime": observed_at,
            "end_datetime": observed_at,
        }
    )
    raw = {
        "dataset_id": request.dataset_id,
        "dataset_version": request.dataset_version,
        "dataset_metadata": {"purpose": "Synthetic software verification"},
        "coordinate_resolution": {"longitude": 0.1, "latitude": 0.1, "time": 3600},
        "toolbox_version": "fixture",
        "samples": [
            {
                "variable": variable,
                "standard_name": standard_name,
                "unit": "m/s",
                "value": value,
                "observed_at": observed_at,
                "latitude": latitude,
                "longitude": longitude,
                "depth_m": 5,
            }
            for latitude in (32.5, 32.6)
            for longitude in (-79.5, -79.4)
            for variable, standard_name, value in (
                ("uo", "eastward_sea_water_velocity", -2.0),
                ("vo", "northward_sea_water_velocity", 0.0),
            )
        ],
    }
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/projects", json={"name": "Synthetic offline currents", "template": "blank"}
        )
        created.raise_for_status()
        project_id = created.json()["id"]
        with app.state.session_factory() as session:
            CopernicusEnvironmentService(
                session,
                app.state.settings,
                fetch=lambda *_: raw,
                now=datetime(2026, 4, 4, tzinfo=UTC),
            ).acquire(project_id, request)
        archive = export_archive(client, app.state.settings, project_id)

    path = output_dir / "environmental-current.reefvision.zip"
    path.write_bytes(archive)
    print(path)


if __name__ == "__main__":
    main()
