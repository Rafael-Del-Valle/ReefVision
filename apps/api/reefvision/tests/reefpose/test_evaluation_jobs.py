from __future__ import annotations

import hashlib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from reefvision.db.models import Job, ModelRegistration, PoseTrainingDataset, Project

PROJECT_ID = "11000000-0000-0000-0000-000000000001"
DATASET_ID = "12000000-0000-0000-0000-000000000001"
MODEL_IDS = (
    "13000000-0000-0000-0000-000000000001",
    "13000000-0000-0000-0000-000000000002",
)
SCHEMA_ID = "14000000-0000-0000-0000-000000000001"
SCHEMA_HASH = "a" * 64
DATASET_HASH = "b" * 64


def _model_metadata() -> dict[str, object]:
    return {
        "source_pose_training_dataset_id": "different-training-dataset",
        "source_pose_training_dataset_manifest_sha256": "c" * 64,
        "source_pose_validation_dataset_id": "different-validation-dataset",
        "source_pose_validation_dataset_manifest_sha256": "d" * 64,
        "source_pose_schema_id": SCHEMA_ID,
        "source_pose_schema_revision": 2,
        "source_pose_schema_content_hash": SCHEMA_HASH,
        "reefpose_anatomy_integrity_hash": "e" * 64,
    }


def _seed(client: TestClient) -> None:
    settings = client.app.state.settings
    with client.app.state.session_factory() as session:
        session.add(
            Project(
                id=PROJECT_ID,
                name="Phase 3B project",
                slug="phase-3b-project",
                storage_root="projects/phase-3b",
            )
        )
        for index, model_id in enumerate(MODEL_IDS, start=1):
            relative_path = f"projects/phase-3b/models/model-{index}.pt"
            checkpoint = settings.resolved_data_dir / relative_path
            checkpoint.parent.mkdir(parents=True, exist_ok=True)
            checkpoint.write_bytes(f"checkpoint-{index}".encode())
            content = checkpoint.read_bytes()
            session.add(
                ModelRegistration(
                    id=model_id,
                    project_id=PROJECT_ID,
                    purpose="detector",
                    display_name=f"ReefPose {index}",
                    source_filename=f"model-{index}.pt",
                    managed_path=relative_path,
                    sha256=hashlib.sha256(content).hexdigest(),
                    file_size_bytes=len(content),
                    framework="reefpose",
                    task="pose",
                    provider_name="reefpose",
                    provider_version="1",
                    class_map_json={},
                    metadata_json=_model_metadata(),
                )
            )
        session.add(
            PoseTrainingDataset(
                id=DATASET_ID,
                project_id=PROJECT_ID,
                source_round_id="15000000-0000-0000-0000-000000000001",
                name="Held-out verified fish",
                status="complete",
                pose_schema_id=SCHEMA_ID,
                pose_schema_revision=2,
                pose_schema_content_hash=SCHEMA_HASH,
                source_selection_sha256="f" * 64,
                source_retraining_manifest_sha256="1" * 64,
                manifest_json={"schema_version": "pose-training-dataset-manifest-0001"},
                manifest_sha256=DATASET_HASH,
                item_count=3,
            )
        )
        session.commit()


def _payload(model_ids: list[str] | None = None) -> dict[str, object]:
    return {
        "model_ids": model_ids or list(MODEL_IDS),
        "evaluation_dataset_id": DATASET_ID,
        "device": "cpu",
        "pck_thresholds": [0.05, 0.1, 0.2],
        "calibration_threshold": 0.1,
        "calibration_bins": 10,
        "confidence_thresholds": [0.0, 0.5, 0.9],
    }


def test_submit_comparison_is_async_durable_and_order_independently_deduplicated(
    client: TestClient,
) -> None:
    _seed(client)

    created = client.post(
        f"/api/v1/projects/{PROJECT_ID}/pose-evaluation-comparisons",
        json=_payload(),
    )
    assert created.status_code == 202, created.text
    job = created.json()
    assert job["job_type"] == "pose_evaluation"
    assert job["status"] == "queued"
    assert job["progress_current"] == 0
    assert job["progress_total"] == 6
    assert job["request_json"]["schema_version"] == "pose-evaluation-comparison-0001"
    assert job["request_json"]["model_ids"] == list(MODEL_IDS)
    assert job["request_json"]["evaluation_dataset_id"] == DATASET_ID
    assert len(job["request_json"]["request_sha256"]) == 64

    duplicate = client.post(
        f"/api/v1/projects/{PROJECT_ID}/pose-evaluation-comparisons",
        json=_payload(list(reversed(MODEL_IDS))),
    )
    assert duplicate.status_code == 202, duplicate.text
    assert duplicate.json()["id"] == job["id"]

    with client.app.state.session_factory() as session:
        jobs = list(session.scalars(select(Job).where(Job.job_type == "pose_evaluation")))
        assert len(jobs) == 1
        assert jobs[0].deduplication_key == job["request_json"]["request_sha256"]


def test_comparison_jobs_are_paginated_and_project_scoped(client: TestClient) -> None:
    _seed(client)
    created = client.post(
        f"/api/v1/projects/{PROJECT_ID}/pose-evaluation-comparisons",
        json=_payload(),
    )
    assert created.status_code == 202, created.text

    response = client.get(
        f"/api/v1/projects/{PROJECT_ID}/pose-evaluation-comparisons?limit=1&offset=0"
    )
    assert response.status_code == 200, response.text
    page = response.json()
    assert page["total"] == 1
    assert page["limit"] == 1
    assert page["offset"] == 0
    assert [item["id"] for item in page["items"]] == [created.json()["id"]]


def test_concurrent_duplicate_submission_returns_the_winning_job(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed(client)
    original_commit = Session.commit
    raced = False
    winning_job_id: str | None = None

    def commit_with_competitor(session: Session) -> None:
        nonlocal raced, winning_job_id
        pending = next(
            (
                item
                for item in session.new
                if isinstance(item, Job) and item.job_type == "pose_evaluation"
            ),
            None,
        )
        if pending is not None and not raced:
            raced = True
            with client.app.state.session_factory() as competitor:
                winner = Job(
                    project_id=pending.project_id,
                    job_type=pending.job_type,
                    deduplication_key=pending.deduplication_key,
                    status="queued",
                    progress_current=0,
                    progress_total=pending.progress_total,
                    request_json=dict(pending.request_json),
                    result_json={"stage": "queued", "evaluation_run_ids": []},
                )
                competitor.add(winner)
                original_commit(competitor)
                competitor.refresh(winner)
                winning_job_id = winner.id
        original_commit(session)

    monkeypatch.setattr(Session, "commit", commit_with_competitor)
    response = client.post(
        f"/api/v1/projects/{PROJECT_ID}/pose-evaluation-comparisons",
        json=_payload(),
    )

    assert response.status_code == 202, response.text
    assert response.json()["id"] == winning_job_id
    with client.app.state.session_factory() as session:
        jobs = list(session.scalars(select(Job).where(Job.job_type == "pose_evaluation")))
        assert len(jobs) == 1


def test_job_deduplication_key_is_database_enforced(client: TestClient) -> None:
    _seed(client)
    with client.app.state.session_factory() as session:
        session.add_all(
            [
                Job(
                    project_id=PROJECT_ID,
                    job_type="pose_evaluation",
                    deduplication_key="8" * 64,
                    request_json={},
                ),
                Job(
                    project_id=PROJECT_ID,
                    job_type="pose_evaluation",
                    deduplication_key="8" * 64,
                    request_json={},
                ),
            ]
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_comparison_submission_rejects_duplicate_models_schema_mismatch_and_leakage(
    client: TestClient,
) -> None:
    _seed(client)

    duplicate = client.post(
        f"/api/v1/projects/{PROJECT_ID}/pose-evaluation-comparisons",
        json=_payload([MODEL_IDS[0], MODEL_IDS[0]]),
    )
    assert duplicate.status_code == 422

    with client.app.state.session_factory() as session:
        model = session.get(ModelRegistration, MODEL_IDS[1])
        assert model is not None
        model.metadata_json = {
            **dict(model.metadata_json),
            "source_pose_schema_content_hash": "9" * 64,
        }
        session.commit()
    mismatch = client.post(
        f"/api/v1/projects/{PROJECT_ID}/pose-evaluation-comparisons",
        json=_payload(),
    )
    assert mismatch.status_code == 400
    assert "schema" in mismatch.json()["detail"].lower()

    with client.app.state.session_factory() as session:
        model = session.get(ModelRegistration, MODEL_IDS[1])
        assert model is not None
        model.metadata_json = {
            **_model_metadata(),
            "source_pose_training_dataset_id": DATASET_ID,
        }
        session.commit()
    leakage = client.post(
        f"/api/v1/projects/{PROJECT_ID}/pose-evaluation-comparisons",
        json=_payload(),
    )
    assert leakage.status_code == 400
    assert "leakage" in leakage.json()["detail"].lower()


def test_comparison_submission_rejects_foreign_or_non_pose_models(client: TestClient) -> None:
    _seed(client)
    with client.app.state.session_factory() as session:
        model = session.get(ModelRegistration, MODEL_IDS[1])
        assert model is not None
        model.task = "detect"
        session.commit()

    response = client.post(
        f"/api/v1/projects/{PROJECT_ID}/pose-evaluation-comparisons",
        json=_payload(),
    )
    assert response.status_code == 400
    assert "pose" in response.json()["detail"].lower()
