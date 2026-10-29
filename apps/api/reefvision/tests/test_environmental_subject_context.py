"""Environmental joins require explicit subject position/time evidence."""

from reefvision.tests.test_annotations import create_project, import_one
from reefvision.tests.test_scientific_data import observation


def context(client, project_id, subject, **options):
    return client.post(
        f"/api/v1/projects/{project_id}/environment/subject-context",
        json={"subject": subject, "max_distance_m": 2000, "max_time_delta_s": 3600, **options},
    )


def add(client, project_id, **options):
    response = client.post(
        f"/api/v1/projects/{project_id}/scientific-records",
        json={"records": [observation(**options)]},
    )
    assert response.status_code == 201, response.text
    return response.json()["items"][0]


def test_station_location_linked_to_image_is_not_subject_position(client):
    project = create_project(client)
    image_id = import_one(client, project["id"])["successful"][0]["image_id"]
    add(client, project["id"], subject={"image_id": image_id})
    response = context(client, project["id"], {"image_id": image_id})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "unavailable"
    assert response.json()["matches"] == {}
    assert "position" in response.json()["reason"].lower()


def test_subject_lookup_reports_spatial_temporal_separation_and_provenance(client):
    project = create_project(client)
    image_id = import_one(client, project["id"])["successful"][0]["image_id"]
    position = add(
        client,
        project["id"],
        variable="geographic_position",
        value=1,
        unit="1",
        subject={"image_id": image_id},
        location={"latitude": 32.76, "longitude": -79.93, "horizontal_uncertainty_m": 5},
    )
    measured = add(
        client,
        project["id"],
        observed_at="2026-04-03T13:10:00Z",
        uncertainty={"value": 1.8, "kind": "bound"},
    )
    add(client, project["id"], qc="rejected")
    response = context(client, project["id"], {"image_id": image_id})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "available"
    assert result["position"]["id"] == position["id"]
    match = result["matches"]["water_temperature"][0]
    assert match["record"]["id"] == measured["id"]
    assert 1100 < match["distance_m"] < 1120
    assert match["time_delta_s"] == 600
    assert match["offline_available"] is True
    assert match["cache_age_s"] is None
    assert result["matches"]["practical_salinity"] == []


def test_conflicting_subject_positions_require_explicit_choice(client):
    project = create_project(client)
    image_id = import_one(client, project["id"])["successful"][0]["image_id"]
    positions = [
        add(
            client,
            project["id"],
            variable="geographic_position",
            value=1,
            unit="1",
            subject={"image_id": image_id},
            observed_at=time,
        )
        for time in ("2026-04-03T13:00:00Z", "2026-04-04T13:00:00Z")
    ]
    response = context(client, project["id"], {"image_id": image_id})
    assert response.json()["status"] == "ambiguous"
    assert len(response.json()["positions"]) == 2
    chosen = context(
        client, project["id"], {"image_id": image_id}, position_record_id=positions[0]["id"]
    )
    assert chosen.json()["position"]["id"] == positions[0]["id"]


def test_subject_lookup_rejects_foreign_images_and_foreign_position_records(client):
    project = create_project(client)
    other = create_project(client, "Other")
    image_id = import_one(client, other["id"])["successful"][0]["image_id"]
    response = context(client, project["id"], {"image_id": image_id})
    assert response.status_code == 400, response.text


def test_track_frame_context_does_not_reuse_another_frame_or_image_position(client, monkeypatch):
    from reefvision.tests.test_video_track_exchange_phase6 import _track, _video

    project = create_project(client)
    video = _video(client, project["id"], monkeypatch)
    track = _track(client, video["id"], project["label_classes"][0]["id"])
    subject = {"video_id": video["id"], "track_id": track["id"], "frame_index": 0}
    add(client, project["id"], variable="geographic_position", value=1, unit="1", subject=subject)
    assert context(client, project["id"], subject).json()["position"]["subject"] == {
        **subject,
        "image_id": None,
        "annotation_id": None,
        "mask_id": None,
        "prediction_id": None,
        "model_run_id": None,
    }
    assert (
        context(client, project["id"], {**subject, "frame_index": 1}).json()["status"]
        == "unavailable"
    )


def test_subject_position_limit_excludes_other_video_frames_before_counting(
    client, monkeypatch
):
    """A busy video must not hide a valid position for a specific frame."""
    from datetime import UTC, datetime, timedelta

    from reefvision.schemas.scientific_data import ScientificRecordCreate
    from reefvision.services.scientific_data import ScientificDataService
    from reefvision.tests.test_video_track_exchange_phase6 import _video

    project = create_project(client)
    video = _video(client, project["id"], monkeypatch)
    unrelated_frame = {"video_id": video["id"], "frame_index": 1}
    requested_frame = {"video_id": video["id"], "frame_index": 0}
    start = datetime(2026, 4, 3, 13, tzinfo=UTC)

    with client.app.state.session_factory() as session:
        science = ScientificDataService(session)
        unrelated = [
            ScientificRecordCreate.model_validate(
                observation(
                    variable="geographic_position",
                    value=1,
                    unit="1",
                    subject=unrelated_frame,
                    observed_at=(start + timedelta(seconds=index)).isoformat(),
                )
            )
            for index in range(1001)
        ]
        science.add_records(project["id"], unrelated)
        target = science.add_records(
            project["id"],
            [
                ScientificRecordCreate.model_validate(
                    observation(
                        variable="geographic_position",
                        value=1,
                        unit="1",
                        subject=requested_frame,
                    )
                )
            ],
        )[0]
        target_id = target.id
        session.commit()

    response = context(client, project["id"], requested_frame)
    assert response.status_code == 200, response.text
    assert [row["id"] for row in response.json()["positions"]] == [target_id]
    assert response.json()["position"]["id"] == target_id
