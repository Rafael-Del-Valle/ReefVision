from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from reefvision.db.models import Job, PoseIdentityAssociationRun, PoseIdentityObservation
from reefvision.jobs.pose_identity_tracking import process_pose_identity_tracking_job
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_pose_identity_tracking_api import (
    _first_class,
    _submit,
    _track,
    _video,
)


def test_cancelled_job_registers_no_partial_observations(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = create_project(client, "Pose identity cancellation")
    video = _video(client, str(project["id"]), monkeypatch, "cancel")
    track = _track(client, str(video["id"]), _first_class(project), offset=20, prefix="cancel")
    job_payload = _submit(client, str(project["id"]), str(video["id"]), [str(track["id"])])
    run_id = str(job_payload["result_json"]["run_id"])

    with client.app.state.session_factory() as session:
        job = session.get(Job, str(job_payload["id"]))
        assert job is not None
        job.status = "cancel_requested"
        session.commit()

    assert process_pose_identity_tracking_job(
        client.app.state.settings,
        client.app.state.session_factory,
        str(job_payload["id"]),
    )

    with client.app.state.session_factory() as session:
        job = session.get(Job, str(job_payload["id"]))
        run = session.get(PoseIdentityAssociationRun, run_id)
        assert job is not None and job.status == "cancelled"
        assert run is not None and run.status == "cancelled"
        assert (
            session.query(PoseIdentityObservation).filter_by(association_run_id=run_id).count() == 0
        )
