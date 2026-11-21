from collections.abc import Iterator
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select

from reefvision.config import Settings
from reefvision.db.models import ExperimentRecord, ModelRegistration, TrainingRun
from reefvision.domain.errors import ValidationError
from reefvision.main import create_app
from reefvision.services.project_exchange_scientific import validate_exchange_records
from reefvision.services.workflow_training import register_workflow_trained_model
from reefvision.tests.test_workflow_pose_registration_phase10 import (
    _fake_pose_model_factory,
    _training_result,
)


def test_exchange_refuses_a_completed_run_linked_to_different_checkpoint_bytes() -> None:
    project, run, model = (str(uuid4()) for _ in range(3))
    sections = {
        "training_runs": [
            {
                "id": run,
                "project_id": project,
                "registered_model_id": model,
                "task": "pose",
                "provider_id": "reefpose",
                "status": "completed",
                "artifact_manifest_json": {"best_checkpoint_sha256": "a" * 64},
            }
        ],
        "models": [
            {
                "id": model,
                "project_id": project,
                "provider_name": "reefpose",
                "task": "pose",
                "sha256": "b" * 64,
            }
        ],
    }
    with pytest.raises(ValidationError, match="Registered model"):
        validate_exchange_records(
            project, sections, {"training_runs": TrainingRun, "models": ModelRegistration}
        )


@pytest.fixture
def migrated_client(test_settings: Settings) -> Iterator[tuple[TestClient, Config]]:
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    config.attributes["configure_logger"] = False
    config.set_main_option("sqlalchemy.url", test_settings.resolved_database_url)
    command.upgrade(config, "b19_registration_0001")
    app = create_app(test_settings)
    with TestClient(app) as client:
        yield client, config
    app.state.engine.dispose()


def test_backfill_requires_unique_project_run_and_consistent_checkpoint_evidence(
    migrated_client: tuple[TestClient, Config],
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, config = migrated_client
    project, _, training = _training_result(client, test_settings, monkeypatch)
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        registered = register_workflow_trained_model(
            session,
            test_settings,
            project_id=str(project["id"]),
            training_payload=training,
            parameters={},
            model_service_factory=_fake_pose_model_factory,
        )
        source = session.get(TrainingRun, training["training_run_id"])
        model = session.get(ModelRegistration, registered["model_id"])
        assert source is not None and model is not None
        base = {column.name: getattr(source, column.name) for column in source.__table__.columns}
        models = {column.name: getattr(model, column.name) for column in model.__table__.columns}
        experiment_ids = list(session.scalars(select(ExperimentRecord.id)))
        primary = source.id
        same_bytes, ambiguous, mismatch = (str(uuid4()) for _ in range(3))
        for run_id in (same_bytes, ambiguous, mismatch):
            session.add(
                TrainingRun(
                    **{
                        **base,
                        "id": run_id,
                        "job_id": None,
                        "registered_model_id": None,
                        "artifact_manifest_json": {},
                    }
                )
            )
        for tag, alias, checksum in (
            ("a", ambiguous, "a" * 64),
            ("b", ambiguous, "b" * 64),
            ("c", mismatch, "c" * 64),
        ):
            metadata = {
                **model.metadata_json,
                "source_training_run_id": alias,
                "source_checkpoint_sha256": checksum,
            }
            if alias == mismatch:
                metadata["source_checkpoint_sha256"] = "d" * 64
            session.add(
                ModelRegistration(
                    **{
                        **models,
                        "id": str(uuid4()),
                        "managed_path": "models/" + tag,
                        "display_name": tag,
                        "sha256": checksum,
                        "metadata_json": metadata,
                    }
                )
            )
        session.commit()
        expected_metadata = {
            m.id: m.metadata_json for m in session.scalars(select(ModelRegistration))
        }

    command.downgrade(config, "b18_spectral_0002")
    assert "registered_model_id" not in {
        c["name"] for c in inspect(app.state.engine).get_columns("training_runs")
    }
    command.upgrade(config, "b19_registration_0001")
    with app.state.session_factory() as session:
        links = dict(session.execute(select(TrainingRun.id, TrainingRun.registered_model_id)).all())
        assert links[primary] == registered["model_id"]
        assert all(links[run_id] is None for run_id in (same_bytes, ambiguous, mismatch))
        assert list(session.scalars(select(ExperimentRecord.id))) == experiment_ids
        assert {
            m.id: m.metadata_json for m in session.scalars(select(ModelRegistration))
        } == expected_metadata
        assert session.connection().exec_driver_sql("PRAGMA foreign_key_check").all() == []
