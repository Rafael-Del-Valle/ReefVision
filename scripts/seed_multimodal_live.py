"""Create a disposable paired acoustic/reflectance control with known spatial and temporal truth."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import wave
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from PIL import Image


def seed(http: TestClient) -> dict[str, Any]:
    from reefvision.tests.test_annotations import create_project
    from reefvision.tests.test_ecology_identity_registry_1_2 import _register
    from reefvision.tests.test_images import import_one
    from reefvision.tests.test_reviewer_lab_v15 import role_fixture, successful

    project = create_project(http, "Generated paired station survey")
    project_id = project["id"]
    base = f"/api/v1/projects/{project_id}"
    organism = "fixture-colony"
    successful(_register(http, project_id, organism), 201)
    _, _, roles = role_fixture(http, project_id)
    root = base + "/ecology/organisms/" + organism
    form_exposures = []
    grid = "Station plate pixels"
    for i, (red, near) in enumerate([(20, 60), (40, 60)]):
        bands = []
        for j, (name, dn, nm) in enumerate([("Red", red, 660), ("NIR", near, 800)]):
            pixels = np.full((8, 8), 90 - 10 * i - 7 * j, dtype=np.uint8)
            pixels[2:6, 2:6] = dn
            stream = BytesIO()
            Image.fromarray(pixels).save(stream, format="PNG")
            content = stream.getvalue()
            filename = f"visit-{i}-{name}.png"
            img = import_one(
                http, project_id, filename=filename, relative_path=filename, content=content
            )["successful"][0]["image_id"]
            bands.append(
                {
                    "name": name,
                    "wavelength_nm": nm,
                    "bandwidth_nm": 10,
                    "image_id": img,
                    "original_sha256": hashlib.sha256(content).hexdigest(),
                    "calibration": {
                        "dark_dn": 0,
                        "white_dn": 100,
                        "white_reflectance": 1,
                        "reference": "Generated optical panel",
                    },
                }
            )
        spectral = base + "/multispectral"
        acq = successful(
            http.post(
                spectral + "/acquisitions",
                json={
                    "label": f"Station visit {i + 1}",
                    "sensor": "Generated registered monochrome pair",
                    "alignment": {
                        "grid": grid,
                        "reviewer": "Generated optical reviewer",
                        "evidence": "Known fixture target corners",
                        "maximum_residual_px": 0,
                    },
                    "bands": bands,
                },
            ),
            201,
        )
        index = successful(
            http.post(
                spectral + "/acquisitions/" + acq["id"] + "/indices",
                json={"acquisition_sha256": acq["content_sha256"], "positive": 1, "negative": 0},
            ),
            201,
        )
        image_id = bands[0]["image_id"]
        box_id = str(uuid4())
        saved = successful(
            http.put(
                f"/api/v1/images/{image_id}/annotations",
                json={
                    "base_revision": 0,
                    "annotation_status": "reviewed",
                    "annotations": [
                        {
                            "id": box_id,
                            "label_class_id": project["label_classes"][0]["id"],
                            "x_min": 2,
                            "y_min": 2,
                            "x_max": 6,
                            "y_max": 6,
                        }
                    ],
                },
            )
        )
        image = successful(
            http.post(
                root + "/image-evidence",
                json={
                    "image_id": image_id,
                    "expected_identity_revision": 1,
                    "reason": "Generated marked colony inside the station target",
                },
            ),
            201,
        )
        link = successful(
            http.post(
                root + "/annotation-evidence",
                json={
                    "image_evidence_id": image["id"],
                    "annotation_kind": "box",
                    "annotation_id": box_id,
                    "expected_annotation_revision": saved["annotations"][0]["revision"],
                    "reason": "Bound reviewed source-pixel region",
                },
            ),
            201,
        )
        time1, time2 = (("200000", "250000"), ("650000", "700000"))[i]
        form_exposures.append(
            {
                "index_id": index["id"],
                "index_sha256": index["content_sha256"],
                "annotation_evidence_id": link["id"],
                "start_utc": "2026-05-07T12:00:00." + time1 + "Z",
                "end_utc": "2026-05-07T12:00:00." + time2 + "Z",
                "uncertainty_us": 100,
                "clock_evidence": "Generated optical exposure log",
                "station_grid_offset_xy": [0, 0],
                "registration_evidence": "Two surveyed fiducials have the same fixture coordinates",
            }
        )
    samples = np.zeros(8000, dtype="<i2")
    samples[1000:3000] = (12000 * np.sin(2 * np.pi * 440 * np.arange(2000) / 8000)).astype("<i2")
    wav = BytesIO()
    with wave.open(wav, "wb") as sound:
        sound.setnchannels(1)
        sound.setsampwidth(2)
        sound.setframerate(8000)
        sound.writeframes(samples.tobytes())
    asset = successful(
        http.post(
            base + "/bioacoustics/assets",
            files={"file": ("station.wav", wav.getvalue(), "audio/wav")},
        ),
        201,
    )
    url = base + "/bioacoustics/assets/" + asset["id"]
    proposal = successful(
        http.post(
            url + "/proposals",
            json={
                "source_sha256": asset["sha256"],
                "channel": 0,
                "start_sample": 1000,
                "end_sample": 3000,
                "label": "tone",
            },
        ),
        201,
    )
    successful(
        http.post(
            url + "/proposals/" + proposal["id"] + "/reviews",
            json={
                "expected_revision": 0,
                "decision": "accepted",
                "reason": "Generated bounded acoustic tone",
            },
        ),
        201,
    )
    anchor = successful(
        http.post(
            url + "/anchors",
            json={
                "kind": "utc",
                "sample": 0,
                "utc": "2026-05-07T12:00:00Z",
                "uncertainty_us": 100,
                "evidence": "Known synchronized fixture origin",
                "source_sha256": asset["sha256"],
            },
        ),
        201,
    )
    report = successful(http.post(url + "/reports", json={"anchor_id": anchor["id"]}), 201)
    form = {
        "operation_id": str(uuid4()),
        "name": "Paired optical response at station",
        "audio_report_id": report["id"],
        "audio_report_sha256": report["report_sha256"],
        "event_label": "tone",
        "channel": 0,
        "maximum_time_uncertainty_us": 500,
        "footprint": {
            "grid": grid,
            "station": "Fixture plate 1",
            "bounds_xyxy": [0, 0, 8, 8],
            "registration_error_px": 0.1,
            "maximum_total_error_px": 0.5,
            "evidence": "Generated 8 by 8 fixture station footprint",
        },
        "exposures": form_exposures,
        "full_recording_reviewed": True,
        "coverage_evidence": "Entire generated one-second WAV examined",
        "identity_review": "same organism",
        "identity_evidence": "Generated tagged colony in both signed optical boxes",
    }
    return {
        "project_id": project_id,
        "project_name": project["name"],
        "fixture_role": roles["Reviewer A"][1]["Authorization"].removeprefix("Bearer "),
        "form": form,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", type=Path)
    path = parser.parse_args().profile.resolve()
    path.mkdir(parents=True, exist_ok=False)
    os.environ.update(
        REEFVISION_DATA_DIR=str(path),
        REEFVISION_DATABASE_URL=f"sqlite:///{(path / 'reefvision.db').as_posix()}",
        REEFVISION_BACKGROUND_WORKER_ENABLED="false",
    )
    from reefvision.config import clear_settings_cache
    from reefvision.main import create_app

    clear_settings_cache()
    config = Config(str(Path(__file__).resolve().parents[1] / "apps/api/alembic.ini"))
    command.upgrade(config, "head")
    with TestClient(create_app()) as http:
        receipt = seed(http)
    (path / "multimodal-fixture.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(path / "multimodal-fixture.json")
