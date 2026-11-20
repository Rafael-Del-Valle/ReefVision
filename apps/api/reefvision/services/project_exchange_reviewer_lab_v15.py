"""Preserve Reviewer Lab source ledgers across independent project copies."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from reefvision.db.models.review_queue import ReviewQueue
from reefvision.db.models.review_queue_item import ReviewQueueItem
from reefvision.db.models.reviewer_lab_v15 import (
    ReviewerLabDecisionRecord,
    ReviewerLabReportRecord,
    ReviewerLabRoundRecord,
)
from reefvision.domain.errors import ValidationError
from reefvision.schemas.reviewer_lab_v15 import (
    ReviewerLabAdjudication,
    ReviewerLabDecision,
    ReviewerLabJudgement,
    ReviewerLabPlan,
    ReviewerLabReport,
    ReviewerLabReportSubject,
    ReviewerLabRole,
    ReviewerLabRoundCreate,
    ReviewerLabSubject,
)
from reefvision.services.review_queue_exchange_checksums import (
    QUEUE_INPUT_HISTORY,
    historical_queue_item_checksums,
    imported_queue_item_checksum,
    matches_pinned_queue_item,
    queue_item_snapshot,
)
from reefvision.services.reviewer_lab_v15 import reviewer_lab_agreement, reviewer_lab_report_sha256
from reefvision.services.workflow_reviewer_lab_v15 import NODE_TYPE
from reefvision.storage.datasets import canonical_json_sha256

REVIEWER_LAB_SECTIONS = (
    "reviewer_lab_members",
    "reviewer_lab_role_revisions",
    "reviewer_lab_rounds",
    "reviewer_lab_decisions",
    "reviewer_lab_reports",
)
REVIEWER_LAB_PARENTS = {
    "reviewer_lab_role_revisions": ("member_id", "reviewer_lab_members"),
    "reviewer_lab_decisions": ("round_id", "reviewer_lab_rounds"),
}
Row = dict[str, Any]
Sections = dict[str, list[Row]]

# These are original identity-bearing documents or literal values, not live database references.
_ORIGINAL_FIELDS: dict[str, tuple[str, ...]] = {
    "reviewer_lab_members": ("name", "name_key", "role"),
    "reviewer_lab_rounds": ("operation_id", "request_sha256", "plan_json", "plan_sha256"),
    "reviewer_lab_decisions": (
        "operation_id",
        "request_sha256",
        "slot",
        "value",
        "reason",
        "decision_ids_json",
    ),
    "reviewer_lab_reports": ("content_json", "content_sha256"),
}


def _live(identifier: str, origin_ids: Mapping[str, str]) -> str:
    return origin_ids.get(identifier, identifier)


def _index(sections: Sections, name: str) -> dict[str, Row]:
    rows = sections.get(name, [])
    index = {row["id"]: row for row in rows}
    if len(index) != len(rows):
        raise ValueError("Duplicate Reviewer Lab record ID")
    return index


def reviewer_lab_exchange_ids(sections: Sections, origin_ids: Mapping[str, str]) -> set[str]:
    """Planner subject UUIDs are scoped to a round and have no ORM primary-key row."""
    return {
        _live(subject["id"], origin_ids)
        for row in sections.get("reviewer_lab_rounds", [])
        for subject in row["plan_json"]["subjects"]
    }


def _roles(sections: Sections, project_id: str) -> dict[str, ReviewerLabRole]:
    members = _index(sections, "reviewer_lab_members")
    revisions = _index(sections, "reviewer_lab_role_revisions")
    name_keys = set()
    for row in members.values():
        name_key = row["name_key"]
        if (
            row["project_id"] != project_id
            or name_key != row["name"].casefold()
            or name_key in name_keys
        ):
            raise ValueError("Invalid Reviewer Lab member scope or name")
        name_keys.add(name_key)

    result = {
        revision_id: ReviewerLabRole.model_validate(
            {
                **revision,
                "name": members[revision["member_id"]]["name"],
                "role": members[revision["member_id"]]["role"],
            }
        )
        for revision_id, revision in revisions.items()
    }
    seen: set[tuple[str, int]] = set()
    for role in result.values():
        key = (role.member_id, role.revision)
        if key in seen or role.revision < 1:
            raise ValueError("Duplicate reviewer role revision")
        seen.add(key)
        preceding = role.previous_revision_id
        if role.revision == 1:
            if preceding is not None:
                raise ValueError("The first reviewer role revision cannot have a parent")
        else:
            prior = result[preceding or ""]
            if prior.member_id != role.member_id or prior.revision + 1 != role.revision:
                raise ValueError("Reviewer role revision ancestry is not consecutive")
            if role.created_at < prior.created_at:
                raise ValueError("Reviewer role revision dates run backwards")
        if role.role == "manager":
            if (
                role.revision != 1
                or not role.active
                or role.granted_by_role_revision_id is not None
            ):
                raise ValueError("Reviewer archive manager is not an original local role")
        else:
            manager = result[role.granted_by_role_revision_id or ""]
            if manager.role != "manager" or manager.created_at > role.created_at:
                raise ValueError("Reviewer role lacks an authorized historical manager")
    if {member for member, _ in seen} != set(members):
        raise ValueError("Reviewer Lab members lack role revisions")
    return result


def _role_matches(
    original: ReviewerLabRole, actual: ReviewerLabRole, origin_ids: Mapping[str, str]
) -> bool:
    update = {}
    for field in ("id", "member_id", "previous_revision_id", "granted_by_role_revision_id"):
        value = getattr(original, field)
        if isinstance(value, str):
            update[field] = _live(value, origin_ids)
    return original.model_copy(update=update) == actual


@dataclass(frozen=True)
class _Round:
    plan: ReviewerLabPlan
    record: Row
    subject_ids: set[str]
    members_by_slot: dict[str, str]


def _rounds(
    sections: Sections,
    project_id: str,
    roles: dict[str, ReviewerLabRole],
    origin_ids: Mapping[str, str],
) -> dict[str, _Round]:
    images = _index(sections, "images")
    queues = _index(sections, "review_queues")
    items = _index(sections, "review_queue_items")
    occupied_ids = {row.get("id") for rows in sections.values() for row in rows}
    rounds = {}
    for round_id, record in _index(sections, "reviewer_lab_rounds").items():
        if (
            record["project_id"] != project_id
            or canonical_json_sha256(record["plan_json"]) != record["plan_sha256"]
        ):
            raise ValueError("Reviewer plan scope or checksum differs")
        plan = ReviewerLabPlan.model_validate(record["plan_json"])
        if plan.model_dump(mode="json") != record["plan_json"]:
            raise ValueError("Original Reviewer Lab plan contains unexpected fields or values")
        request = ReviewerLabRoundCreate.model_validate(
            {
                "operation_id": record["operation_id"],
                "title": plan.title,
                "criterion": plan.criterion,
                "reviewer_member_ids": [role.member_id for role in plan.reviewers],
                "adjudicator_member_id": plan.adjudicator.member_id,
                "sources": [
                    {
                        "type": "queue_item" if subject.queue_item_id else "image",
                        "id": subject.queue_item_id or subject.image_id,
                    }
                    for subject in plan.subjects
                ],
            }
        )
        if canonical_json_sha256(request.model_dump(mode="json")) != record["request_sha256"]:
            raise ValueError("Original Reviewer Lab assignment request checksum differs")
        expected_roles = (plan.manager, *plan.reviewers, plan.adjudicator)
        if (
            tuple(role.role for role in expected_roles)
            != ("manager", "reviewer", "reviewer", "adjudicator")
            or not all(
                role.active and _role_matches(role, roles[_live(role.id, origin_ids)], origin_ids)
                for role in expected_roles
            )
            or len({_live(role.member_id, origin_ids) for role in expected_roles}) != 4
            or not 1 <= len(plan.subjects) <= 100
        ):
            raise ValueError("Reviewer plan does not establish distinct qualified roles")

        subject_ids = set()
        image_ids = set()
        for subject in plan.subjects:
            subject_id = _live(subject.id, origin_ids)
            UUID(subject_id)
            if subject_id in occupied_ids:
                raise ValueError("Reviewer subject UUID collides with another archive identity")
            occupied_ids.add(subject_id)
            subject_ids.add(subject_id)
            image_id = _live(subject.image_id, origin_ids)
            image = images[image_id]
            if (
                image_id in image_ids
                or image["project_id"] != project_id
                or image["sha256"] != subject.source_sha256
                or image["annotation_revision"] < subject.annotation_revision
                or image["original_filename"] != subject.filename
            ):
                raise ValueError("Reviewer subject does not bind the original project image")
            image_ids.add(image_id)
            if subject.queue_item_id is None:
                if subject.queue_id is not None or subject.queue_input_sha256 is not None:
                    raise ValueError("Reviewer queue source is incomplete")
                continue
            item = items[_live(subject.queue_item_id, origin_ids)]
            queue_id = _live(subject.queue_id or "", origin_ids)
            if (
                queues[queue_id]["project_id"] != project_id
                or item["project_id"] != project_id
                or item["review_queue_id"] != queue_id
                or item["image_id"] != image_id
                or not matches_pinned_queue_item(
                    queues[queue_id]["configuration_json"], item, subject.queue_input_sha256
                )
            ):
                raise ValueError("Reviewer subject differs from its pinned queue item")
        rounds[round_id] = _Round(
            plan,
            record,
            subject_ids,
            {
                slot: _live(role.member_id, origin_ids)
                for slot, role in zip(
                    ("first", "second", "adjudication"), expected_roles[1:], strict=True
                )
            },
        )
    return rounds


def _decisions(
    sections: Sections,
    rounds: dict[str, _Round],
    roles: dict[str, ReviewerLabRole],
    origin_ids: Mapping[str, str],
) -> dict[tuple[str, str, str], ReviewerLabDecision]:
    index: dict[tuple[str, str, str], ReviewerLabDecision] = {}
    operations = set()
    rows = _index(sections, "reviewer_lab_decisions")
    for row in rows.values():
        decision = ReviewerLabDecision.model_validate(row)
        lab_round = rounds[row["round_id"]]
        role = roles[decision.role_revision_id]
        op = (row["round_id"], row["operation_id"])
        assignment = (row["round_id"], row["subject_id"], decision.slot)
        if (
            assignment in index
            or op in operations
            or row["subject_id"] not in lab_round.subject_ids
            or role.member_id != lab_round.members_by_slot[decision.slot]
            or not role.active
            or decision.created_at < role.created_at
        ):
            raise ValueError("Reviewer decision does not belong to its original assignment")
        values = {key: row[key] for key in ("operation_id", "value", "reason")}
        values["plan_sha256"] = lab_round.record["plan_sha256"]
        ids = row["decision_ids_json"]
        request: ReviewerLabJudgement
        if decision.slot == "adjudication":
            if ids is None:
                raise ValueError("Adjudication must bind both independent decisions")
            request = ReviewerLabAdjudication.model_validate({**values, "decision_ids": ids})
        else:
            if ids is not None:
                raise ValueError("A peer's independent decision cannot cite other decisions")
            request = ReviewerLabJudgement.model_validate(values)
        if canonical_json_sha256(request.model_dump(mode="json")) != row["request_sha256"]:
            raise ValueError("Original Reviewer Lab decision checksum differs")
        index[assignment] = decision
        operations.add(op)

    for (round_id, subject_id, slot), decision in index.items():
        if slot != "adjudication":
            continue
        left = index[(round_id, subject_id, "first")]
        right = index[(round_id, subject_id, "second")]
        cited = [_live(value, origin_ids) for value in rows[decision.id]["decision_ids_json"]]
        if (
            cited != [left.id, right.id]
            or left.value == right.value
            or max(left.created_at, right.created_at) > decision.created_at
        ):
            raise ValueError(
                "Adjudication does not match two earlier disagreeing independent decisions"
            )
    return index


def _decision_matches(
    original: ReviewerLabDecision | None,
    actual: ReviewerLabDecision | None,
    origin_ids: Mapping[str, str],
) -> bool:
    if original is None or actual is None:
        return original is actual
    mapped = original.model_copy(
        update={
            "id": _live(original.id, origin_ids),
            "role_revision_id": _live(original.role_revision_id, origin_ids),
        }
    )
    return mapped == actual


def _reports(
    sections: Sections,
    project_id: str,
    rounds: dict[str, _Round],
    roles: dict[str, ReviewerLabRole],
    decisions: dict[tuple[str, str, str], ReviewerLabDecision],
    origin_ids: Mapping[str, str],
) -> None:
    reports = _index(sections, "reviewer_lab_reports")
    sealed_rounds = set()
    for report_id, row in reports.items():
        body = row["content_json"]
        digest = row["content_sha256"]
        report = ReviewerLabReport.model_validate({**body, "content_sha256": digest})
        round_id = row["round_id"]
        lab_round = rounds[round_id]
        sealer_id = _live(report.sealed_by_role_revision_id, origin_ids)
        sealer = roles[sealer_id]
        if (
            row["project_id"] != project_id
            or _live(report.project_id, origin_ids) != project_id
            or _live(report.id, origin_ids) != report_id
            or _live(report.round_id, origin_ids) != round_id
            or round_id in sealed_rounds
            or reviewer_lab_report_sha256(body) != digest
            or report.model_dump(mode="json", exclude={"content_sha256"}) != body
            or report.plan_sha256 != lab_round.record["plan_sha256"]
            or report.plan != lab_round.plan
            or report.plan.model_dump(mode="json") != lab_round.record["plan_json"]
            or sealer.role != "manager"
            or not sealer.active
            or sealer.created_at > report.sealed_at
            or len(report.subjects) != len(lab_round.plan.subjects)
        ):
            raise ValueError("Sealed Reviewer Lab report identity, source plan, or digest differs")
        sealed_rounds.add(round_id)
        used_roles = {sealer_id}
        for subject, source in zip(report.subjects, lab_round.plan.subjects, strict=True):
            _check_report_subject(
                subject,
                source,
                round_id,
                report,
                decisions,
                used_roles,
                origin_ids,
            )
        if (
            len(report.role_revisions) != len(used_roles)
            or {_live(role.id, origin_ids) for role in report.role_revisions} != used_roles
            or not all(
                _role_matches(role, roles[_live(role.id, origin_ids)], origin_ids)
                for role in report.role_revisions
            )
            or reviewer_lab_agreement(report.subjects) != report.agreement
        ):
            raise ValueError("Sealed Reviewer Lab agreement does not match its reviewed decisions")

    nodes = _index(sections, "workflow_node_runs")
    for artifact in sections.get("workflow_artifacts", []):
        if artifact["data_type"] != NODE_TYPE:
            continue
        producer = nodes[artifact["producer_node_run_id"]]
        report_row = reports[producer["parameters_json"]["report_id"]]
        expected = {**report_row["content_json"], "content_sha256": report_row["content_sha256"]}
        if (
            producer["node_type"] != NODE_TYPE
            or artifact["producer_port_id"] != "report"
            or artifact["payload_json"] != expected
            or artifact["payload_sha256"] != canonical_json_sha256(expected)
        ):
            raise ValueError("Reviewer Lab workflow artifact differs from the sealed report")


def _check_report_subject(
    subject: ReviewerLabReportSubject,
    source: ReviewerLabSubject,
    round_id: str,
    report: ReviewerLabReport,
    decisions: dict[tuple[str, str, str], ReviewerLabDecision],
    used_roles: set[str],
    origin_ids: Mapping[str, str],
) -> None:
    subject_id = _live(source.id, origin_ids)
    left = decisions[(round_id, subject_id, "first")]
    right = decisions[(round_id, subject_id, "second")]
    resolution = decisions.get((round_id, subject_id, "adjudication"))
    if (
        subject.source != source
        or (left.value != right.value) != (resolution is not None)
        or not _decision_matches(subject.first, left, origin_ids)
        or not _decision_matches(subject.second, right, origin_ids)
        or not _decision_matches(subject.resolution, resolution, origin_ids)
    ):
        raise ValueError("Sealed Reviewer Lab subject differs from its independent decisions")
    for decision in (left, right, resolution):
        if decision is not None:
            if decision.created_at > report.sealed_at:
                raise ValueError("Reviewer Lab report predates a sealed decision")
            used_roles.add(decision.role_revision_id)


def validate_reviewer_lab_exchange(
    sections: Sections, *, project_id: str, origin_ids: Mapping[str, str]
) -> None:
    """Recompute the sealed evidence against the archived plans and independent ledger."""
    try:
        if "reviewer_lab_credentials" in sections or any(
            "credential_sha256" in row
            for name in REVIEWER_LAB_SECTIONS
            for row in sections.get(name, [])
        ):
            raise ValueError("Reviewer Lab credentials are local to the source project")
        if not isinstance(origin_ids, Mapping):
            raise ValueError("The Reviewer Lab source identity map is invalid")
        roles = _roles(sections, project_id)
        rounds = _rounds(sections, project_id, roles, origin_ids)
        decisions = _decisions(sections, rounds, roles, origin_ids)
        _reports(sections, project_id, rounds, roles, decisions, origin_ids)
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise ValidationError(f"Invalid Reviewer Lab archive evidence: {exc}") from exc


def restore_reviewer_lab_row(name: str, row: Row, values: Row, id_map: Mapping[str, str]) -> None:
    """Map only live links, while preserving frozen evidence and author text verbatim."""
    for field in _ORIGINAL_FIELDS.get(name, ()):
        values[field] = row[field]
    if name == "reviewer_lab_decisions":
        values["subject_id"] = id_map[row["subject_id"]]


def restore_reviewer_lab_exchange(
    session: Session, sections: Sections, id_map: Mapping[str, str]
) -> None:
    """Confirm original evidence persisted intact before committing the project copy."""
    for name, model in (
        ("reviewer_lab_rounds", ReviewerLabRoundRecord),
        ("reviewer_lab_decisions", ReviewerLabDecisionRecord),
        ("reviewer_lab_reports", ReviewerLabReportRecord),
    ):
        for row in sections.get(name, []):
            restored = session.get(model, id_map[row["id"]])
            if restored is None or any(
                getattr(restored, field) != row[field] for field in _ORIGINAL_FIELDS[name]
            ):
                raise ValidationError("Reviewer Lab original evidence changed during project copy")
    if sections.get("reviewer_lab_rounds"):
        _restore_queue_checksums(session, sections, id_map)


def _restore_queue_checksums(
    session: Session, sections: Sections, id_map: Mapping[str, str]
) -> None:
    queues = _index(sections, "review_queues")
    pinned = {
        subject["queue_input_sha256"]
        for round_ in sections["reviewer_lab_rounds"]
        for subject in round_["plan_json"]["subjects"]
        if subject["queue_item_id"]
    }
    histories: dict[str, dict[str, Any]] = {}
    for original in sections.get("review_queue_items", []):
        queue_id = original["review_queue_id"]
        archive_queue = queues[queue_id]["configuration_json"]
        ancestors = {
            original["input_checksum"],
            *historical_queue_item_checksums(archive_queue, original),
        }
        if not ancestors.intersection(pinned):
            continue
        current = session.get(ReviewQueueItem, id_map[original["id"]])
        if current is None:
            raise ValidationError("Reviewer Lab review queue item is missing after import")
        if current.input_checksum != imported_queue_item_checksum(queue_item_snapshot(current)):
            raise ValidationError("Reviewer Lab review queue input failed import verification")
        histories.setdefault(queue_id, {})[current.id] = {
            "current": current.input_checksum,
            "ancestors": sorted(ancestors),
        }
    for queue_id, history in histories.items():
        queue = session.get(ReviewQueue, id_map[queue_id])
        if queue is None:
            raise ValidationError("Reviewer Lab review queue is missing after import")
        queue.configuration_json = {**queue.configuration_json, QUEUE_INPUT_HISTORY: history}
