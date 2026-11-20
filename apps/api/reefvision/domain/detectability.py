"""Known-positive detection under an explicit repeated-visit sampling design."""

from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from math import log, sqrt
from statistics import fmean

from reefvision.schemas.taxonomy import (
    AssessmentVisit,
    DetectabilityGroup,
    DetectabilityRequest,
    DetectabilityResult,
    DetectabilityVisitSnapshot,
    DetectionInterval,
    ExcludedVisit,
    PresenceReviewRead,
    TaxonProposalRead,
)
from reefvision.storage.datasets import canonical_json_sha256

MINIMUM_GROUPS = 5
ASSUMPTIONS = [
    "Conditional on known presence from a separate source and local review for each visit.",
    "The protocol and minimum observed effort define comparable observation opportunities.",
    "Units are declared independent. Repeated visits within a unit need not be independent.",
    "Each retained unit has at least two nonoverlapping visits and receives equal weight.",
    "The interval applies to the mean expected detection across the represented units under "
    "their sampling conditions. It does not establish representativeness, occupancy, or survival.",
]


def survey_visit_exclusion(
    request: DetectabilityRequest,
    visit: DetectabilityVisitSnapshot,
    proposal: TaxonProposalRead,
    presence: PresenceReviewRead | None,
) -> str | None:
    """Check eligibility from the same frozen fields in live and portable results."""
    if visit.outcome in ("unobserved", "unknown"):
        return visit.outcome
    if visit.effort_seconds < request.minimum_effort_seconds:
        return "insufficient_observation_effort"
    if proposal.state != "confirmed":
        return "taxonomy_not_confirmed"
    unit_type = visit.identity.experimental_unit_type
    if visit.identity.experimental_unit_id is None or unit_type is None:
        return "independent_unit_not_declared"
    if unit_type.casefold() != request.unit_type.casefold():
        return "independent_unit_type_mismatch"
    if presence is None or presence.review.decision != "confirmed":
        return "independent_presence_not_confirmed"
    return None


def _digest_sources(record: AssessmentVisit) -> Iterable[str]:
    if record.visit.source:
        yield record.visit.source.sha256
    if record.presence_review and record.presence_review.review.source:
        yield record.presence_review.review.source.sha256


def _exclude(record: AssessmentVisit, reason: str) -> AssessmentVisit:
    return record.model_copy(update={"exclusion": reason})


def _overlapping(indices: list[int], records: list[AssessmentVisit]) -> set[int]:
    """Flag all visits sharing time in a unit instead of arbitrarily selecting one."""
    overlaps: set[int] = set()
    last_index: int | None = None
    latest_end = None
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    for index in indices:
        visit = records[index].visit
        start = visit.started_at - epoch
        end = start + timedelta(seconds=visit.effort_seconds)
        if latest_end is not None and last_index is not None and start < latest_end:
            overlaps.update((last_index, index))
        if latest_end is None or end > latest_end:
            latest_end = end
            last_index = index
    return overlaps


def calculate_detectability(
    request: DetectabilityRequest, visits: list[AssessmentVisit]
) -> DetectabilityResult:
    records = sorted(visits, key=lambda record: (record.visit.started_at, record.id))
    uses = Counter(
        sha for record in records if record.exclusion is None for sha in _digest_sources(record)
    )
    units: dict[str, list[int]] = defaultdict(list)
    for index, record in enumerate(records):
        if record.exclusion is not None:
            continue
        if any(uses[sha] > 1 for sha in _digest_sources(record)):
            records[index] = _exclude(record, "reused_source_bytes")
            continue
        unit_id = record.visit.identity.experimental_unit_id
        if unit_id is None:
            raise ValueError("Eligible visits must have an independent unit")
        units[unit_id].append(index)

    groups: list[DetectabilityGroup] = []
    for unit_id, indices in sorted(units.items()):
        overlaps = _overlapping(indices, records)
        for index in overlaps:
            records[index] = _exclude(records[index], "overlapping_visits_in_unit")
        independent_visits = [index for index in indices if index not in overlaps]
        if len(independent_visits) < 2:
            for index in independent_visits:
                records[index] = _exclude(records[index], "insufficient_repeated_visits_in_unit")
            continue
        selected = [records[index] for index in independent_visits]
        detected = sum(row.visit.outcome == "detected" for row in selected)
        groups.append(
            DetectabilityGroup(
                unit_id=unit_id,
                eligible_visits=len(selected),
                detections=detected,
                nondetections=len(selected) - detected,
                effort_seconds=sum(row.visit.effort_seconds for row in selected),
                detection_fraction=detected / len(selected),
                visit_ids=[row.id for row in selected],
            )
        )

    count = len(groups)
    estimate = None
    interval = None
    if count >= MINIMUM_GROUPS:
        estimate = fmean(group.detections / group.eligible_visits for group in groups)
        # Hoeffding's two-sided bound for independent [0, 1] unit-level fractions.
        radius = sqrt(log(2 / 0.05) / (2 * count))
        interval = DetectionInterval(
            lower=max(0.0, estimate - radius), upper=min(1.0, estimate + radius)
        )

    return DetectabilityResult(
        request=request,
        assumptions=ASSUMPTIONS,
        status="withheld" if estimate is None else "estimated",
        withhold_reason=(
            f"At least {MINIMUM_GROUPS} independent units are required, "
            "with two eligible visits in each unit."
            if estimate is None
            else None
        ),
        estimate=estimate,
        confidence_interval=interval,
        independent_groups=count,
        total_recorded_visits=len(records),
        eligible_visits=sum(group.eligible_visits for group in groups),
        observed_detections=sum(group.detections for group in groups),
        observed_nondetections=sum(group.nondetections for group in groups),
        included_effort_seconds=sum(group.effort_seconds for group in groups),
        groups=groups,
        exclusions=[
            ExcludedVisit(visit_id=record.id, reason=record.exclusion)
            for record in records
            if record.exclusion is not None
        ],
        evidence_sha256=canonical_json_sha256([r.model_dump(mode="json") for r in records]),
        visits=records,
    )
