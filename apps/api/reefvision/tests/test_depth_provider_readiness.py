from __future__ import annotations

import json
from pathlib import Path

from reefvision.ml import depth_runtime


def install_dependency_stubs(monkeypatch) -> None:
    monkeypatch.setattr(
        depth_runtime.importlib.util,
        "find_spec",
        lambda name: object() if name in {"torch", "transformers", "huggingface_hub"} else None,
    )


def write_checkpoint(checkpoint: Path, *, metric: bool = False) -> None:
    checkpoint.mkdir()
    config: dict[str, object] = {"model_type": "depth_anything"}
    if metric:
        config.update(
            {
                "depth_estimation_type": "metric",
                "max_depth": 20,
            }
        )
    (checkpoint / "config.json").write_text(json.dumps(config), encoding="utf-8")
    (checkpoint / "preprocessor_config.json").write_text("{}", encoding="utf-8")
    (checkpoint / "model.safetensors").write_bytes(b"weights")


def test_local_depth_checkpoint_directory_is_verified(tmp_path: Path, monkeypatch) -> None:
    install_dependency_stubs(monkeypatch)
    checkpoint = tmp_path / "depth-model"
    write_checkpoint(checkpoint)

    result = depth_runtime.inspect_depth_provider_readiness(
        provider_id="depth_anything_v2_relative",
        model_id=str(checkpoint),
        device="cpu",
        local_files_only=True,
    )
    assert result["ready"] is True
    assert result["model_source"] == "local_path"


def test_local_depth_checkpoint_requires_processor_metadata(
    tmp_path: Path,
    monkeypatch,
) -> None:
    install_dependency_stubs(monkeypatch)
    checkpoint = tmp_path / "depth-model"
    checkpoint.mkdir()
    (checkpoint / "config.json").write_text(
        json.dumps({"model_type": "depth_anything"}),
        encoding="utf-8",
    )
    (checkpoint / "model.safetensors").write_bytes(b"weights")

    result = depth_runtime.inspect_depth_provider_readiness(
        provider_id="depth_anything_v2_relative",
        model_id=str(checkpoint),
        device="cpu",
        local_files_only=True,
    )
    assert result["ready"] is False
    assert "preprocessor_config.json" in str(result["reason"])


def test_relative_checkpoint_is_blocked_for_metric_provider(
    tmp_path: Path,
    monkeypatch,
) -> None:
    install_dependency_stubs(monkeypatch)
    checkpoint = tmp_path / "relative-depth-model"
    write_checkpoint(checkpoint)

    result = depth_runtime.inspect_depth_provider_readiness(
        provider_id="depth_anything_v2_metric",
        model_id=str(checkpoint),
        device="cpu",
        local_files_only=True,
    )
    assert result["ready"] is False
    assert "requires a metric" in str(result["reason"])


def test_metric_checkpoint_is_verified(tmp_path: Path, monkeypatch) -> None:
    install_dependency_stubs(monkeypatch)
    checkpoint = tmp_path / "metric-depth-model"
    write_checkpoint(checkpoint, metric=True)

    result = depth_runtime.inspect_depth_provider_readiness(
        provider_id="depth_anything_v2_metric",
        model_id=str(checkpoint),
        device="cpu",
        local_files_only=True,
    )
    assert result["ready"] is True
    assert result["model_source"] == "local_path"


def test_metric_checkpoint_requires_positive_max_depth(
    tmp_path: Path,
    monkeypatch,
) -> None:
    install_dependency_stubs(monkeypatch)
    checkpoint = tmp_path / "metric-depth-model"
    checkpoint.mkdir()
    (checkpoint / "config.json").write_text(
        json.dumps(
            {
                "model_type": "depth_anything",
                "depth_estimation_type": "metric",
                "max_depth": 0,
            }
        ),
        encoding="utf-8",
    )
    (checkpoint / "preprocessor_config.json").write_text("{}", encoding="utf-8")
    (checkpoint / "model.safetensors").write_bytes(b"weights")

    result = depth_runtime.inspect_depth_provider_readiness(
        provider_id="depth_anything_v2_metric",
        model_id=str(checkpoint),
        device="cpu",
        local_files_only=True,
    )
    assert result["ready"] is False
    assert "positive max_depth" in str(result["reason"])


def test_missing_local_depth_checkpoint_is_blocked(tmp_path: Path, monkeypatch) -> None:
    install_dependency_stubs(monkeypatch)
    result = depth_runtime.inspect_depth_provider_readiness(
        provider_id="depth_anything_v2_relative",
        model_id=str(tmp_path / "missing-model"),
        device="cpu",
        local_files_only=True,
    )
    assert result["ready"] is False
    assert result["model_source"] == "missing"


def test_uncached_remote_model_requires_explicit_network(monkeypatch) -> None:
    install_dependency_stubs(monkeypatch)

    class Hub:
        @staticmethod
        def snapshot_download(**_kwargs):
            raise RuntimeError("not cached")

    monkeypatch.setitem(__import__("sys").modules, "huggingface_hub", Hub)
    result = depth_runtime.inspect_depth_provider_readiness(
        provider_id="depth_anything_v2_relative",
        model_id="depth-anything/example",
        device="cpu",
        local_files_only=False,
    )
    assert result["ready"] is True
    assert result["requires_network"] is True
    assert result["model_source"] == "remote"
