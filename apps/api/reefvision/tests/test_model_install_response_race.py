"""Legacy endpoint rejection must not schedule a background acquisition worker."""

from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.tests.test_annotations import create_project


def test_install_rejection_never_starts_background_thread(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cast(FastAPI, client.app).state.settings, "background_worker_enabled", True)

    def unexpected_start(*args: object) -> None:
        raise AssertionError("Rejected requests must not schedule model acquisition")

    monkeypatch.setattr(
        "reefvision.api.routes.model_catalog._start_model_install_thread", unexpected_start
    )
    project = create_project(client, "No background acquisition")
    response = client.post(
        f"/api/v1/projects/{project['id']}/model-installs/ultralytics%2Fyolo11%2Fdetect%2Fn",
        json={"confirmed": True},
    )
    assert response.status_code == 400
    assert "register" in response.text
