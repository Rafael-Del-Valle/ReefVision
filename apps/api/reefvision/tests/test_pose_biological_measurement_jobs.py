from __future__ import annotations

from reefvision.jobs.pose_biological_measurement import process_pose_biological_measurement_job


def test_job_dispatch_contract_is_available() -> None:
    assert callable(process_pose_biological_measurement_job)
