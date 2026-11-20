"""Taxonomy receipts preserve local attribution and real evidence across project copies."""

import json
from copy import deepcopy
from datetime import timedelta
from io import BytesIO
from typing import Any
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from reefvision.config import Settings
from reefvision.db.models import ImageAsset
from reefvision.db.models.ecology_identity_revision import EcologyIdentityRevision
from reefvision.db.models.reviewer_lab_v15 import ReviewerLabMember, ReviewerLabRoleRevision
from reefvision.db.models.taxonomy import (
    DetectabilityAssessment,
    DetectabilityPresenceReview,
    DetectabilityVisit,
    TaxonProposal,
    TaxonReview,
)
from reefvision.domain.errors import ValidationError
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.project_exchange import _row
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.tests.test_reviewer_lab_v15 import role_fixture, successful
from reefvision.tests.test_scientific_project_exchange import (
    MANIFEST,
    database_counts,
    export_archive,
    import_archive,
    rewrite,
)
from reefvision.tests.test_taxonomy import PROTOCOL, START, organism, proposal_body, source
from reefvision.tests.test_workflow_execution_phase10 import _queue_run, _save_graph


def taxonomy_history(client: TestClient) -> tuple[str, dict[str, Any], dict[str, Any]]:
    project, _, roles = role_fixture(client)
    root = f"/api/v1/projects/{project}"
    taxonomy = root + "/taxonomy"
    manager = roles["Manager"][1]
    reviewer = roles["Reviewer A"][1]
    proposal = successful(
        client.post(
            taxonomy + "/proposals",
            headers=manager,
            json=proposal_body(organism(client, root, 1), source(client, project, 1)),
        ),
        201,
    )
    successful(
        client.post(
            taxonomy + f"/proposals/{proposal['id']}/reviews",
            json={
                "expected_revision": 0,
                "decision": "confirmed",
                "reason": "Local synthetic corroboration",
            },
            headers=reviewer,
        ),
        201,
    )
    for count in range(2):
        visit = successful(
            client.post(
                taxonomy + "/visits",
                headers=manager,
                json={
                    "proposal_id": proposal["id"],
                    "protocol": PROTOCOL,
                    "started_at": (START + timedelta(minutes=2 * count)).isoformat(),
                    "effort_seconds": 9,
                    "outcome": "detected" if count else "not_detected",
                    "source": source(client, project, 2 + 2 * count),
                    "notes": "Documented generated control",
                },
            ),
            201,
        )
        successful(
            client.post(
                taxonomy + f"/visits/{visit['id']}/presence-reviews",
                headers=reviewer,
                json={
                    "expected_revision": 0,
                    "decision": "confirmed",
                    "source": source(client, project, 3 + 2 * count),
                    "reason": "Reviewed distinct known presence reference",
                },
            ),
            201,
        )
    assessment = successful(
        client.post(
            taxonomy + "/assessments",
            json={
                "scientific_name": "Plexaura homomalla",
                "rank": "species",
                "protocol": PROTOCOL,
                "unit_type": "tank",
                "minimum_effort_seconds": 5,
                "window_start": START.isoformat(),
                "window_end": (START + timedelta(hours=1)).isoformat(),
            },
        ),
        201,
    )
    assert assessment["result"]["status"] == "withheld"
    assert assessment["result"]["eligible_visits"] == 2
    return project, proposal, assessment


@pytest.mark.parametrize(
    "case", ["false_estimate", "unknown_authority", "foreign_source", "self_review"]
)
def test_exchange_validates_generated_visit_and_frozen_result(
    client: TestClient, case: str
) -> None:
    from reefvision.services.project_exchange_taxonomy_v18 import validate_taxonomy_exchange

    project, proposal, _ = taxonomy_history(client)
    with client.app.state.session_factory() as session:
        models = (
            ImageAsset,
            EcologyIdentityRevision,
            ReviewerLabMember,
            TaxonProposal,
            TaxonReview,
            DetectabilityVisit,
            DetectabilityPresenceReview,
            DetectabilityAssessment,
        )
        sections = {
            model.__tablename__: [
                _row(row)
                for row in session.scalars(select(model).where(model.project_id == project))
            ]
            for model in models
        }
        member_ids = [row["id"] for row in sections["reviewer_lab_members"]]
        sections["reviewer_lab_role_revisions"] = [
            _row(row)
            for row in session.scalars(
                select(ReviewerLabRoleRevision).where(
                    ReviewerLabRoleRevision.member_id.in_(member_ids)
                )
            )
        ]
    validate_taxonomy_exchange(project, sections, None)
    tampered = deepcopy(sections)
    if case == "false_estimate":
        changed = tampered["detectability_assessments"][0]
        changed["snapshot_json"]["estimate"] = 0.92
    elif case == "unknown_authority":
        changed = tampered["taxonomy_proposals"][0]
        changed["snapshot_json"]["author"]["authority"] = "externally_certified"
    elif case == "foreign_source":
        changed = tampered["taxonomy_proposals"][0]
        changed["snapshot_json"]["source"]["id"] = "7488b239-eba6-4b8e-a81f-1295e65c9b15"
    else:
        changed = tampered["taxonomy_reviews"][0]
        changed["snapshot_json"]["reviewer"] = proposal["proposal"]["author"]
        changed["reviewer_role_revision_id"] = proposal["proposal"]["author"]["role_revision_id"]
    changed["content_sha256"] = canonical_json_sha256(changed["snapshot_json"])
    with pytest.raises(ValidationError, match="Taxonomy"):
        validate_taxonomy_exchange(project, tampered, None)


def test_project_exchange_twice_retains_taxon_attribution_and_replays_cached_result(
    client: TestClient, test_settings: Settings
) -> None:
    project, proposal, assessment = taxonomy_history(client)
    root = f"/api/v1/projects/{project}"
    payload = {
        "graph_id": "archived-detectability",
        "name": "Archived detectability",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "assess",
                "node_type": "detectability_assessment",
                "parameters": {
                    "assessment_id": assessment["id"],
                    "assessment_sha256": assessment["result_sha256"],
                },
            },
        ],
        "edges": [
            {
                "edge_id": "project-assess",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "assess",
                "target_port_id": "project",
            }
        ],
    }
    graph = _save_graph(client, project, payload)
    app = client.app.state
    queued = _queue_run(client, project, graph["id"])
    assert process_workflow_run_job(app.settings, app.session_factory, str(queued["job_id"]))
    detail = successful(client.get(f"/api/v1/workflow-runs/{queued['id']}"))
    [original_artifact] = [
        row for row in detail["artifacts"] if row["data_type"] == "detectability_assessment"
    ]
    original_bytes = export_archive(client, test_settings, project)
    with ZipFile(BytesIO(original_bytes)) as package:
        archive_manifest = json.loads(package.read(MANIFEST))
        assert archive_manifest["format_version"] == "1.8"
        assert not any("reviewer_lab_credentials" in name for name in package.namelist())

    archive = original_bytes
    current_proposal, current_assessment, current_graph = (
        proposal["id"],
        assessment["id"],
        graph["id"],
    )
    source = proposal["proposal"]["source"]
    measure_path = f"/taxonomy/source/image/{source['id']}?sha256={source['sha256']}"
    original_media = client.get(root + measure_path)
    assert original_media.status_code == 200
    for _ in range(2):
        imported = successful(import_archive(client, archive), 201)
        copied = imported["project_id"]
        mapping = imported["package"]["options_json"]["id_map"]
        current_proposal, current_assessment, current_graph = (
            mapping[current_proposal],
            mapping[current_assessment],
            mapping[current_graph],
        )
        copy_root = f"/api/v1/projects/{copied}"
        copied_proposal = successful(
            client.get(copy_root + f"/taxonomy/proposals/{current_proposal}")
        )
        assert copied_proposal["project_id"] == copied
        assert copied_proposal["proposal_sha256"] == proposal["proposal_sha256"]
        assert copied_proposal["proposal"] == proposal["proposal"]
        copied_assessment = successful(
            client.get(copy_root + f"/taxonomy/assessments/{current_assessment}/export")
        )
        assert copied_assessment["project_id"] == copied
        assert copied_assessment["result"] == assessment["result"]
        assert copied_assessment["result_sha256"] == assessment["result_sha256"]
        remapped = client.get(copy_root + measure_path, follow_redirects=False)
        assert remapped.status_code == 307
        assert source["id"] not in remapped.headers["location"]
        assert client.get(remapped.headers["location"]).content == original_media.content
        pre_restore = successful(client.get(copy_root + "/workflow-runs"))
        assert len(pre_restore) >= 1
        historic = [
            artifact
            for row in pre_restore
            for artifact in successful(client.get(f"/api/v1/workflow-runs/{row['id']}"))[
                "artifacts"
            ]
            if artifact["data_type"] == "detectability_assessment"
            and artifact["payload_sha256"] == original_artifact["payload_sha256"]
        ]
        assert historic and historic[0]["payload_json"] == original_artifact["payload_json"]

        run = _queue_run(client, copied, current_graph)
        assert process_workflow_run_job(app.settings, app.session_factory, str(run["job_id"]))
        detail = successful(client.get(f"/api/v1/workflow-runs/{run['id']}"))
        [artifact] = [
            row for row in detail["artifacts"] if row["data_type"] == "detectability_assessment"
        ]
        assert artifact["payload_json"] == copied_assessment
        assert canonical_json_sha256(copied_assessment) == artifact["payload_sha256"]
        # Recompute from re-bound observations without relabeling the inherited snapshot.
        reviewed_control = successful(
            client.post(copy_root + "/taxonomy/assessments", json=assessment["result"]["request"]),
            201,
        )
        assert reviewed_control["result"]["eligible_visits"] == 2
        archive = export_archive(client, test_settings, copied)
    assert successful(client.get(root + f"/taxonomy/assessments/{assessment['id']}")) == assessment


def test_exchange_inspection_rejects_rehashed_false_group_totals(
    client: TestClient, test_settings: Settings
) -> None:
    project, _, _ = taxonomy_history(client)
    original = export_archive(client, test_settings, project)

    def tamper(_manifest: Any, sections: dict[str, Any]) -> None:
        row = sections["detectability_assessments"][0]
        row["snapshot_json"]["eligible_visits"] = 110
        row["content_sha256"] = canonical_json_sha256(row["snapshot_json"])

    changed = rewrite(original, tamper)
    before = database_counts(client)
    response = client.post(
        "/api/v1/exchange-packages/inspect",
        files={"file": ("altered.zip", changed, "application/zip")},
    )
    assert response.status_code == 200, response.text
    assert not response.json()["compatible"]
    assert database_counts(client) == before
    assert import_archive(client, changed).status_code == 400
    assert database_counts(client) == before
