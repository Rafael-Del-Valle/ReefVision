"""Append-only ecological identity chronology: API, saved workflows and replay."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import select

from reefvision.db.models.ecology_identity_revision import EcologyIdentityRevision
from reefvision.domain.ecology_lineage_policy import (
    require_chronological_ecological_identity_revisions,
)
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.schemas.ecology_identity import EcologyIdentityRegistryResponse
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_ecology_identity_registry_1_2 import _register


def _history(client: TestClient, project_id: str) -> str:
    base = f"/api/v1/projects/{project_id}/ecology"
    assert _register(client, project_id, "colony-16").status_code == 201
    revised = client.post(
        f"{base}/organisms/colony-16/revisions",
        json={"expected_revision": 1, "kind": "colony", "reason": "Second identity revision"},
    )
    assert revised.status_code == 201, revised.text
    return base


def _run_saved_registry(client: TestClient, project_id: str) -> tuple[bool, dict]:
    graph = {
        "graph_id": "identity-chronology-1-2",
        "name": "Chronological biological identity audit",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "identity", "node_type": "ecology_identity_registry_source"},
        ],
        "edges": [
            {
                "edge_id": "project-identity",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "identity",
                "target_port_id": "project",
            }
        ],
    }
    saved = client.post(
        f"/api/v1/projects/{project_id}/workflow-graphs",
        json={"graph": graph, "create_new_revision": True},
    )
    assert saved.status_code == 201, saved.text
    queued = client.post(
        f"/api/v1/projects/{project_id}/workflow-runs",
        json={"graph_record_id": saved.json()["id"]},
    )
    assert queued.status_code == 202, queued.text
    app = cast(FastAPI, client.app)
    succeeded = process_workflow_run_job(
        app.state.settings, app.state.session_factory, str(queued.json()["job_id"])
    )
    detail = client.get(f"/api/v1/workflow-runs/{queued.json()['id']}")
    assert detail.status_code == 200, detail.text
    return succeeded, detail.json()


def test_imported_reverse_chronology_blocks_writes_and_saved_workflow(
    client: TestClient,
) -> None:
    project_id = str(create_project(client, "Reversed coral identity chronology")["id"])
    base = _history(client, project_id)
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        rows = list(
            session.scalars(
                select(EcologyIdentityRevision)
                .where(EcologyIdentityRevision.project_id == project_id)
                .order_by(EcologyIdentityRevision.revision)
            )
        )
        assert len(rows) == 2
        rows[0].created_at = rows[1].created_at + timedelta(days=1)
        session.commit()
    invalid = client.get(f"{base}/identity-registry")
    assert invalid.status_code == 400, invalid.text
    assert "revision timestamps are not chronological" in invalid.text
    assert _register(client, project_id, "colony-20").status_code == 400
    rejected = client.post(
        f"{base}/organisms/colony-16/revisions",
        json={"expected_revision": 2, "kind": "colony", "reason": "Reject corrupted history"},
    )
    assert rejected.status_code == 400, rejected.text
    succeeded, detail = _run_saved_registry(client, project_id)
    assert succeeded is False
    assert detail["run"]["status"] == "failed"
    assert "revision timestamps are not chronological" in detail["run"]["error_message"]
    assert not any(row["data_type"] == "ecology_identity_registry" for row in detail["artifacts"])


def test_equal_revision_timestamps_preserve_unverified_workflow_artifact(
    client: TestClient,
) -> None:
    project_id = str(create_project(client, "Equal UTC revision timestamps")["id"])
    base = _history(client, project_id)
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        rows = list(
            session.scalars(
                select(EcologyIdentityRevision)
                .where(EcologyIdentityRevision.project_id == project_id)
                .order_by(EcologyIdentityRevision.revision)
            )
        )
        rows[0].created_at = rows[1].created_at
        session.commit()
    response = client.get(f"{base}/identity-registry")
    assert response.status_code == 200, response.text
    succeeded, detail = _run_saved_registry(client, project_id)
    assert succeeded is True
    assert detail["run"]["status"] == "succeeded"
    artifacts = [
        row for row in detail["artifacts"] if row["data_type"] == "ecology_identity_registry"
    ]
    assert len(artifacts) == 1
    assert artifacts[0]["payload_json"] == response.json()
    assert artifacts[0]["payload_json"]["review_gate"] == "scientist_review_required"
    assert artifacts[0]["payload_json"]["evidence_level"] == "registered_unverified"


def test_resigned_history_replay_rejects_reversed_timestamps(client: TestClient) -> None:
    project_id = str(create_project(client, "Re-fingerprinted identity chronology")["id"])
    base = _history(client, project_id)
    response = client.get(f"{base}/identity-registry")
    assert response.status_code == 200, response.text
    changed = deepcopy(response.json())
    EcologyIdentityRegistryResponse.model_validate(changed)
    history = sorted(changed["identity_history"], key=lambda row: row["revision"])
    latest_time = datetime.fromisoformat(history[1]["created_at"].replace("Z", "+00:00"))
    history[0]["created_at"] = (latest_time + timedelta(days=1)).isoformat()
    changed["history_sha256"] = canonical_json_sha256(
        {
            "algorithm_version": "ecology-identity-history-0001",
            "project_id": project_id,
            "revisions": [
                {
                    **{
                        field: row[field]
                        for field in (
                            "id",
                            "organism_key",
                            "revision",
                            "kind",
                            "parent_colony_key",
                            "experimental_unit_type",
                            "experimental_unit_id",
                            "reason",
                        )
                    },
                    "created_at": datetime.fromisoformat(
                        row["created_at"].replace("Z", "+00:00")
                    ).isoformat(),
                }
                for row in changed["identity_history"]
            ],
        }
    )
    with pytest.raises(PydanticValidationError, match="revision timestamps are not chronological"):
        EcologyIdentityRegistryResponse.model_validate(changed)


def test_chronology_normalizes_timezone_offsets() -> None:
    first = SimpleNamespace(
        organism_key="coral-A",
        revision=1,
        created_at=datetime(2026, 1, 1, 0, 0, tzinfo=timezone(timedelta(hours=-5))),
    )
    second = SimpleNamespace(
        organism_key="coral-A",
        revision=2,
        created_at=datetime(2026, 1, 1, 6, 0, tzinfo=UTC),
    )
    require_chronological_ecological_identity_revisions([second, first])
    second.created_at = datetime(2026, 1, 1, 4, 59, tzinfo=UTC)
    with pytest.raises(ValueError, match="revision timestamps are not chronological"):
        require_chronological_ecological_identity_revisions([first, second])


def test_independent_organism_revision_clocks_do_not_require_global_order() -> None:
    """Separate specimens have independent append-only revision chronologies."""
    first_a = SimpleNamespace(
        organism_key="coral-A", revision=1, created_at=datetime(2026, 2, 3, tzinfo=UTC)
    )
    second_a = SimpleNamespace(
        organism_key="coral-A", revision=2, created_at=datetime(2026, 2, 4, tzinfo=UTC)
    )
    first_b = SimpleNamespace(
        organism_key="coral-B", revision=1, created_at=datetime(2026, 1, 1, tzinfo=UTC)
    )
    second_b = SimpleNamespace(
        organism_key="coral-B", revision=2, created_at=datetime(2026, 1, 2, tzinfo=UTC)
    )
    require_chronological_ecological_identity_revisions([second_a, second_b, first_a, first_b])
    second_b.created_at = datetime(2025, 12, 31, tzinfo=UTC)
    with pytest.raises(ValueError, match="revision timestamps are not chronological"):
        require_chronological_ecological_identity_revisions([first_a, second_a, first_b, second_b])
