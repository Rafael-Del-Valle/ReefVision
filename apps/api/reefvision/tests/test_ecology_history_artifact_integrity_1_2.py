"""Revision-history integrity for standalone and persisted ecology registry evidence."""

from __future__ import annotations

from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from reefvision.schemas.ecology_identity import EcologyIdentityRegistryResponse
from reefvision.tests.test_annotations import create_project, import_one
from reefvision.tests.test_ecology_image_evidence_1_2 import _link, _register, _workflow


def test_registered_history_matches_standalone_and_saved_workflow(
    client: TestClient,
) -> None:
    project_id = str(create_project(client, "Ecology history reconciliation")["id"])
    _register(client, project_id, "colony-16")
    image_id = str(import_one(client, project_id)["successful"][0]["image_id"])
    linked = _link(client, project_id, "colony-16", image_id)
    assert linked.status_code == 201, linked.text
    revised = client.post(
        f"/api/v1/projects/{project_id}/ecology/organisms/colony-16/revisions",
        json={
            "expected_revision": 1,
            "kind": "colony",
            "reason": "Second unverified identity revision",
        },
    )
    assert revised.status_code == 201, revised.text
    response = client.get(f"/api/v1/projects/{project_id}/ecology/identity-registry")
    assert response.status_code == 200, response.text
    snapshot = response.json()
    assert len(snapshot["identity_history"]) == 2
    assert snapshot["image_evidence_links"][0]["identity_revision"] == 1
    assert EcologyIdentityRegistryResponse.model_validate(snapshot).review_gate == (
        "scientist_review_required"
    )
    run = _workflow(client, project_id)
    assert run["run"]["status"] == "succeeded"
    artifacts = [
        item for item in run["artifacts"] if item["data_type"] == "ecology_identity_registry"
    ]
    assert len(artifacts) == 1
    assert artifacts[0]["payload_json"] == snapshot

    tampered = deepcopy(artifacts[0]["payload_json"])
    tampered["identity_history"][0]["reason"] = "Retroactively changed source notes"
    with pytest.raises(ValidationError, match="history fingerprint mismatch"):
        EcologyIdentityRegistryResponse.model_validate(tampered)

    tampered = deepcopy(artifacts[0]["payload_json"])
    tampered["identities"][0]["reason"] = "A different latest identity"
    with pytest.raises(ValidationError, match="latest identity contradicts"):
        EcologyIdentityRegistryResponse.model_validate(tampered)

    tampered = deepcopy(artifacts[0]["payload_json"])
    tampered["image_evidence_links"][0]["identity_revision"] = 99
    with pytest.raises(ValidationError, match="unknown identity revision"):
        EcologyIdentityRegistryResponse.model_validate(tampered)


def test_missing_history_and_corrupt_revision_chain_fail_closed(
    client: TestClient,
) -> None:
    project_id = str(create_project(client, "Ecology history legacy boundary")["id"])
    _register(client, project_id, "colony-20")
    image_id = str(import_one(client, project_id)["successful"][0]["image_id"])
    assert _link(client, project_id, "colony-20", image_id).status_code == 201
    response = client.get(f"/api/v1/projects/{project_id}/ecology/identity-registry")
    assert response.status_code == 200, response.text
    original = response.json()

    explicit_empty = deepcopy(original)
    explicit_empty["identity_history"] = []
    explicit_empty["history_revision_count"] = 0
    with pytest.raises(ValidationError, match="latest identities contradict"):
        EcologyIdentityRegistryResponse.model_validate(explicit_empty)

    # Older saved workflows can omit history entirely, but not claim future
    # identity revisions or nonexistent organisms in their image links.
    legacy = deepcopy(original)
    for key in ("identity_history", "history_revision_count", "history_sha256"):
        legacy.pop(key)
    assert EcologyIdentityRegistryResponse.model_validate(legacy).review_gate == (
        "scientist_review_required"
    )
    future = deepcopy(legacy)
    future["image_evidence_links"][0]["identity_revision"] = 9
    with pytest.raises(ValidationError, match="unknown identity revision"):
        EcologyIdentityRegistryResponse.model_validate(future)

    orphan = deepcopy(legacy)
    orphan["image_evidence_links"][0]["organism_key"] = "unknown-colony"
    with pytest.raises(ValidationError, match="unknown identity revision"):
        EcologyIdentityRegistryResponse.model_validate(orphan)

    discontinuous = deepcopy(original)
    discontinuous["identity_history"][0]["revision"] = 3
    discontinuous["identities"][0]["revision"] = 3
    with pytest.raises(ValidationError, match="revision history is not contiguous"):
        EcologyIdentityRegistryResponse.model_validate(discontinuous)


def test_signed_registry_evidence_survives_workflow_and_rejects_tampering(
    client: TestClient,
) -> None:
    """Saved workflow provenance is not silently rewritten during replay."""
    from reefvision.tests.test_ecology_calibration_evidence_1_2 import (
        _link_calibration,
        _prepared_annotation,
        _save_calibration,
    )

    project_id, image_id, annotation = _prepared_annotation(client)
    _save_calibration(client, image_id)
    linked = _link_calibration(client, project_id, annotation)
    assert linked.status_code == 201, linked.text
    response = client.get(f"/api/v1/projects/{project_id}/ecology/identity-registry")
    assert response.status_code == 200, response.text
    original = response.json()
    run = _workflow(client, project_id)
    assert run["run"]["status"] == "succeeded"
    artifacts = [
        row for row in run["artifacts"] if row["data_type"] == "ecology_identity_registry"
    ]
    assert len(artifacts) == 1
    assert artifacts[0]["payload_json"] == original
    assert EcologyIdentityRegistryResponse.model_validate(original).review_gate == (
        "scientist_review_required"
    )

    changed = deepcopy(original)
    changed["snapshot_sha256"] = "0" * 64
    with pytest.raises(ValidationError, match="identity snapshot fingerprint mismatch"):
        EcologyIdentityRegistryResponse.model_validate(changed)

    # A legacy workflow without history still cannot rewrite signed identity.
    legacy = deepcopy(original)
    for field in ("identity_history", "history_revision_count", "history_sha256"):
        legacy.pop(field)
    assert EcologyIdentityRegistryResponse.model_validate(legacy).review_gate == (
        "scientist_review_required"
    )
    legacy["identities"][0]["kind"] = "individual"
    with pytest.raises(ValidationError, match="identity snapshot fingerprint mismatch"):
        EcologyIdentityRegistryResponse.model_validate(legacy)

    for collection, expected in (
        ("annotation_evidence_links", "annotation evidence fingerprint mismatch"),
        ("calibration_evidence_links", "calibration evidence fingerprint mismatch"),
    ):
        changed = deepcopy(artifacts[0]["payload_json"])
        changed[collection][0]["reason"] = "Retroactively altered scientific source"
        with pytest.raises(ValidationError, match=expected):
            EcologyIdentityRegistryResponse.model_validate(changed)

    for digest_field, expected in (
        ("annotation_evidence_sha256", "annotation evidence fingerprint mismatch"),
        ("calibration_evidence_sha256", "calibration evidence fingerprint mismatch"),
    ):
        changed = deepcopy(original)
        changed[digest_field] = "0" * 64
        with pytest.raises(ValidationError, match=expected):
            EcologyIdentityRegistryResponse.model_validate(changed)

    unsigned = deepcopy(original)
    unsigned.pop("annotation_evidence_sha256")
    unsigned.pop("calibration_evidence_sha256")
    assert EcologyIdentityRegistryResponse.model_validate(unsigned).review_gate == (
        "scientist_review_required"
    )
