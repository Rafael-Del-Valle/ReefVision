"""Check and restore portable taxonomy and detectability receipts."""

from collections.abc import Mapping
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any, TypeVar
from uuid import UUID

from pydantic import ValidationError as SchemaError

from reefvision.domain.detectability import calculate_detectability, survey_visit_exclusion
from reefvision.domain.errors import ValidationError
from reefvision.schemas.ecology_identity import EcologyIdentityRow
from reefvision.schemas.taxonomy import (
    AssessmentVisit,
    DetectabilityResult,
    DetectabilityVisitSnapshot,
    LocalAttribution,
    PresenceReviewSnapshot,
    TaxonomyModel,
    TaxonomySource,
    TaxonProposalSnapshot,
    TaxonReviewSnapshot,
)
from reefvision.services.taxonomy import taxonomy_identity_matches
from reefvision.storage.datasets import canonical_json_sha256

TAXONOMY_SECTIONS = (
    "taxonomy_proposals",
    "taxonomy_reviews",
    "detectability_visits",
    "detectability_presence_reviews",
    "detectability_assessments",
)
PROPOSALS, REVIEWS, VISITS, PRESENCE, ASSESSMENTS = TAXONOMY_SECTIONS
_LOCAL_FIELDS = {
    PROPOSALS: {"identity_revision_id", "author_role_revision_id"},
    REVIEWS: {"proposal_id", "reviewer_role_revision_id", "revision"},
    VISITS: {"proposal_id", "observer_role_revision_id", "organism_key", "protocol", "started_at"},
    PRESENCE: {"visit_id", "reviewer_role_revision_id", "revision"},
    ASSESSMENTS: set(),
}
_COMMON_FIELDS = {"id", "project_id", "snapshot_json", "content_sha256", "created_at"}
_AGGREGATE_EXCLUSIONS = {
    "reused_source_bytes",
    "overlapping_visits_in_unit",
    "insufficient_repeated_visits_in_unit",
}
_HISTORICAL_EXCLUSIONS = {
    "organism_revision_changed",
    "shared_parent_across_units",
    "source_unavailable",
}
_Snapshot = TypeVar("_Snapshot", bound=TaxonomyModel)
_Row = dict[str, Any]
_Rows = Mapping[str, list[_Row]]


def _instant(serialized: str) -> datetime:
    value = datetime.fromisoformat(serialized)
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _snapshot(row: _Row, schema: type[_Snapshot]) -> _Snapshot:
    result = schema.model_validate(row["snapshot_json"])
    if (
        canonical_json_sha256(row["snapshot_json"]) != row["content_sha256"]
        or canonical_json_sha256(result.model_dump(mode="json")) != row["content_sha256"]
    ):
        raise ValueError("receipt checksum")
    return result


class _ArchiveTaxonomy:
    def __init__(self, project_id: str, sections: _Rows, origin: Any) -> None:
        self.project_id = project_id
        self.origins = origin.get("id_map", {}) if isinstance(origin, dict) else {}
        if not isinstance(self.origins, dict):
            raise ValueError("origin map")
        self.sections = sections
        self.records = {name: self._index(name) for name in TAXONOMY_SECTIONS}
        for name, rows in self.records.items():
            for identifier, row in rows.items():
                UUID(identifier)
                if (
                    row["project_id"] != project_id
                    or set(row) != _COMMON_FIELDS | _LOCAL_FIELDS[name]
                ):
                    raise ValueError("record scope or fields")
        self.roles = self._index("reviewer_lab_role_revisions")
        self.members = self._index("reviewer_lab_members")
        self.identities = self._index("ecology_identity_revisions")
        self.media = {
            kind: self._index(section)
            for kind, section in (("image", "images"), ("video", "videos"))
        }
        self.proposals: dict[str, TaxonProposalSnapshot] = {}
        self.reviews: dict[str, TaxonReviewSnapshot] = {}
        self.visits: dict[str, DetectabilityVisitSnapshot] = {}
        self.presence: dict[str, PresenceReviewSnapshot] = {}

    def _index(self, section: str) -> dict[str, _Row]:
        rows = self.sections.get(section, [])
        by_id = {row["id"]: row for row in rows}
        if len(rows) != len(by_id):
            raise ValueError("duplicate identifier")
        return by_id

    def live(self, identifier: UUID | str) -> str:
        source = str(identifier)
        value = self.origins.get(source, source)
        if not isinstance(value, str):
            raise ValueError("invalid source identifier binding")
        return value

    def source(self, source: TaxonomySource | None) -> None:
        if source is None:
            return
        actual = self.media[source.kind][self.live(source.id)]
        if actual["project_id"] != self.project_id or actual["sha256"] != source.sha256:
            raise ValueError("foreign or changed source")

    def actor(self, stamp: LocalAttribution, role_id: str, at: datetime) -> None:
        role = self.roles[role_id]
        actual = self.members[self.live(stamp.member_id)]
        if (
            role_id != self.live(stamp.role_revision_id)
            or actual["id"] != role["member_id"]
            or actual["project_id"] != self.project_id
            or actual["role"] != stamp.role
            or actual["name"] != stamp.name
            or role["active"] is not True
            or _instant(role["created_at"]) > at
        ):
            raise ValueError("unsupported local authority")

    def verify_rows(self) -> None:
        for row_id, row in self.records[PROPOSALS].items():
            proposal = _snapshot(row, TaxonProposalSnapshot)
            identity = EcologyIdentityRow.model_validate(
                self.identities[row["identity_revision_id"]]
            )
            if (
                proposal.identity_revision_id != proposal.identity.id
                or identity.project_id != self.project_id
                or not taxonomy_identity_matches(identity, proposal.identity, self.origins)
                or proposal.proposed_at < _instant(identity.created_at.isoformat())
                or proposal.proposed_at > _instant(row["created_at"])
            ):
                raise ValueError("invalid registered-organism evidence")
            self.source(proposal.source)
            self.actor(proposal.author, row["author_role_revision_id"], proposal.proposed_at)
            self.proposals[row_id] = proposal

        for row_id, row in self.records[VISITS].items():
            visit = _snapshot(row, DetectabilityVisitSnapshot)
            proposal = self.proposals[row["proposal_id"]]
            if (
                self.live(visit.proposal_id) != row["proposal_id"]
                or visit.proposal_sha256
                != self.records[PROPOSALS][row["proposal_id"]]["content_sha256"]
                or visit.identity != proposal.identity
                or visit.identity.organism_key != row["organism_key"]
                or visit.protocol != row["protocol"]
                or visit.started_at != _instant(row["started_at"])
                or not proposal.proposed_at <= visit.recorded_at <= _instant(row["created_at"])
            ):
                raise ValueError("visit lost its proposal, unit, or start time")
            self.source(visit.source)
            self.actor(visit.observer, row["observer_role_revision_id"], visit.recorded_at)
            self.visits[row_id] = visit

        self._verify_review_chain(REVIEWS)
        self._verify_review_chain(PRESENCE)
        accepted: set[tuple[str, str]] = set()
        for parent, latest in self._latest_reviews().items():
            if latest.decision != "confirmed":
                continue
            proposal = self.proposals[parent]
            key = (self.live(proposal.identity.id), proposal.rank)
            if key in accepted:
                raise ValueError("multiple confirmed taxa at the same rank")
            accepted.add(key)

    def _latest_reviews(self) -> dict[str, TaxonReviewSnapshot]:
        return {
            row["proposal_id"]: self.reviews[row["id"]]
            for row in sorted(self.records[REVIEWS].values(), key=lambda row: row["revision"])
        }

    def _verify_review_chain(self, section: str) -> None:
        for_presence = section == PRESENCE
        parent_type, column = (VISITS, "visit_id") if for_presence else (PROPOSALS, "proposal_id")
        seen: dict[str, tuple[int, datetime]] = {}
        for row_id, row in sorted(
            self.records[section].items(), key=lambda pair: pair[1]["revision"]
        ):
            parent_id = row[column]
            target = self.records[parent_type][parent_id]
            body: TaxonReviewSnapshot
            if for_presence:
                visit = self.visits[parent_id]
                author, since = visit.observer, visit.recorded_at
                presence = _snapshot(row, PresenceReviewSnapshot)
                if presence.decision == "confirmed" and presence.source is None:
                    raise ValueError("no independent known-presence reference")
                if (
                    presence.source
                    and visit.source
                    and presence.source.sha256 == visit.source.sha256
                ):
                    raise ValueError("known-presence reference shares observation bytes")
                self.source(presence.source)
                self.presence[row_id] = presence
                body = presence
            else:
                proposal = self.proposals[parent_id]
                author, since = proposal.author, proposal.proposed_at
                body = _snapshot(row, TaxonReviewSnapshot)
                self.reviews[row_id] = body
            previous_revision, previous_time = seen.get(parent_id, (0, since))
            if (
                body.target_sha256 != target["content_sha256"]
                or type(row["revision"]) is not int
                or row["revision"] != previous_revision + 1
                or body.expected_revision != previous_revision
                or self.live(body.reviewer.member_id) == self.live(author.member_id)
                or body.reviewer.role not in ("reviewer", "adjudicator")
                or not previous_time <= body.reviewed_at <= _instant(row["created_at"])
            ):
                raise ValueError("non-independent, stale, or discontinuous decision")
            self.actor(body.reviewer, row["reviewer_role_revision_id"], body.reviewed_at)
            seen[parent_id] = (row["revision"], body.reviewed_at)

    def history(self, result: DetectabilityResult, visit: AssessmentVisit) -> None:
        visit_id = self.live(visit.id)
        parent = self.records[VISITS][visit_id]
        proposal_id = parent["proposal_id"]
        original = visit.proposal
        if (
            visit.visit != self.visits[visit_id]
            or visit.visit_sha256 != parent["content_sha256"]
            or self.live(original.id) != proposal_id
            or self.live(original.project_id) != self.project_id
            or original.proposal != self.proposals[proposal_id]
            or original.proposal_sha256 != self.records[PROPOSALS][proposal_id]["content_sha256"]
            or visit.visit.protocol != result.request.protocol
            or not result.request.window_start <= visit.visit.started_at < result.request.window_end
            or original.proposal.scientific_name.casefold()
            != result.request.scientific_name.casefold()
            or original.proposal.rank != result.request.rank
        ):
            raise ValueError("assessment visit is not its referenced frozen evidence")
        if visit.taxonomy_review is None:
            if original.state != "proposed" or original.review_revision != 0:
                raise ValueError("unsupported taxon state")
        else:
            taxon = visit.taxonomy_review
            review_id = self.live(taxon.id)
            row = self.records[REVIEWS][review_id]
            if (
                row["proposal_id"] != proposal_id
                or row["revision"] != taxon.revision
                or row["content_sha256"] != taxon.review_sha256
                or self.reviews[review_id] != taxon.review
                or original.state != taxon.review.decision
                or original.review_revision != taxon.revision
            ):
                raise ValueError("assessment taxon review is not the attributed original")
        if visit.presence_review is not None:
            decision = visit.presence_review
            review_id = self.live(decision.id)
            row = self.records[PRESENCE][review_id]
            if (
                row["visit_id"] != visit_id
                or row["revision"] != decision.revision
                or row["content_sha256"] != decision.review_sha256
                or self.presence[review_id] != decision.review
            ):
                raise ValueError("assessment presence decision is not the attributed original")

    def check_assessments(self) -> None:
        for row in self.records[ASSESSMENTS].values():
            result = _snapshot(row, DetectabilityResult)
            if len({self.live(record.id) for record in result.visits}) != len(result.visits):
                raise ValueError("duplicate assessment visit")
            prepared = []
            for record in result.visits:
                self.history(result, record)
                exclusion = survey_visit_exclusion(
                    result.request, record.visit, record.proposal, record.presence_review
                )
                if exclusion is None and record.exclusion in _HISTORICAL_EXCLUSIONS:
                    # These decisions reflect availability or design at the recorded time.
                    # They may conservatively narrow support, but cannot create positive evidence.
                    exclusion = record.exclusion
                if record.exclusion in _AGGREGATE_EXCLUSIONS or record.exclusion == exclusion:
                    prepared.append(record.model_copy(update={"exclusion": exclusion}))
                else:
                    raise ValueError("assessment retained an ineligible visit or unknown exclusion")
            if calculate_detectability(result.request, prepared) != result:
                raise ValueError(
                    "estimate, denominators, interval or visit digest differs from evidence"
                )


def validate_taxonomy_exchange(project_id: str, sections: _Rows, origin: Any) -> None:
    if not any(sections.get(section) for section in TAXONOMY_SECTIONS):
        return
    if not all(section in sections for section in TAXONOMY_SECTIONS):
        raise ValidationError("Taxonomy archive is missing part of its visit and review inventory")
    try:
        archive = _ArchiveTaxonomy(project_id, sections, origin)
        archive.verify_rows()
        archive.check_assessments()
    except (KeyError, TypeError, SchemaError, ValueError) as exc:
        raise ValidationError(
            "Taxonomy archive has invalid evidence, attribution or grouped results"
        ) from exc


def restore_taxonomy_row(name: str, row: _Row, values: _Row, id_map: dict[str, str]) -> None:
    if name not in TAXONOMY_SECTIONS:
        return
    values["snapshot_json"] = deepcopy(row["snapshot_json"])
    values["content_sha256"] = row["content_sha256"]
    for field in _LOCAL_FIELDS[name]:
        value = row[field]
        if field.endswith("_id"):
            if value not in id_map:
                raise ValidationError("Taxonomy archive lost a local identity or role binding")
            values[field] = id_map[value]
        elif field in {"protocol", "organism_key"}:
            values[field] = value
