from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.pose_identity_tracking import process_pose_identity_tracking_job
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_ecology_identity_registry_1_2 import _register
from reefvision.tests.test_pose_identity_tracking_api import _first_class, _submit, _track, _video


def test_scoped_pose_links_preserve_review_and_correction_history(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = create_project(client, "Organism pose evidence")
    project_id = str(project["id"])
    other_project = str(create_project(client, "Unrelated organism records")["id"])
    first = _register(client, project_id, "fish-a", "individual").json()
    second = _register(client, project_id, "fish-b", "individual").json()
    foreign = _register(client, other_project, "fish-a", "individual").json()
    video = _video(client, project_id, monkeypatch, "organism-pose-evidence")
    video_id = str(video["id"])
    tracks = [
        _track(client, video_id, _first_class(project), offset=offset, prefix=prefix)
        for offset, prefix in ((10, "first"), (150, "second"))
    ]
    job = _submit(client, project_id, video_id, [str(track["id"]) for track in tracks])
    app = cast(FastAPI, client.app)
    assert process_pose_identity_tracking_job(
        app.state.settings, app.state.session_factory, str(job["id"])
    )
    run_id = cast(dict[str, str], job["result_json"])["run_id"]
    source_url = f"/api/v1/pose-identity-runs/{run_id}"
    animals = client.get(f"{source_url}/identities").json()
    first_pose_id, second_pose_id = [animal["id"] for animal in animals]
    base = f"/api/v1/projects/{project_id}/ecology/pose-links"
    payload = {
        "confirm": True,
        "organism_revision_id": first["id"],
        "association_run_id": run_id,
        "animal_identity_id": first_pose_id,
        "expected_identity_run_revision": 1,
        "frame_start": 0,
        "frame_end": 1,
        "reason": "This fish has the recorded identifying markings",
        "reviewer": "fixture scientist",
    }

    unreviewed = client.post(base, json=payload)
    assert unreviewed.status_code == 400
    assert "scientist-reviewed" in unreviewed.json()["detail"]
    for pose_id, frame_end in ((first_pose_id, 1), (second_pose_id, 2)):
        accepted = client.post(
            f"{source_url}/corrections",
            json={
                "action": "accept",
                "target_type": "identity",
                "target_id": pose_id,
                "frame_start": 0,
                "frame_end": frame_end,
                "actor": "fixture scientist",
            },
        )
        assert accepted.status_code == 201, accepted.text

    payload["expected_identity_run_revision"] = 3
    assert client.post(base, json={**payload, "confirm": False}).status_code == 422
    assert (
        client.post(base, json={**payload, "organism_revision_id": foreign["id"]}).status_code
        == 404
    )
    linked = client.post(base, json=payload)
    assert linked.status_code == 201, linked.text
    original = linked.json()
    assert original["status"] == "current"
    assert original["source"]["video_id"] == video_id
    assert [row["frame_index"] for row in original["source"]["observations"]] == [0, 1]
    assert original["source"]["identity_run_revision"] == 3
    assert len(original["source_sha256"]) == 64
    assert (
        client.post(base, json={**payload, "organism_revision_id": second["id"]}).status_code == 409
    )
    assert (
        client.post(base, json={**payload, "animal_identity_id": second_pose_id}).status_code == 409
    )
    other_animal = client.post(
        base,
        json={
            **payload,
            "organism_revision_id": second["id"],
            "animal_identity_id": second_pose_id,
        },
    )
    assert other_animal.status_code == 201, other_animal.text

    out_of_scope = client.post(
        f"{source_url}/corrections",
        json={
            "action": "accept",
            "target_type": "identity",
            "target_id": first_pose_id,
            "frame_start": 2,
            "frame_end": 2,
            "actor": "fixture scientist",
        },
    )
    assert out_of_scope.status_code == 201, out_of_scope.text
    current = client.get(f"{base}?organism_key=fish-a").json()["items"]
    assert [item["status"] for item in current] == ["current"]

    rejected = client.post(
        f"{source_url}/corrections",
        json={
            "action": "reject",
            "target_type": "identity",
            "target_id": first_pose_id,
            "frame_start": 1,
            "frame_end": 1,
            "actor": "fixture scientist",
        },
    )
    assert rejected.status_code == 201, rejected.text
    stale = client.get(f"{base}?organism_key=fish-a").json()["items"][0]
    assert stale["status"] == "stale"
    assert stale["source"] == original["source"]
    assert (
        client.get(
            f"/api/v1/projects/{other_project}/ecology/pose-links/{original['link_id']}"
        ).status_code
        == 404
    )

    corrected = client.post(
        f"{base}/{original['link_id']}/corrections",
        json={
            **payload,
            "expected_identity_run_revision": 5,
            "expected_revision": 1,
            "frame_end": 0,
        },
    )
    assert corrected.status_code == 201, corrected.text
    fixed = corrected.json()
    assert fixed["revision"] == 2
    assert fixed["supersedes_id"] == original["id"]
    assert fixed["status"] == "current"
    unlink_payload = {
        "confirm": True,
        "reviewer": "fixture scientist",
        "reason": "Link withdrawn after reinspection",
    }
    assert (
        client.post(
            f"{base}/{original['link_id']}/unlink", json={**unlink_payload, "expected_revision": 1}
        ).status_code
        == 409
    )
    removed = client.post(
        f"{base}/{original['link_id']}/unlink", json={**unlink_payload, "expected_revision": 2}
    )
    assert removed.status_code == 201, removed.text
    assert removed.json()["status"] == "unlinked"
    history = client.get(f"{base}/{original['link_id']}").json()
    assert [item["status"] for item in history] == ["superseded", "superseded", "unlinked"]
    assert history[0]["source_sha256"] == original["source_sha256"]

    second_link = other_animal.json()
    relinked = client.post(
        f"{base}/{second_link['link_id']}/corrections",
        json={
            **payload,
            "animal_identity_id": second_pose_id,
            "expected_identity_run_revision": 5,
            "expected_revision": 1,
        },
    )
    assert relinked.status_code == 201, relinked.text
    previous_animal = client.get(f"{base}?organism_key=fish-b").json()
    assert previous_animal["total"] == 1
    assert previous_animal["items"][0]["status"] == "superseded"
    assert previous_animal["items"][0]["id"] == second_link["id"]
    assert client.get(f"{base}?organism_key=fish-a&limit=1&offset=1").json()["total"] == 2
