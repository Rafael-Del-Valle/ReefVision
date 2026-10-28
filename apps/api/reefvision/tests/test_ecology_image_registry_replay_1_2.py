"""Image evidence signatures must survive API and saved Workflow Builder replay."""

from __future__ import annotations

from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from reefvision.schemas.ecology_identity import EcologyIdentityRegistryResponse
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.tests.test_annotations import create_project, import_one
from reefvision.tests.test_ecology_image_evidence_1_2 import _link, _register, _workflow


def _linked_registry(client: TestClient) -> tuple[str, dict]:
    project_id = str(create_project(client, "Ecology signed image replay")["id"])
    _register(client, project_id, "colony-source")
    image_id = str(import_one(client, project_id)["successful"][0]["image_id"])
    assert _link(client, project_id, "colony-source", image_id).status_code == 201
    response = client.get(f"/api/v1/projects/{project_id}/ecology/identity-registry")
    assert response.status_code == 200, response.text
    return project_id, response.json()


def test_signed_image_evidence_matches_api_and_saved_workflow_and_detects_tampering(
    client: TestClient,
) -> None:
    project_id, snapshot = _linked_registry(client)
    assert snapshot["image_evidence_count"] == 1
    assert snapshot["image_evidence_links"][0]["source_metadata_evidence_status"] == "frozen"
    assert EcologyIdentityRegistryResponse.model_validate(snapshot).review_gate == (
        "scientist_review_required"
    )
    run = _workflow(client, project_id)
    assert run["run"]["status"] == "succeeded"
    artifacts = [row for row in run["artifacts"] if row["data_type"] == "ecology_identity_registry"]
    assert len(artifacts) == 1
    assert artifacts[0]["payload_json"] == snapshot

    for field, altered in (
        ("reason", "Rewritten specimen attribution"),
        ("image_sha256", "0" * 64),
        ("source_metadata_sha256", "0" * 64),
    ):
        changed = deepcopy(artifacts[0]["payload_json"])
        changed["image_evidence_links"][0][field] = altered
        with pytest.raises(ValidationError, match="image evidence fingerprint mismatch"):
            EcologyIdentityRegistryResponse.model_validate(changed)

    changed = deepcopy(snapshot)
    changed["image_evidence_sha256"] = "0" * 64
    with pytest.raises(ValidationError, match="image evidence fingerprint mismatch"):
        EcologyIdentityRegistryResponse.model_validate(changed)


def test_legacy_v1_image_signatures_remain_readable_but_not_forgeable(
    client: TestClient,
) -> None:
    _, snapshot = _linked_registry(client)
    legacy = deepcopy(snapshot)
    link = legacy["image_evidence_links"][0]
    link["source_metadata_sha256"] = None
    link["source_metadata_evidence_status"] = "legacy_unfrozen"
    legacy_rows = [
        {
            key: value
            for key, value in row.items()
            if key not in ("source_metadata_sha256", "source_metadata_evidence_status", "evidence_level", "project_id")
        }
        for row in legacy["image_evidence_links"]
    ]
    legacy["image_evidence_sha256"] = canonical_json_sha256(
        {
            "algorithm_version": "ecology-image-evidence-0001",
            "project_id": legacy["project_id"],
            "links": legacy_rows,
        }
    )
    assert EcologyIdentityRegistryResponse.model_validate(legacy).review_gate == (
        "scientist_review_required"
    )

    altered = deepcopy(legacy)
    altered["image_evidence_links"][0]["reason"] = "Rewritten legacy link"
    with pytest.raises(ValidationError, match="image evidence fingerprint mismatch"):
        EcologyIdentityRegistryResponse.model_validate(altered)

    # A frozen modern link cannot be laundered through the old digest format.
    forged = deepcopy(legacy)
    forged["image_evidence_links"][0]["source_metadata_sha256"] = (
        snapshot["image_evidence_links"][0]["source_metadata_sha256"]
    )
    forged["image_evidence_links"][0]["source_metadata_evidence_status"] = "frozen"
    with pytest.raises(ValidationError, match="image evidence fingerprint mismatch"):
        EcologyIdentityRegistryResponse.model_validate(forged)


def test_modern_signature_with_explicit_legacy_unfrozen_image_still_validates(
    client: TestClient,
) -> None:
    _, snapshot = _linked_registry(client)
    current = deepcopy(snapshot)
    current["image_evidence_links"][0]["source_metadata_sha256"] = None
    current["image_evidence_links"][0]["source_metadata_evidence_status"] = "legacy_unfrozen"
    row = current["image_evidence_links"][0]
    fingerprint_row = {
        key: row[key]
        for key in (
            "id",
            "organism_key",
            "identity_revision",
            "image_id",
            "image_sha256",
            "source_metadata_sha256",
            "source_metadata_evidence_status",
            "reason",
            "created_at",
        )
    }
    current["image_evidence_sha256"] = canonical_json_sha256(
        {
            "algorithm_version": "ecology-image-evidence-0002",
            "project_id": current["project_id"],
            "links": [fingerprint_row],
        }
    )
    assert EcologyIdentityRegistryResponse.model_validate(current).review_gate == (
        "scientist_review_required"
    )
