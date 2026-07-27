from __future__ import annotations

import csv
import io
import json
import zipfile
from typing import cast

import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.db.models import ArtifactRecord
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.tests.test_classification_phase5 import _seed_classification_project
from reefvision.tests.test_classification_scientific_export_phase5 import (
    _accept_box_assignment,
)


def test_scientific_classification_bundle_contains_safe_csv_json_and_npz(
    client: TestClient,
) -> None:
    project, image_id, class_ids = _seed_classification_project(client)
    project_id = str(project["id"])
    annotation_id = "e52cc1a2-321a-4c12-ad46-1b95a48600e1"
    _accept_box_assignment(
        client,
        project_id=project_id,
        image_id=image_id,
        annotation_id=annotation_id,
        label_class_id=class_ids["open"],
    )

    response = client.post(
        f"/api/v1/projects/{project_id}/classification-assignments/scientific-data-exports",
        json={"formats": ["csv", "json", "npz"]},
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["row_count"] == 1
    assert payload["formats"] == ["csv", "json", "npz"]

    app = cast(FastAPI, client.app)
    archive_path = resolve_managed_project_path(
        app.state.settings,
        payload["archive_path"],
    )
    assert archive_path.is_file()
    with zipfile.ZipFile(archive_path) as archive:
        names = set(archive.namelist())
        assert names == {
            "classification-assignments.csv",
            "classification-assignments.json",
            "classification-assignments.npz",
            "manifest.json",
        }
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["row_count"] == 1
        assert manifest["format"] == "reefvision-scientific-classification-export"
        assert manifest["artifact_id"] == payload["artifact_id"]
        assert {item["path"] for item in manifest["files"]} == {
            "classification-assignments.csv",
            "classification-assignments.json",
            "classification-assignments.npz",
        }

        csv_rows = list(
            csv.DictReader(
                io.StringIO(archive.read("classification-assignments.csv").decode("utf-8"))
            )
        )
        assert len(csv_rows) == 1
        assert csv_rows[0]["annotation_id"] == annotation_id
        assert csv_rows[0]["label_class_id"] == class_ids["open"]
        assert json.loads(csv_rows[0]["probabilities_json"])

        json_payload = json.loads(archive.read("classification-assignments.json"))
        assert json_payload["row_count"] == 1
        assert json_payload["rows"][0]["annotation_id"] == annotation_id

        with np.load(
            io.BytesIO(archive.read("classification-assignments.npz")),
            allow_pickle=False,
        ) as arrays:
            assert arrays["assignment_id"].shape == (1,)
            assert arrays["bbox"].shape == (1, 4)
            assert arrays["annotation_id"].tolist() == [annotation_id]
            assert arrays["label_class_id"].tolist() == [class_ids["open"]]
            assert np.isfinite(arrays["confidence"][0])
            assert json.loads(arrays["probabilities_json"][0])

    with app.state.session_factory() as session:
        artifact = session.get(ArtifactRecord, payload["artifact_id"])
        assert artifact is not None
        assert artifact.artifact_type == "scientific_classification_data_bundle"
        assert artifact.managed_path == payload["archive_path"]
        assert artifact.checksum == payload["archive_sha256"]
        assert artifact.metadata_json["manifest_path"] == payload["manifest_path"]


def test_scientific_classification_bundle_rejects_duplicate_formats(
    client: TestClient,
) -> None:
    project, _image_id, _class_ids = _seed_classification_project(client)
    response = client.post(
        f"/api/v1/projects/{project['id']}/classification-assignments/scientific-data-exports",
        json={"formats": ["csv", "csv"]},
    )
    assert response.status_code == 422, response.text
