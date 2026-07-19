from __future__ import annotations

from pathlib import Path
from typing import Any

from reefvision.config import Settings
from reefvision.ml.assist_runtime import AssistRuntime
from reefvision.ml.providers import (
    AssistPrediction,
    BrushStroke,
    PixelBox,
    PixelPoint,
)


class FakePointProvider:
    provider_name = "fake-point-provider"
    provider_version = "1"

    def __init__(self) -> None:
        self.positive_points: list[PixelPoint] = []
        self.negative_points: list[PixelPoint] = []
        self.context_box: PixelBox | None = None
        self.unloaded = False

    def load_model(self, _model_path: Path, _device: str) -> None:
        return None

    def prepare_image(self, _image_path: Path) -> object:
        return object()

    def predict_from_points(
        self,
        _prepared_image: Any,
        positive_points: list[PixelPoint],
        negative_points: list[PixelPoint],
        context_box: PixelBox | None = None,
    ) -> AssistPrediction:
        self.positive_points = list(positive_points)
        self.negative_points = list(negative_points)
        self.context_box = context_box
        return AssistPrediction(
            mask=object(),
            box=PixelBox(x_min=5, y_min=5, x_max=30, y_max=30),
            score=0.9,
        )

    def predict_from_box(
        self,
        _prepared_image: Any,
        box: PixelBox,
    ) -> AssistPrediction:
        return AssistPrediction(mask=object(), box=box, score=0.8)

    def unload_model(self) -> None:
        self.unloaded = True


def test_point_prompts_accumulate_mix_with_brush_and_enter_provenance(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    settings = Settings(data_dir=tmp_path)
    runtime = AssistRuntime(settings)
    provider = FakePointProvider()
    monkeypatch.setattr(runtime, "_provider_for_model", lambda _name: provider)
    monkeypatch.setattr(
        "reefvision.ml.assist_runtime.mask_to_png_base64",
        lambda _mask: "encoded-mask",
    )
    image_path = tmp_path / "image.png"
    model_path = tmp_path / "model.pth"
    image_path.write_bytes(b"image")
    model_path.write_bytes(b"model")
    session = runtime.create_session(
        project_id="project",
        image_id="image",
        image_sha256="a" * 64,
        image_path=image_path,
        model_id="model",
        model_display_name="Point model",
        model_checksum="b" * 64,
        model_path=model_path,
        provider_name="fake",
        provider_version="1",
        device="cpu",
    )
    context = PixelBox(x_min=0, y_min=0, x_max=40, y_max=40)

    pointed = runtime.apply_point_prompts(
        session_id=session.session_id,
        positive_points=[PixelPoint(x=10, y=10)],
        negative_points=[PixelPoint(x=20, y=20)],
        context_box=context,
        image_width=100,
        image_height=100,
    )
    assert pointed.prompt_type == "point_prompt"
    assert pointed.candidate_mask_png_base64 == "encoded-mask"
    assert provider.positive_points == [PixelPoint(x=10, y=10)]
    assert provider.negative_points == [PixelPoint(x=20, y=20)]
    assert provider.context_box == context

    mixed = runtime.apply_brush_prompts(
        session_id=session.session_id,
        strokes=[
            BrushStroke(
                points=[PixelPoint(x=12, y=12)],
                brush_radius=2,
            )
        ],
        mode="add",
        image_width=100,
        image_height=100,
    )
    assert mixed.prompt_type == "mixed_point_brush"
    assert PixelPoint(x=10, y=10) in provider.positive_points
    assert PixelPoint(x=12, y=12) in provider.positive_points
    assert provider.negative_points == [PixelPoint(x=20, y=20)]

    accepted_state, accepted_box, provenance = runtime.accept_session(
        session.session_id
    )
    assert accepted_state.session_id == session.session_id
    assert accepted_box == PixelBox(x_min=5, y_min=5, x_max=30, y_max=30)
    assert provenance["prompt_type"] == "mixed_point_brush"
    assert provenance["positive_points"] == [{"x": 10, "y": 10}]
    assert provenance["negative_points"] == [{"x": 20, "y": 20}]
    assert len(provenance["add_strokes"]) == 1

    reset = runtime.reset_session(session.session_id)
    assert reset.positive_points == []
    assert reset.negative_points == []
    assert reset.add_strokes == []
    assert reset.candidate_prediction is None
