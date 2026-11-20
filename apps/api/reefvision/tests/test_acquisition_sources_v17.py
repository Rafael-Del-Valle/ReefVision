"""Exercise local acquisition via ordinary APIs and sealed workflow artifacts."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from io import BytesIO
from json import dumps
from uuid import uuid4

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from reefvision.db.models.field_capture import FieldCaptureObservation
from reefvision.ml.acquisition_camera import CameraUnavailable, LocalCameraFrame
from reefvision.services import acquisition_sources
from reefvision.storage.projects import resolve_managed_project_path


def project(client: TestClient) -> str:
    response = client.post(
        "/api/v1/projects", json={"name": "Generated source", "template": "blank"}
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def check(response, status: int):
    assert response.status_code == status, response.text
    return response.json()


def png() -> bytes:
    stream = BytesIO()
    Image.new("RGB", (12, 8), (25, 130, 165)).save(stream, "PNG")
    return stream.getvalue()


def source_create(client: TestClient, project_id: str, config: dict) -> tuple[str, dict]:
    route = f"/api/v1/projects/{project_id}/acquisition-sources"
    item = check(
        client.post(route, json={"label": "Synthetic source", "configuration": config}), 201
    )
    return f"{route}/{item['id']}", item


def capture(client: TestClient, source: str, item: dict, key: str, **extra):
    return client.post(
        f"{source}/captures",
        json={"source_sha256": item["source_sha256"], "capture_key": key, **extra},
    )


def test_simulated_capture_is_a_durable_idempotent_field_original(client: TestClient) -> None:
    project_id = project(client)
    route, source = source_create(
        client,
        project_id,
        {
            "kind": "simulated",
            "seed": 41,
            "start_at_utc": "2025-02-01T15:03:00+02:00",
            "period_seconds": 30,
        },
    )
    key = str(uuid4())
    with ThreadPoolExecutor(max_workers=3) as executor:
        attempts = [executor.submit(capture, client, route, source, key) for _ in range(3)]
        first, *duplicates = [check(attempt.result(), 200) for attempt in attempts]
    assert duplicates == [first, first]
    assert check(capture(client, route, source, key), 200) == first
    receipt = first["receipt"]
    assert receipt["ordinal"] == 0
    assert receipt["time"]["captured_at_utc"] == "2025-02-01T13:03:00Z"
    assert receipt["time"]["uncertainty_seconds"] == 0
    assert receipt["synthetic_reading"]["unit"] == "synthetic arbitrary units"
    assert receipt["dispatch"]["kind"] == "manual"
    assert check(client.get(route), 200)["cursor"] == 1
    media = receipt["media"]
    response = client.get(
        f"/api/v1/projects/{project_id}/field-capture/batches/{media['field_batch_id']}"
    )
    assert check(response, 200)["manifest_sha256"] == media["field_batch_sha256"]
    assert check(client.get(f"{route}/captures/{receipt['id']}"), 200) == first


def test_recorded_source_keeps_original_clocks_and_cursor_through_disconnect(client, monkeypatch):
    now = datetime(2025, 8, 12, tzinfo=UTC)
    monkeypatch.setattr(acquisition_sources, "utc_now", lambda: now)
    pid = project(client)
    root = f"/api/v1/projects/{pid}/field-capture/batches"
    batch = check(client.post(root, json={"label": "Recorded fixture"}), 201)
    first_clock = {
        "state": "known_offset",
        "wall_time": "2024-09-12T10:00:00",
        "utc_offset_minutes": -240,
        "evidence": "Generated field clock with an explicit offset",
    }
    missing_clock = {"state": "unknown", "evidence": "Generated recording had no clock offset"}
    for name, clock in [("first.png", first_clock), ("second.png", missing_clock)]:
        check(
            client.post(
                f"{root}/{batch['id']}/observations",
                data={
                    "metadata": dumps({"observer": "Fixture owner", "clock": clock}),
                },
                files={"file": (name, png(), "image/png")},
            ),
            201,
        )
    sealed = check(client.post(f"{root}/{batch['id']}/seal"), 200)
    route, source = source_create(
        client,
        pid,
        {
            "kind": "recorded",
            "batch_id": batch["id"],
            "manifest_sha256": sealed["manifest_sha256"],
        },
    )
    with client.app.state.session_factory() as session:
        observation = session.scalar(
            select(FieldCaptureObservation).where(
                FieldCaptureObservation.id == sealed["observations"][0]["id"]
            )
        )
        original = resolve_managed_project_path(client.app.state.settings, observation.managed_path)
    initial_bytes = original.read_bytes()
    original.write_bytes(b"Temporary generated fixture corruption")
    retry_key = str(uuid4())
    assert capture(client, route, source, retry_key).status_code == 409
    down = check(client.get(route), 200)
    assert down["state"] == "disconnected" and down["cursor"] == 0
    assert down["next_retry_at"] == "2025-08-12T00:00:05Z"
    assert (
        client.patch(
            f"{route}/state", json={"revision": down["revision"], "action": "resume"}
        ).status_code
        == 409
    )
    original.write_bytes(initial_bytes)
    now += timedelta(seconds=6)
    check(
        client.patch(f"{route}/state", json={"revision": down["revision"], "action": "resume"}), 200
    )
    first = check(capture(client, route, source, retry_key), 200)["receipt"]
    second = check(capture(client, route, source, str(uuid4())), 200)["receipt"]
    assert first["time"]["captured_at_utc"] == "2024-09-12T14:00:00Z"
    assert first["time"]["uncertainty_seconds"] is None
    assert second["time"]["clock"]["state"] == "unknown"
    assert second["time"]["captured_at_utc"] is None
    for ordinal, receipt in enumerate((first, second)):
        assert receipt["ordinal"] == ordinal
        assert receipt["media"]["sha256"] == sha256(initial_bytes).hexdigest()
        assert receipt["media"]["field_observation_id"] == sealed["observations"][ordinal]["id"]
    assert check(client.get(route), 200)["state"] == "exhausted"
    assert capture(client, route, source, str(uuid4())).status_code == 409
    assert check(client.get(f"{route}/captures"), 200)["total"] == 2


def test_local_camera_remains_unopened_without_consent_and_does_not_recapture_on_retry(
    client, monkeypatch
):
    now = datetime(2025, 8, 12, tzinfo=UTC)
    attempts = []
    monkeypatch.setattr(acquisition_sources, "utc_now", lambda: now)

    def camera(index, _directory):
        attempts.append(index)
        if len(attempts) == 1:
            raise CameraUnavailable("The selected local camera did not return a frame")
        return LocalCameraFrame(png(), now, 0.02)

    monkeypatch.setattr(acquisition_sources, "capture_local_camera", camera)
    route, source = source_create(client, project(client), {"kind": "camera", "camera_index": 2})
    capture_key = str(uuid4())
    assert capture(client, route, source, capture_key, confirm_camera=True).status_code == 409
    assert attempts == []
    approved = check(
        client.patch(f"{route}/state", json={"action": "approve_camera", "revision": 1}), 200
    )
    assert attempts == []
    assert capture(client, route, source, capture_key).status_code == 409
    assert attempts == []
    assert capture(client, route, source, capture_key, confirm_camera=True).status_code == 409
    disconnected = check(client.get(route), 200)
    assert disconnected["cursor"] == 0 and disconnected["local_consent_until"] is None
    assert disconnected["state"] == "disconnected"
    now += timedelta(seconds=6)
    resumed = check(
        client.patch(
            f"{route}/state", json={"action": "resume", "revision": disconnected["revision"]}
        ),
        200,
    )
    assert capture(client, route, source, capture_key, confirm_camera=True).status_code == 409
    check(
        client.patch(
            f"{route}/state", json={"action": "approve_camera", "revision": resumed["revision"]}
        ),
        200,
    )
    saved = check(capture(client, route, source, capture_key, confirm_camera=True), 200)
    assert saved["receipt"]["time"]["captured_at_utc"] is None
    assert saved["receipt"]["time"]["clock"]["state"] == "unknown"
    assert saved["receipt"]["time"]["host_received_at_utc"] == "2025-08-12T00:00:06Z"
    assert saved["receipt"]["time"]["host_read_elapsed_seconds"] == 0.02
    now += timedelta(minutes=16)
    assert capture(client, route, source, str(uuid4()), confirm_camera=True).status_code == 409
    assert check(capture(client, route, source, capture_key), 200) == saved
    assert check(client.get(f"{route}/captures/{saved['receipt']['id']}"), 200) == saved
    assert attempts == [2, 2]
    assert check(client.get(route), 200)["cursor"] == 1
    assert (
        approved["source_sha256"] == resumed["source_sha256"] == saved["receipt"]["source_sha256"]
    )
