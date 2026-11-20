"""Known-answer bioacoustic fixtures use generated PCM and real project routes."""

import hashlib
import struct
import wave
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from reefvision.tests.test_paired_growth_contrast import _run_graph


def wav_fixture() -> bytes:
    result = BytesIO()
    with wave.open(result, "wb") as recording:
        recording.setnchannels(2)
        recording.setsampwidth(2)
        recording.setframerate(8_000)
        recording.writeframes(struct.pack("<4h", -16_384, 8_192, 16_384, -8_192) * 4_000)
    return result.getvalue()


def assets(client: TestClient, name: str) -> str:
    project = client.post("/api/v1/projects", json={"name": name, "template": "blank"})
    assert project.status_code == 201, project.text
    return f"/api/v1/projects/{project.json()['id']}/bioacoustics/assets"


def recording(client: TestClient, root: str) -> tuple[dict, bytes]:
    original = wav_fixture()
    response = client.post(root, files={"file": ("hydrophone-fixture.wav", original, "audio/wav")})
    assert response.status_code == 201, response.text
    return response.json(), original


def test_import_preserves_wav_and_decimates_each_channel(client: TestClient) -> None:
    root = assets(client, "Generated stereo audio")
    asset, original = recording(client, root)
    assert asset["sha256"] == hashlib.sha256(original).hexdigest()
    assert (
        asset["channel_count"],
        asset["sample_rate_hz"],
        asset["sample_count"],
        asset["bits_per_sample"],
    ) == (2, 8_000, 8_000, 16)
    url = f"{root}/{asset['id']}"
    assert client.get(f"{url}/content").content == original
    partial = client.get(f"{url}/content", headers={"Range": "bytes=0-7"})
    assert partial.status_code == 206 and partial.content == original[:8]
    waveform = client.get(f"{url}/waveform", params={"channel": 1, "bins": 16})
    assert waveform.status_code == 200, waveform.text
    assert len(waveform.json()["peaks"]) == 16
    assert waveform.json()["peaks"][0] == {
        "start_sample": 0,
        "end_sample": 500,
        "minimum": -0.25,
        "maximum": 0.25,
    }
    bad = client.post(root, files={"file": ("truncated.wav", original[:-1], "audio/wav")})
    assert bad.status_code == 400 and "truncated" in bad.text.lower()
    assert client.get(root).json()["total"] == 1
    assert (
        client.get(f"{assets(client, 'Unrelated survey')}/{asset['id']}/content").status_code == 404
    )


def test_review_and_utc_anchor_freeze_a_half_open_interval(client: TestClient) -> None:
    root = assets(client, "Generated reviewed audio")
    asset, _ = recording(client, root)
    url = f"{root}/{asset['id']}"
    source = asset["sha256"]
    proposal_body = {
        "start_sample": 2_000,
        "end_sample": 6_000,
        "channel": 1,
        "label": "Generated pulse",
        "source_sha256": source,
    }
    assert client.post(f"{url}/proposals", json={**proposal_body, "channel": 2}).status_code == 400
    proposal = client.post(f"{url}/proposals", json=proposal_body)
    assert proposal.status_code == 201, proposal.text
    record = proposal.json()
    assert record["status"] == "proposed" and record["review_revision"] == 0
    assert (
        client.post(f"{url}/reports", json={}).json()["snapshot"]["entries"][0]["alignment"][
            "status"
        ]
        == "withheld"
    )
    review_url = f"{url}/proposals/{record['id']}/reviews"
    decision = {
        "expected_revision": 0,
        "decision": "accepted",
        "reason": "Generated fixture pulse reviewed by listening.",
    }
    review = client.post(review_url, json=decision)
    assert review.status_code == 201, review.text
    assert review.json()["reviewer"].startswith("local-user:")
    assert client.post(review_url, json=decision).status_code == 409

    anchor = {
        "kind": "utc",
        "sample": 4_000,
        "utc": "2026-04-17T11:30:00-04:00",
        "uncertainty_us": 200_000,
        "evidence": "Generated date and independently declared UTC offset",
        "source_sha256": source,
    }
    assert (
        client.post(f"{url}/anchors", json={**anchor, "utc": "2026-04-17T11:30:00"}).status_code
        == 422
    )
    anchored = client.post(f"{url}/anchors", json=anchor)
    assert anchored.status_code == 201, anchored.text
    assert anchored.json()["utc"] == "2026-04-17T15:30:00Z"
    report = client.post(f"{url}/reports", json={"anchor_id": anchored.json()["id"]})
    assert report.status_code == 201, report.text
    saved = report.json()
    aligned = saved["snapshot"]["entries"][0]["alignment"]
    assert aligned == {
        "status": "utc",
        "reason": None,
        "start_utc": "2026-04-17T15:29:59.750000Z",
        "end_utc": "2026-04-17T15:30:00.250000Z",
        "start_video_us": None,
        "end_video_us": None,
        "uncertainty_us": 200_000,
    }
    assert client.get(f"{url}/reports/{saved['id']}/export").json() == saved
    assert client.get(f"{url}/reports/{uuid4()}/export").status_code == 404
    assert (
        client.post(f"{url}/anchors", json={**anchor, "utc": "2026-04-17T18:30:00Z"}).status_code
        == 201
    )
    conflicted = client.post(f"{url}/reports", json={"anchor_id": anchored.json()["id"]}).json()
    assert conflicted["snapshot"]["entries"][0]["alignment"]["status"] == "withheld"
    assert "conflict" in conflicted["snapshot"]["entries"][0]["alignment"]["reason"].lower()
    assert client.get(f"{url}/reports/{saved['id']}").json() == saved

    project = asset["project_id"]
    graph = {
        "graph_id": "reviewed-bioacoustic-report",
        "name": "Reviewed bioacoustic report",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "report",
                "node_type": "bioacoustic_report",
                "parameters": {"report_id": saved["id"], "report_sha256": saved["report_sha256"]},
            },
        ],
        "edges": [
            {
                "edge_id": "project-report",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "report",
                "target_port_id": "project",
            }
        ],
    }
    persisted = client.post(f"/api/v1/projects/{project}/workflow-graphs", json={"graph": graph})
    assert persisted.status_code == 201, persisted.text
    replays = [_run_graph(client, project, persisted.json()["id"]) for _ in range(2)]
    assert replays[0]["run"]["id"] != replays[1]["run"]["id"]
    results = []
    for run in replays:
        assert run["run"]["status"] == "succeeded", run
        [result] = [item for item in run["artifacts"] if item["data_type"] == "bioacoustic_report"]
        assert result["payload_json"] == saved
        results.append(result["payload_sha256"])
    assert results[0] == results[1]


def test_anchor_binds_real_project_video_and_never_claims_utc(client: TestClient) -> None:
    root = assets(client, "Audio with a shared video event")
    asset, _ = recording(client, root)
    url = f"{root}/{asset['id']}"
    source = asset["sha256"]
    project = asset["project_id"]
    video_bytes = (
        Path(__file__).resolve().parents[4]
        / "apps/web/tests/e2e/fixtures/synthetic-ordinary-clip.mp4"
    ).read_bytes()
    video = client.post(
        f"/api/v1/projects/{project}/imports/videos",
        files={"file": ("fixture.mp4", video_bytes, "video/mp4")},
    )
    assert video.status_code == 201, video.text
    video_id, video_sha = video.json()["id"], video.json()["sha256"]
    candidate = {
        "kind": "video",
        "sample": 4_000,
        "video_id": video_id,
        "video_sha256": video_sha,
        "video_time_us": 800_000,
        "source_sha256": source,
        "uncertainty_us": 20_000,
        "evidence": "Generated clap in both sources",
    }
    assert (
        client.post(f"{url}/anchors", json={**candidate, "video_sha256": "0" * 64}).status_code
        == 400
    )
    anchor = client.post(f"{url}/anchors", json=candidate)
    assert anchor.status_code == 201, anchor.text
    proposal = client.post(
        f"{url}/proposals",
        json={
            "start_sample": 2_000,
            "end_sample": 6_000,
            "channel": 0,
            "label": "Generated clap",
            "source_sha256": source,
        },
    ).json()
    assert (
        client.post(
            f"{url}/proposals/{proposal['id']}/reviews",
            json={
                "decision": "accepted",
                "reason": "Reviewed the synchronized fixture",
                "expected_revision": 0,
            },
        ).status_code
        == 201
    )

    def alignment(anchor_id: str) -> dict:
        report = client.post(f"{url}/reports", json={"anchor_id": anchor_id})
        assert report.status_code == 201, report.text
        return report.json()["snapshot"]["entries"][0]["alignment"]

    aligned = alignment(anchor.json()["id"])
    assert aligned["status"] == "video" and aligned["start_utc"] is None
    assert (aligned["start_video_us"], aligned["end_video_us"], aligned["uncertainty_us"]) == (
        550_000,
        1_050_000,
        20_000,
    )
    second = client.post(f"{url}/anchors", json={**candidate, "uncertainty_us": 600_000})
    assert second.status_code == 201, second.text
    withheld = alignment(second.json()["id"])
    assert withheld["status"] == "withheld" and "exceed" in withheld["reason"]
