"""Taxonomy receipts preserve local attribution and real evidence across project copies."""

from copy import deepcopy
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

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
from reefvision.services.project_exchange import _row
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.tests.test_reviewer_lab_v15 import role_fixture, successful
from reefvision.tests.test_taxonomy import PROTOCOL, START, organism, proposal_body, source


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
