from __future__ import annotations

import pytest
from alembic import command
from fastapi.testclient import TestClient

from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_pose_biological_measurement_migration import _config
from reefvision.tests.test_pose_identity_tracking_api import _video


def freeze_fixture(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    project = create_project(client, "Independent reference fixture")
    project_id = str(project["id"])
    video = _video(client, project_id, monkeypatch, "phase6-reference")
    schema = client.post(
        f"/api/v1/projects/{project_id}/pose-schemas",
        json={"name": "Fish jaws", "landmarks": [{"id": "jaw", "name": "Jaw"}], "edges": []},
    )
    assert schema.status_code == 201, schema.text
    recording = {
        "video_id": video["id"],
        "video_sha256": video["sha256"],
        "group_id": "session-a",
        "split": "development",
        "individuals": [{"id": "animal-a", "species": "synthetic fish"}],
        "schema_id": schema.json()["id"],
        "schema_revision": 1,
        "schema_sha256": schema.json()["content_hash"],
        "event_windows": [
            {"individual_id": "animal-a", "label": "gape", "start_s": 0, "end_s": 0.5}
        ],
        "annotations": [
            {
                "rater_id": rater,
                "blinded": True,
                "events": [
                    {
                        "id": "cycle-1",
                        "individual_id": "animal-a",
                        "label": "gape",
                        "start_s": 0.1,
                        "end_s": end,
                    }
                ],
            }
            for rater, end in (("rater-a", 0.3), ("rater-b", 0.4))
        ],
    }
    payload = {"name": "Synthetic study", "data_kind": "synthetic", "recordings": [recording]}
    url = f"/api/v1/projects/{project_id}/reefpose-references"
    response = client.post(url, json=payload)
    assert response.status_code == 201, response.text
    return url, payload, response.json()


def test_reference_freezes_independent_annotations_and_appends_revision(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    url, payload, first = freeze_fixture(client, monkeypatch)
    payload["parent_id"] = first["id"]
    payload["recordings"][0]["annotations"][1]["events"][0]["end_s"] = 0.45
    second = client.post(url, json=payload)
    assert second.status_code == 201, second.text
    assert second.json()["revision"] == 2
    assert second.json()["manifest_sha256"] != first["manifest_sha256"]
    original = client.get(f"{url}/{first['id']}").json()
    assert original["manifest"]["recordings"][0]["annotations"][1]["events"][0]["end_s"] == 0.4
    assert len(original["manifest"]["recordings"][0]["annotation_sha256"]) == 2


def test_reference_rejects_shared_recording_group_across_splits(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    url, payload, _ = freeze_fixture(client, monkeypatch)
    project_id = url.split("/")[-2]
    other_video = _video(client, project_id, monkeypatch, "phase6-test")
    payload["recordings"].append(
        {
            **payload["recordings"][0],
            "split": "test",
            "video_id": other_video["id"],
            "video_sha256": other_video["sha256"],
        }
    )
    response = client.post(url, json=payload)
    assert response.status_code in (400, 422)
    assert "group" in response.text.lower()


def test_reference_migration_round_trip(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    import sqlite3

    path = tmp_path / "reference.db"
    monkeypatch.setenv("REEFVISION_DATABASE_URL", f"sqlite:///{path.as_posix()}")
    config = _config(path)
    command.upgrade(config, "0043")
    command.downgrade(config, "0042")
    with sqlite3.connect(path) as database:
        tables = {row[0] for row in database.execute("SELECT name FROM sqlite_master")}
        assert "reefpose_references" not in tables
        assert "pose_measurement_runs" in tables
    command.upgrade(config, "0043")
    with sqlite3.connect(path) as database:
        assert database.execute("SELECT count(*) FROM reefpose_references").fetchone() == (0,)
