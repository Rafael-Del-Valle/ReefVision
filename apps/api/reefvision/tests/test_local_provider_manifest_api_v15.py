from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.config import Settings
from reefvision.tests.test_annotations import create_project


def _settings(client: TestClient) -> Settings:
    return cast(Settings, cast(FastAPI, client.app).state.settings)


def _write_manifest(
    client: TestClient,
    filename: str,
    *,
    provider_id: str,
    display_name: str = "Local Depth Inspector",
) -> Path:
    directory = _settings(client).resolved_data_dir / "provider-manifests"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    path.write_text(
        json.dumps(
            {
                "manifest_version": 1,
                "provider_id": provider_id,
                "display_name": display_name,
                "provider_version": "0.1.0",
                "description": "A local declaration with no executable adapter.",
                "capabilities": ["image_semantic_segmentation", "cpu_inference"],
                "supported_tasks": ["relative_depth"],
                "availability": {
                    "status": "unavailable",
                    "reason": "A reviewed ReefVision adapter is not installed.",
                },
                "code_license": "Apache-2.0",
                "weight_license": "User supplied",
                "notes": ["Inspection only"],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_manifest_endpoint_merges_local_inspection_record_without_changing_builtins(
    client: TestClient,
) -> None:
    _write_manifest(client, "local-depth.json", provider_id="local_depth")

    response = client.get("/api/v1/advanced-providers/manifests")

    assert response.status_code == 200, response.text
    manifests = {item["provider_id"]: item for item in response.json()}
    assert manifests["grounding_dino"]["source_kind"] == "built_in"
    assert manifests["grounding_dino"]["execution_surface"] == "provider_lab"
    local = manifests["local_depth"]
    assert local["display_name"] == "Local Depth Inspector"
    assert local["source_kind"] == "local_manifest"
    assert local["manifest_version"] == 1
    assert local["source_filename"] == "local-depth.json"
    assert len(local["source_sha256"]) == 64
    assert local["discovery_status"] == "valid"
    assert local["discovery_errors"] == []
    assert local["declared_capabilities"] == [
        "image_semantic_segmentation",
        "cpu_inference",
    ]
    assert local["availability_status"] == "unavailable"
    assert local["availability_reason"] == "A reviewed ReefVision adapter is not installed."
    assert local["execution_supported"] is False
    assert local["execution_surface"] == "blocked"


def test_invalid_and_duplicate_manifests_are_visible_without_breaking_catalog(
    client: TestClient,
) -> None:
    _write_manifest(client, "a-first.json", provider_id="duplicate_local")
    _write_manifest(client, "b-duplicate.json", provider_id="duplicate_local")
    directory = _settings(client).resolved_data_dir / "provider-manifests"
    (directory / "c-invalid.json").write_text("{invalid", encoding="utf-8")

    response = client.get("/api/v1/advanced-providers/manifests")

    assert response.status_code == 200, response.text
    local = [item for item in response.json() if item["source_kind"] == "local_manifest"]
    assert [item["source_filename"] for item in local] == [
        "a-first.json",
        "b-duplicate.json",
        "c-invalid.json",
    ]
    assert [item["discovery_status"] for item in local] == ["valid", "duplicate", "invalid"]
    assert all(item["execution_supported"] is False for item in local)
    assert all(item["execution_surface"] == "blocked" for item in local)
    assert local[1]["discovery_errors"]
    assert local[2]["discovery_errors"]


def test_builtin_shadow_manifest_is_preserved_under_non_executable_record_id(
    client: TestClient,
) -> None:
    _write_manifest(client, "shadow.json", provider_id="grounding_dino")

    response = client.get("/api/v1/advanced-providers/manifests")

    assert response.status_code == 200, response.text
    grounding = [item for item in response.json() if item["display_name"] == "Grounding DINO"]
    assert len(grounding) == 1
    assert grounding[0]["source_kind"] == "built_in"
    shadow = next(item for item in response.json() if item["source_filename"] == "shadow.json")
    assert shadow["provider_id"].startswith("local_manifest_")
    assert shadow["discovery_status"] == "built_in_conflict"
    assert shadow["execution_surface"] == "blocked"


def test_local_manifest_preflight_returns_structured_inspect_only_blocker(
    client: TestClient,
) -> None:
    _write_manifest(client, "local-depth.json", provider_id="local_depth")
    project = create_project(client, "Local provider preflight")

    response = client.post(
        f"/api/v1/projects/{project['id']}/advanced-providers/local_depth/preflight",
        json={
            "task": "relative_depth",
            "device": "cpu",
            "prompt_fields": {"image_id": "not-executed"},
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ready"] is False
    assert payload["execution_supported"] is False
    assert payload["execution_surface"] == "blocked"
    assert payload["availability_status"] == "unavailable"
    assert any("inspect-only" in blocker for blocker in payload["blockers"])
    assert payload["selected_model_id"] is None


def test_local_manifest_cannot_reach_execution_route(client: TestClient) -> None:
    _write_manifest(client, "local-depth.json", provider_id="local_depth")
    project = create_project(client, "Local provider execution block")

    response = client.post(
        f"/api/v1/projects/{project['id']}/advanced-providers/local_depth/execute",
        json={
            "task": "relative_depth",
            "device": "cpu",
            "allow_model_download": False,
            "prompt_fields": {"image_id": "not-executed"},
        },
    )

    assert response.status_code in {400, 404}, response.text
