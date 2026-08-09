from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from reefvision.config import Settings
from reefvision.domain.errors import ValidationError
from reefvision.services.workflow_vlm import (
    CloudVlmProviderError,
    VlmClassDefinition,
    run_vlm_detection,
)


@pytest.fixture
def classes() -> list[VlmClassDefinition]:
    return [
        VlmClassDefinition(
            label_class_id="class-open",
            name="Open polyp",
            scientific_name="Swiftia exserta",
            state_name="open",
        )
    ]


def _settings(tmp_path: Path, provider: str) -> Settings:
    kwargs: dict[str, Any] = {
        "data_dir": tmp_path,
        "cloud_inference_enabled": True,
    }
    kwargs[f"{provider}_api_key"] = f"secret-{provider}"
    return Settings(**kwargs)


def _run(
    settings: Settings,
    provider: str,
    client: httpx.Client,
    classes: list[VlmClassDefinition],
) -> dict[str, Any]:
    return run_vlm_detection(
        settings,
        provider=provider,
        model=f"test-{provider}-vision",
        prompt="Find every visible coral polyp.",
        classes=classes,
        image_id="image-1",
        image_bytes=b"fake-image-bytes",
        media_type="image/jpeg",
        image_width=1000,
        image_height=500,
        client=client,
    )


def test_openai_vlm_uses_structured_output_and_normalizes_pixels(
    tmp_path: Path,
    classes: list[VlmClassDefinition],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/responses"
        assert request.headers["authorization"] == "Bearer secret-openai"
        body = json.loads(request.content)
        assert body["store"] is False
        assert body["text"]["format"]["type"] == "json_schema"
        assert body["input"][0]["content"][1]["type"] == "input_image"
        output = {
            "detections": [
                {"label_class_id": "class-open", "box_2d": [100, 200, 500, 600]}
            ]
        }
        return httpx.Response(
            200,
            json={
                "id": "resp-openai",
                "usage": {"input_tokens": 10, "output_tokens": 8},
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {"type": "output_text", "text": json.dumps(output)}
                        ],
                    }
                ],
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = _run(_settings(tmp_path, "openai"), "openai", client, classes)

    detection = result["detections"][0]
    assert detection["label_class_id"] == "class-open"
    assert detection["predicted_label"] == "Open polyp"
    assert detection["confidence_kind"] == "vote_only_not_calibrated"
    assert detection["box"] == {
        "x_min": 200.0,
        "y_min": 50.0,
        "x_max": 600.0,
        "y_max": 250.0,
    }
    assert result["response_id"] == "resp-openai"
    assert result["usage"]["input_tokens"] == 10
    assert "secret-openai" not in json.dumps(result)


def test_gemini_vlm_uses_generate_content_inline_image_and_structured_schema(
    tmp_path: Path,
    classes: list[VlmClassDefinition],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1beta/models/test-gemini-vision:generateContent"
        assert request.headers["x-goog-api-key"] == "secret-gemini"
        body = json.loads(request.content)
        assert body["contents"][0]["role"] == "user"
        parts = body["contents"][0]["parts"]
        assert parts[0]["text"]
        assert parts[1]["inline_data"]["mime_type"] == "image/jpeg"
        assert parts[1]["inline_data"]["data"]
        response_format = body["generationConfig"]["responseFormat"]["text"]
        assert response_format["mimeType"] == "application/json"
        assert response_format["schema"]["required"] == ["detections"]
        return httpx.Response(
            200,
            json={
                "usageMetadata": {
                    "promptTokenCount": 11,
                    "candidatesTokenCount": 7,
                },
                "candidates": [
                    {
                        "content": {
                            "role": "model",
                            "parts": [
                                {
                                    "text": json.dumps(
                                        {
                                            "detections": [
                                                {
                                                    "label_class_id": "class-open",
                                                    "box_2d": [0, 0, 1000, 1000],
                                                }
                                            ]
                                        }
                                    )
                                }
                            ],
                        }
                    }
                ],
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = _run(_settings(tmp_path, "gemini"), "gemini", client, classes)

    assert result["provider"] == "gemini"
    assert result["response_id"] is None
    assert result["detections"][0]["box"]["x_max"] == 1000.0
    assert result["detections"][0]["box"]["y_max"] == 500.0
    assert result["usage"]["promptTokenCount"] == 11
    assert "secret-gemini" not in json.dumps(result)


def test_anthropic_vlm_forces_detection_tool_output(
    tmp_path: Path,
    classes: list[VlmClassDefinition],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/messages"
        assert request.headers["x-api-key"] == "secret-anthropic"
        body = json.loads(request.content)
        assert body["tool_choice"] == {"type": "tool", "name": "submit_detections"}
        assert body["messages"][0]["content"][0]["type"] == "image"
        return httpx.Response(
            200,
            json={
                "id": "msg-anthropic",
                "usage": {"input_tokens": 13, "output_tokens": 9},
                "content": [
                    {
                        "type": "tool_use",
                        "name": "submit_detections",
                        "input": {
                            "detections": [
                                {
                                    "label_class_id": "class-open",
                                    "box_2d": [250, 250, 750, 750],
                                }
                            ]
                        },
                    }
                ],
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = _run(_settings(tmp_path, "anthropic"), "anthropic", client, classes)

    assert result["provider"] == "anthropic"
    assert result["response_id"] == "msg-anthropic"
    assert result["detections"][0]["box"] == {
        "x_min": 250.0,
        "y_min": 125.0,
        "x_max": 750.0,
        "y_max": 375.0,
    }
    assert "secret-anthropic" not in json.dumps(result)


def test_cloud_vlm_is_opt_in(classes: list[VlmClassDefinition]) -> None:
    settings = Settings(cloud_inference_enabled=False, openai_api_key="secret")
    with pytest.raises(ValidationError, match="Cloud Auto Label is disabled"):
        run_vlm_detection(
            settings,
            provider="openai",
            model="test",
            prompt="test",
            classes=classes,
            image_id="image-1",
            image_bytes=b"image",
            media_type="image/jpeg",
            image_width=100,
            image_height=100,
        )


def test_provider_failure_is_not_treated_as_model_disagreement(
    tmp_path: Path,
    classes: list[VlmClassDefinition],
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"message": "rate limited"}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(CloudVlmProviderError) as exc_info:
            _run(_settings(tmp_path, "openai"), "openai", client, classes)

    assert exc_info.value.provider == "openai"
    assert exc_info.value.status_code == 429
    assert exc_info.value.retryable is True
