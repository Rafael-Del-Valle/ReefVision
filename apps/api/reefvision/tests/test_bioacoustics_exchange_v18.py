"""Authenticate generated WAV, immutable review, and typed remapping at the archive boundary."""

import json
from collections.abc import Sequence
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from typing import Any, cast
from uuid import uuid4
from zipfile import ZipFile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.config import Settings
from reefvision.db.models.bioacoustics import BioacousticAsset
from reefvision.domain.errors import ValidationError
from reefvision.jobs.project_exchange import process_project_exchange_export_job
from reefvision.services.project_exchange import _row
from reefvision.services.project_exchange_bioacoustics_v18 import (
    AUDIO_SECTION_MODELS,
    audio_exchange_records,
    gather_audio_media,
    restore_audio_origin,
    restore_audio_row,
    validate_audio_exchange,
    validate_audio_origin,
)
from reefvision.tests.test_bioacoustics_v18 import assets, recording
from reefvision.tests.test_paired_growth_contrast import _run_graph
from reefvision.tests.test_scientific_project_exchange import (
    MANIFEST,
    database_counts,
    export_archive,
    import_archive,
    rewrite,
)


def _zip(member: str, wav: bytes) -> ZipFile:
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr(member, wav)
    return ZipFile(buffer)


def test_audio_exchange_rebinds_reviewed_ids_and_preserves_original_receipt(
    client: TestClient,
    test_settings: Settings,
) -> None:
    base = assets(client, "Portable generated stereo original")
    asset, wav = recording(client, base)
    project = asset["project_id"]
    url = f"{base}/{asset['id']}"
    source_root = f"projects/{project}"
    proposal_response = client.post(
        f"{url}/proposals",
        json={
            "start_sample": 10,
            "end_sample": 25,
            "channel": 0,
            "label": project,
            "notes": asset["id"],
            "source_sha256": asset["sha256"],
        },
    )
    assert proposal_response.status_code == 201, proposal_response.text
    proposal = proposal_response.json()
    decision = client.post(
        f"{url}/proposals/{proposal['id']}/reviews",
        json={
            "expected_revision": 0,
            "decision": "accepted",
            "reason": proposal["id"],
        },
    )
    assert decision.status_code == 201, decision.text
    anchor = client.post(
        f"{url}/anchors",
        json={
            "kind": "utc",
            "sample": 10,
            "utc": "2026-04-17T15:30:00Z",
            "source_sha256": asset["sha256"],
            "uncertainty_us": 50,
            "evidence": project,
        },
    )
    assert anchor.status_code == 201, anchor.text
    frozen = client.post(f"{url}/reports", json={"anchor_id": anchor.json()["id"]})
    assert frozen.status_code == 201, frozen.text
    original = frozen.json()

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        found = audio_exchange_records(session, project)
        sections = {key: [_row(row) for row in rows] for key, rows in found.items()}
        [(descriptor, input_path)] = gather_audio_media(
            test_settings,
            source_root,
            cast(Sequence[BioacousticAsset], found["bioacoustic_assets"]),
        )
    assert input_path.read_bytes() == wav
    member = str(descriptor["path"])
    with _zip(member, wav) as package:
        validate_audio_exchange(project, source_root, sections, [descriptor], package)
        with pytest.raises(ValidationError, match="original media member"):
            validate_audio_exchange(project, source_root, sections, [], package)
        forged = deepcopy(sections)
        forged["bioacoustic_reviews"][0]["project_id"] = str(uuid4())
        with pytest.raises(ValidationError, match="foreign project ownership"):
            validate_audio_exchange(project, source_root, forged, [descriptor], package)
    with (
        _zip(member, wav[:-1] + bytes([wav[-1] ^ 1])) as package,
        pytest.raises(ValidationError, match="recorded SHA-256"),
    ):
        validate_audio_exchange(project, source_root, sections, [descriptor], package)

    previous: dict[str, Any] = {}
    full_map: dict[str, str] = {}
    for _ in range(2):
        id_map = {
            key: str(uuid4())
            for key in (project, *(row["id"] for rows in sections.values() for row in rows))
        }
        full_map = (
            {first: id_map[latest] for first, latest in full_map.items()} if full_map else id_map
        )
        previous = restore_audio_origin(sections, previous, id_map)
        mapped: dict[str, list[dict[str, Any]]] = {}
        for key in AUDIO_SECTION_MODELS:
            mapped[key] = []
            for row in sections[key]:
                values = deepcopy(row)
                for field in ("id", "project_id", "asset_id", "proposal_id"):
                    if field in values:
                        values[field] = id_map[values[field]]
                restore_audio_row(key, row, values, id_map, {})
                mapped[key].append(values)
        project = id_map[project]
        sections = mapped
        validate_audio_origin(sections, previous, {"id_map": full_map})
        [rewritten] = sections["bioacoustic_reports"]
        receipt = previous[rewritten["id"]]
        assert receipt["original_report_id"] == original["id"]
        assert receipt["original_report_sha256"] == original["report_sha256"]
        assert (
            receipt["local_report_sha256"]
            == rewritten["report_sha256"]
            != original["report_sha256"]
        )
        assert rewritten["snapshot_json"]["source"]["original_asset_id"] == asset["id"]
        local = rewritten["snapshot_json"]["entries"][0]["proposal"]
        assert local["label"] == asset["project_id"] and local["notes"] == asset["id"]
        assert local["latest_review"]["reason"] == proposal["id"]


def test_registered_project_exchange_reopens_original_wav_and_graph_twice(
    client: TestClient,
    test_settings: Settings,
) -> None:
    base = assets(client, "Generated audio-to-video portable proof")
    audio, wav = recording(client, base)
    owner = audio["project_id"]
    url = f"{base}/{audio['id']}"
    input_clip = (
        Path(__file__).resolve().parents[4]
        / "apps/web/tests/e2e/fixtures/synthetic-ordinary-clip.mp4"
    ).read_bytes()
    imported = client.post(
        f"/api/v1/projects/{owner}/imports/videos",
        files={"file": ("fixture.mp4", input_clip, "video/mp4")},
    )
    assert imported.status_code == 201, imported.text
    video = imported.json()
    new_proposal = client.post(
        f"{url}/proposals",
        json={
            "start_sample": 2000,
            "end_sample": 6000,
            "channel": 1,
            "label": "Generated clap",
            "notes": audio["id"],
            "source_sha256": audio["sha256"],
        },
    )
    assert new_proposal.status_code == 201, new_proposal.text
    proposal = new_proposal.json()
    note = video["id"]
    reviewed = client.post(
        f"{url}/proposals/{proposal['id']}/reviews",
        json={
            "expected_revision": 0,
            "decision": "accepted",
            "reason": note,
        },
    )
    assert reviewed.status_code == 201, reviewed.text
    clock = client.post(
        f"{url}/anchors",
        json={
            "kind": "video",
            "sample": 4000,
            "video_id": video["id"],
            "video_sha256": video["sha256"],
            "video_time_us": 800000,
            "source_sha256": audio["sha256"],
            "uncertainty_us": 20_000,
            "evidence": owner,
        },
    )
    assert clock.status_code == 201, clock.text
    frozen = client.post(f"{url}/reports", json={"anchor_id": clock.json()["id"]})
    assert frozen.status_code == 201, frozen.text
    original = frozen.json()
    definition = {
        "graph_id": "portable-bioacoustics",
        "name": "Portable verified audio report",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "report",
                "node_type": "bioacoustic_report",
                "parameters": {
                    "report_id": original["id"],
                    "report_sha256": original["report_sha256"],
                },
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
    graph_response = client.post(
        f"/api/v1/projects/{owner}/workflow-graphs", json={"graph": definition}
    )
    assert graph_response.status_code == 201, graph_response.text
    graph = graph_response.json()
    first_execution = _run_graph(client, owner, graph["id"])
    assert first_execution["run"]["status"] == "succeeded", first_execution

    metadata_only = client.post(
        f"/api/v1/projects/{owner}/exchange-packages", json={"include_media": False}
    )
    assert metadata_only.status_code == 202, metadata_only.text
    queued = metadata_only.json()
    assert not process_project_exchange_export_job(
        test_settings, client.app.state.session_factory, queued["job_id"]
    )
    job = client.get(f"/api/v1/jobs/{queued['job_id']}").json()
    assert job["status"] == "failed" and "original media" in job["error_message"]

    archive = export_archive(client, test_settings, owner, include_generated_artifacts=True)
    with ZipFile(BytesIO(archive)) as package:
        manifest = json.loads(package.read(MANIFEST))
        assert manifest["format_version"] == "1.8"
        [audio_member] = [
            entry for entry in manifest["media"] if entry["kind"] == "bioacoustic_source"
        ]
        assert package.read(audio_member["path"]) == wav
        assert all("bioacoustics/" not in item["path"] for item in manifest["generated_artifacts"])

    def invalid_assessment(_manifest, sections):
        sections["bioacoustic_reports"][0]["snapshot_json"]["source"]["sample_count"] -= 1

    baseline = database_counts(client)
    rejected = import_archive(client, rewrite(archive, invalid_assessment))
    assert rejected.status_code == 400 and "bioacoustic" in rejected.text.lower()
    assert database_counts(client) == baseline
    missing_media = BytesIO()
    with (
        ZipFile(BytesIO(archive)) as current_package,
        ZipFile(missing_media, "w") as incomplete,
    ):
        for name in current_package.namelist():
            if name != audio_member["path"]:
                incomplete.writestr(name, current_package.read(name))
    assert import_archive(client, missing_media.getvalue()).status_code == 400
    assert database_counts(client) == baseline

    for _ in range(2):
        response = import_archive(client, archive)
        assert response.status_code == 201, response.text
        copy = response.json()
        project = copy["project_id"]
        options = copy["package"]["options_json"]
        ids = options["origin_id_map"]
        local = f"/api/v1/projects/{project}/bioacoustics/assets/{ids[audio['id']]}"
        record = client.get(local).json()
        assert record["original_asset_id"] == audio["id"] and record["original_project_id"] == owner
        assert client.get(f"{local}/content").content == wav
        report_response = client.get(f"{local}/reports/{ids[original['id']]}")
        assert report_response.status_code == 200, report_response.text
        report = report_response.json()
        assert report["snapshot"]["anchor"]["video_id"] == ids[video["id"]]
        assert report["snapshot"]["anchor"]["video_sha256"] == video["sha256"]
        assert report["snapshot"]["anchor"]["evidence"] == owner
        assert report["snapshot"]["entries"][0]["proposal"]["latest_review"]["reason"] == note
        assert (
            report["snapshot"]["entries"][0]["alignment"]
            == original["snapshot"]["entries"][0]["alignment"]
        )
        assert (
            options["bioacoustic_report_origins"][report["id"]]["original_report_sha256"]
            == original["report_sha256"]
        )
        historical = client.get(f"/api/v1/workflow-runs/{ids[first_execution['run']['id']]}")
        assert historical.status_code == 200, historical.text
        [historical_artifact] = [
            row
            for row in historical.json()["artifacts"]
            if row["data_type"] == "bioacoustic_report"
        ]
        assert historical_artifact["payload_json"] == report
        output = []
        for _ in range(2):
            replay = _run_graph(client, project, ids[graph["id"]])
            assert replay["run"]["status"] == "succeeded", replay
            [artifact] = [
                row for row in replay["artifacts"] if row["data_type"] == "bioacoustic_report"
            ]
            assert artifact["payload_json"] == report
            output.append(artifact["payload_sha256"])
        assert output[0] == output[1] == historical_artifact["payload_sha256"]
        archive = export_archive(client, test_settings, project)
