from pathlib import Path
from uuid import uuid4

from reefvision.jobs.pose_appearance import process_appearance
from reefvision.jobs.project_exchange import process_project_exchange_export_job
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.schemas.reefpose_validation import ReferenceRecording
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.tests.test_project_exchange_reefpose_workflow import import_archive
from reefvision.tests.test_reviewer_lab_v15 import role_fixture
from reefvision.tests.test_scientific_project_exchange import rewrite


def test_native_appearance_review_heldout_replay_and_two_exchanges(client, tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[4] / "scripts"))
    from seed_pose_appearance_live import seed
    from verify_reefpose_temporal_lineage_live import checked, queue_workflow

    data = seed(client, tmp_path)
    app = client.app
    settings, factory = app.state.settings, app.state.session_factory
    project = data["project_id"]
    base = f"/api/v1/projects/{project}"
    api = base + "/pose-appearance"

    def get(url):
        return checked(client.get(url), 200)

    videos = data["videos"]
    probe = videos[-2]["observations"]["striped"][0]
    match = videos[-1]["observations"]["striped"][0]
    other = videos[-1]["observations"]["spotted"][0]
    payload = {
        "operation_id": str(uuid4()),
        "name": "Generated cross-video appearance",
        "model_id": data["model_id"],
        "query_observation_id": probe,
        "gallery_observation_ids": [other, match],
        "minimum_gap_seconds": 0.9,
        "minimum_margin": 0,
        "maximum_heldout_false_rate": 0.1,
        "maximum_heldout_missed_rate": 0.2,
        "reference_id": data["reference_id"],
        "reference_rater": data["rater"],
        "device": "cpu",
    }
    assert probe in {o["id"] for o in get(api + "/observations")}
    near = client.post(
        api + "/studies",
        json={**payload, "gallery_observation_ids": [videos[-2]["observations"]["striped"][1]]},
    )
    assert near.status_code == 400 and "gap" in near.text
    records = [
        {k: v for k, v in row.items() if k in ReferenceRecording.model_fields}
        for row in get(base + "/reefpose-references/" + data["reference_id"])["manifest"][
            "recordings"
        ]
    ]
    for row in records:
        if row["split"] == "test":
            row["individuals"][0]["id"] = "development-striped"
            for label in row["annotations"]:
                for pose in label["poses"]:
                    if pose["individual_id"] == "test-striped":
                        pose["individual_id"] = "development-striped"
    reused = checked(
        client.post(
            base + "/reefpose-references",
            json={
                "name": "Deliberate overlapping identity",
                "data_kind": "synthetic",
                "recordings": records,
            },
        ),
        201,
    )
    leak = client.post(api + "/studies", json={**payload, "reference_id": reused["id"]})
    assert leak.status_code == 400 and "both development and held-out" in leak.text
    queued = checked(client.post(api + "/studies", json=payload), 202)
    assert checked(client.post(api + "/studies", json=payload), 202)["id"] == queued["id"]
    assert process_appearance(settings, factory, queued["id"])
    done = get("/api/v1/jobs/" + queued["id"])
    assert done["status"] == "succeeded", done
    receipt = done["result_json"]
    study = api + "/studies/" + receipt["study_id"]
    result = get(study)
    assert result["content_sha256"] == receipt["study_sha256"]
    changed = checked(
        client.post(
            api + "/studies",
            json={**payload, "operation_id": str(uuid4()), "maximum_heldout_false_rate": 0.2},
        ),
        202,
    )
    assert process_appearance(settings, factory, changed["id"])
    rejected = get("/api/v1/jobs/" + changed["id"])
    assert (
        rejected["status"] == "failed" and "frozen appearance protocol" in rejected["error_message"]
    )
    computation = result["snapshot"]["result"]
    assert computation["checkpoint_training_step"] > 0
    assert computation["ranking"]["selected"] == match
    heldout = computation["evaluation"]["heldout"]
    assert heldout["prespecified_targets"] == {
        "false_match_rate": {"limit": 0.1, "within_limit": True},
        "missed_match_rate": {"limit": 0.2, "within_limit": True},
    }
    assert heldout["scored_animals"] == 2 and heldout["scored_recording_groups"] == 2
    assert heldout["counts"]["genuine_pairs"] == 8 and heldout["counts"]["impostor_pairs"] == 8
    assert (
        heldout["counts"]["false_match_rate"] == 0 and heldout["counts"]["missed_match_rate"] == 0
    )
    assert client.get(study + "/crops/" + probe).headers["content-type"] == "image/png"
    _, _, roles = role_fixture(client, project)

    def review(actor, outcome, identifier):
        return client.post(
            study + "/reviews",
            headers=roles[actor][1],
            json={
                "operation_id": str(uuid4()),
                "study_sha256": result["content_sha256"],
                "candidate_observation_id": identifier,
                "outcome": outcome,
                "reason": "Generated comparison against known pixels",
            },
        )

    assert (
        checked(review("Reviewer A", "same", match), 200)["resolution"]
        == "awaiting independent review"
    )
    assert get(study)["decisions"] == []
    assert review("Reviewer A", "different", match).status_code == 409
    assert checked(review("Reviewer B", "different", match), 200)["resolution"] == "disputed"
    sealed = checked(review("Adjudicator", "same", match), 200)
    assert sealed["resolution"] == "same" and len(sealed["decisions"]) == 3
    assert get(study + "/export")["snapshot"] == result["snapshot"]
    graph = {
        "graph_id": "fixture-appearance",
        "name": "Replay appearance reference",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "appearance",
                "node_type": "reefpose_appearance_replay",
                "parameters": {
                    "study_id": receipt["study_id"],
                    "study_sha256": result["content_sha256"],
                },
            },
        ],
        "edges": [
            {
                "edge_id": "input",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "appearance",
                "target_port_id": "project",
            }
        ],
    }
    workflow = queue_workflow(client, base, graph)
    assert process_workflow_run_job(settings, factory, workflow["job_id"])
    actual = get("/api/v1/workflow-runs/" + workflow["id"])
    assert actual["run"]["status"] == "succeeded", actual["run"]
    assert any(a["data_type"] == "pose_appearance_report" for a in actual["artifacts"])
    snapshots = sealed["snapshot"]
    study_id = receipt["study_id"]
    for hop in range(2):
        source = f"/api/v1/projects/{project}"
        exported = checked(
            client.post(
                source + "/exchange-packages",
                json={"include_media": True, "include_model_weights": True},
            ),
            202,
        )
        assert process_project_exchange_export_job(settings, factory, exported["job_id"])
        archive = client.get("/api/v1/exchange-packages/" + exported["package"]["id"] + "/download")
        assert archive.status_code == 200
        if hop == 0:

            def change_candidate(_manifest, sections):
                decision = sections["pose_appearance_decisions"][0]
                decision["payload_json"]["candidate_observation_id"] = str(uuid4())
                decision["content_sha256"] = canonical_json_sha256(decision["payload_json"])

            inconsistent = import_archive(client, rewrite(archive.content, change_candidate))
            assert inconsistent.status_code == 400 and "Appearance review" in inconsistent.text
        imported = checked(import_archive(client, archive.content), 201)
        assert imported["package"]["format_version"] == "2.0"
        project = imported["project_id"]
        mapping = imported["package"]["options_json"]["id_map"]
        study_id = mapping[study_id]
        archived_run = get("/api/v1/workflow-runs/" + mapping[workflow["id"]])
        report = next(
            a for a in archived_run["artifacts"] if a["data_type"] == "pose_appearance_report"
        )
        assert (
            report["payload_json"]["download_url"]
            == f"/projects/{project}/pose-appearance/studies/{study_id}/export"
        )
        graph_id = archived_run["run"]["workflow_graph_record_id"]
        workflow = checked(
            client.post(
                f"/api/v1/projects/{project}/workflow-runs", json={"graph_record_id": graph_id}
            ),
            202,
        )
        assert process_workflow_run_job(settings, factory, workflow["job_id"])
        assert get("/api/v1/workflow-runs/" + workflow["id"])["run"]["status"] == "succeeded"
        copy = f"/api/v1/projects/{project}/pose-appearance/studies/{study_id}"
        reopened = get(copy)
        assert reopened["content_sha256"] == sealed["content_sha256"]
        assert reopened["snapshot"] == snapshots and reopened["resolution"] == "same"
        replay_job = checked(
            client.post(
                copy + "/replay",
                json={"study_sha256": sealed["content_sha256"], "operation_id": str(uuid4())},
            ),
            202,
        )
        assert process_appearance(settings, factory, replay_job["id"])
        assert get("/api/v1/jobs/" + replay_job["id"])["result_json"]["replayed"]
