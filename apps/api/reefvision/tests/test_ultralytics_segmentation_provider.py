from __future__ import annotations

from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
from PIL import Image

import reefvision.ml.segmentation as segmentation_module
from reefvision.ml.providers import DetectionSettings, PixelBox
from reefvision.ml.segmentation import UltralyticsSegmentationProvider

pytestmark = pytest.mark.unit


class FakeUltralyticsModel:
    def __init__(self, results: list[Any]) -> None:
        self.results = results
        self.names: dict[int, str] = {}
        self.last_predict: dict[str, Any] | None = None

    def predict(self, source: str, **kwargs: Any) -> list[Any]:
        self.last_predict = {"source": source, **kwargs}
        return self.results


def _source_image(tmp_path: Path, *, size: tuple[int, int] = (12, 8)) -> Path:
    path = tmp_path / "source.png"
    Image.new("RGB", size, (10, 20, 30)).save(path)
    return path


def _result(
    *,
    boxes: list[list[float]],
    confidences: list[float],
    classes: list[float],
    polygons: Any,
    mask_data: Any,
    names: dict[int, str],
) -> Any:
    return SimpleNamespace(
        boxes=SimpleNamespace(
            xyxy=np.asarray(boxes, dtype=np.float32),
            conf=np.asarray(confidences, dtype=np.float32),
            cls=np.asarray(classes, dtype=np.float32),
        ),
        masks=SimpleNamespace(xy=polygons, data=mask_data),
        names=names,
    )


def _predict(
    monkeypatch: pytest.MonkeyPatch,
    image_path: Path,
    results: list[Any],
) -> tuple[FakeUltralyticsModel, list[Any]]:
    monkeypatch.setattr(segmentation_module, "resolve_torch_device", lambda _device: "cpu")
    model = FakeUltralyticsModel(results)
    provider = UltralyticsSegmentationProvider()
    provider._model = model
    predictions = provider.predict(
        image_path,
        DetectionSettings(
            confidence_threshold=0.25,
            iou_threshold=0.7,
            device="cpu",
        ),
    )
    return model, predictions


def test_ultralytics_segment_prefers_valid_reviewable_polygon(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image_path = _source_image(tmp_path)
    result = _result(
        boxes=[[1.0, 1.0, 7.0, 6.0]],
        confidences=[0.93],
        classes=[1.0],
        polygons=[
            np.asarray(
                [[1.0, 1.0], [7.0, 1.0], [7.0, 6.0], [1.0, 6.0], [1.0, 1.0]],
                dtype=np.float32,
            )
        ],
        mask_data=np.ones((1, 2, 3), dtype=np.float32),
        names={0: "coral", 1: "sponge"},
    )

    model, predictions = _predict(monkeypatch, image_path, [result])

    assert len(predictions) == 1
    prediction = predictions[0]
    assert prediction.label == "sponge"
    assert prediction.class_index == 1
    assert prediction.confidence == pytest.approx(0.93)
    assert prediction.box == PixelBox(x_min=1.0, y_min=1.0, x_max=7.0, y_max=6.0)
    assert prediction.polygon == [[1.0, 1.0], [7.0, 1.0], [7.0, 6.0], [1.0, 6.0]]
    assert prediction.mask_png_bytes is None
    assert model.last_predict == {
        "source": str(image_path),
        "conf": 0.25,
        "iou": 0.7,
        "device": "cpu",
        "retina_masks": True,
        "verbose": False,
    }


def test_ultralytics_segment_falls_back_to_source_sized_binary_png(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image_path = _source_image(tmp_path)
    result = _result(
        boxes=[[2.0, 1.0, 10.0, 7.0]],
        confidences=[0.81],
        classes=[0.0],
        polygons=[
            np.asarray(
                [[2.0, 1.0], [9.0, 7.0], [2.0, 7.0], [9.0, 1.0]],
                dtype=np.float32,
            )
        ],
        mask_data=np.asarray([[[0.0, 1.0, 0.0], [0.0, 1.0, 1.0]]], dtype=np.float32),
        names={0: "coral"},
    )

    _model, predictions = _predict(monkeypatch, image_path, [result])

    assert len(predictions) == 1
    prediction = predictions[0]
    assert prediction.label == "coral"
    assert prediction.class_index == 0
    assert prediction.confidence == pytest.approx(0.81)
    assert prediction.box == PixelBox(x_min=2.0, y_min=1.0, x_max=10.0, y_max=7.0)
    assert prediction.polygon is None
    assert prediction.mask_png_bytes is not None
    with Image.open(BytesIO(prediction.mask_png_bytes)) as mask:
        mask.load()
        assert mask.mode == "L"
        assert mask.size == (12, 8)
        assert set(mask.getdata()) == {0, 255}
        assert mask.getbbox() is not None


@pytest.mark.parametrize(
    "mask_data",
    [
        np.zeros((1, 2, 3), dtype=np.float32),
        np.asarray([0.0, 1.0, 0.0], dtype=np.float32),
        np.asarray([[[0.0, np.nan], [0.0, 1.0]]], dtype=np.float32),
    ],
    ids=["empty", "malformed-shape", "non-finite"],
)
def test_ultralytics_segment_skips_instances_without_valid_mask_geometry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mask_data: Any,
) -> None:
    image_path = _source_image(tmp_path)
    result = _result(
        boxes=[[1.0, 1.0, 5.0, 5.0]],
        confidences=[0.75],
        classes=[0.0],
        polygons=[["malformed-polygon"]],
        mask_data=mask_data,
        names={0: "coral"},
    )

    _model, predictions = _predict(monkeypatch, image_path, [result])

    assert predictions == []


def test_ultralytics_segment_preserves_multiple_instances_classes_and_confidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image_path = _source_image(tmp_path)
    result = _result(
        boxes=[[1.0, 1.0, 5.0, 5.0], [6.0, 2.0, 11.0, 7.0]],
        confidences=[0.97, 0.61],
        classes=[1.0, 0.0],
        polygons=[
            np.asarray([[1.0, 1.0], [5.0, 1.0], [5.0, 5.0], [1.0, 5.0]]),
            np.asarray([[-1.0, 2.0], [11.0, 2.0], [11.0, 7.0], [6.0, 7.0]]),
        ],
        mask_data=np.asarray(
            [
                [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]],
                [[0.0, 0.0, 1.0], [0.0, 1.0, 1.0]],
            ],
            dtype=np.float32,
        ),
        names={0: "coral", 1: "sponge"},
    )

    _model, predictions = _predict(monkeypatch, image_path, [result])

    assert len(predictions) == 2
    assert [(item.label, item.class_index, item.confidence) for item in predictions] == [
        ("sponge", 1, pytest.approx(0.97)),
        ("coral", 0, pytest.approx(0.61)),
    ]
    assert predictions[0].polygon is not None
    assert predictions[0].mask_png_bytes is None
    assert predictions[1].polygon is None
    assert predictions[1].mask_png_bytes is not None
