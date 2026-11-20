"""Authenticate generated WAV, immutable review, and typed remapping at the archive boundary."""

from collections.abc import Sequence
from copy import deepcopy
from io import BytesIO
from typing import Any, cast
from uuid import uuid4
from zipfile import ZipFile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.config import Settings
from reefvision.db.models.bioacoustics import BioacousticAsset
from reefvision.domain.errors import ValidationError
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
