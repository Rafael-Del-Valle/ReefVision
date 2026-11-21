from math import isclose
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from reefvision.domain.multimodal import classify_window, paired_difference


def test_multimodal_migration_keeps_earlier_tables(tmp_path, monkeypatch):
    database = "sqlite:///" + (tmp_path / "survey.sqlite").as_posix()
    monkeypatch.setenv("REEFVISION_DATABASE_URL", database)
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database)
    command.upgrade(config, "b20_appearance_0001")
    engine = create_engine(database)
    try:
        previous = set(inspect(engine).get_table_names())
        command.upgrade(config, "b20_multimodal_0002")
        assert set(inspect(engine).get_table_names()) == previous | {"multimodal_studies"}
        command.downgrade(config, "b20_appearance_0001")
        assert set(inspect(engine).get_table_names()) == previous
    finally:
        engine.dispose()


def test_interior_exterior_edges_and_uncertain_events():
    events = [(125000, 375000, "accepted")]
    assert classify_window((200000, 250000), events, 200, 1000000) == "inside accepted event"
    assert classify_window((650000, 700000), events, 200, 1000000) == "outside reviewed events"
    assert classify_window((124950, 200000), events, 200, 1000000) == "uncertain event boundary"
    assert classify_window((25000, 50000), [], 30000, 1000000) == "outside reviewed recording"
    assert (
        classify_window((650000, 700000), [*events, (610000, 670000, "uncertain")], 200, 1000000)
        == "unresolved event review"
    )


def test_within_organism_contrast_requires_one_exposed_and_one_control():
    events = [(125000, 375000, "accepted")]
    rows = [
        {"exposure": classify_window(interval, events, 100, 1000000), "roi_mean": value}
        for interval, value in [((200000, 250000), 0.5), ((650000, 700000), 0.2)]
    ]
    assert isclose(paired_difference(rows), 0.3)
    assert paired_difference([rows[0], rows[0]]) is None


def test_reviewed_joint_survey_replays_and_travels(client, test_settings, monkeypatch):
    from reefvision.jobs.workflow import process_workflow_run_job
    from reefvision.storage.datasets import canonical_json_sha256
    from reefvision.tests.test_reviewer_lab_v15 import successful
    from reefvision.tests.test_scientific_project_exchange import (
        export_archive,
        import_archive,
        rewrite,
    )

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[4] / "scripts"))
    from seed_multimodal_live import seed

    fixture = seed(client)
    project = fixture["project_id"]
    base = f"/api/v1/projects/{project}"
    form = fixture["form"]
    headers = {"Authorization": "Bearer " + fixture["fixture_role"]}

    def create(**changes):
        return successful(
            client.post(
                base + "/multimodal/studies",
                json={**form, "operation_id": str(uuid4()), **changes},
                headers=headers,
            ),
            201,
        )

    signed = create()
    result = signed["snapshot"]["result"]
    assert result["status"] == "available" and isclose(
        result["exposed_minus_control"], 0.3, abs_tol=1e-6
    )
    assert [o["valid_pixels"] for o in result["observations"]] == [16, 16]
    assert result["optical_sources"][0]["bands"][0]["wavelength_nm"] == 800
    assert (
        result["optical_sources"][1]["bands"][1]["calibration"]["reference"]
        == "Generated optical panel"
    )
    assert [o["exposure"] for o in result["observations"]] == [
        "inside accepted event",
        "outside reviewed events",
    ]
    for changed in (
        {"identity_review": "uncertain"},
        {"full_recording_reviewed": False},
        {"maximum_time_uncertainty_us": 5},
        {"footprint": {**form["footprint"], "grid": "another frame"}},
        {"footprint": {**form["footprint"], "bounds_xyxy": [0, 0, 4, 4]}},
        {
            "exposures": [
                {**form["exposures"][0], "start_utc": "2026-05-07T12:00:00.125000Z"},
                form["exposures"][1],
            ]
        },
    ):
        refused = create(**changed)["snapshot"]["result"]
        assert (
            refused["status"] == "withheld"
            and refused["reasons"]
            and refused["exposed_minus_control"] is None
        )
    from reefvision.db.models import BioacousticReport
    from reefvision.schemas.multispectral import AcquisitionInput, BandInput

    index = successful(
        client.get(base + "/multispectral/indices/" + form["exposures"][0]["index_id"] + "/export")
    )["snapshot"]
    original = index["acquisition"]
    raw = {key: original[key] for key in AcquisitionInput.model_fields}
    raw["bands"] = [
        {key: b[key] for key in BandInput.model_fields if key in b} for b in raw["bands"]
    ]
    raw["bands"][0]["calibration"] = None
    uncal = successful(client.post(base + "/multispectral/acquisitions", json=raw), 201)
    uncal_index = successful(
        client.post(
            base + "/multispectral/acquisitions/" + uncal["id"] + "/indices",
            json={**index["selection"], "acquisition_sha256": uncal["content_sha256"]},
        ),
        201,
    )
    missing = create(
        exposures=[
            {
                **form["exposures"][0],
                "index_id": uncal_index["id"],
                "index_sha256": uncal_index["content_sha256"],
            },
            form["exposures"][1],
        ]
    )["snapshot"]["result"]
    assert (
        missing["exposed_minus_control"] is None and "calibrat" in str(missing["reasons"]).lower()
    )
    with client.app.state.session_factory() as session:
        audio = session.get(BioacousticReport, form["audio_report_id"])
        audio_base = base + "/bioacoustics/assets/" + audio.asset_id
        source = audio.snapshot_json["source"]["sha256"]
        original_anchor = audio.snapshot_json["anchor"]["id"]
    successful(
        client.post(
            audio_base + "/anchors",
            json={
                "kind": "utc",
                "sample": 0,
                "utc": "2026-05-07T13:00:00Z",
                "source_sha256": source,
                "uncertainty_us": 100,
                "evidence": "Generated conflicting clock source",
            },
        ),
        201,
    )
    conflict = successful(
        client.post(audio_base + "/reports", json={"anchor_id": original_anchor}), 201
    )
    wrong_clock = create(
        audio_report_id=conflict["id"], audio_report_sha256=conflict["report_sha256"]
    )["snapshot"]["result"]
    assert wrong_clock["exposed_minus_control"] is None and "UTC anchor" in str(
        wrong_clock["reasons"]
    )
    study = signed["id"]
    graph = successful(
        client.post(
            base + "/workflow-graphs",
            json={
                "create_new_revision": True,
                "graph": {
                    "graph_id": "paired-survey",
                    "name": "Paired survey replay",
                    "nodes": [
                        {"node_id": "project", "node_type": "project_source"},
                        {
                            "node_id": "survey",
                            "node_type": "multimodal_study_replay",
                            "parameters": {
                                "study_id": study,
                                "study_sha256": signed["content_sha256"],
                            },
                        },
                    ],
                    "edges": [
                        {
                            "edge_id": "project-reference",
                            "source_node_id": "project",
                            "source_port_id": "project",
                            "target_node_id": "survey",
                            "target_port_id": "project",
                        }
                    ],
                },
            },
        ),
        201,
    )["id"]
    for hop in range(3):
        base = f"/api/v1/projects/{project}"
        page = base + "/multimodal/studies/" + study
        assert successful(client.get(page + "/export"))["snapshot"] == signed["snapshot"]
        assert (
            successful(
                client.post(page + "/replay", json={"study_sha256": signed["content_sha256"]})
            )["content_sha256"]
            == signed["content_sha256"]
        )
        run = successful(client.post(base + "/workflow-runs", json={"graph_record_id": graph}), 202)
        assert process_workflow_run_job(
            test_settings, client.app.state.session_factory, run["job_id"]
        )
        completed = successful(client.get("/api/v1/workflow-runs/" + run["id"]))
        assert completed["run"]["status"] == "succeeded"
        artifact = next(
            a for a in completed["artifacts"] if a["data_type"] == "multimodal_study_report"
        )
        assert artifact["payload_json"]["result"] == result
        if hop < 2:
            archive = export_archive(client, test_settings, project)
            if hop == 0:

                def move_box(_manifest, rows):
                    record = next(r for r in rows["multimodal_studies"] if r["id"] == signed["id"])
                    record["snapshot_json"]["boxes"][0]["bounds_xyxy"][0] += 1
                    record["content_sha256"] = canonical_json_sha256(record["snapshot_json"])

                invalid = import_archive(client, rewrite(archive, move_box))
                assert invalid.status_code == 400 and "spatial" in invalid.text
            copied = successful(import_archive(client, archive), 201)
            assert copied["package"]["format_version"] == "2.0"
            mapping = copied["package"]["options_json"]["id_map"]
            graph, study = mapping[graph], mapping[study]
            project = copied["project_id"]
