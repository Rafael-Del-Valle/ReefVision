from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from reefvision.db.models import Project
from reefvision.services.validation_dashboard import ValidationDashboardService


def test_validation_dashboard_combines_project_release_checks(client: TestClient) -> None:
    settings = client.app.state.settings
    with client.app.state.session_factory() as session:
        project = Project(
            name="Validation project",
            slug="validation-project",
            storage_root="projects/validation-project",
        )
        session.add(project)
        session.commit()
        session.refresh(project)
        Path(settings.resolved_data_dir, project.storage_root).mkdir(parents=True, exist_ok=True)

        report = ValidationDashboardService(session, settings).build(project.id)

        categories = {check.category for check in report.checks}
        assert categories == {
            "database",
            "managed_files",
            "models",
            "datasets",
            "annotations",
            "class_maps",
            "training",
            "videos",
            "exports",
            "workflows",
            "disk",
            "versions",
            "recovery",
        }
        assert report.disk_total_bytes > 0
        assert report.disk_free_bytes > 0
        assert report.overall_status in {"pass", "warning", "error"}
