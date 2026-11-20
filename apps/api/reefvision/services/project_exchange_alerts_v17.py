"""Validate and rebind one project's portable monitoring evidence."""

from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timedelta
from math import ceil, fsum
from typing import Any
from uuid import UUID

from pydantic import ValidationError as InvalidSchema

from reefvision.domain.errors import ValidationError
from reefvision.schemas.ecology_event_summary import EventSummarySnapshot
from reefvision.schemas.monitoring import (
    MONITORING_RULE,
    BiologicalMonitoringRule,
    EnvironmentalMonitoringRule,
    MonitoringAlertReviewRead,
    MonitoringAssessmentResult,
    MonitoringFinding,
    MonitoringRuleCreate,
    MonitoringSourceReference,
)
from reefvision.schemas.scientific_data import ScientificRecordResponse
from reefvision.services.ecology_event_summary import EVENT_SUMMARY_JOB
from reefvision.services.monitoring_evidence import (
    biological_session_evidence,
    monitoring_evidence_checksum,
    monitoring_utc,
    sort_monitoring_evidence,
)
from reefvision.services.scientific_data import content_hash
from reefvision.storage.datasets import canonical_json_sha256

RULES = "monitoring_rules"
ASSESSMENTS = "monitoring_assessments"
ALERTS = "monitoring_alerts"
REVIEWS = "monitoring_alert_reviews"
SECTIONS = (RULES, ASSESSMENTS, ALERTS, REVIEWS)
Rows = dict[str, list[dict[str, Any]]]


def _uuid(value: Any) -> str:
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError("Expected canonical UUID")
    return value


def _rule_body(row: dict[str, Any]) -> dict[str, Any]:
    return {
        **{key: row[key] for key in ("label", "kind", "protocol", "metric", "unit")},
        "parameters": row["parameters_json"],
    }


def _evidence_hash(body: MonitoringAssessmentResult) -> str:
    return monitoring_evidence_checksum(
        body.rule_sha256, body, body.source_refs, body.exclusions, body.biological_sessions
    )


def _finding_key(finding: MonitoringFinding, *, biological: bool) -> str:
    if finding.kind == "drop":
        if finding.source_ids or not finding.missing_slots or not finding.observed_at:
            raise ValidationError("A monitoring drop does not have its expected time slots")
        first, sep, count = finding.finding_key.removeprefix("drop/").partition("/")
        if (
            not sep
            or not first.isascii()
            or not first.isdigit()
            or count != str(finding.missing_slots)
        ):
            raise ValidationError("Monitoring drop has an invalid slot identity")
        return f"drop/{int(first)}/{count}"
    if biological:
        if finding.kind not in {"lower_limit", "upper_limit"} or not finding.source_ids:
            raise ValidationError("Biological alert does not bind reviewed source summaries")
        return f"{finding.kind}/event_rate"
    required_sources = 2 if finding.kind == "drift" else 1
    if (
        len(finding.source_ids) != required_sources
        or len(set(finding.source_ids)) != required_sources
    ):
        raise ValidationError("Monitoring finding does not bind its source observations")
    return f"{finding.kind}/" + "/".join(str(source) for source in finding.source_ids)


def _owned_index(section: str, rows: Rows, project_id: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows.get(section, []):
        identifier = _uuid(row["id"])
        if row["project_id"] != project_id or identifier in result:
            raise ValidationError("Monitoring archive contains a duplicate or foreign project row")
        result[identifier] = row
    return result


def _event_summary(row: dict[str, Any]) -> EventSummarySnapshot:
    result = row["result_json"]
    if (
        row["job_type"] != EVENT_SUMMARY_JOB
        or row["status"] != "succeeded"
        or canonical_json_sha256(result["snapshot"]) != result["content_sha256"]
    ):
        raise ValidationError("Monitoring rule refers to an invalid reviewed event summary")
    return EventSummarySnapshot.model_validate(result["snapshot"])


def _source_links(
    result: MonitoringAssessmentResult,
    sources: dict[str, dict[str, Any]],
    summaries: dict[str, dict[str, Any]],
    rule: MonitoringRuleCreate,
) -> None:
    references: set[str] = set()
    for ref in result.source_refs:
        identifier = str(ref.id)
        if identifier in references:
            raise ValidationError("Monitoring assessment repeats an evidence reference")
        references.add(identifier)
        if isinstance(rule, EnvironmentalMonitoringRule):
            if ref.kind != "scientific_record":
                raise ValidationError(
                    "An environmental result needs scientific observation evidence"
                )
            row = sources[identifier]
            raw = row["payload_json"]
            record = ScientificRecordResponse.model_validate(
                {
                    **raw,
                    "id": identifier,
                    "project_id": row["project_id"],
                    "content_sha256": row["content_sha256"],
                }
            )
            if (
                content_hash(raw) != row["content_sha256"]
                or ref.sha256 != row["content_sha256"]
                or ref.observed_at != record.observed_at
                or ref.acquired_at != record.provenance.acquired_at
                or ref.source != record.provenance.source
                or ref.original_value != record.value
                or ref.original_unit != record.unit
                or ref.normalized_value != record.normalized_value
                or ref.normalized_unit != record.normalized_unit
                or ref.qc != record.qc
                or record.variable != rule.metric
                or record.source_kind != rule.parameters.source_kind
                or not result.window_start <= record.observed_at < result.window_end
                or (
                    rule.parameters.source is not None
                    and record.provenance.source != rule.parameters.source
                )
            ):
                raise ValidationError("The monitoring observation differs from its source snapshot")
        elif (
            ref.kind != "reviewed_event_summary"
            or ref.id not in rule.parameters.summary_ids
            or ref.sha256 != summaries[identifier]["result_json"]["content_sha256"]
        ):
            raise ValidationError("Biological assessment lost a reviewed summary and its hash")

    for excluded in result.exclusions:
        if excluded.source_id is None:
            if excluded.kind != "assessment":
                raise ValidationError("Monitoring exclusion is missing its source identity")
            continue
        identifier = str(excluded.source_id)
        if isinstance(rule, EnvironmentalMonitoringRule):
            if excluded.kind != "scientific_record" or identifier not in sources:
                raise ValidationError(
                    "Environmental exclusion refers to an unavailable observation"
                )
        elif (
            excluded.kind != "reviewed_event_summary"
            or excluded.source_id not in rule.parameters.summary_ids
        ):
            raise ValidationError("Biological exclusion refers to an unselected summary")
        elif excluded.session_id is not None:
            row = summaries[identifier]
            snapshot = _event_summary(row)
            mapping = row["result_json"].get("source_id_map", {})
            if not any(
                mapping.get(item.link_revision_id, item.link_revision_id) == excluded.session_id
                for item in snapshot.sessions
            ):
                raise ValidationError(
                    "An excluded biological session is outside its reviewed summary"
                )

    findings: set[str] = set()
    for finding in result.findings:
        if (
            finding.finding_key in findings
            or _finding_key(finding, biological=isinstance(rule, BiologicalMonitoringRule))
            != finding.finding_key
            or any(str(pointer) not in references for pointer in finding.source_ids)
        ):
            raise ValidationError("Monitoring finding has an invalid source binding")
        findings.add(finding.finding_key)


def _verify_effort(
    result: MonitoringAssessmentResult,
    sources: dict[str, dict[str, Any]],
    summaries: dict[str, dict[str, Any]],
    rule: MonitoringRuleCreate,
) -> None:
    if isinstance(rule, EnvironmentalMonitoringRule):
        if result.biological_sessions:
            raise ValidationError("Environmental coverage cannot contain biological session effort")
        cadence = rule.parameters.cadence_seconds
        expected = ceil((result.window_end - result.window_start).total_seconds() / cadence)
        slots: dict[int, list[MonitoringSourceReference]] = defaultdict(list)
        for ref in result.source_refs:
            raw = sources[str(ref.id)]["payload_json"]
            protocol = raw["provenance"]["source_metadata"].get("protocol")
            if (
                ref.observed_at is not None
                and ref.normalized_unit == rule.unit
                and protocol == rule.protocol
            ):
                elapsed = ref.observed_at - result.window_start
                slots[elapsed // timedelta(seconds=cadence)].append(ref)
        excluded = {row.source_id for row in result.exclusions}
        same_source = len({ref.source for members in slots.values() for ref in members}) <= 1
        eligible = [
            ref
            for members in slots.values()
            for ref in members
            if same_source
            and len(members) == 1
            and ref.qc == "accepted"
            and ref.observed_at is not None
            and ref.acquired_at is not None
            and ref.acquired_at >= ref.observed_at
        ]
        if {ref.id for ref in eligible} != {
            ref.id for ref in result.source_refs if ref.id not in excluded
        } or any(ref.normalized_value is None for ref in eligible):
            raise ValidationError("Monitoring assessment has inconsistent observation eligibility")
        values = [ref.normalized_value for ref in eligible if ref.normalized_value is not None]
        estimate = fsum(value / len(values) for value in values) if values else None
        effort = result.effort
        if (
            effort.expected_slots != expected
            or effort.observed_slots != len(slots)
            or effort.accepted_observations != len(values)
            or effort.coverage_fraction != len(slots) / expected
            or effort.accepted_fraction != len(values) / expected
            or result.estimate != estimate
        ):
            raise ValidationError("Monitoring estimate and coverage do not match their evidence")
        return

    references = {ref.id for ref in result.source_refs}
    sessions: set[tuple[UUID, str]] = set()
    for item in result.biological_sessions:
        key = (item.summary_id, item.link_revision_id)
        row = summaries[str(item.summary_id)]
        snapshot = _event_summary(row)
        mapping = row["result_json"].get("source_id_map", {})
        expected_session = next(
            (
                biological_session_evidence(item.summary_id, source, mapping)
                for source in snapshot.sessions
                if source.observed_at is not None
                and mapping.get(source.link_revision_id, source.link_revision_id)
                == item.link_revision_id
            ),
            None,
        )
        if (
            key in sessions
            or item.summary_id not in references
            or item != expected_session
            or item.valid_duration_s <= 0
            or not result.window_start <= item.observed_at < result.window_end
        ):
            raise ValidationError("Biological assessment differs from its reviewed session")
        sessions.add(key)

    latest_end_frame: dict[tuple[str, str], int] = {}
    for item in sorted(
        result.biological_sessions,
        key=lambda row: (row.video_sha256, row.organism_key, row.frame_start),
    ):
        group = (item.video_sha256, item.organism_key)
        if item.frame_start <= latest_end_frame.get(group, -1):
            raise ValidationError(
                "Overlapping reviewed sessions cannot add observation effort twice"
            )
        latest_end_frame[group] = item.frame_end

    count = sum(item.confirmed_event_count for item in result.biological_sessions)
    duration = fsum(item.valid_duration_s for item in result.biological_sessions)
    estimate = count / duration * 60 if duration >= rule.parameters.minimum_effort_seconds else None
    if (
        result.effort.accepted_sessions != len(sessions)
        or result.effort.confirmed_event_count != count
        or result.effort.valid_duration_s != duration
        or result.estimate != estimate
    ):
        raise ValidationError("Biological estimate does not match reviewed observation effort")


def validate_alert_records(project_id: str, rows: Rows) -> None:
    """Reject corrupt records, altered evidence, and foreign references before import."""
    if not any(rows.get(section) for section in SECTIONS):
        return
    try:
        rules = _owned_index(RULES, rows, project_id)
        assessments = _owned_index(ASSESSMENTS, rows, project_id)
        alerts = _owned_index(ALERTS, rows, project_id)
        reviews = _owned_index(REVIEWS, rows, project_id)
        scientific = _owned_index("scientific_records", rows, project_id)
        summaries = _owned_index(
            "jobs",
            {
                "jobs": [
                    row for row in rows.get("jobs", []) if row.get("job_type") == EVENT_SUMMARY_JOB
                ]
            },
            project_id,
        )
        definitions: dict[str, MonitoringRuleCreate] = {}
        for key, row in rules.items():
            body = _rule_body(row)
            rule = MONITORING_RULE.validate_python(body)
            if (
                canonical_json_sha256(body) != row["rule_sha256"]
                or canonical_json_sha256(rule.model_dump(mode="json")) != row["rule_sha256"]
            ):
                raise ValidationError("Monitoring rule has an invalid checksum")
            if isinstance(rule, BiologicalMonitoringRule) and any(
                _event_summary(summaries[str(identifier)]).protocol_sha256 != rule.protocol
                for identifier in rule.parameters.summary_ids
            ):
                raise ValidationError(
                    "A biological rule references an incompatible reviewed protocol"
                )
            definitions[key] = rule

        proposals: dict[tuple[str, str], MonitoringFinding] = {}
        for key, row in assessments.items():
            result = MonitoringAssessmentResult.model_validate(row["result_json"])
            rule = definitions[row["rule_id"]]
            if (
                str(result.project_id) != project_id
                or str(result.rule_id) != row["rule_id"]
                or result.rule_sha256 != rules[row["rule_id"]]["rule_sha256"]
                or (result.kind, result.protocol, result.metric, result.unit)
                != (rule.kind, rule.protocol, rule.metric, rule.unit)
                or result.window_start
                != monitoring_utc(datetime.fromisoformat(row["window_start"]))
                or result.window_end != monitoring_utc(datetime.fromisoformat(row["window_end"]))
                or result.evidence_sha256 != row["evidence_sha256"]
                or result.evidence_sha256 != _evidence_hash(result)
                or canonical_json_sha256(row["result_json"]) != row["result_sha256"]
            ):
                raise ValidationError(
                    "Monitoring assessment has inconsistent evidence or window pins"
                )
            _source_links(result, scientific, summaries, rule)
            _verify_effort(result, scientific, summaries, rule)
            proposals.update({(key, item.finding_key): item for item in result.findings})

        for row in alerts.values():
            finding = MonitoringFinding.model_validate(row["proposal_json"])
            finding_key = (row["assessment_id"], row["finding_key"])
            if (
                row["kind"] != finding.kind
                or finding != proposals.pop(finding_key)
                or canonical_json_sha256(row["proposal_json"]) != row["proposal_sha256"]
            ):
                raise ValidationError("Monitoring alert differs from its immutable assessment")
        if proposals:
            raise ValidationError("Monitoring archive is missing assessment alerts")

        history: dict[str, list[int]] = {}
        for row in reviews.values():
            alert_id = _uuid(row["alert_id"])
            if alert_id not in alerts:
                raise ValidationError("The monitored decision has no owned alert")
            stamp = monitoring_utc(datetime.fromisoformat(row["reviewed_at"]))
            review = MonitoringAlertReviewRead.model_validate({**row, "reviewed_at": stamp})
            if not review.reviewer.startswith("local-user:") or not 3 <= len(review.reason) <= 500:
                raise ValidationError("Monitoring review has invalid local attribution")
            history.setdefault(alert_id, []).append(review.revision)
        if any(
            sorted(revisions) != list(range(1, len(revisions) + 1))
            for revisions in history.values()
        ):
            raise ValidationError("Monitoring review history has missing or repeated revisions")
    except (KeyError, TypeError, ValueError, AttributeError, InvalidSchema) as exc:
        raise ValidationError(
            "Monitoring archive has an invalid or missing evidence reference"
        ) from exc


def _map_proposal(
    body: dict[str, Any], id_map: dict[str, str], *, biological: bool | None = None
) -> dict[str, Any]:
    original = MonitoringFinding.model_validate(body)
    if biological is None:
        biological = original.finding_key.endswith("/event_rate")
    identifiers = [UUID(id_map[str(old)]) for old in original.source_ids]
    if biological:
        identifiers.sort()
    bound = original.model_copy(update={"source_ids": identifiers})
    rebound = bound.model_copy(update={"finding_key": _finding_key(bound, biological=biological)})
    return rebound.model_dump(mode="json")


def restore_alert_row(
    name: str,
    original: dict[str, Any],
    values: dict[str, Any],
    id_map: dict[str, str],
    digests: dict[str, str],
) -> None:
    """Remap only scope, IDs and identity-bound hashes, retaining literal research evidence."""
    if name == RULES:
        body = deepcopy(_rule_body(original))
        if body["kind"] == "biological":
            body["parameters"]["summary_ids"] = sorted(
                id_map[identifier] for identifier in body["parameters"]["summary_ids"]
            )
        definition = MONITORING_RULE.validate_python(body).model_dump(mode="json")
        digest = canonical_json_sha256(definition)
        parameters = definition.pop("parameters")
        values.update(definition, parameters_json=parameters, rule_sha256=digest)
        digests[original["rule_sha256"]] = digest
    elif name == ASSESSMENTS:
        body = deepcopy(original["result_json"])
        for key in ("project_id", "rule_id"):
            body[key] = id_map[body[key]]
        body["rule_sha256"] = digests.get(body["rule_sha256"], body["rule_sha256"])
        for ref in body["source_refs"]:
            ref["id"] = id_map[ref["id"]]
            if ref["kind"] == "scientific_record":
                ref["sha256"] = digests.get(ref["sha256"], ref["sha256"])
        for excluded in body["exclusions"]:
            for key in ("source_id", "session_id"):
                if excluded[key] is not None:
                    excluded[key] = id_map[excluded[key]]
        for session in body.get("biological_sessions", []):
            for key in ("summary_id", "link_revision_id", "video_id"):
                session[key] = id_map[session[key]]
            session["event_ids"] = [id_map[event_id] for event_id in session["event_ids"]]
        body["findings"] = [
            _map_proposal(finding, id_map, biological=body["kind"] == "biological")
            for finding in body["findings"]
        ]
        result = MonitoringAssessmentResult.model_validate(body)
        sort_monitoring_evidence(result.source_refs, result.exclusions, result.biological_sessions)
        result.evidence_sha256 = _evidence_hash(result)
        result_json = result.model_dump(mode="json")
        digest = canonical_json_sha256(result_json)
        values.update(
            result_json=result_json, result_sha256=digest, evidence_sha256=result.evidence_sha256
        )
        digests[original["result_sha256"]] = digest
        digests[original["evidence_sha256"]] = result.evidence_sha256
    elif name == ALERTS:
        proposal = _map_proposal(original["proposal_json"], id_map)
        digest = canonical_json_sha256(proposal)
        values.update(
            kind=proposal["kind"],
            finding_key=proposal["finding_key"],
            proposal_json=proposal,
            proposal_sha256=digest,
        )
        digests[original["proposal_sha256"]] = digest
    elif name == REVIEWS:
        values.update(
            {key: original[key] for key in ("reviewer", "decision", "reason", "revision")}
        )
