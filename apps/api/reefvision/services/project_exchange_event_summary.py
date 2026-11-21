"""Validate archived event summaries and remap their live evidence references."""

from copy import deepcopy
from itertools import pairwise
from math import fsum
from typing import Any

from reefvision.db.models import PoseMeasurementSample
from reefvision.domain.errors import ValidationError
from reefvision.schemas.ecology_event_summary import EventSummarySnapshot
from reefvision.schemas.pose_biological_measurement import CycleDefinition
from reefvision.services.ecology_event_summary import (
    EVENT_SUMMARY_JOB,
    _valid_intervals,
    rates,
    summarize,
)
from reefvision.storage.datasets import canonical_json_sha256


def evidence_references(snapshot: EventSummarySnapshot) -> dict[str, set[str]]:
    return {
        "ecology_pose_link_revisions": {row.link_revision_id for row in snapshot.sessions},
        "ecology_identity_revisions": {row.identity_revision_id for row in snapshot.sessions},
        "videos": {row.video_id for row in snapshot.sessions},
        "pose_identity_association_runs": {row.identity_run_id for row in snapshot.sessions},
        "pose_animal_identities": {row.animal_identity_id for row in snapshot.sessions},
        "pose_measurement_runs": {row.measurement_run_id for row in snapshot.sessions},
        "pose_measurement_series": {row.measurement_series_id for row in snapshot.sessions},
        "pose_event_detection_runs": {row.event_run_id for row in snapshot.sessions},
        "pose_biological_event_revisions": {
            event.id for row in snapshot.sessions for event in row.events
        },
    }


def validate_event_summary_exchange(sections: dict[str, list[dict[str, Any]]]) -> None:
    samples: dict[str, list[dict[str, Any]]] = {}
    for item in sections.get("pose_measurement_samples", []):
        samples.setdefault(item["series_id"], []).append(item)
    detectors = {row["id"]: row for row in sections.get("pose_event_detection_runs", [])}
    for job in sections.get("jobs", []):
        if job["job_type"] != EVENT_SUMMARY_JOB:
            continue
        stored = job["result_json"]
        snapshot = EventSummarySnapshot.model_validate(stored["snapshot"])
        mapping = stored.get("source_id_map", {})
        refs = evidence_references(snapshot)
        if (
            job["status"] != "succeeded"
            or canonical_json_sha256(stored["snapshot"]) != stored["content_sha256"]
            or mapping.keys() - set().union(*refs.values())
        ):
            raise ValidationError("Event summary provenance checksum or mapping is invalid")
        for section, identifiers in refs.items():
            known = {item["id"] for item in sections.get(section, [])}
            if any(mapping.get(identifier, identifier) not in known for identifier in identifiers):
                raise ValidationError("Event summary source evidence is missing")
        chosen = {
            (str(row.link_revision_id), str(row.measurement_series_id), str(row.event_run_id))
            for row in snapshot.selection.sessions
        }
        sources = {
            (row.link_revision_id, row.measurement_series_id, row.event_run_id)
            for row in snapshot.sessions
        }
        if chosen != sources or len(snapshot.sessions) != len(sources):
            raise ValidationError("Event summary scopes disagree with the reviewed selection")
        events = {item["id"]: item for item in sections.get("pose_biological_event_revisions", [])}
        seen: set[str] = set()
        links = {row["id"]: row for row in sections.get("ecology_pose_link_revisions", [])}
        identities = {row["id"]: row for row in sections.get("ecology_identity_revisions", [])}
        series = {row["id"]: row for row in sections.get("pose_measurement_series", [])}
        recordings = {row["id"]: row for row in sections.get("videos", [])}
        for row in snapshot.sessions:
            link = links[mapping.get(row.link_revision_id, row.link_revision_id)]
            identity = identities[mapping.get(row.identity_revision_id, row.identity_revision_id)]
            series_id = mapping.get(row.measurement_series_id, row.measurement_series_id)
            measurement = series[series_id]
            video = recordings[mapping.get(row.video_id, row.video_id)]
            if (
                link["organism_revision_id"] != identity["id"]
                or row.organism_key != identity["organism_key"]
                or row.unit_type != identity["experimental_unit_type"]
                or row.unit_id != identity["experimental_unit_id"]
                or row.video_sha256 != video["sha256"]
                or (link["frame_start"], link["frame_end"]) != (row.frame_start, row.frame_end)
                or link["animal_identity_id"] != measurement["animal_identity_id"]
                or link["association_run_id"]
                != mapping.get(row.identity_run_id, row.identity_run_id)
                or measurement["measurement_run_id"]
                != mapping.get(row.measurement_run_id, row.measurement_run_id)
                or not any(item["id"] == series_id for item in link["source_json"]["measurements"])
            ):
                raise ValidationError("Event summary does not match its scoped reviewed link")
            pinned_events = {item["id"] for item in link["source_json"]["events"]}
            detector = detectors[mapping.get(row.event_run_id, row.event_run_id)]
            cycles = [
                CycleDefinition.model_validate(config)
                for config in detector["configuration_json"]["cycles"]
                if config["measurement_series_id"] == series_id
            ]
            if (
                len(cycles) != 1
                or detector["measurement_run_id"] != measurement["measurement_run_id"]
            ):
                raise ValidationError("Event summary detector does not match its reviewed evidence")
            cycle = cycles[0]
            intervals, valid_frames = _valid_intervals(
                [
                    PoseMeasurementSample(
                        **{
                            field: item[field]
                            for field in (
                                "frame_index",
                                "time_s",
                                "pixel_value",
                                "physical_value",
                                "confidence",
                                "valid",
                            )
                        }
                    )
                    for item in sorted(
                        samples.get(series_id, []), key=lambda item: item["frame_index"]
                    )
                    if row.frame_start <= item["frame_index"] <= row.frame_end
                ],
                {item["frame_index"] for item in link["source_json"]["observations"]},
                measurement["physical_unit"] is not None,
                cycle.maximum_gap_s,
                cycle.minimum_confidence,
            )
            if (
                intervals != row.valid_intervals
                or row.invalid_frame_count != row.frame_end - row.frame_start + 1 - valid_frames
                or any(
                    first.end_frame > second.start_frame for first, second in pairwise(row.events)
                )
            ):
                raise ValidationError(
                    "Event summary does not replay from reviewed measurement effort"
                )
            eligible = set()
            for identifier in pinned_events:
                event_row = events.get(identifier)
                if (
                    event_row
                    and event_row["event_detection_run_id"] == detector["id"]
                    and event_row["measurement_series_id"] == series_id
                    and event_row["review_state"] == "confirmed"
                    and event_row["cycle_state"] == "complete"
                    and event_row["end_frame"] is not None
                    and event_row["end_time_s"] is not None
                    and event_row["duration_s"] is not None
                    and any(
                        span.start_frame
                        <= event_row["start_frame"]
                        <= event_row["end_frame"]
                        <= span.end_frame
                        for span in intervals
                    )
                ):
                    eligible.add(identifier)
            if {mapping.get(item.id, item.id) for item in row.events} != eligible:
                raise ValidationError("Event summary does not replay its confirmed reviewed events")
            elapsed = fsum(item.end_time_s - item.start_time_s for item in intervals)
            expected = rates(len(row.events), elapsed)
            if any(
                abs(getattr(row, key) - number) > 1e-9
                if number is not None and getattr(row, key) is not None
                else getattr(row, key) != number
                for key, number in expected.model_dump().items()
            ):
                raise ValidationError("Event summary rates do not match valid effort")
            for event in row.events:
                source = events[mapping.get(event.id, event.id)]
                if (
                    source["event_series_id"] in seen
                    or source["review_state"] != "confirmed"
                    or source["cycle_state"] != "complete"
                    or source["amplitude"] != event.amplitude
                    or source["duration_s"] != event.duration_s
                    or source["start_frame"] != event.start_frame
                    or source["end_frame"] != event.end_frame
                    or source["start_time_s"] != event.start_time_s
                    or source["end_time_s"] != event.end_time_s
                    or source["event_detection_run_id"] != detector["id"]
                    or source["measurement_series_id"] != series_id
                    or not any(
                        span.start_frame <= event.start_frame <= event.end_frame <= span.end_frame
                        for span in intervals
                    )
                ):
                    raise ValidationError("Event summary disagrees with its confirmed source event")
                seen.add(source["event_series_id"])
        if (snapshot.organisms, snapshot.units) != summarize(snapshot.sessions):
            raise ValidationError("Event summary groups do not match the saved sessions")


def remap_event_summary_archive_job(
    original: dict[str, Any], target: dict[str, Any], id_map: dict[str, str]
) -> None:
    if original["job_type"] != EVENT_SUMMARY_JOB:
        return
    archive = deepcopy(original["result_json"])
    snapshot = EventSummarySnapshot.model_validate(archive["snapshot"])
    historical = archive.get("source_id_map", {})
    archive["source_id_map"] = {
        source: id_map[local]
        for identifiers in evidence_references(snapshot).values()
        for source in identifiers
        if (local := historical.get(source, source)) in id_map
    }
    target["result_json"] = archive
