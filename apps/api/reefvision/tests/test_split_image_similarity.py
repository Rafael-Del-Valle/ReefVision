from io import BytesIO
from pathlib import Path
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from reefvision.domain.errors import ValidationError
from reefvision.jobs.quality_control import process_quality_control_job
from reefvision.tests.test_annotations import create_project


def test_similar_images_across_frozen_splits_require_reviewer_adjudication(
    client: TestClient,
) -> None:
    project = create_project(client, "Frozen image screen")
    pid = project["id"]
    source = Image.new("RGB", (160, 120), (90, 110, 130))
    draw = ImageDraw.Draw(source)
    for x in range(0, 144, 13):
        draw.line((x, 3, 155 - x // 2, 113), fill=(20, 55, 210), width=4)
    assignments = []
    ids = []
    for name, image, fmt, split in [
        ("source.png", source, "PNG", "train"),
        ("renamed.jpg", source.resize((320, 240)), "JPEG", "test"),
        ("unrelated.png", Image.new("RGB", (160, 120), "orange"), "PNG", "validation"),
    ]:
        data = BytesIO()
        image.save(data, format=fmt, quality=83)
        res = client.post(
            f"/api/v1/projects/{pid}/imports/images", files={"files": (name, data.getvalue())}
        )
        assert res.status_code == 200, res.text
        iid = res.json()["successful"][0]["image_id"]
        ids.append(iid)
        annotations = client.put(
            f"/api/v1/images/{iid}/annotations",
            json={"base_revision": 0, "annotation_status": "reviewed", "annotations": []},
        )
        assert annotations.status_code == 200, annotations.text
        assignments.append({"image_id": iid, "split": split})
    response = client.post(
        f"/api/v1/projects/{pid}/dataset-versions",
        json={
            "name": "Labelled splits",
            "eligible_annotation_statuses": ["reviewed"],
            "split_method": "manual",
            "manual_assignments": assignments,
        },
    )
    assert response.status_code == 201, response.text
    version = response.json()
    config = {
        "rule_categories": ["dataset_versions"],
        "selected_rule_ids": ["cross_split_similar_images"],
    }
    endpoint = f"/api/v1/dataset-versions/{version['id']}/quality-control-runs"
    queued = client.post(endpoint, json=config)
    assert queued.status_code == 201, queued.text
    app = cast(FastAPI, client.app)
    run = queued.json()
    assert process_quality_control_job(app.state.settings, app.state.session_factory, run["job_id"])
    complete = client.get(f"/api/v1/quality-control-runs/{run['id']}").json()
    screening = complete["summary_json"]["cross_split_similar_images"]
    assert screening["images_by_split"] == {"train": 1, "validation": 1, "test": 1}
    assert screening["checked_images"] == 3 and screening["flagged_pairs"] == 1
    issues = client.get(f"/api/v1/quality-control-runs/{run['id']}/issues").json()["items"]
    assert len(issues) == 1
    issue = issues[0]
    assert issue["severity"] == "warning" and issue["status"] == "open"
    assert set(issue["measured_values_json"]["image_ids"]) == set(ids[:2])
    assert set(issue["measured_values_json"]["splits"]) == {"train", "test"}
    assert issue["dataset_version_id"] == version["id"]
    assert (
        client.get(f"/api/v1/dataset-versions/{version['id']}").json()["manifest_sha256"]
        == version["manifest_sha256"]
    )
    refused = client.post(f"/api/v1/projects/{pid}/quality-control-runs", json=config)
    assert refused.status_code in (400, 422)

    # Changed bytes cannot clear the last verified cross-split finding.
    managed = client.get(f"/api/v1/images/{ids[0]}/annotations").json()["image"]["managed_path"]
    (Path(app.state.settings.data_dir) / managed).write_bytes(b"changed after freeze")
    repeat = client.post(endpoint, json=config).json()
    with pytest.raises(ValidationError, match="checksum changed"):
        process_quality_control_job(app.state.settings, app.state.session_factory, repeat["job_id"])
    result = client.get(f"/api/v1/quality-control-runs/{repeat['id']}").json()
    assert result["status"] == "failed" and "checksum changed" in result["error_message"]
    assert (
        client.get(f"/api/v1/quality-control-runs/{run['id']}/issues").json()["items"][0]["status"]
        == "open"
    )
