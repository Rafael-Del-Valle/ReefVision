"""Round-trip the available project exchange sections and disclose unsupported records."""

import pytest
from fastapi.testclient import TestClient

from reefvision.config import Settings
from reefvision.tests.test_ecology_image_evidence_1_2 import _register
from reefvision.tests.test_pose_training_project_exchange_phase9 import (
    _archive_with_pose_training_truth,
)
from reefvision.tests.test_scientific_project_exchange import export_archive, import_archive


def test_pose_dataset_exchange_discloses_untransported_identity_history(
    client: TestClient, test_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, source_project, _ = _archive_with_pose_training_truth(client, test_settings, monkeypatch)
    project_id = str(source_project["id"])
    _register(client, project_id, "exchange-colony")

    raw = export_archive(client, test_settings, project_id)
    inspected = client.post(
        "/api/v1/exchange-packages/inspect",
        files={"file": ("integrated.zip", raw, "application/zip")},
    )
    assert inspected.status_code == 200, inspected.text
    report = inspected.json()
    assert report["compatible"]
    assert report["section_counts"]["pose_training_datasets"] == 1
    assert any("ecological identity" in warning for warning in report["warnings"])
    imported = import_archive(client, raw)
    assert imported.status_code == 201, imported.text
    assert any("ecological identity" in warning for warning in imported.json()["warnings"])
    assert imported.json()["imported_counts"]["pose_training_datasets"] == 1
    assert (
        client.get(f"/api/v1/projects/{project_id}/ecology/identity-registry").json()["identities"][
            0
        ]["organism_key"]
        == "exchange-colony"
    )
