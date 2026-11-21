from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from wasmtime import wat2wasm

from reefvision.config import Settings
from reefvision.plugin_sdk import build_rgb_plugin
from reefvision.tests.test_annotations import create_project, image_bytes, import_one

PLUGINS = "/api/v1/plugins"


def package(body: str = "local.get 1", *, version: str = "1.0.0") -> dict:
    module = bytes(
        wat2wasm(f'(module (func (export "measure") (param f64 f64 f64 i64) (result f64) {body}))')
    )
    return {
        "manifest": {
            "manifest_version": 2,
            "abi": "reefvision.rgb-summary/1",
            "plugin_id": "fixture_green",
            "version": version,
            "display_name": "Green channel",
            "description": "Mean green intensity divided by 255.",
            "license": "AGPL-3.0-only",
            "permissions": ["read_image_rgb_summary"],
            "quantity": "green_fraction",
            "unit": "1",
            "module_sha256": hashlib.sha256(module).hexdigest(),
        },
        "module_base64": base64.b64encode(module).decode("ascii"),
    }


def install(client: TestClient, upload: dict) -> dict:
    installed = client.post(PLUGINS, json=upload)
    assert installed.status_code == 201, installed.text
    return installed.json()


def enable(client: TestClient, record: dict, state: bool = True) -> dict:
    response = client.patch(
        f"{PLUGINS}/{record['id']}",
        json={"enabled": state, "package_sha256": record["package_sha256"]},
    )
    assert response.status_code == 200, response.text
    return response.json()


def source(client: TestClient) -> tuple[str, dict]:
    project = create_project(client, "Plugin measurements")
    image = import_one(client, project["id"])["successful"][0]
    return project["id"], {
        "image_id": image["image_id"],
        "image_sha256": hashlib.sha256(image_bytes()).hexdigest(),
    }


def test_install_measure_disable_and_reopen_pinned_original(client: TestClient) -> None:
    project, image = source(client)
    upload = package("local.get 1 f64.const 255 f64.div")
    plugin = install(client, upload)
    assert not plugin["enabled"] and plugin["available"]
    assert client.get(PLUGINS).json() == {"items": [plugin], "total": 1}
    endpoint = f"/api/v1/projects/{project}/plugin-measurements"
    binding = {
        "plugin_record_id": plugin["id"],
        "package_sha256": plugin["package_sha256"],
        **image,
    }
    assert client.post(endpoint, json=binding).status_code == 409
    enabled = enable(client, plugin)
    assert install(client, upload) == enabled
    saved = client.post(endpoint, json=binding)
    assert saved.status_code == 200, saved.text
    result = saved.json()
    assert result["value"] == pytest.approx(90 / 255) and result["unit"] == "1"
    assert (result["source_kind"], result["qc"]) == ("derived", "unassessed")
    params = result["provenance"]["processing_parameters"]
    assert params["module_sha256"] == upload["manifest"]["module_sha256"]
    assert (
        params["package_sha256"] == plugin["package_sha256"]
        and params["image_sha256"] == image["image_sha256"]
    )
    assert params["rgb_summary"] == {
        "red_mean": 20.0,
        "green_mean": 90.0,
        "blue_mean": 120.0,
        "pixel_count": 4800,
    }
    assert client.post(endpoint, json=binding).json() == result
    assert client.post(endpoint, json={**binding, "image_sha256": "a" * 64}).status_code == 409
    assert client.post(endpoint, json={**binding, "package_sha256": "b" * 64}).status_code == 409
    other = create_project(client, "Independent project")["id"]
    assert client.post(
        f"/api/v1/projects/{other}/plugin-measurements", json=binding
    ).status_code in (400, 404)
    assert not enable(client, plugin, False)["enabled"]
    assert client.post(endpoint, json=binding).status_code == 409
    assert client.get(endpoint).json() == {"items": [result], "total": 1}


def test_plugin_failure_does_not_interrupt_research_or_publish_measurement(
    client: TestClient,
) -> None:
    project, image = source(client)
    endpoint = f"/api/v1/projects/{project}/plugin-measurements"
    first = enable(client, install(client, package("unreachable")))
    error = client.post(
        endpoint,
        json={"plugin_record_id": first["id"], "package_sha256": first["package_sha256"], **image},
    )
    assert error.status_code == 400 and "plugin" in error.text.lower()
    assert client.get(endpoint).json()["total"] == 0
    second = enable(client, install(client, package("f64.const 0.5", version="1.1.0")))
    result = client.post(
        endpoint,
        json={
            "plugin_record_id": second["id"],
            "package_sha256": second["package_sha256"],
            **image,
        },
    )
    assert result.status_code == 200 and result.json()["value"] == 0.5
    assert client.get(PLUGINS, params={"limit": 1, "offset": 1}).json()["total"] == 2


def test_incompatible_mismatched_and_conflicting_packages_leave_first_version_intact(
    client: TestClient,
) -> None:
    upload = package()
    first = install(client, upload)
    for override in (
        {"manifest_version": 9},
        {"permissions": ["network"]},
        {"module_sha256": "0" * 64},
        {"abi": "unsupported/1"},
    ):
        wrong = {**upload, "manifest": {**upload["manifest"], **override}}
        assert client.post(PLUGINS, json=wrong).status_code in (400, 422)
    changed = package("f64.const 1")
    assert client.post(PLUGINS, json=changed).status_code == 409
    assert client.get(PLUGINS).json()["items"] == [first]


def test_missing_module_keeps_history_and_exact_reinstall_restores_it(
    client: TestClient, test_settings: Settings
) -> None:
    project, image = source(client)
    upload = package("f64.const 0.25")
    plugin = enable(client, install(client, upload))
    pin = {"plugin_record_id": plugin["id"], "package_sha256": plugin["package_sha256"], **image}
    endpoint = f"/api/v1/projects/{project}/plugin-measurements"
    first = client.post(endpoint, json=pin)
    assert first.status_code == 200, first.text
    module = test_settings.resolved_data_dir / "plugins" / plugin["id"] / "module.wasm"
    module.unlink()
    record = client.get(PLUGINS).json()["items"][0]
    assert record["id"] == plugin["id"] and not record["available"]
    assert "reinstall" in record["reason"].lower()
    assert client.post(endpoint, json=pin).status_code == 409
    assert client.get(endpoint).json()["items"] == [first.json()]
    assert install(client, upload) == plugin
    assert client.post(endpoint, json=pin).json() == first.json()


def test_authored_sample_compiles_to_the_published_module_and_rejects_wrong_signature(
    client: TestClient,
) -> None:
    directory = Path(__file__).resolve().parents[4] / "examples/plugins"
    bundled = json.loads((directory / "green-fraction.rvplugin.json").read_text(encoding="utf-8"))
    fields = {
        k: bundled["manifest"][k]
        for k in (
            "plugin_id",
            "version",
            "display_name",
            "description",
            "license",
            "quantity",
            "unit",
        )
    }
    text = (directory / "green-fraction.wat").read_text(encoding="utf-8")
    assert build_rgb_plugin(bytes(wat2wasm(text)), **fields).model_dump(mode="json") == bundled
    incompatible = build_rgb_plugin(
        bytes(wat2wasm('(module (func (export "measure") (result i32) i32.const 7))')), **fields
    )
    result = client.post(PLUGINS, json=incompatible.model_dump(mode="json"))
    assert result.status_code == 400 and "three f64" in result.text
    assert client.get(PLUGINS).json()["total"] == 0
