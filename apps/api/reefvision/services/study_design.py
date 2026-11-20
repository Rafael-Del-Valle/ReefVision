"""Freeze, bind and replay a reviewed two-visit design."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from reefvision.db.models.project import Project, utc_now
from reefvision.db.models.study_design import StudyDesignRevision
from reefvision.domain.ecology_lineage_policy import classify_ecological_unit_level
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.schemas.ecology_analysis import GrowthResult, GrowthSelection
from reefvision.schemas.ecology_study_assignment import (
    EcologyStudyAssignmentRead,
    validate_study_assignments,
)
from reefvision.schemas.paired_growth_contrast import (
    PairedGrowthContrastRequest,
    PairedGrowthRosterIdentity,
)
from reefvision.schemas.study_design import (
    StudyDesignBind,
    StudyDesignBinding,
    StudyDesignCreate,
    StudyDesignDeclaration,
    StudyDesignPage,
    StudyDesignRead,
    StudyDesignReport,
    StudyDesignRosterMember,
    StudyDesignSnapshot,
    StudyDesignSource,
    validate_study_design_snapshot,
)
from reefvision.services.ecology_analysis import EcologyAnalysisService
from reefvision.services.ecology_identity import EcologyIdentityService
from reefvision.services.paired_growth_contrast import build_paired_growth_report
from reefvision.storage.datasets import canonical_json_sha256


class StudyDesignService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _require_project(self, project_id: str) -> None:
        if self.session.get(Project, project_id) is None:
            raise NotFoundError("Project not found")

    def _row(self, project_id: str, revision_id: str) -> StudyDesignRevision:
        row = self.session.get(StudyDesignRevision, revision_id)
        if row is None or row.project_id != project_id:
            raise NotFoundError("Study design revision not found in project")
        return row

    def _read(self, row: StudyDesignRevision) -> StudyDesignRead:
        snapshot = validate_study_design_snapshot(row.snapshot_json, row.content_sha256)
        bound = snapshot.binding

        def live(original: UUID | None) -> str | None:
            if original is None:
                return None
            return row.source_id_map_json.get(str(original), str(original))

        if (
            live(snapshot.project_id) != row.project_id
            or live(snapshot.revision_id) != row.id
            or live(snapshot.design_id) != row.design_id
            or live(snapshot.supersedes_revision_id) != row.supersedes_revision_id
            or snapshot.revision != row.revision
            or live(bound.analysis_id if bound else None) != row.growth_analysis_id
            or (bound.source_sha256 if bound else None) != row.growth_source_sha256
        ):
            raise ConflictError("Study design snapshot and live references do not match")
        return StudyDesignRead(
            id=UUID(row.id),
            project_id=UUID(row.project_id),
            design_id=UUID(row.design_id),
            revision=row.revision,
            supersedes_revision_id=UUID(row.supersedes_revision_id)
            if row.supersedes_revision_id
            else None,
            created_at=snapshot.created_at,
            growth_analysis_id=UUID(row.growth_analysis_id) if row.growth_analysis_id else None,
            growth_source_sha256=row.growth_source_sha256,
            content_sha256=row.content_sha256,
            source_id_map=row.source_id_map_json,
            snapshot=snapshot,
        )

    def _require_tip(self, row: StudyDesignRevision, digest: str) -> None:
        if row.content_sha256 != digest:
            raise ConflictError("Study design digest differs from the selected digest")
        child = self.session.scalar(
            select(StudyDesignRevision.id).where(
                StudyDesignRevision.supersedes_revision_id == row.id
            )
        )
        if child is not None:
            raise ConflictError("A newer study design revision already supersedes this revision")

    def _roster(
        self, project_id: str, declaration: StudyDesignDeclaration
    ) -> list[StudyDesignRosterMember]:
        current = EcologyIdentityService(self.session)._latest(project_id)
        roster = []
        lineages: dict[str, str] = {}
        for key in sorted(declaration.organism_keys):
            identity = current.get(key)
            if identity is None or identity.study_assignment is None:
                raise ValidationError(f"{key} requires a reviewed study assignment in this project")
            unit_id = identity.experimental_unit_id
            unit_type = identity.experimental_unit_type
            if (
                not unit_id
                or not unit_type
                or unit_type.casefold() != declaration.contrast.experimental_unit_type.casefold()
            ):
                raise ValidationError(
                    "The enrolled organisms must use the declared independent unit type"
                )
            lineage = identity.parent_colony_key or key
            if lineages.setdefault(lineage, unit_id) != unit_id:
                raise ValidationError("A colony lineage spans multiple declared independent units")
            roster.append(
                StudyDesignRosterMember(
                    identity_id=UUID(identity.id),
                    organism_key=key,
                    identity_revision=identity.revision,
                    kind=identity.kind,
                    parent_colony_key=identity.parent_colony_key,
                    experimental_unit_type=unit_type,
                    experimental_unit_id=unit_id,
                    assignment=EcologyStudyAssignmentRead.model_validate(identity.study_assignment),
                )
            )
        if (
            classify_ecological_unit_level(declaration.contrast.experimental_unit_type)
            == "organism"
        ):
            counts = Counter(member.experimental_unit_id for member in roster)
            if any(count > 1 for count in counts.values()):
                raise ValidationError("An organism-level unit cannot contain multiple organisms")
        treatments = {row.assignment.treatment_code for row in roster}
        if treatments - {None} != {item.code for item in declaration.treatments} or (
            None in treatments and len(treatments) > 1
        ):
            raise ValidationError(
                "Declared treatments must match each enrolled reviewed assignment"
            )
        try:
            validate_study_assignments((row, row.assignment) for row in roster)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        return roster

    def _require_current_roster(self, saved: StudyDesignRead) -> list[StudyDesignRosterMember]:
        try:
            current = self._roster(str(saved.project_id), saved.snapshot.declaration)
        except ValidationError as exc:
            raise ConflictError(
                "Study design roster identity revision changed; review a new design"
            ) from exc
        for original, live in zip(saved.snapshot.roster, current, strict=False):
            live_id = saved.source_id_map.get(str(original.identity_id), str(original.identity_id))
            if (
                str(live.identity_id) != live_id
                or live.model_copy(update={"identity_id": original.identity_id}) != original
            ):
                break
        else:
            if len(saved.snapshot.roster) == len(current):
                return current
        raise ConflictError("Study design roster identity revision changed; review a new design")

    def _binding(
        self,
        project_id: str,
        source: StudyDesignSource,
        declaration: StudyDesignDeclaration,
        roster: list[StudyDesignRosterMember],
        declared_at: datetime,
        *,
        original: StudyDesignSnapshot | None = None,
    ) -> StudyDesignBinding:
        analysis = EcologyAnalysisService(self.session).get(
            project_id, str(source.growth_analysis_id)
        )
        if analysis.content_sha256 != source.growth_source_sha256:
            raise ConflictError("Reviewed growth source digest differs from the selected digest")
        if analysis.stale:
            raise ConflictError(
                "Selected growth evidence has changed; save a freshly reviewed analysis"
            )
        selection, result = analysis.snapshot.selection, analysis.snapshot.result
        if (
            not isinstance(selection, GrowthSelection)
            or not selection.sampling_plan
            or not isinstance(result, GrowthResult)
        ):
            raise ValidationError("Select reviewed calibrated growth evidence with a sampling plan")
        if selection.metric != declaration.metric:
            raise ValidationError("The measurement metric must match the reviewed growth analysis")
        enrolled = {(member.experimental_unit_id, member.organism_key) for member in roster}
        sampled = {
            (unit.experimental_unit_id, organism)
            for unit in selection.sampling_plan
            for organism in unit.organism_keys
        }
        if sampled != enrolled:
            raise ValidationError(
                "The growth plan must contain the same enrolled organisms and independent units"
            )
        if declaration.exclusion_policy == "no_source_exclusions" and any(
            exclusion.source_kind == "calibration" for exclusion in result.exclusions
        ):
            raise ValidationError("The reviewed growth analysis contains excluded sources")
        if declaration.timing == "prospective" and (
            analysis.created_at < declared_at
            or any(item.observed_at < declared_at for item in result.observations)
        ):
            raise ValidationError("Prospective evidence must follow the original plan freeze")

        request = PairedGrowthContrastRequest.model_validate(
            {
                **declaration.contrast.model_dump(mode="json"),
                "source_sha256": source.growth_source_sha256,
            }
        )
        identities = {
            item.organism_key: PairedGrowthRosterIdentity(
                organism_key=item.organism_key,
                revision=item.identity_revision,
                parent_colony_key=item.parent_colony_key,
                experimental_unit_type=item.experimental_unit_type,
                experimental_unit_id=item.experimental_unit_id,
            )
            for item in roster
        }
        prior = original.binding if original else None
        report = build_paired_growth_report(
            original.project_id if original else analysis.project_id,
            prior.analysis_id if prior else analysis.id,
            analysis.snapshot,
            request,
            identities,
            calculate_t_interval=prior is None
            or prior.paired_report.interval_status != "statistics_runtime_unavailable",
        )
        return StudyDesignBinding(
            analysis_id=report.analysis_id, source_sha256=report.source_sha256, paired_report=report
        )

    def _append(
        self,
        project_id: str,
        declaration: StudyDesignDeclaration,
        roster: list[StudyDesignRosterMember],
        created_at: datetime,
        *,
        declared_at: datetime,
        binding: StudyDesignBinding | None,
        parent: StudyDesignRevision | None,
    ) -> StudyDesignRead:
        snapshot = StudyDesignSnapshot(
            project_id=UUID(project_id),
            design_id=UUID(parent.design_id) if parent else uuid4(),
            revision_id=uuid4(),
            supersedes_revision_id=UUID(parent.id) if parent else None,
            revision=parent.revision + 1 if parent else 1,
            declaration=declaration,
            roster=roster,
            declared_at=declared_at,
            created_at=created_at,
            binding=binding,
        )
        payload = snapshot.model_dump(mode="json")
        row = StudyDesignRevision(
            id=str(snapshot.revision_id),
            project_id=project_id,
            design_id=str(snapshot.design_id),
            revision=snapshot.revision,
            supersedes_revision_id=parent.id if parent else None,
            growth_analysis_id=str(binding.analysis_id) if binding else None,
            growth_source_sha256=binding.source_sha256 if binding else None,
            snapshot_json=payload,
            source_id_map_json={},
            content_sha256=canonical_json_sha256(payload),
            created_at=created_at,
        )
        self.session.add(row)
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise ConflictError(
                "Study design revision changed; reopen the selected revision"
            ) from exc
        return self._read(row)

    def save(self, project_id: str, request: StudyDesignCreate) -> StudyDesignRead:
        self._require_project(project_id)
        declared_at = utc_now()
        declaration = request.declaration
        if (
            declaration.timing == "prospective"
            and declaration.contrast.baseline_date <= declared_at.astimezone(UTC).date()
        ):
            raise ValidationError("A prospective baseline UTC date must be after the freeze date")
        parent = None
        if request.supersedes_revision_id and request.supersedes_sha256:
            parent = self._row(project_id, str(request.supersedes_revision_id))
            self._require_tip(parent, request.supersedes_sha256)
            self._read(parent)
        roster = self._roster(project_id, declaration)
        binding = None
        if request.growth_analysis_id and request.growth_source_sha256:
            binding = self._binding(
                project_id,
                StudyDesignSource(
                    growth_analysis_id=request.growth_analysis_id,
                    growth_source_sha256=request.growth_source_sha256,
                ),
                declaration,
                roster,
                declared_at,
            )
        return self._append(
            project_id,
            declaration,
            roster,
            declared_at,
            declared_at=declared_at,
            binding=binding,
            parent=parent,
        )

    def bind(self, project_id: str, revision_id: str, request: StudyDesignBind) -> StudyDesignRead:
        parent = self._row(project_id, revision_id)
        self._require_tip(parent, request.design_sha256)
        selected = self._read(parent)
        snapshot = selected.snapshot
        if snapshot.declaration.timing != "prospective" or snapshot.binding is not None:
            raise ConflictError(
                "Bind evidence to a frozen prospective design without an existing binding"
            )
        roster = self._require_current_roster(selected)
        binding = self._binding(
            project_id, request, snapshot.declaration, roster, snapshot.declared_at
        )
        return self._append(
            project_id,
            snapshot.declaration,
            roster,
            utc_now(),
            declared_at=snapshot.declared_at,
            binding=binding,
            parent=parent,
        )

    def list(self, project_id: str, page: int, page_size: int) -> StudyDesignPage:
        self._require_project(project_id)
        query = select(StudyDesignRevision).where(StudyDesignRevision.project_id == project_id)
        total = self.session.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = self.session.scalars(
            query.order_by(StudyDesignRevision.created_at.desc(), StudyDesignRevision.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return StudyDesignPage(
            items=[self._read(row) for row in rows], page=page, page_size=page_size, total=total
        )

    def get(self, project_id: str, revision_id: str) -> StudyDesignRead:
        return self._read(self._row(project_id, revision_id))

    def replay(self, project_id: str, revision_id: str, digest: str) -> StudyDesignReport:
        saved = self.get(project_id, revision_id)
        if saved.content_sha256 != digest:
            raise ConflictError("Study design digest differs from the selected digest")
        roster = self._require_current_roster(saved)
        snapshot = saved.snapshot
        if snapshot.binding and saved.growth_analysis_id and saved.growth_source_sha256:
            verified = self._binding(
                project_id,
                StudyDesignSource(
                    growth_analysis_id=saved.growth_analysis_id,
                    growth_source_sha256=saved.growth_source_sha256,
                ),
                snapshot.declaration,
                roster,
                snapshot.declared_at,
                original=snapshot,
            )
            if verified != snapshot.binding:
                raise ConflictError("Replayed growth evidence differs from the frozen study design")
        return StudyDesignReport(content_sha256=saved.content_sha256, snapshot=snapshot)
