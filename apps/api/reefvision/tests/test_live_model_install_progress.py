from __future__ import annotations

from reefvision.api.routes.jobs import _live_model_install_response
from reefvision.config import Settings
from reefvision.db.models import Job
from reefvision.storage.catalog_models import catalog_model_directories


def test_running_model_install_reports_partial_file_size(test_settings: Settings) -> None:
    job = Job(
        id="11111111-2222-3333-4444-555555555555",
        project_id=None,
        job_type="model_install",
        status="running",
        progress_current=0,
        progress_total=10_000,
        request_json={"catalog_id": "ultralytics/yolov8/detect/m"},
        result_json={"stage": "downloading", "filename": "yolov8m.pt"},
    )
    temporary_dir = catalog_model_directories(test_settings)["temporary_downloads"]
    partial = temporary_dir / f"{job.id}-yolov8m.pt.part"
    partial.write_bytes(b"x" * 4_096)

    response = _live_model_install_response(job, test_settings)

    assert response.progress_current == 4_096
    assert response.progress_total == 10_000
    assert response.result_json is not None
    assert response.result_json["bytes_downloaded"] == 4_096
    assert response.result_json["progress_source"] == "partial_file"


def test_persisted_progress_wins_when_a_partial_file_is_smaller(
    test_settings: Settings,
) -> None:
    job = Job(
        id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        project_id=None,
        job_type="model_install",
        status="running",
        progress_current=8_192,
        progress_total=10_000,
        request_json={"catalog_id": "ultralytics/yolov8/detect/m"},
        result_json={"stage": "downloading", "filename": "yolov8m.pt"},
    )
    temporary_dir = catalog_model_directories(test_settings)["temporary_downloads"]
    partial = temporary_dir / f"{job.id}-yolov8m.pt.part"
    partial.write_bytes(b"x" * 4_096)

    response = _live_model_install_response(job, test_settings)

    assert response.progress_current == 8_192
    assert response.result_json == job.result_json
