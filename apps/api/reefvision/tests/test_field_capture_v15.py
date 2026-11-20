from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from typing import cast
from zipfile import ZipFile

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from reefvision.config import Settings
from reefvision.jobs.workflow import process_workflow_run_job


def _project(client: TestClient, name: str) -> str:
    response = client.post("/api/v1/projects", json={"name": name, "template": "blank"})
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def _root(project: str) -> str:
    return f"/api/v1/projects/{project}/field-capture"


def _image(rgb: tuple[int, int, int] = (24, 102, 108)) -> bytes:
    stream = BytesIO()
    Image.new("RGB", (23, 17), rgb).save(stream, "PNG")
    return stream.getvalue()


def _metadata(*, key: str = "Transect 7 / frame 1", known: bool = True) -> dict:
    return {
        "observer": "Fixture observer",
        "observation_key": key,
        "site": "Synthetic station 7",
        "subject": "Fixture specimen",
        "notes": "Declared in disposable test",
        "clock": {
            "state": "known_offset" if known else "unknown",
            "wall_time": "2026-11-18T09:07:31",
            "utc_offset_minutes": -300 if known else None,
            "evidence": "Declared UTC-05:00 from capture sheet" if known else "Clock offset absent",
        },
    }


def _batch(client: TestClient, root: str, title: str = "Offline fixture batch") -> str:
    response = client.post(f"{root}/batches", json={"label": title})
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def _capture(
    client: TestClient,
    root: str,
    batch: str,
    filename: str,
    content: bytes,
    metadata: dict,
) -> dict:
    response = client.post(
        f"{root}/batches/{batch}/observations",
        data={"metadata": json.dumps(metadata)},
        files={"file": (filename, content)},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _seal(client: TestClient, root: str, batch: str) -> dict:
    response = client.post(f"{root}/batches/{batch}/seal")
    assert response.status_code == 200, response.text
    return response.json()


def test_field_batch_portable_archive_preserves_originals_without_inventing_utc(
    client: TestClient,
) -> None:
    source_project = _project(client, "Offline field source")
    destination_project = _project(client, "Field archive receiver")
    source, destination = _root(source_project), _root(destination_project)
    batch = _batch(client, source)
    image = _image()
    video = (
        Path(__file__).resolve().parents[4]
        / "apps/web/tests/e2e/fixtures/synthetic-ordinary-clip.mp4"
    ).read_bytes()
    image_row = _capture(client, source, batch, "survey.png", image, _metadata())
    video_row = _capture(
        client, source, batch, "clip.mp4", video, _metadata(key="Transect 7 / clip", known=False)
    )
    assert image_row["captured_at_utc"] == "2026-11-18T14:07:31Z"
    assert video_row["captured_at_utc"] is None
    assert video_row["metadata"]["clock"]["wall_time"] == "2026-11-18T09:07:31"
    assert video_row["metadata"]["clock"]["evidence"] == "Clock offset absent"
    for row, content in [(image_row, image), (video_row, video)]:
        assert row["sha256"] == hashlib.sha256(content).hexdigest()
        assert row["size_bytes"] == len(content)
        downloaded = client.get(f"{source}/batches/{batch}/observations/{row['id']}/content")
        assert downloaded.content == content

    sealed = _seal(client, source, batch)
    assert len(sealed["manifest_sha256"]) == 64
    assert _seal(client, source, batch) == sealed
    reopened = client.get(f"{source}/batches/{batch}").json()
    assert reopened == sealed
    assert {entry["id"] for entry in reopened["observations"]} == {image_row["id"], video_row["id"]}
    exported = client.get(f"{source}/batches/{batch}/archive")
    assert exported.status_code == 200, exported.text
    with ZipFile(BytesIO(exported.content)) as package:
        manifest = json.loads(package.read("manifest.json"))
        assert manifest["manifest_sha256"] == sealed["manifest_sha256"]
        assert manifest["manifest"]["origin_project_id"] == source_project
        assert manifest["manifest"]["origin_batch_id"] == batch
        assert sorted(
            package.read(name) for name in package.namelist() if name != "manifest.json"
        ) == sorted([image, video])

    def transfer() -> dict:
        result = client.post(
            f"{destination}/imports",
            files={"file": ("field.reefvision-field.zip", exported.content)},
        )
        assert result.status_code == 200, result.text
        return result.json()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, repeated = sorted(
            pool.map(lambda _: transfer(), range(2)), key=lambda row: row["duplicate"]
        )
    assert first["duplicate"] is False and repeated["duplicate"] is True
    assert repeated["batch"] == first["batch"]
    imported = first["batch"]
    assert imported["id"] != batch
    assert imported["origin_batch_id"] == batch
    assert imported["manifest_sha256"] == sealed["manifest_sha256"]
    assert {r["source_observation_id"] for r in imported["observations"]} == {
        image_row["source_observation_id"],
        video_row["source_observation_id"],
    }
    assert {r["id"] for r in imported["observations"]}.isdisjoint(
        {image_row["id"], video_row["id"]}
    )
    # A ZIP can be internally well formed and still substitute source bytes.
    corrupted = BytesIO()
    with ZipFile(BytesIO(exported.content)) as package, ZipFile(corrupted, "w") as changed:
        media_path = next(name for name in package.namelist() if name != "manifest.json")
        for name in package.namelist():
            payload = package.read(name)
            if name == media_path:
                payload = payload[:-1] + bytes([payload[-1] ^ 1])
            changed.writestr(name, payload)
    rejected = client.post(
        f"{destination}/imports", files={"file": ("tampered.zip", corrupted.getvalue())}
    )
    assert rejected.status_code == 400, rejected.text

    reconciled = _reconcile(client, destination, imported)
    by_kind = {row["kind"]: row for row in reconciled["rows"]}
    assert by_kind["video"]["sha256"] == video_row["sha256"]
    project_video = client.get(f"/api/v1/videos/{by_kind['video']['asset_id']}").json()
    assert project_video["sha256"] == video_row["sha256"]
    assert project_video["frame_count"] == 12


def _reconcile(client: TestClient, root: str, sealed: dict) -> dict:
    response = client.post(
        f"{root}/batches/{sealed['id']}/reconcile",
        json={"manifest_sha256": sealed["manifest_sha256"]},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_reconciliation_reuses_project_media_and_retains_conflict_evidence(
    client: TestClient,
) -> None:
    project = _project(client, "Field reconciliation")
    root = _root(project)
    original = _image()
    response = client.post(
        f"/api/v1/projects/{project}/imports/images", files={"files": ("existing.png", original)}
    )
    existing = response.json()["successful"][0]["image_id"]
    first = _batch(client, root)
    base = _capture(client, root, first, "field.png", original, _metadata())
    first_result = _reconcile(client, root, _seal(client, root, first))
    assert first_result["rows"][0]["asset_id"] == existing
    assert first_result["rows"][0]["outcome"] == "duplicate_media"

    batch = _batch(client, root, "Contradictory field notes")
    altered = _metadata()
    altered["notes"] = "Second observer disputed the identification"
    incoming = _capture(client, root, batch, "repeat.png", original, altered)
    distinct = _capture(client, root, batch, "another.png", _image((20, 60, 90)), altered)
    sealed = _seal(client, root, batch)
    report = _reconcile(client, root, sealed)
    by_id = {row["observation_id"]: row for row in report["rows"]}
    assert by_id[incoming["id"]]["outcome"] == "conflict"
    assert by_id[incoming["id"]]["asset_id"] == existing
    assert by_id[distinct["id"]]["asset_id"] != existing
    candidate = by_id[incoming["id"]]["conflicts"][0]
    assert candidate["against_observation_id"] == base["id"]
    assert candidate["against_batch_id"] == first
    assert candidate["against"]["metadata"]["notes"] == "Declared in disposable test"
    assert client.get(f"/api/v1/images/{existing}").json()["original_filename"] == "existing.png"

    decision = {
        "observation_id": incoming["id"],
        "against_observation_id": base["id"],
        "reviewer": "Independent fixture reviewer",
        "decision": "retain_both",
        "notes": "Keep both attributed observation records for review.",
    }
    url = f"{root}/batches/{batch}/reviews"
    reviewed = client.post(url, json=decision)
    assert reviewed.status_code == 200, reviewed.text
    assert client.post(url, json=decision).json() == reviewed.json()
    assert client.post(url, json={**decision, "decision": "prefer_existing"}).status_code == 409
    assert client.get(url).json() == [reviewed.json()]
    assert _reconcile(client, root, sealed) == report
    assert client.get(f"{root}/batches/{batch}/reconciliation").json() == report


def test_failed_reconciliation_leaves_no_visible_assets_and_concurrent_retry_is_idempotent(
    client: TestClient,
    test_settings: Settings,
) -> None:
    project = _project(client, "Transactional field reconciliation")
    root = _root(project)
    batch = _batch(client, root)
    image_a, image_b = _image(), _image((30, 100, 102))
    _capture(client, root, batch, "first.png", image_a, _metadata(key="first"))
    second = _capture(client, root, batch, "second.png", image_b, _metadata(key="second"))
    sealed = _seal(client, root, batch)
    file = (
        test_settings.resolved_data_dir
        / "projects"
        / project
        / "field_capture"
        / "originals"
        / "image"
        / second["sha256"]
    )
    file.write_bytes(b"damaged test source")
    url = f"{root}/batches/{batch}/reconcile"
    body = {"manifest_sha256": sealed["manifest_sha256"]}
    failed = client.post(url, json=body)
    assert failed.status_code == 400, failed.text
    gallery = f"/api/v1/projects/{project}/images"
    assert client.get(gallery).json()["total"] == 0
    assert client.get(f"{root}/batches/{batch}/reconciliation").status_code == 404
    file.write_bytes(image_b)

    with ThreadPoolExecutor(max_workers=3) as pool:
        calls = list(pool.map(lambda _: client.post(url, json=body), range(3)))
    assert all(call.status_code == 200 for call in calls), [call.text for call in calls]
    assert calls[0].json() == calls[1].json() == calls[2].json()
    assert [row["outcome"] for row in calls[0].json()["rows"]] == ["imported", "imported"]
    assert client.get(gallery).json()["total"] == 2
    assert client.post(url, json={"manifest_sha256": "0" * 64}).status_code == 409


def test_pinned_field_workflow_runs_and_replays_standalone_receipt(client: TestClient) -> None:
    project = _project(client, "Field workflow replay")
    root = _root(project)
    batch = _batch(client, root)
    raw = _image()
    captured = _capture(client, root, batch, "field.png", raw, _metadata(known=False))
    sealed = _seal(client, root, batch)
    graph = {
        "graph_id": "field-reconciliation-fixture",
        "name": "Saved field reconciliation",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "reconcile",
                "node_type": "field_capture_reconcile",
                "parameters": {
                    "batch_id": batch,
                    "manifest_sha256": sealed["manifest_sha256"],
                },
            },
        ],
        "edges": [
            {
                "edge_id": "project-reconcile",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "reconcile",
                "target_port_id": "project",
            }
        ],
    }
    base = f"/api/v1/projects/{project}"
    saved = client.post(f"{base}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text

    def run() -> dict:
        queued = client.post(f"{base}/workflow-runs", json={"graph_record_id": saved.json()["id"]})
        assert queued.status_code == 202, queued.text
        app = cast(FastAPI, client.app)
        process_workflow_run_job(
            app.state.settings, app.state.session_factory, queued.json()["job_id"]
        )
        completed = client.get(f"/api/v1/workflow-runs/{queued.json()['id']}").json()
        assert completed["run"]["status"] == "succeeded", completed
        [result] = [
            a for a in completed["artifacts"] if a["data_type"] == "field_capture_reconciliation"
        ]
        return result["payload_json"]

    first, replayed = run(), run()
    assert first == replayed == _reconcile(client, root, sealed)
    [row] = first["rows"]
    assert row["source_observation_id"] == captured["source_observation_id"]
    assert row["sha256"] == hashlib.sha256(raw).hexdigest()
    assert client.get(f"/api/v1/images/{row['asset_id']}/content").content == raw
    assert client.get(f"/api/v1/images/{row['asset_id']}").json()["capture_timestamp"] is None
