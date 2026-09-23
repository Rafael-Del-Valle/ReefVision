import io
from pathlib import Path

import pytest

from reefvision.db.models import VideoAsset
from reefvision.services import video_assets as video_assets_module
from reefvision.services.video_assets import VideoAssetService
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_telemetry import FIXTURES
from reefvision.tests.test_video_tracking_phase6 import _fake_metadata


def _upload(client, project_id, *, srt_name="fish.SRT", srt=None):
    files = {"file": ("fish.mp4", io.BytesIO(b"fake-video"), "video/mp4")}
    if srt is not None:
        files["telemetry_file"] = (srt_name, io.BytesIO(srt), "application/x-subrip")
    return client.post(f"/api/v1/projects/{project_id}/imports/videos", files=files)


def test_uploaded_sidecar_survives_new_session_and_frame_extraction(client, monkeypatch):
    monkeypatch.setattr(video_assets_module, "_inspect_video", _fake_metadata)
    project = create_project(client, "Telemetry")
    response = _upload(client, project["id"], srt=(FIXTURES / "modern.SRT").read_bytes())
    assert response.status_code == 201, response.text
    video = response.json()
    metadata = video["telemetry"]
    assert metadata["available"] and metadata["found"]
    assert metadata["source_type"] == "dji_srt" and metadata["sample_count"] == 3
    assert metadata["path_kind"] == "managed"
    assert not Path(metadata["source_path"]).is_absolute()
    settings = client.app.state.settings
    assert resolve_managed_project_path(settings, metadata["source_path"]).is_file()
    with client.app.state.session_factory() as session:
        source = VideoAssetService(session, settings).telemetry_source(video["id"])
        assert source.sample_for_frame(1, 10).sample.latitude == 25.126
    queued = client.post(f"/api/v1/videos/{video['id']}/extract", json={"every_n_frames": 5})
    assert queued.status_code == 200
    assert client.get(f"/api/v1/videos/{video['id']}").json()["telemetry"] == metadata


def test_ordinary_and_old_videos_have_no_telemetry(client, monkeypatch):
    monkeypatch.setattr(video_assets_module, "_inspect_video", _fake_metadata)
    project = create_project(client, "Ordinary")
    response = _upload(client, project["id"])
    assert response.status_code == 201
    video = response.json()
    assert not video["telemetry"]["available"]
    with client.app.state.session_factory() as session:
        record = session.get(VideoAsset, video["id"])
        record.metadata_json = {"file_size_bytes": 10}
        session.commit()
        assert (
            VideoAssetService(session, client.app.state.settings).telemetry_source(video["id"])
            is None
        )
    assert not client.get(f"/api/v1/videos/{video['id']}").json()["telemetry"]["found"]


@pytest.mark.parametrize(("name", "data"), [("other.srt", b"bad"), ("fish.srt", b"bad")])
def test_explicit_invalid_upload_returns_domain_error_without_import(
    client, monkeypatch, name, data
):
    monkeypatch.setattr(video_assets_module, "_inspect_video", _fake_metadata)
    project = create_project(client, "Bad upload")
    response = _upload(client, project["id"], srt_name=name, srt=data)
    assert response.status_code == 400, response.text
    assert client.get(f"/api/v1/projects/{project['id']}/videos").json() == []


def test_path_pairing_metadata_and_missing_external_source(client, monkeypatch, tmp_path):
    monkeypatch.setattr(video_assets_module, "_inspect_video", _fake_metadata)
    monkeypatch.delenv("REEFVISION_WHALEDRONE_ROOT", raising=False)
    project = create_project(client, "Path import")
    video_path = tmp_path / "DJI.MP4"
    video_path.write_bytes(b"fake-video")
    sidecar = tmp_path / "DJI.SRT"
    sidecar.write_bytes((FIXTURES / "modern.SRT").read_bytes())
    settings = client.app.state.settings
    with client.app.state.session_factory() as session:
        service = VideoAssetService(session, settings)
        video = service.import_video_path(project["id"], video_path)
        assert video.telemetry.path_kind == "external"
        assert video.telemetry.source_path == str(sidecar.resolve())
        assert video.telemetry.sample_count == 3
        assert service.telemetry_source(video.id).sample_for_frame(0, video.fps).error_s == 0
        sidecar.unlink()
        assert service.telemetry_source(video.id) is None
    assert list(settings.resolved_data_dir.rglob("*.srt")) == []


@pytest.mark.parametrize(
    "corrupt", ["malformed", "1\n" + "9" * 310 + ":00:00,000 --> 00:00:01,000\n[latitude: 25]"]
)
def test_invalid_auto_sidecar_does_not_block_video_import(client, monkeypatch, tmp_path, corrupt):
    monkeypatch.setattr(video_assets_module, "_inspect_video", _fake_metadata)
    project = create_project(client, "Invalid auto sidecar")
    video_path = tmp_path / "DJI.mp4"
    video_path.write_bytes(b"fake-video")
    (tmp_path / "DJI.srt").write_text(corrupt)
    with client.app.state.session_factory() as session:
        video = VideoAssetService(session, client.app.state.settings).import_video_path(
            project["id"], video_path
        )
        assert video.telemetry.found and not video.telemetry.available
        assert video.telemetry.error
        assert video.status == "imported"


def test_duplicate_import_can_attach_previously_missing_telemetry(client, monkeypatch):
    monkeypatch.setattr(video_assets_module, "_inspect_video", _fake_metadata)
    project = create_project(client, "Duplicate")
    original = _upload(client, project["id"]).json()
    second = _upload(client, project["id"], srt=(FIXTURES / "modern.SRT").read_bytes())
    assert second.status_code == 201
    assert second.json()["id"] == original["id"]
    assert second.json()["telemetry"]["sample_count"] == 3
    assert len(client.get(f"/api/v1/projects/{project['id']}/videos").json()) == 1


def test_failed_video_import_does_not_leave_sidecar(client, monkeypatch):
    from reefvision.domain.errors import ValidationError

    def fail(_):
        raise ValidationError("bad video")

    monkeypatch.setattr(video_assets_module, "_inspect_video", fail)
    project = create_project(client, "Rollback")
    response = _upload(client, project["id"], srt=(FIXTURES / "modern.SRT").read_bytes())
    assert response.status_code == 400
    assert list(client.app.state.settings.resolved_data_dir.rglob("*.srt")) == []


def test_failed_database_commit_removes_new_managed_media(client, monkeypatch):
    monkeypatch.setattr(video_assets_module, "_inspect_video", _fake_metadata)
    project = create_project(client, "Commit rollback")

    def fail_commit():
        raise RuntimeError("simulated database failure")

    settings = client.app.state.settings
    with client.app.state.session_factory() as session:
        monkeypatch.setattr(session, "commit", fail_commit)
        with pytest.raises(RuntimeError, match="database failure"):
            VideoAssetService(session, settings).import_video(
                project["id"],
                filename="fish.mp4",
                stream=io.BytesIO(b"fake-video"),
                media_type="video/mp4",
                telemetry_filename="fish.srt",
                telemetry_stream=io.BytesIO((FIXTURES / "modern.SRT").read_bytes()),
            )
    assert list(settings.resolved_data_dir.rglob("*.srt")) == []
    assert list(settings.resolved_data_dir.rglob("*.mp4")) == []


AIRDATA_CSV = b"""time(millisecond),latitude,longitude,height_above_takeoff(meters),gimbal_heading(degrees),gimbal_pitch(degrees),gimbal_roll(degrees),compass_heading(degrees)
10000,22.892814,-109.840571,83.4,265.1,-23.4,0,248.9
10100,22.892808,-109.840590,83.5,265.6,-23.4,0,249.3
"""


def test_uploaded_airdata_is_preferred_over_srt_and_persists_alignment(client, monkeypatch):
    monkeypatch.setattr(video_assets_module, "_inspect_video", _fake_metadata)
    project = create_project(client, "AirData precedence")
    files = {
        "file": ("fish.mp4", io.BytesIO(b"fake-video"), "video/mp4"),
        "telemetry_file": (
            "fish.SRT",
            io.BytesIO((FIXTURES / "modern.SRT").read_bytes()),
            "application/x-subrip",
        ),
        "airdata_file": ("flight-Airdata.csv", io.BytesIO(AIRDATA_CSV), "text/csv"),
    }
    response = client.post(
        f"/api/v1/projects/{project['id']}/imports/videos",
        files=files,
        data={
            "airdata_time_offset_s": "10.0",
            "airdata_time_offset_evidence": "Known flight-log/video start alignment",
        },
    )
    assert response.status_code == 201, response.text
    video = response.json()
    assert video["telemetry"]["source_type"] == "dji_srt"
    assert video["airdata_telemetry"]["source_type"] == "airdata"
    assert video["airdata_telemetry"]["sample_count"] == 2
    assert video["airdata_alignment"]["time_offset_s"] == 10.0
    assert video["airdata_alignment"]["evidence"]

    settings = client.app.state.settings
    airdata_path = resolve_managed_project_path(
        settings, video["airdata_telemetry"]["source_path"]
    )
    assert airdata_path.is_file()
    with client.app.state.session_factory() as session:
        source = VideoAssetService(session, settings).telemetry_source(video["id"])
        assert source is not None
        match = source.sample_for_frame(1, 10)
        assert match is not None
        assert match.sample.gimbal_yaw_deg == 265.6
        assert match.provenance is not None
        assert match.provenance.gimbal_yaw_source == "airdata"


def test_airdata_nonzero_offset_requires_evidence_and_does_not_import(client, monkeypatch):
    monkeypatch.setattr(video_assets_module, "_inspect_video", _fake_metadata)
    project = create_project(client, "AirData evidence")
    files = {
        "file": ("fish.mp4", io.BytesIO(b"fake-video"), "video/mp4"),
        "airdata_file": ("flight.csv", io.BytesIO(AIRDATA_CSV), "text/csv"),
    }
    response = client.post(
        f"/api/v1/projects/{project['id']}/imports/videos",
        files=files,
        data={"airdata_time_offset_s": "10.0"},
    )
    assert response.status_code == 400, response.text
    assert client.get(f"/api/v1/projects/{project['id']}/videos").json() == []


def test_failed_video_import_removes_managed_airdata(client, monkeypatch):
    from reefvision.domain.errors import ValidationError

    def fail(_):
        raise ValidationError("bad video")

    monkeypatch.setattr(video_assets_module, "_inspect_video", fail)
    project = create_project(client, "AirData rollback")
    files = {
        "file": ("fish.mp4", io.BytesIO(b"fake-video"), "video/mp4"),
        "airdata_file": ("flight.csv", io.BytesIO(AIRDATA_CSV), "text/csv"),
    }
    response = client.post(f"/api/v1/projects/{project['id']}/imports/videos", files=files)
    assert response.status_code == 400
    settings = client.app.state.settings
    assert list(settings.resolved_data_dir.rglob("*.airdata.csv")) == []
