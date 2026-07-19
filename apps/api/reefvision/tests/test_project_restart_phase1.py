from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from reefvision.db.models import Job, Project
from reefvision.services.recovery import RecoveryService


def test_project_restart_plan_handles_stale_work_and_partial_files(
    client: TestClient,
) -> None:
    settings = client.app.state.settings
    with client.app.state.session_factory() as session:
        project = Project(
            name="Restart project",
            slug="restart-project",
            storage_root="projects/restart-project",
        )
        session.add(project)
        session.flush()
        stale = Job(
            project_id=project.id,
            job_type="inference",
            status="running",
            started_at=datetime.now(UTC) - timedelta(hours=1),
            heartbeat_at=datetime.now(UTC) - timedelta(hours=1),
            resume_supported=False,
        )
        session.add(stale)
        session.commit()

        partial = Path(settings.resolved_data_dir) / project.storage_root / "exports" / "result.tmp"
        partial.parent.mkdir(parents=True, exist_ok=True)
        partial.write_text("partial", encoding="utf-8")
        old = (datetime.now(UTC) - timedelta(hours=1)).timestamp()
        os.utime(partial, (old, old))

        service = RecoveryService(session, settings)
        plan = service.plan(project.id, stale_after_seconds=60)
        categories = {issue.category for issue in plan.issues}
        assert {"stale_job", "temporary_file"}.issubset(categories)
        result = service.apply(
            project.id,
            plan.automatic_issue_ids,
            stale_after_seconds=60,
        )

        session.refresh(stale)
        assert stale.status == "failed"
        assert not partial.exists()
        assert result.quarantined_paths
        relocated = Path(settings.resolved_data_dir) / result.quarantined_paths[0]
        assert relocated.read_text(encoding="utf-8") == "partial"
