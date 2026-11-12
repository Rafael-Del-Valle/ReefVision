from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from reefvision.db.models import (
    Job,
    ModelRegistration,
    PoseEvaluationRun,
    PoseTrainingDataset,
    Project,
)
from reefvision.domain.errors import ConflictError
from reefvision.ml.pose_evaluation import PoseEvaluationProviderExclusion
from reefvision.schemas.pose_evaluation import PoseEvaluationCreateRequest
from reefvision.services.models import ModelService

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


def test_worker_executes_models_and_persists_comparison_report(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from reefvision.jobs.pose_evaluation import process_pose_evaluation_job
    from reefvision.services.pose_evaluation import PoseEvaluationService

    _seed(client)
    created = client.post(
        f"/api/v1/projects/{PROJECT_ID}/pose-evaluation-comparisons",
        json=_payload(),
    ).json()

    def fake_create(
        _service: PoseEvaluationService,
        _project_id: str,
        payload: PoseEvaluationCreateRequest,
        **kwargs: object,
    ) -> object:
        callback = kwargs["progress_callback"]
        assert callable(callback)
        callback(1, 3)
        callback(3, 3)
        model_id = str(payload.model_id)
        return SimpleNamespace(
            id=f"run-{model_id[-1]}",
            model_id=model_id,
            metrics_json={"nme": 0.1, "mean_euclidean_error": 2.0},
            warnings_json=[],
            result_sha256=model_id.replace("-", "")[:64].ljust(64, "0"),
            inference_latency_ms=4.0,
            images_per_second=250.0,
            provenance_json={"provider_name": "reefpose"},
        )

    monkeypatch.setattr(PoseEvaluationService, "create", fake_create)

    assert process_pose_evaluation_job(
        client.app.state.settings,
        client.app.state.session_factory,
        created["id"],
    )
    with client.app.state.session_factory() as session:
        job = session.get(Job, created["id"])
        assert job is not None
        assert job.status == "succeeded"
        assert job.progress_current == job.progress_total == 6
        assert job.deduplication_key is None
        assert job.result_json["schema_version"] == "reefvision-pose-comparison-0001"
        assert job.result_json["evaluation_run_ids"] == ["run-1", "run-2"]
        assert len(job.result_json["models"]) == 2
        assert job.result_json["report_sha256"]

    detail = client.get(f"/api/v1/pose-evaluation-comparisons/{created['id']}")
    assert detail.status_code == 200
    assert detail.json()["result_json"]["report_sha256"]
    exported_json = client.get(
        f"/api/v1/pose-evaluation-comparisons/{created['id']}/export?format=json"
    )
    assert exported_json.status_code == 200
    assert exported_json.json()["schema_version"] == "reefvision-pose-comparison-0001"
    exported_csv = client.get(
        f"/api/v1/pose-evaluation-comparisons/{created['id']}/export?format=csv"
    )
    assert exported_csv.status_code == 200
    assert "row_type,model_id,provider_name" in exported_csv.text
    assert "aggregate" in exported_csv.text


def test_worker_records_provider_exclusion_without_failing_comparison(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from reefvision.jobs.pose_evaluation import process_pose_evaluation_job
    from reefvision.services.pose_evaluation import PoseEvaluationService

    _seed(client)
    created = client.post(
        f"/api/v1/projects/{PROJECT_ID}/pose-evaluation-comparisons",
        json=_payload([MODEL_IDS[0]]),
    ).json()

    def excluded(*_args: object, **_kwargs: object) -> object:
        raise PoseEvaluationProviderExclusion(
            "provider_runtime_unavailable", "Synthetic optional runtime is unavailable"
        )

    monkeypatch.setattr(PoseEvaluationService, "create", excluded)
    assert process_pose_evaluation_job(
        client.app.state.settings,
        client.app.state.session_factory,
        created["id"],
    )
    with client.app.state.session_factory() as session:
        job = session.get(Job, created["id"])
        assert job is not None
        assert job.status == "succeeded"
        assert job.result_json["models"] == []
        assert job.result_json["exclusions"][0]["code"] == "provider_runtime_unavailable"


def test_worker_cooperatively_cancels_and_keeps_partial_report(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from reefvision.jobs.pose_evaluation import process_pose_evaluation_job
    from reefvision.services.pose_evaluation import PoseEvaluationService

    _seed(client)
    created = client.post(
        f"/api/v1/projects/{PROJECT_ID}/pose-evaluation-comparisons",
        json=_payload(),
    ).json()

    calls = 0

    def cancel_during_second(
        _service: PoseEvaluationService,
        _project_id: str,
        payload: PoseEvaluationCreateRequest,
        **kwargs: object,
    ) -> object:
        nonlocal calls
        calls += 1
        if calls == 1:
            model_id = str(payload.model_id)
            return SimpleNamespace(
                id="run-complete",
                model_id=model_id,
                metrics_json={"nme": 0.2},
                warnings_json=[],
                result_sha256="1" * 64,
                inference_latency_ms=5.0,
                images_per_second=200.0,
                provenance_json={},
            )
        with client.app.state.session_factory() as session:
            job = session.get(Job, created["id"])
            assert job is not None
            job.status = "cancel_requested"
            session.commit()
        cancellation_check = kwargs["cancellation_check"]
        assert callable(cancellation_check)
        cancellation_check()
        raise AssertionError("cancellation check must interrupt")

    monkeypatch.setattr(PoseEvaluationService, "create", cancel_during_second)
    assert process_pose_evaluation_job(
        client.app.state.settings,
        client.app.state.session_factory,
        created["id"],
    )
    with client.app.state.session_factory() as session:
        job = session.get(Job, created["id"])
        assert job is not None
        assert job.status == "cancelled"
        assert job.result_json["evaluation_run_ids"] == ["run-complete"]
        assert job.result_json["stage"] == "cancelled"
        assert job.deduplication_key is None


def test_model_with_scientific_evaluation_cannot_be_deleted(client: TestClient) -> None:
    _seed(client)
    with client.app.state.session_factory() as session:
        session.add(
            PoseEvaluationRun(
                project_id=PROJECT_ID,
                model_id=MODEL_IDS[0],
                evaluation_dataset_id=DATASET_ID,
                schema_version="reefpose-evaluation-run-0001",
                status="completed",
                configuration_json={},
                metrics_json={},
                predictions_json=[],
                provenance_json={},
                warnings_json=[],
                result_sha256="9" * 64,
                inference_latency_ms=1.0,
                images_per_second=1.0,
            )
        )
        session.commit()

        with pytest.raises(ConflictError, match="evaluation"):
            ModelService(session, client.app.state.settings).delete_model(MODEL_IDS[0])


def test_later_model_failure_preserves_completed_partial_result(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from reefvision.jobs.pose_evaluation import process_pose_evaluation_job
    from reefvision.services.pose_evaluation import PoseEvaluationService

    _seed(client)
    created = client.post(
        f"/api/v1/projects/{PROJECT_ID}/pose-evaluation-comparisons",
        json=_payload(),
    ).json()
    calls = 0

    def fail_second(
        _service: PoseEvaluationService,
        _project_id: str,
        payload: PoseEvaluationCreateRequest,
        **_kwargs: object,
    ) -> object:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("synthetic second-model failure")
        return SimpleNamespace(
            id="run-first",
            model_id=payload.model_id,
            metrics_json={"nme": 0.2},
            warnings_json=[],
            result_sha256="3" * 64,
            inference_latency_ms=5.0,
            images_per_second=200.0,
            provenance_json={},
        )

    monkeypatch.setattr(PoseEvaluationService, "create", fail_second)
    assert process_pose_evaluation_job(
        client.app.state.settings,
        client.app.state.session_factory,
        created["id"],
    )
    with client.app.state.session_factory() as session:
        job = session.get(Job, created["id"])
        assert job is not None
        assert job.status == "failed"
        assert job.result_json["evaluation_run_ids"] == ["run-first"]
        assert "synthetic second-model failure" in str(job.error_message)
        assert job.deduplication_key is None
