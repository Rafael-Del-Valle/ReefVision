"""Archive integrity for figures derived from saved scientific results."""

from copy import deepcopy
from types import SimpleNamespace
from typing import Any

from reefvision.domain.errors import ValidationError
from reefvision.schemas.ecology_analysis import EcologyAnalysisSnapshot
from reefvision.schemas.ecology_event_summary import EventSummarySnapshot
from reefvision.schemas.research_reports import FigureSnapshot
from reefvision.schemas.scientific_comparison import ComparisonSnapshot
from reefvision.schemas.static_comparison import StaticSnapshot
from reefvision.services.ecology_event_summary import EVENT_SUMMARY_JOB
from reefvision.services.research_reports import REPORT_JOB, assemble_figure_snapshot
from reefvision.services.scientific_comparison import JOB_TYPE as COMPARISON_JOB
from reefvision.services.static_comparison import STATIC_COMPARISON_JOB
from reefvision.storage.datasets import canonical_json_sha256


def validate_report_exchange(sections: dict[str, list[dict[str, Any]]]) -> None:
    jobs = {record["id"]: record for record in sections.get("jobs", [])}
    ecological = {record["id"]: record for record in sections.get("ecology_analysis_records", [])}
    for row in jobs.values():
        if row["job_type"] != REPORT_JOB:
            continue
        stored = row["result_json"]
        parsed = FigureSnapshot.model_validate(stored["snapshot"])
        source_id = stored.get("local_source_id")
        kind = parsed.configuration.source_kind
        if kind == "ecology":
            resolved = ecological.get(source_id)
            checksum = resolved["content_sha256"] if resolved else None
        else:
            resolved = jobs.get(source_id)
            expected = {
                "event_summary": EVENT_SUMMARY_JOB,
                "comparison": COMPARISON_JOB,
                "static_comparison": STATIC_COMPARISON_JOB,
            }[kind]
            checksum = (
                (resolved["result_json"] or {}).get("content_sha256")
                if resolved and resolved["job_type"] == expected
                else None
            )
        request = row.get("request_json") or {}
        reviewed_configuration = parsed.configuration.model_dump(mode="json")
        reviewed_configuration["source_id"] = source_id
        if (
            row["status"] != "succeeded"
            or resolved is None
            or resolved["project_id"] != row["project_id"]
            or checksum != parsed.source_sha256
            or request != reviewed_configuration
            or canonical_json_sha256(stored["snapshot"]) != stored.get("content_sha256")
            or not any(series.points for series in parsed.series)
        ):
            raise ValidationError("Publication figure is inconsistent with its saved source")

        snapshot: (
            EcologyAnalysisSnapshot | EventSummarySnapshot | ComparisonSnapshot | StaticSnapshot
        )
        if kind == "ecology":
            snapshot = EcologyAnalysisSnapshot.model_validate(resolved["snapshot_json"])
        else:
            source_json = resolved["result_json"]["snapshot"]
            if kind == "event_summary":
                snapshot = EventSummarySnapshot.model_validate(source_json)
            elif kind == "static_comparison":
                snapshot = StaticSnapshot.model_validate(source_json)
            else:
                snapshot = ComparisonSnapshot.model_validate(source_json)
        source = SimpleNamespace(snapshot=snapshot, content_sha256=checksum)
        replayed = assemble_figure_snapshot(
            source, parsed.configuration, software_version=parsed.software_version
        )
        if replayed != parsed:
            raise ValidationError("Publication figure does not replay from its saved source")


def remap_report_archive_job(
    original: dict[str, Any], target: dict[str, Any], id_map: dict[str, str]
) -> None:
    if original["job_type"] != REPORT_JOB:
        return
    stored = deepcopy(original["result_json"])
    stored["local_source_id"] = id_map[stored["local_source_id"]]
    target["result_json"] = stored
