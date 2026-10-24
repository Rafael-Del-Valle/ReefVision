"""Read-only training-log tail security and API regression tests for 1.0.3."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from reefvision.api.routes import training as training_routes
from reefvision.config import Settings


def test_missing_log_does_not_fabricate_output(tmp_path: Path) -> None:
    assert training_routes._training_log_tail(None, tmp_path) == {
        "available": False,
        "text": "",
    }
    assert training_routes._training_log_tail("missing.log", tmp_path) == {
        "available": False,
        "text": "",
    }


def test_log_tail_is_bounded_and_read_only(tmp_path: Path) -> None:
    log = tmp_path / "training.log"
    original = b"earlier epochs\n" + b"x" * 20000 + b"\ntrain/box_loss=0.25\n"
    log.write_bytes(original)
    result = training_routes._training_log_tail(str(log), tmp_path)
    assert result["available"] is True
    assert isinstance(result["text"], str)
    assert result["text"].endswith("train/box_loss=0.25\n")
    assert len(result["text"].encode("utf-8")) <= 16384
    assert log.read_bytes() == original


@pytest.mark.parametrize("filename", ["../private.log", "reefvision.db", "private.csv"])
def test_log_tail_rejects_unsafe_paths(tmp_path: Path, filename: str) -> None:
    if filename.startswith("../"):
        (tmp_path.parent / "private.log").write_text("private", encoding="utf-8")
    else:
        (tmp_path / filename).write_text("private", encoding="utf-8")
    with pytest.raises(HTTPException) as error:
        training_routes._training_log_tail(filename, tmp_path)
    assert error.value.status_code == 403


def test_log_tail_strips_terminal_control_sequences(tmp_path: Path) -> None:
    log = tmp_path / "training.log"
    original = (
        b"\x1b[2J\x1b[31mEpoch 2\x1b[0m\n"
        b"\x1b]0;Spoofed terminal title\x07"
        b"train/box_loss=0.25\x00\x08\n"
    )
    log.write_bytes(original)

    result = training_routes._training_log_tail("training.log", tmp_path)

    assert result == {
        "available": True,
        "text": "Epoch 2\ntrain/box_loss=0.25\n",
    }
    assert log.read_bytes() == original


def test_log_tail_strips_hyperlinks_graphics_and_carriage_return_rewrites(
    tmp_path: Path,
) -> None:
    """Terminal payloads cannot spoof or overwrite actual persisted loss values."""
    log = tmp_path / "training.log"
    original = (
        b"epoch 3\rtrain/box_loss=0.20\n"
        b"\x1b]8;;https://example.invalid\x1b\\"
        b"train/cls_loss=0.30"
        b"\x1b]8;;\x1b\\\n"
        b"\x1bPgraphics payload\x1b\\"
        b"\x1b_private APC payload\x1b\\"
        b"\x1b^private PM payload\x1b\\"
        b"\x1b[2Ktrain/dfl_loss=0.10\n"
    )
    log.write_bytes(original)

    assert training_routes._training_log_tail("training.log", tmp_path) == {
        "available": True,
        "text": ("epoch 3\ntrain/box_loss=0.20\ntrain/cls_loss=0.30\ntrain/dfl_loss=0.10\n"),
    }
    assert log.read_bytes() == original


def test_log_tail_discards_unterminated_terminal_title(tmp_path: Path) -> None:
    log = tmp_path / "training.log"
    original = b"train/box_loss=0.25\n\x1b]0;Spoofed terminal title"
    log.write_bytes(original)

    assert training_routes._training_log_tail("training.log", tmp_path) == {
        "available": True,
        "text": "train/box_loss=0.25\n",
    }
    assert log.read_bytes() == original


def test_log_tail_strips_bidi_spoofing(tmp_path: Path) -> None:
    """Invisible Unicode direction controls must not spoof scientific losses."""
    log = tmp_path / "training.log"
    original = (
        "train/box_loss=\u202e0.25\u202c\n"
        "train/cls_loss=\u20660.30\u2069\n"
        "train/dfl_loss=\u200e0.10\u200f\n"
        "sensor=24 °C; scale=10 µm\n"
    ).encode("utf-8")
    log.write_bytes(original)

    assert training_routes._training_log_tail("training.log", tmp_path) == {
        "available": True,
        "text": (
            "train/box_loss=0.25\n"
            "train/cls_loss=0.30\n"
            "train/dfl_loss=0.10\n"
            "sensor=24 °C; scale=10 µm\n"
        ),
    }
    assert log.read_bytes() == original


def test_training_log_api_uses_persisted_run_path_only(
    client: TestClient,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log = test_settings.resolved_data_dir / "training.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("epoch 2 train/cls_loss=0.44\n", encoding="utf-8")
    looked_up: list[str] = []

    def fake_service(_request: object, _session: object) -> SimpleNamespace:
        def get_run(run_id: str) -> SimpleNamespace:
            looked_up.append(run_id)
            return SimpleNamespace(logs_path=str(log))

        return SimpleNamespace(get_run=get_run)

    monkeypatch.setattr(training_routes, "service", fake_service)
    response = client.get("/api/v1/training-runs/run-1/logs/tail")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "available": True,
        "text": "epoch 2 train/cls_loss=0.44\n",
    }
    assert looked_up == ["run-1"]
