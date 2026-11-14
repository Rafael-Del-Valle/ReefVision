from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from reefvision.db.models import ModelRegistration
from reefvision.ml.pose_evaluation import (
    PoseEvaluationLandmark,
    PoseEvaluationProviderExclusion,
    PoseEvaluationSchema,
    create_pose_evaluation_runtime,
)

SCHEMA = PoseEvaluationSchema(
    schema_id="schema-1",
    revision=2,
    content_hash="a" * 64,
    landmarks=(
        PoseEvaluationLandmark("snout-id", "Snout", 0),
        PoseEvaluationLandmark("tail-id", "Tail", 0),
    ),
)


def _model(provider_name: str, metadata: dict[str, object] | None = None) -> ModelRegistration:
    return ModelRegistration(
        id=f"model-{provider_name}",
        project_id="project-1",
        purpose="detector",
        display_name=f"{provider_name} fish",
        source_filename="model.pt",
        managed_path="projects/p1/models/model.pt",
        sha256="b" * 64,
        file_size_bytes=12,
        framework=provider_name,
        task="pose",
        provider_name=provider_name,
        provider_version="1",
        class_map_json={},
        metadata_json=metadata or {},
    )


class _Tensor:
    def __init__(self, value: object) -> None:
        self.value = value

    def tolist(self) -> object:
        return self.value


class _FakeUltralyticsModel:
    def __init__(self, *, instances: list[list[list[float]]]) -> None:
        self.instances = instances
        self.task = "pose"

    def predict(self, **kwargs: object) -> list[object]:
        del kwargs
        confidences = [
            [0.9 - landmark_index * 0.1 for landmark_index, _point in enumerate(instance)]
            for instance in self.instances
        ]
        boxes = [[1.0, 2.0, 9.0, 8.0] for _instance in self.instances]
        return [
            SimpleNamespace(
                keypoints=SimpleNamespace(
                    xy=_Tensor(self.instances),
                    conf=_Tensor(confidences),
                ),
                boxes=SimpleNamespace(xyxy=_Tensor(boxes)),
            )
        ]


def test_reefpose_runtime_preserves_stable_ids_and_native_integrity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from reefvision.ml import pose_evaluation

    prediction = SimpleNamespace(
        landmarks=(
            SimpleNamespace(
                landmark_id="snout-id",
                name="Snout",
                occurrence_index=0,
                x=3.0,
                y=4.0,
                confidence=0.9,
                visibility_state="visible",
            ),
            SimpleNamespace(
                landmark_id="tail-id",
                name="Tail",
                occurrence_index=0,
                x=8.0,
                y=4.0,
                confidence=0.8,
                visibility_state="visible",
            ),
        ),
        bbox=(3.0, 4.0, 8.0, 4.0),
        anatomy_schema_id=SCHEMA.schema_id,
        anatomy_schema_revision=SCHEMA.revision,
        anatomy_integrity_hash="c" * 64,
    )
    fake_predictor = SimpleNamespace(
        device="cpu",
        predict=lambda _image, confidence_threshold: prediction,
    )
    monkeypatch.setattr(
        pose_evaluation,
        "_reefpose_predictor_from_checkpoint",
        lambda _path, *, device: fake_predictor,
    )
    runtime = create_pose_evaluation_runtime(
        _model("reefpose", {"reefpose_anatomy_integrity_hash": "c" * 64}),
        Path("model.pt"),
        SCHEMA,
        "cpu",
    )

    result = runtime.predict(Image.new("RGB", (12, 10), "black"))

    assert [item.landmark_id for item in result.landmarks] == ["snout-id", "tail-id"]
    assert result.schema_id == SCHEMA.schema_id
    assert result.schema_revision == SCHEMA.revision
    assert result.native_integrity_hash == "c" * 64
    assert runtime.visibility_metrics_available is True
    assert runtime.resolved_device == "cpu"


def test_ultralytics_runtime_maps_schema_order_in_source_coordinates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from reefvision.ml import pose_evaluation

    monkeypatch.setattr(
        pose_evaluation,
        "_load_ultralytics_model",
        lambda _path: _FakeUltralyticsModel(instances=[[[3.0, 4.0], [8.0, 7.0]]]),
    )
    monkeypatch.setattr(pose_evaluation, "_resolve_ultralytics_device", lambda _device: "cpu")
    runtime = create_pose_evaluation_runtime(
        _model("ultralytics"),
        Path("model.pt"),
        SCHEMA,
        "cpu",
    )

    result = runtime.predict(Image.new("RGB", (12, 10), "black"))

    assert [(item.landmark_id, item.x, item.y) for item in result.landmarks] == [
        ("snout-id", 3.0, 4.0),
        ("tail-id", 8.0, 7.0),
    ]
    assert result.bbox == (1.0, 2.0, 9.0, 8.0)
    assert runtime.visibility_metrics_available is False


def test_ultralytics_zero_detection_is_a_valid_all_misses_prediction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from reefvision.ml import pose_evaluation

    monkeypatch.setattr(
        pose_evaluation,
        "_load_ultralytics_model",
        lambda _path: _FakeUltralyticsModel(instances=[]),
    )
    monkeypatch.setattr(pose_evaluation, "_resolve_ultralytics_device", lambda _device: "cpu")
    runtime = create_pose_evaluation_runtime(_model("ultralytics"), Path("model.pt"), SCHEMA, "cpu")

    result = runtime.predict(Image.new("RGB", (12, 10), "black"))

    assert result.landmarks == ()
    assert result.bbox is None


@pytest.mark.parametrize(
    ("instances", "expected_code"),
    [
        (
            [
                [[1.0, 1.0], [2.0, 2.0]],
                [[3.0, 3.0], [4.0, 4.0]],
            ],
            "multiple_animals",
        ),
        ([[[1.0, 1.0]]], "landmark_count_mismatch"),
    ],
)
def test_ultralytics_incompatible_output_is_structurally_excluded(
    monkeypatch: pytest.MonkeyPatch,
    instances: list[list[list[float]]],
    expected_code: str,
) -> None:
    from reefvision.ml import pose_evaluation

    monkeypatch.setattr(
        pose_evaluation,
        "_load_ultralytics_model",
        lambda _path: _FakeUltralyticsModel(instances=instances),
    )
    monkeypatch.setattr(pose_evaluation, "_resolve_ultralytics_device", lambda _device: "cpu")
    runtime = create_pose_evaluation_runtime(_model("ultralytics"), Path("model.pt"), SCHEMA, "cpu")

    with pytest.raises(PoseEvaluationProviderExclusion) as error:
        runtime.predict(Image.new("RGB", (12, 10), "black"))

    assert error.value.code == expected_code


def test_sleap_runtime_is_explicitly_excluded_without_importing_optional_runtime() -> None:
    with pytest.raises(PoseEvaluationProviderExclusion) as error:
        create_pose_evaluation_runtime(_model("sleap_nn"), Path("model.zip"), SCHEMA, "cpu")

    assert error.value.code in {"provider_runtime_unavailable", "still_frame_unsupported"}
    assert "sleap" in str(error.value).lower()
