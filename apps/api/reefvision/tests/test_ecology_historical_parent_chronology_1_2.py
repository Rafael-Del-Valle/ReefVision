"""Historical parent-colony chronology: standalone, saved workflow, replay."""

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
    require_current_ecological_parent_registration,
    require_historical_ecological_parent_registration,
)
from reefvision.schemas.ecology_identity import EcologyIdentityRegistryResponse, EcologyIdentityRow
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_ecology_identity_registry_1_2 import _register
from reefvision.tests.test_ecology_identity_revision_chronology_1_2 import (
    _run_saved_registry,
)


def _parent_and_fragment(client: TestClient, project_id: str) -> str:
    base = f"/api/v1/projects/{project_id}/ecology"
    assert _register(client, project_id, "parent-A").status_code == 201
    fragment = _register(
        client,
        project_id,
        "fragment-A",
        "fragment",
        parent_colony_key="parent-A",
    )
    assert fragment.status_code == 201, fragment.text
    return base


def test_imported_fragment_predating_parent_fails_api_writes_and_saved_graph(
    client: TestClient,
) -> None:
    project_id = str(create_project(client, "Parent registration chronology")["id"])
    base = _parent_and_fragment(client, project_id)
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        records = list(
            session.scalars(
                select(EcologyIdentityRevision).where(
                    EcologyIdentityRevision.project_id == project_id
                )
            )
        )
        parent = next(row for row in records if row.organism_key == "parent-A")
        fragment = next(row for row in records if row.organism_key == "fragment-A")
        fragment.created_at = parent.created_at - timedelta(seconds=1)
        session.commit()

    invalid = client.get(f"{base}/identity-registry")
    assert invalid.status_code == 400, invalid.text
    assert "not registered before fragment" in invalid.text
    assert _register(client, project_id, "parent-B").status_code == 400

    succeeded, detail = _run_saved_registry(client, project_id)
    assert succeeded is False
    assert detail["run"]["status"] == "failed"
    assert "not registered before fragment" in detail["run"]["error_message"]
    assert not any(row["data_type"] == "ecology_identity_registry" for row in detail["artifacts"])


def test_parent_reclassified_to_colony_before_fragment_preserves_workflow(
    client: TestClient,
) -> None:
    project_id = str(create_project(client, "Legitimate parent identity correction")["id"])
    base = f"/api/v1/projects/{project_id}/ecology"
    assert _register(client, project_id, "parent-A", "individual").status_code == 201
    revised = client.post(
        f"{base}/organisms/parent-A/revisions",
        json={
            "expected_revision": 1,
            "kind": "colony",
            "reason": "Reviewed correction before fragment registration",
        },
    )
    assert revised.status_code == 201, revised.text
    fragment = _register(
        client,
        project_id,
        "fragment-A",
        "fragment",
        parent_colony_key="parent-A",
    )
    assert fragment.status_code == 201, fragment.text

    response = client.get(f"{base}/identity-registry")
    assert response.status_code == 200, response.text
    succeeded, detail = _run_saved_registry(client, project_id)
    assert succeeded is True
    artifacts = [
        row for row in detail["artifacts"] if row["data_type"] == "ecology_identity_registry"
    ]
    assert len(artifacts) == 1
    assert artifacts[0]["payload_json"] == response.json()
    assert artifacts[0]["payload_json"]["review_gate"] == "scientist_review_required"
    assert artifacts[0]["payload_json"]["evidence_level"] == "registered_unverified"


def test_resigned_registry_rejects_fragment_predating_parent(client: TestClient) -> None:
    project_id = str(create_project(client, "Resigned parent chronology")["id"])
    base = _parent_and_fragment(client, project_id)
    response = client.get(f"{base}/identity-registry")
    assert response.status_code == 200, response.text
    changed = deepcopy(response.json())
    EcologyIdentityRegistryResponse.model_validate(changed)

    history = changed["identity_history"]
    parent = next(row for row in history if row["organism_key"] == "parent-A")
    fragment = next(row for row in history if row["organism_key"] == "fragment-A")
    parent_time = datetime.fromisoformat(parent["created_at"].replace("Z", "+00:00"))
    fragment["created_at"] = (parent_time - timedelta(days=1)).isoformat()
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
                for row in history
            ],
        }
    )
    with pytest.raises(PydanticValidationError, match="not registered before fragment"):
        EcologyIdentityRegistryResponse.model_validate(changed)


def test_resigned_registry_rejects_later_parent_reclassification(
    client: TestClient,
) -> None:
    """A valid historical link must not hide an invalid latest parent kind."""
    project_id = str(create_project(client, "Re-signed latest parent lineage")["id"])
    base = _parent_and_fragment(client, project_id)
    response = client.get(f"{base}/identity-registry")
    assert response.status_code == 200, response.text
    source = response.json()
    parent = next(row for row in source["identities"] if row["organism_key"] == "parent-A")
    fragment = next(row for row in source["identities"] if row["organism_key"] == "fragment-A")

    # Simulate an imported revision *after* the fragment was linked. Historical
    # parent-at-link checks still pass; the current parent is now an individual.
    revised_parent = deepcopy(parent)
    revised_parent["id"] = "imported-parent-revision-2"
    revised_parent["revision"] = 2
    revised_parent["kind"] = "individual"
    revised_parent["reason"] = "Imported later parent reclassification"
    fragment_time = datetime.fromisoformat(fragment["created_at"].replace("Z", "+00:00"))
    revised_parent["created_at"] = (fragment_time + timedelta(days=1)).isoformat()
    latest = [
        revised_parent if row["organism_key"] == "parent-A" else row for row in source["identities"]
    ]
    history = sorted(
        [*source["identity_history"], revised_parent],
        key=lambda row: (row["organism_key"], row["revision"]),
    )
    snapshot_sha256 = canonical_json_sha256(
        {
            "schema_version": "ecology-identity-registry-0001",
            "project_id": project_id,
            "identities": [
                {
                    field: row[field]
                    for field in (
                        "id",
                        "organism_key",
                        "revision",
                        "kind",
                        "parent_colony_key",
                        "experimental_unit_type",
                        "experimental_unit_id",
                    )
                }
                for row in latest
            ],
        }
    )
    history_sha256 = canonical_json_sha256(
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
                for row in history
            ],
        }
    )
    forged = {
        "project_id": project_id,
        "identities": latest,
        "snapshot_sha256": snapshot_sha256,
        "identity_history": history,
        "history_revision_count": len(history),
        "history_sha256": history_sha256,
        "evidence_level": "registered_unverified",
        "review_gate": "scientist_review_required",
    }
    with pytest.raises(PydanticValidationError, match="invalid parent-colony link"):
        EcologyIdentityRegistryResponse.model_validate(forged)


def test_parent_chronology_uses_utc_instead_of_wall_clock_order() -> None:
    parent = SimpleNamespace(
        organism_key="parent-A",
        revision=1,
        kind="colony",
        parent_colony_key=None,
        created_at=datetime(2026, 1, 1, 5, 0, tzinfo=UTC),
    )
    fragment = SimpleNamespace(
        organism_key="fragment-A",
        revision=1,
        kind="fragment",
        parent_colony_key="parent-A",
        created_at=datetime(2026, 1, 1, 0, 0, tzinfo=timezone(timedelta(hours=-5))),
    )
    require_historical_ecological_parent_registration([fragment, parent])
    fragment.created_at -= timedelta(seconds=1)
    with pytest.raises(ValueError, match="not registered before fragment"):
        require_historical_ecological_parent_registration([parent, fragment])


def test_pydantic_identity_rows_share_current_and_historical_parent_policy() -> None:
    """Both lineage validators must accept the typed persisted registry rows."""
    recorded = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    parent = EcologyIdentityRow(
        id="parent-record",
        project_id="project-A",
        organism_key="parent-A",
        revision=1,
        kind="colony",
        parent_colony_key=None,
        experimental_unit_type=None,
        experimental_unit_id=None,
        reason="Registered parent colony",
        created_at=recorded,
    )
    fragment = EcologyIdentityRow(
        id="fragment-record",
        project_id="project-A",
        organism_key="fragment-A",
        revision=1,
        kind="fragment",
        parent_colony_key="parent-A",
        experimental_unit_type=None,
        experimental_unit_id=None,
        reason="Registered linked fragment",
        created_at=recorded + timedelta(minutes=1),
    )
    require_current_ecological_parent_registration([parent, fragment])
    require_historical_ecological_parent_registration([parent, fragment])

    # A later imported kind change cannot be hidden by the same row contract.
    invalid_parent = parent.model_copy(update={"kind": "individual"})
    with pytest.raises(ValueError, match="invalid parent-colony link"):
        require_current_ecological_parent_registration([invalid_parent, fragment])
    with pytest.raises(ValueError, match="not a colony at fragment revision"):
        require_historical_ecological_parent_registration([invalid_parent, fragment])


def test_equal_parent_timestamps_with_conflicting_kinds_are_ambiguous() -> None:
    """Timestamp ties cannot prove parent-colony state at fragment linkage."""
    recorded = datetime(2026, 4, 3, 12, 0, tzinfo=UTC)
    parent_first = SimpleNamespace(
        organism_key="parent-A",
        revision=1,
        kind="individual",
        parent_colony_key=None,
        created_at=recorded,
    )
    parent_second = SimpleNamespace(
        organism_key="parent-A",
        revision=2,
        kind="colony",
        parent_colony_key=None,
        created_at=recorded,
    )
    fragment = SimpleNamespace(
        organism_key="fragment-A",
        revision=1,
        kind="fragment",
        parent_colony_key="parent-A",
        created_at=recorded,
    )
    with pytest.raises(ValueError, match="ambiguous at fragment revision"):
        require_historical_ecological_parent_registration([fragment, parent_second, parent_first])

    # Multiple same-instant revisions agreeing that the parent is a colony
    # are not ambiguous, preserving SQLite timestamp-precision compatibility.
    parent_first.kind = "colony"
    require_historical_ecological_parent_registration([fragment, parent_second, parent_first])


def test_same_instant_parent_state_conflict_uses_utc_not_local_wall_time() -> None:
    """Offset-equivalent parent revisions must not invent a colony-at-link state."""
    parent_first = SimpleNamespace(
        organism_key="parent-A",
        revision=1,
        kind="individual",
        parent_colony_key=None,
        created_at=datetime(2026, 4, 3, 12, 0, tzinfo=UTC),
    )
    parent_second = SimpleNamespace(
        organism_key="parent-A",
        revision=2,
        kind="colony",
        parent_colony_key=None,
        created_at=datetime(2026, 4, 3, 8, 0, tzinfo=timezone(timedelta(hours=-4))),
    )
    fragment = SimpleNamespace(
        organism_key="fragment-A",
        revision=1,
        kind="fragment",
        parent_colony_key="parent-A",
        created_at=datetime(2026, 4, 3, 14, 0, tzinfo=timezone(timedelta(hours=2))),
    )
    with pytest.raises(ValueError, match="ambiguous at fragment revision"):
        require_historical_ecological_parent_registration([parent_first, parent_second, fragment])

    # Identical colony states at the same actual UTC instant are acceptable.
    parent_first.kind = "colony"
    require_historical_ecological_parent_registration([parent_first, parent_second, fragment])


def test_imported_ambiguous_parent_timestamp_blocks_api_and_saved_graph(
    client: TestClient,
) -> None:
    project_id = str(create_project(client, "Ambiguous historical colony state")["id"])
    base = f"/api/v1/projects/{project_id}/ecology"
    assert _register(client, project_id, "parent-A", "individual").status_code == 201
    revised = client.post(
        f"{base}/organisms/parent-A/revisions",
        json={
            "expected_revision": 1,
            "kind": "colony",
            "reason": "Reviewed parent colony correction",
        },
    )
    assert revised.status_code == 201, revised.text
    assert (
        _register(
            client,
            project_id,
            "fragment-A",
            "fragment",
            parent_colony_key="parent-A",
        ).status_code
        == 201
    )
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        rows = list(
            session.scalars(
                select(EcologyIdentityRevision).where(
                    EcologyIdentityRevision.project_id == project_id
                )
            )
        )
        assert len(rows) == 3
        parent_rows = sorted(
            (row for row in rows if row.organism_key == "parent-A"),
            key=lambda row: row.revision,
        )
        fragment = next(row for row in rows if row.organism_key == "fragment-A")
        parent_rows[0].created_at = parent_rows[1].created_at
        fragment.created_at = parent_rows[1].created_at
        session.commit()

    response = client.get(f"{base}/identity-registry")
    assert response.status_code == 400, response.text
    assert "ambiguous at fragment revision" in response.text
    assert _register(client, project_id, "another-colony").status_code == 400
    rejected_revision = client.post(
        f"{base}/organisms/parent-A/revisions",
        json={
            "expected_revision": 2,
            "kind": "colony",
            "reason": "Must not append to an ambiguous historical parent state",
        },
    )
    assert rejected_revision.status_code == 400, rejected_revision.text
    assert "ambiguous at fragment revision" in rejected_revision.text

    succeeded, detail = _run_saved_registry(client, project_id)
    assert succeeded is False
    assert detail["run"]["status"] == "failed"
    assert "ambiguous at fragment revision" in detail["run"]["error_message"]
    assert not any(row["data_type"] == "ecology_identity_registry" for row in detail["artifacts"])
    with app.state.session_factory() as session:
        unchanged = list(
            session.scalars(
                select(EcologyIdentityRevision).where(
                    EcologyIdentityRevision.project_id == project_id
                )
            )
        )
        assert len(unchanged) == 3
