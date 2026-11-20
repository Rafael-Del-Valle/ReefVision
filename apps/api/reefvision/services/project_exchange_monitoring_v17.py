"""Portable 1.7 acquisition/monitoring records and frozen cross-project history."""

from copy import deepcopy
from typing import Any

from pydantic import ValidationError as SchemaError
from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.db.models import AcquisitionSource, MonitoringProjectSummary, MonitoringRule
from reefvision.domain.errors import ValidationError
from reefvision.schemas.monitoring_summary import ComparisonSnapshot
from reefvision.services.project_exchange_alerts_v17 import validate_alert_records
from reefvision.services.project_exchange_device_v17 import validate_device_records
from reefvision.storage.datasets import canonical_json_sha256

FORMAT = "1.7.1"
SECTIONS = (
    "acquisition_sources",
    "acquisition_captures",
    "monitoring_rules",
    "monitoring_assessments",
    "monitoring_alerts",
    "monitoring_alert_reviews",
    "monitoring_project_summaries",
)
Rows = dict[str, list[dict[str, Any]]]


def has_monitoring_records(session: Session, project_id: str) -> bool:
    return any(
        session.scalar(select(model.id).where(model.project_id == project_id).limit(1)) is not None
        for model in (AcquisitionSource, MonitoringRule, MonitoringProjectSummary)
    )


def validate_monitoring_exchange(
    version: str, project_id: str, sections: Rows, origin: Any
) -> None:
    present = any(sections.get(name) for name in SECTIONS)
    if version != FORMAT:
        if present:
            raise ValidationError(
                "Local acquisition and monitoring history requires Project Exchange 1.7.1"
            )
        return
    if not present or not all(name in sections for name in SECTIONS):
        raise ValidationError("The acquisition and monitoring exchange inventory is incomplete")
    if any(row.get("project_id") != project_id for name in SECTIONS for row in sections[name]):
        raise ValidationError("An acquisition or monitoring record belongs to another project")
    origins = origin.get("id_map", {}) if isinstance(origin, dict) else {}
    if not isinstance(origins, dict):
        raise ValidationError("The monitoring archive has an invalid identity map")
    validate_alert_records(project_id, sections)
    validate_device_records(project_id, sections, origin_ids=origins)
    owned_assessments = {row["id"] for row in sections["monitoring_assessments"]}
    for row in sections["monitoring_project_summaries"]:
        try:
            snapshot = ComparisonSnapshot.model_validate(row["snapshot_json"])
        except (KeyError, SchemaError) as exc:
            raise ValidationError("The saved monitoring comparison is invalid") from exc
        reference = str(snapshot.reference_project_id)
        assessment = str(snapshot.rows[0].assessment_id)
        if (
            canonical_json_sha256(row["snapshot_json"]) != row.get("content_sha256")
            or snapshot.rows[0].project_id != snapshot.reference_project_id
            or len({r.project_id for r in snapshot.rows}) != len(snapshot.rows)
            or (reference != project_id and origins.get(reference) != project_id)
            or (
                assessment not in owned_assessments
                and origins.get(assessment) not in owned_assessments
            )
        ):
            raise ValidationError("The monitoring comparison lost its source, owner or checksum")
        for compared in snapshot.rows:
            review = compared.review
            counts = {
                state: sum(a.status == state for a in review.alerts)
                for state in ("confirmed", "dismissed", "proposed")
            }
            if (
                counts != review.model_dump(include=set(counts))
                or (
                    compared.status == "included"
                    and (review.proposed or compared.reasons or compared.values.estimate is None)
                )
                or (compared.status == "excluded" and not compared.reasons)
            ):
                raise ValidationError(
                    "The frozen monitoring comparison has inconsistent review or exclusion evidence"
                )
            for alert in review.alerts:
                decision = alert.latest_review
                if (
                    alert.status == "proposed"
                    and (alert.review_revision != 0 or decision is not None)
                ) or (
                    alert.status != "proposed"
                    and (
                        decision is None
                        or decision.decision != alert.status
                        or decision.project_id != compared.project_id
                        or decision.alert_id != alert.alert_id
                        or decision.revision != alert.review_revision
                    )
                ):
                    raise ValidationError(
                        "The frozen comparison lost its attributed alert decision"
                    )


def preserve_comparison_snapshot(
    name: str, original: dict[str, Any], values: dict[str, Any]
) -> None:
    if name == "monitoring_project_summaries":
        # Other projects do not travel with this project. All identifiers inside the saved
        # comparison belong to its source; the owning record receives a new local identity.
        values["snapshot_json"] = deepcopy(original["snapshot_json"])
        values["content_sha256"] = original["content_sha256"]
