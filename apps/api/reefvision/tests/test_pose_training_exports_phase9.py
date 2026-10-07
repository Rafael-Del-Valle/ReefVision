from __future__ import annotations

import io
import json
import zipfile

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from reefvision.services import pose_training_exports as export_module
from reefvision.services.pose_interoperability import (
    PoseInteroperabilityService,
)
from reefvision.tests.test_pose_interoperability import (
    _FakeSio,
)
from reefvision.tests.test_pose_training_datasets_phase9 import (
    _verified_round,
)


class _FakeCapture:
    def __init__(
        self,
        _path: str,
    ) -> None:
        self.index = 0
        self.opened = True

    def isOpened(
        self,
    ) -> bool:
        return self.opened

    def read(
        self,
    ) -> tuple[
        bool,
        np.ndarray | None,
    ]:
        if self.index >= 30:
            return (
                False,
                None,
            )

        value = self.index % 255

        frame = np.full(
            (
                240,
                320,
                3,
            ),
            value,
            dtype=np.uint8,
        )

        self.index += 1

        return (
            True,
            frame,
        )

    def release(
        self,
    ) -> None:
        self.opened = False


def _frozen_dataset(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, object]:
    (
        _,
        _,
        _,
        round_payload,
    ) = _verified_round(
        client,
        monkeypatch,
    )

    response = client.post(
        f"/api/v1/pose-active-learning-rounds/{round_payload['id']}/training-dataset",
        json={
            "name": "Phase 9B frozen poses",
            "created_by": "scientist",
        },
    )

    assert response.status_code == 201, response.text

    return response.json()


@pytest.mark.parametrize(
    "export_format",
    [
        "coco",
        "dlc_csv",
        "ultralytics_pose",
        "slp",
        "nwb",
    ],
)
def test_frozen_dataset_exports_exact_frames_and_loss_manifest(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    export_format: str,
) -> None:
    dataset = _frozen_dataset(
        client,
        monkeypatch,
    )

    monkeypatch.setattr(
        cv2,
        "VideoCapture",
        _FakeCapture,
    )

    monkeypatch.setattr(
        PoseInteroperabilityService,
        "_sleap_io",
        staticmethod(lambda: _FakeSio),
    )

    response = client.get(
        f"/api/v1/pose-training-datasets/{dataset['id']}/export",
        params={
            "format": export_format,
        },
    )

    assert response.status_code == 200, response.text

    assert response.headers["x-reefvision-pose-training-format"] == export_format

    assert response.headers["x-reefvision-pose-training-lossy"] == "true"

    assert len(response.headers["x-reefvision-pose-training-bundle-sha256"]) == 64

    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = set(archive.namelist())

        manifest = json.loads(archive.read("reefvision-pose-training-export-manifest.json"))

        assert manifest["schema_version"] == "pose-training-external-export-0001"

        assert manifest["format"] == export_format

        assert manifest["truth_policy"] == "scientist_verified_only"

        assert manifest["dataset"]["dataset_manifest_sha256"] == dataset["manifest_sha256"]

        assert manifest["native_loss_policy"]["lossy_native_artifact"] is True

        frames = manifest["frame_extraction"]["frames"]

        assert len(frames) == 1

        frame_record = frames[0]

        assert frame_record["path"] in names

        assert len(frame_record["sha256"]) == 64

        frame_bytes = archive.read(frame_record["path"])

        decoded = cv2.imdecode(
            np.frombuffer(
                frame_bytes,
                dtype=np.uint8,
            ),
            cv2.IMREAD_COLOR,
        )

        assert decoded is not None

        expected_value = int(frame_record["source_frame_index"]) % 255

        assert (
            int(
                decoded[
                    0,
                    0,
                    0,
                ]
            )
            == expected_value
        )

        node_names = manifest["pose_schema"]["external_node_names"]

        assert node_names == [
            "tentacle__1",
            "tentacle__2",
        ]

        assert len(manifest["annotations"]) == 1

        if export_format == "coco":
            assert "annotations/instances_pose.json" in names

            coco = json.loads(archive.read("annotations/instances_pose.json"))

            assert coco["categories"][0]["keypoints"] == node_names

        elif export_format == "dlc_csv":
            assert "CollectedData_ReefVision.csv" in names

            csv_text = archive.read("CollectedData_ReefVision.csv").decode("utf-8")

            assert "tentacle__1" in csv_text
            assert "tentacle__2" in csv_text

        elif export_format == "ultralytics_pose":
            assert "data.yaml" in names

            assert any(name.startswith("labels/train/") and name.endswith(".txt") for name in names)

            yaml_text = archive.read("data.yaml").decode("utf-8")

            assert "reefvision_keypoint_names" in yaml_text

        elif export_format == "slp":
            assert "dataset.pose.slp" in names

        else:
            assert "dataset.pose.nwb" in names


def test_text_training_exports_do_not_require_sleap_io(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset = _frozen_dataset(
        client,
        monkeypatch,
    )

    monkeypatch.setattr(
        cv2,
        "VideoCapture",
        _FakeCapture,
    )

    def _should_not_run() -> object:
        raise AssertionError("SLEAP-IO should not be required for COCO export")

    monkeypatch.setattr(
        PoseInteroperabilityService,
        "_sleap_io",
        staticmethod(_should_not_run),
    )

    response = client.get(
        f"/api/v1/pose-training-datasets/{dataset['id']}/export",
        params={
            "format": "coco",
        },
    )

    assert response.status_code == 200, response.text


def test_training_export_fails_closed_on_source_video_checksum_mismatch(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset = _frozen_dataset(
        client,
        monkeypatch,
    )

    monkeypatch.setattr(
        export_module,
        "sha256_file",
        lambda _path: "0" * 64,
    )

    response = client.get(
        f"/api/v1/pose-training-datasets/{dataset['id']}/export",
        params={
            "format": "coco",
        },
    )

    assert response.status_code == 409

    assert "source video bytes differ" in response.text.lower()
