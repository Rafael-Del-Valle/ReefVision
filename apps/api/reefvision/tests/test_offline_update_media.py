"""Read-only offline media preflight through the same endpoint used by Help."""

import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROUTE = "/api/v1/system/updates/inspect"
MSI = "ReefVision_2.0.0_x64_en-US.msi"
UPGRADE = "{5EDA8EE0-2A5D-5B08-A8DF-9BECFC3A4351}"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fixture_media(directory: Path) -> tuple[dict, str]:
    files = []
    for name, payload in [
        (MSI, b"fixture MSI content"),
        ("rv1.cab", b"first generated cabinet"),
        ("rv2.cab", b"second generated cabinet"),
    ]:
        (directory / name).write_bytes(payload)
        files.append({"name": name, "size_bytes": len(payload), "sha256": digest(payload)})
    manifest = {
        "version": "2.0.0",
        "source_commit": "a" * 40,
        "source_tree_clean": True,
        "msi_verified": True,
        "msi": {
            "identity": {
                "ProductVersion": "2.0.0",
                "ProductCode": "{19167BC8-042B-489B-A0F2-97ABA985E771}",
                "UpgradeCode": UPGRADE,
            },
            "media": [{"disk_id": i, "cabinet": f"rv{i}.cab", "embedded": False} for i in (1, 2)],
        },
        "files": files,
    }
    return manifest, save_manifest(directory, manifest)


def save_manifest(directory: Path, manifest: dict) -> str:
    payload = json.dumps(manifest).encode("utf-8-sig")
    (directory / "build-provenance.json").write_bytes(payload)
    return digest(payload)


def inspect(client: TestClient, folder: Path, pin: str):
    return client.post(ROUTE, json={"directory": str(folder), "manifest_sha256": pin})


def test_verified_check_is_read_only_and_reports_source_and_bytes(
    client: TestClient, tmp_path: Path
) -> None:
    tmp_path = tmp_path / "media"
    tmp_path.mkdir()
    _, pin = fixture_media(tmp_path)
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    response = inspect(client, tmp_path, pin)
    assert response.status_code == 200, response.text
    check = response.json()
    assert check["status"] == "verified" and check["version"] == "2.0.0"
    assert check["source_commit"] == "a" * 40 and check["manifest_sha256"] == pin
    assert {entry["name"]: entry["status"] for entry in check["files"]} == {
        MSI: "matched",
        "rv1.cab": "matched",
        "rv2.cab": "matched",
    }
    assert check["installer"] == MSI
    assert check["total_verified_bytes"] == sum(len(before[n]) for n in (MSI, "rv1.cab", "rv2.cab"))
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before


def test_missing_corrupt_and_extra_cab_can_be_rechecked(client: TestClient, tmp_path: Path) -> None:
    tmp_path = tmp_path / "media"
    tmp_path.mkdir()
    _, pin = fixture_media(tmp_path)
    original = (tmp_path / "rv1.cab").read_bytes()
    (tmp_path / "rv1.cab").write_bytes(b"!" * len(original))
    other = (tmp_path / "rv2.cab").read_bytes()
    (tmp_path / "rv2.cab").unlink()
    (tmp_path / "rv3.cab").write_bytes(b"other media")
    response = inspect(client, tmp_path, pin)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "incomplete"
    assert {r["name"]: r["status"] for r in result["files"]} == {
        MSI: "matched",
        "rv1.cab": "changed",
        "rv2.cab": "missing",
        "rv3.cab": "unexpected",
    }
    (tmp_path / "rv1.cab").write_bytes(original)
    (tmp_path / "rv2.cab").write_bytes(other)
    (tmp_path / "rv3.cab").unlink()
    assert inspect(client, tmp_path, pin).json()["status"] == "verified"


@pytest.mark.parametrize("edit", ["pin", "path", "lineage", "media", "duplicate", "unverified"])
def test_wrong_or_inconsistent_manifest_is_refused_before_hashing_members(
    client: TestClient, tmp_path: Path, edit: str
) -> None:
    tmp_path = tmp_path / "media"
    tmp_path.mkdir()
    manifest, _ = fixture_media(tmp_path)
    if edit == "path":
        manifest["files"][1]["name"] = "../outside.cab"
    elif edit == "lineage":
        manifest["msi"]["identity"]["UpgradeCode"] = manifest["msi"]["identity"]["ProductCode"]
    elif edit == "media":
        manifest["msi"]["media"].pop()
    elif edit == "duplicate":
        manifest["files"].append(manifest["files"][1])
    elif edit == "unverified":
        manifest["msi_verified"] = False
    pin = save_manifest(tmp_path, manifest)
    response = inspect(client, tmp_path, "0" * 64 if edit == "pin" else pin)
    assert response.status_code == 400, response.text
    assert response.json()["detail"]
