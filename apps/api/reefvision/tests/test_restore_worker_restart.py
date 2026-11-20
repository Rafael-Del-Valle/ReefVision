"""Exercise a real restore worker exit and the desktop's startup recovery."""

import json
import multiprocessing
import os
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.config import Settings
from reefvision.db.session import create_database_engine, create_session_factory
from reefvision.jobs import restores
from reefvision.jobs.backups import process_backup_job
from reefvision.jobs.worker import recover_interrupted_jobs
from reefvision.main import create_app

from .test_backups import create_completed_backup


def test_backup_of_reopened_recovery_preserves_each_generation_after_restart(
    client: TestClient, test_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, first_backup = create_completed_backup(client, test_settings)
    first = (
        client.post(
            f"/api/v1/backups/{first_backup['id']}/restore", json={"destination_name": "first"}
        )
        .raise_for_status()
        .json()
    )
    assert restores.process_restore_job(
        test_settings, cast(FastAPI, client.app).state.session_factory, first["job"]["id"]
    )
    profile = test_settings.resolved_data_dir / first["destination_path"]
    settings = test_settings.model_copy(
        update={
            "data_dir": profile,
            "database_url": f"sqlite:///{(profile / 'test.db').as_posix()}",
        }
    )
    app = create_app(settings)
    factory = app.state.session_factory
    with TestClient(app) as reopened:
        created = reopened.post("/api/v1/backups", json={}).raise_for_status().json()
        assert process_backup_job(settings, factory, created["job"]["id"])
        backup = created["backup"]
        route = f"/api/v1/backups/{backup['id']}"
        assert reopened.post(route + "/verify").raise_for_status().json()["status"] == "valid"
        restore = (
            reopened.post(route + "/restore", json={"destination_name": "second"})
            .raise_for_status()
            .json()
        )
        job_id = restore["job"]["id"]
        target = profile / restore["destination_path"]

        # Stop after the atomic directory publication and before the database commit.
        class WorkerExit(BaseException):
            pass

        def stop_after_publication(*_args: Any, **_kwargs: Any) -> None:
            raise WorkerExit()

        with monkeypatch.context() as patch:
            patch.setattr(restores, "_finalize_success", stop_after_publication)
            with pytest.raises(WorkerExit):
                restores.process_restore_job(settings, factory, job_id)
        reopened.post(f"/api/v1/jobs/{job_id}/cancel").raise_for_status()
        recover_interrupted_jobs(factory, settings)
        assert restores.process_restore_job(settings, factory, job_id)
        result = reopened.get(f"/api/v1/jobs/{job_id}").raise_for_status().json()
        assert result["status"] == "succeeded"

        # All archived paths, including both previous restore documents, keep their bytes.
        manifest = json.loads((profile / backup["manifest_path"]).read_bytes())
        assert {"data/restore-receipt.json", "data/restored-from-backup-complete.json"} <= {
            row["path"] for row in manifest["file_inventory"]
        }
        for row in manifest["file_inventory"]:
            member = row["path"].split("/", 1)[1]
            assert restores.hash_file(target / member) == (row["sha256"], row["size_bytes"])
        receipt = target / result["result_json"]["restore_receipt_filename"]
        marker = target / result["result_json"]["completion_marker_filename"]
        assert json.loads(receipt.read_bytes())["restore_job_id"] == job_id
        assert marker.read_bytes() == (profile / backup["completion_marker_path"]).read_bytes()
        assert (
            json.loads((target / "restore-receipt.json").read_bytes())["restore_job_id"]
            == first["job"]["id"]
        )
    app.state.engine.dispose()


def _stop_child(data_dir: Path, database_url: str, job_id: str, published: bool) -> None:
    settings = Settings(
        env="test", data_dir=data_dir, database_url=database_url, background_worker_enabled=False
    )
    factory = create_session_factory(create_database_engine(settings))
    copy_member = restores.copy_file_with_sha256

    def exit_after_copy(*args: Any, **kwargs: Any) -> None:
        copy_member(*args, **kwargs)
        os._exit(71)

    def exit_before_database_commit(*args: Any, **kwargs: Any) -> None:
        os._exit(72)

    edge, stop = (
        ("_finalize_success", exit_before_database_commit)
        if published
        else ("copy_file_with_sha256", exit_after_copy)
    )
    with patch.object(restores, edge, stop):
        restores.process_restore_job(settings, factory, job_id)


@pytest.mark.parametrize(
    "interruption",
    ["copy", "published", "changed", "other_owner", "cancelled", "cancelled_after_publication"],
)
def test_restarted_worker_finishes_only_its_own_intact_restore(
    client: TestClient, test_settings: Settings, interruption: str
) -> None:
    _, backup = create_completed_backup(client, test_settings)
    root = test_settings.resolved_data_dir
    endpoint = f"/api/v1/backups/{backup['id']}"
    destination = {"destination_name": "retain-after-restart"}
    launch = client.post(endpoint + "/restore", json=destination).raise_for_status().json()
    job_id = launch["job"]["id"]
    target = root / launch["destination_path"]
    original_manifest = (root / backup["manifest_path"]).read_bytes()
    inventory = json.loads(original_manifest)["file_inventory"]
    other = root / ".t" / "separate-active-restore" / "member"
    other.parent.mkdir(parents=True)
    other.write_bytes(b"independent worker")

    published = interruption in {
        "published",
        "changed",
        "other_owner",
        "cancelled_after_publication",
    }
    child = multiprocessing.get_context("spawn").Process(
        target=_stop_child, args=(root, test_settings.resolved_database_url, job_id, published)
    )
    child.start()
    child.join(60)
    if child.is_alive():
        child.terminate()
        child.join()
        pytest.fail("The restore worker did not reach the interruption")
    assert child.exitcode == (72 if published else 71)
    job_path = f"/api/v1/jobs/{job_id}"
    assert client.get(job_path).raise_for_status().json()["status"] == "running"
    assert target.exists() == published
    if interruption == "changed":
        (target / backup["database_filename"]).write_bytes(b"preserve user's modified copy")
    if interruption == "other_owner":
        receipt = target / "restore-receipt.json"
        foreign = {**json.loads(receipt.read_bytes()), "restore_job_id": str(uuid4())}
        receipt.write_text(json.dumps(foreign), encoding="utf-8")
    if interruption in {"cancelled", "cancelled_after_publication"}:
        client.post(job_path + "/cancel").raise_for_status()

    factory = cast(FastAPI, client.app).state.session_factory
    assert recover_interrupted_jobs(factory, test_settings) == 1
    if interruption == "cancelled":
        assert client.get(job_path).raise_for_status().json()["status"] == "cancelled"
        assert not target.exists()
    else:
        assert client.get(job_path).raise_for_status().json()["status"] == "queued"
        result = restores.process_restore_job(test_settings, factory, job_id)
        done = client.get(job_path).raise_for_status().json()
        if interruption == "changed":
            assert not result and done["status"] == "failed"
            assert (
                target / backup["database_filename"]
            ).read_bytes() == b"preserve user's modified copy"
        elif interruption == "other_owner":
            assert not result and done["status"] == "failed"
            assert json.loads((target / "restore-receipt.json").read_bytes()) == foreign
        else:
            assert result and done["status"] == "succeeded"
            assert done["result_json"]["restored_file_count"] == len(inventory)
            for row in inventory:
                member = row["path"].split("/", 1)[1]
                assert restores.hash_file(target / member) == (row["sha256"], row["size_bytes"])
        assert client.post(endpoint + "/restore", json=destination).status_code == 409
    assert {p.name for p in (root / ".t").iterdir()} == {other.parent.name}
    assert other.read_bytes() == b"independent worker"
    assert (root / backup["manifest_path"]).read_bytes() == original_manifest
    assert client.post(endpoint + "/verify").raise_for_status().json()["status"] == "valid"
