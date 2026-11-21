"""An ordinary annotation save can be retried after SQLite exhausts its file quota."""

from typing import Any, cast
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event

from reefvision.tests.test_annotations import create_project, import_one


def test_storage_full_save_preserves_revision_and_can_be_retried(client: TestClient) -> None:
    project = create_project(client)
    image = import_one(client, project["id"])["successful"][0]["image_id"]
    url = f"/api/v1/images/{image}/annotations"
    box = {
        "id": str(uuid4()),
        "label_class_id": project["label_classes"][0]["id"],
        "x_min": 1,
        "y_min": 2,
        "x_max": 11,
        "y_max": 17,
    }
    original_save = {"base_revision": 0, "annotation_status": "in_progress", "annotations": [box]}
    assert client.put(url, json=original_save).status_code == 200
    original = client.get(url).json()
    batch = [box, *[{**box, "id": str(uuid4())} for _ in range(1000)]]
    payload = {"base_revision": 1, "annotation_status": "annotated", "annotations": batch}
    engine = cast(FastAPI, client.app).state.engine
    with engine.connect() as conn:
        pages = conn.exec_driver_sql("PRAGMA page_count").scalar_one()
        previous = conn.exec_driver_sql("PRAGMA max_page_count").scalar_one()

    def limit_file(conn: Any, *_: Any) -> None:
        conn.execute(f"PRAGMA max_page_count={pages}")

    event.listen(engine, "checkout", limit_file)
    try:
        response = client.put(url, json=payload)
        assert response.status_code == 507, response.text
        assert response.json()["code"] == "storage_full"
        assert "retry" in response.json()["detail"].lower()
        assert client.get(url).json() == original
    finally:
        event.remove(engine, "checkout", limit_file)
        with engine.connect() as conn:
            conn.exec_driver_sql(f"PRAGMA max_page_count={previous}")
    assert client.put(url, json=payload).status_code == 200
    saved = client.get(url).json()
    assert saved["image"]["annotation_revision"] == 2
    assert {b["id"] for b in saved["annotations"]} == {b["id"] for b in batch}
