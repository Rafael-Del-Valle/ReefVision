from __future__ import annotations

from fastapi.testclient import TestClient

from reefvision.jobs.project_archives import (
    process_project_archive_export_job,
    process_project_archive_import_job,
)
from reefvision.storage.projects import resolve_managed_project_path


def test_project_archive_export_verify_and_import(client: TestClient) -> None:
    created = client.post(
        "/api/v1/projects",
        json={"name": "Portable source", "template": "octocoral"},
    )
    assert created.status_code == 201
    source = created.json()
    marker = resolve_managed_project_path(
        client.app.state.settings,
        f"{source['storage_root']}/notes/archive-marker.txt",
    )
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("portable project content", encoding="utf-8")

    queued = client.post(
        f"/api/v1/projects/{source['id']}/archive-export",
        json={"include_archived_records": True, "notes": "round trip"},
    )
    assert queued.status_code == 202
    export_job_id = queued.json()["job"]["id"]
    assert (
        process_project_archive_export_job(
            client.app.state.settings,
            client.app.state.session_factory,
            export_job_id,
        )
        is True
    )

    export_job = client.get(f"/api/v1/jobs/{export_job_id}").json()
    assert export_job["status"] == "succeeded"
    archive_path = export_job["result_json"]["archive_path"]
    verification = client.get(
        "/api/v1/project-archives/verify",
        params={"archive_path": archive_path},
    )
    assert verification.status_code == 200
    verification_payload = verification.json()
    assert verification_payload["valid"] is True
    assert verification_payload["source_project_id"] == source["id"]
    assert verification_payload["file_count"] >= 1

    import_queued = client.post(
        "/api/v1/project-archives/import",
        json={
            "archive_path": archive_path,
            "name": "Portable imported",
            "slug": "portable-imported",
            "restore_as_active": True,
        },
    )
    assert import_queued.status_code == 202
    import_job_id = import_queued.json()["job"]["id"]
    assert (
        process_project_archive_import_job(
            client.app.state.settings,
            client.app.state.session_factory,
            import_job_id,
        )
        is True
    )

    import_job = client.get(f"/api/v1/jobs/{import_job_id}").json()
    assert import_job["status"] == "succeeded"
    imported_project_id = import_job["result_json"]["project_id"]
    assert imported_project_id != source["id"]
    imported = client.get(f"/api/v1/projects/{imported_project_id}")
    assert imported.status_code == 200
    imported_payload = imported.json()
    assert imported_payload["name"] == "Portable imported"
    assert imported_payload["slug"] == "portable-imported"
    assert len(imported_payload["label_classes"]) == len(source["label_classes"])
    imported_marker = resolve_managed_project_path(
        client.app.state.settings,
        f"{imported_payload['storage_root']}/notes/archive-marker.txt",
    )
    assert imported_marker.read_text(encoding="utf-8") == "portable project content"


def test_archived_project_can_be_restored(client: TestClient) -> None:
    created = client.post(
        "/api/v1/projects",
        json={"name": "Restore me", "template": "blank"},
    ).json()
    archived = client.post(f"/api/v1/projects/{created['id']}/archive")
    assert archived.status_code == 200
    assert archived.json()["archived_at"] is not None
    restored = client.post(f"/api/v1/projects/{created['id']}/restore")
    assert restored.status_code == 200
    assert restored.json()["project"]["archived_at"] is None
