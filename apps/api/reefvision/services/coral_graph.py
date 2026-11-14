"""Project-owned coral evidence, audit history, and paired 2D growth."""

from datetime import UTC, datetime
from math import isfinite
from typing import Any, TypeVar
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models.coral_graph import (
    CoralBranchCorrespondenceRevision,
    CoralGraphRevision,
    CoralGrowthRecord,
)
from reefvision.db.models.ecology_identity_revision import EcologyIdentityRevision
from reefvision.db.models.image import ImageAsset
from reefvision.db.models.mask_annotation import MaskAnnotation
from reefvision.db.models.project import Project
from reefvision.db.models.skeleton_analysis import SkeletonAnalysisRevision
from reefvision.domain.ecology_physical_units import is_ecological_physical_length_unit
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.schemas.connected_branch_editing import (
    ConnectedBranchEdgeResponse,
    ConnectedBranchNodeResponse,
)
from reefvision.schemas.coral_graph import (
    BranchSupersession,
    CorrespondenceRecord,
    CorrespondenceReview,
    CorrespondenceSnapshot,
    GraphRecord,
    GraphReview,
    GraphSnapshot,
    GrowthBranch,
    GrowthChange,
    GrowthRecord,
    GrowthSnapshot,
)
from reefvision.schemas.skeletonization import SkeletonPixelEdit
from reefvision.services.connected_branch_editing import BranchEditError, validate_branch_graph
from reefvision.services.connected_branch_preview import source_skeleton_graph
from reefvision.services.coral_graph_geometry import (
    apply_graph_edit,
    assign_ids,
    match_unchanged_geometry,
    pixel,
    restore_graph,
)
from reefvision.services.skeletonization import (
    SkeletonizationService,
    skeleton_calibration_payload,
    skeleton_calibration_sha256,
    skeleton_edge_physical_lengths,
)
from reefvision.storage.datasets import canonical_json_sha256

Row = TypeVar(
    "Row",
    CoralGraphRevision,
    CoralBranchCorrespondenceRevision,
    CoralGrowthRecord,
    EcologyIdentityRevision,
)


def utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def checked_snapshot(
    row: CoralGraphRevision | CoralBranchCorrespondenceRevision | CoralGrowthRecord,
) -> dict[str, Any]:
    if canonical_json_sha256(row.payload_json) != row.content_sha256:
        raise ValidationError("Stored coral evidence checksum does not match")
    return row.payload_json


class CoralGraphService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def owned(self, model: type[Row], project_id: str, identifier: str) -> Row:
        row = self.session.get(model, identifier)
        if row is None or row.project_id != project_id:
            raise NotFoundError("Coral evidence record was not found in this project")
        return row

    def _project(self, project_id: str) -> None:
        if self.session.get(Project, project_id) is None:
            raise NotFoundError("Project not found")

    def _start_write(self) -> None:
        # Serialize validation and append on the local SQLite authority.
        if self.session.get_bind().dialect.name != "sqlite":
            return
        try:
            self.session.execute(text("BEGIN IMMEDIATE"))
        except OperationalError as exc:
            self.session.rollback()
            raise ConflictError("The database is busy. Reload and retry the review.") from exc

    def _commit(self) -> None:
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise ConflictError("Review changed concurrently. Reload and retry.") from exc

    def _latest_identity(self, identity: EcologyIdentityRevision) -> str | None:
        return self.session.scalar(
            select(EcologyIdentityRevision.id)
            .where(
                EcologyIdentityRevision.project_id == identity.project_id,
                EcologyIdentityRevision.organism_key == identity.organism_key,
            )
            .order_by(EcologyIdentityRevision.revision.desc())
            .limit(1)
        )

    def _active_graph(self, graph_id: str) -> CoralGraphRevision | None:
        return self.session.scalar(
            select(CoralGraphRevision)
            .where(
                CoralGraphRevision.graph_id == graph_id, CoralGraphRevision.decision == "accepted"
            )
            .order_by(CoralGraphRevision.revision.desc())
            .limit(1)
        )

    def graph_record(self, row: CoralGraphRevision) -> GraphRecord:
        snapshot = GraphSnapshot.model_validate(checked_snapshot(row))
        identity = self.owned(EcologyIdentityRevision, row.project_id, row.identity_revision_id)
        image = self.session.get(
            ImageAsset, row.source_id_map_json.get(snapshot.image_id, snapshot.image_id)
        )
        mask = self.session.get(
            MaskAnnotation,
            row.source_id_map_json.get(snapshot.mask_annotation_id, snapshot.mask_annotation_id),
        )
        active = self._active_graph(row.graph_id)
        stale = []
        analysis = self.session.get(SkeletonAnalysisRevision, row.analysis_id)
        if analysis is None:
            stale.append("source_analysis_missing")
        else:
            latest = self.session.scalar(
                select(SkeletonAnalysisRevision.id)
                .where(SkeletonAnalysisRevision.analysis_series_id == analysis.analysis_series_id)
                .order_by(SkeletonAnalysisRevision.analysis_revision.desc())
                .limit(1)
            )
            if latest != row.analysis_id or (analysis.result_sha256 != snapshot.analysis_sha256):
                stale.append("source_analysis_changed")
        if row.decision == "accepted" and active is not None and active.id != row.id:
            stale.append("superseded_graph")
        if self._latest_identity(identity) != identity.id:
            stale.append("colony_registration_changed")
        if (
            image is None
            or image.project_id != row.project_id
            or image.sha256 != snapshot.image_sha256
        ):
            stale.append("source_image_changed")
        else:
            if image.annotation_status != "reviewed":
                stale.append("source_image_review_changed")
            try:
                current_calibration = skeleton_calibration_sha256(image)
                if current_calibration != snapshot.calibration_sha256:
                    original = snapshot.calibration
                    mapped = skeleton_calibration_payload(image)
                    source_id = original.profile_source_image_id if original else None
                    equivalent_profile = bool(
                        original
                        and mapped
                        and source_id
                        and source_id in row.source_id_map_json
                        and row.source_id_map_json[source_id] == mapped.profile_source_image_id
                        and mapped.model_copy(update={"profile_source_image_id": source_id})
                        == original
                    )
                    if not equivalent_profile:
                        stale.append("source_calibration_changed")
            except ValidationError:
                stale.append("source_calibration_changed")
        if (
            mask is None
            or mask.deleted_at is not None
            or mask.revision != snapshot.mask_revision
            or mask.status != "verified"
        ):
            stale.append("source_mask_changed")
        return GraphRecord(
            id=row.id,
            graph_id=row.graph_id,
            project_id=row.project_id,
            identity_revision_id=row.identity_revision_id,
            analysis_id=row.analysis_id,
            revision=row.revision,
            supersedes_id=row.supersedes_id,
            decision="accepted" if row.decision == "accepted" else "rejected",
            reviewer=row.reviewer,
            reason=row.reason,
            created_at=utc(row.created_at),
            content_sha256=row.content_sha256,
            snapshot=snapshot,
            current=row.decision == "accepted" and not stale,
            stale_reasons=stale,
        )

    def list_graphs(
        self,
        project_id: str,
        *,
        analysis_id: str | None,
        limit: int,
        offset: int,
        mask_id: str | None = None,
    ) -> list[GraphRecord]:
        self._project(project_id)
        query = select(CoralGraphRevision).where(CoralGraphRevision.project_id == project_id)
        if analysis_id:
            query = query.where(CoralGraphRevision.analysis_id == analysis_id)
        if mask_id:
            query = query.join(
                SkeletonAnalysisRevision,
                CoralGraphRevision.analysis_id == SkeletonAnalysisRevision.id,
            ).where(SkeletonAnalysisRevision.mask_annotation_id == mask_id)

        rows = self.session.scalars(
            query.order_by(CoralGraphRevision.created_at.desc(), CoralGraphRevision.id)
            .limit(limit)
            .offset(offset)
        )
        return [self.graph_record(row) for row in rows]

    def review_graph(self, project_id: str, payload: GraphReview) -> GraphRecord:
        self._start_write()
        identity = self.owned(
            EcologyIdentityRevision, project_id, str(payload.identity_revision_id)
        )
        if identity.kind != "colony" or self._latest_identity(identity) != identity.id:
            raise ConflictError("Select the current registered colony revision")
        stored = self.session.get(SkeletonAnalysisRevision, str(payload.analysis_id))
        image = self.session.get(ImageAsset, stored.image_id) if stored else None
        if stored is None or image is None or image.project_id != project_id:
            raise NotFoundError("Skeleton analysis was not found in this project")
        mask = self.session.get(MaskAnnotation, stored.mask_annotation_id)
        if (
            mask is None
            or mask.deleted_at is not None
            or mask.status != "verified"
            or image.annotation_status != "reviewed"
        ):
            raise ValidationError(
                "Review and save the source mask and image before reviewing a coral graph"
            )
        analysis = SkeletonizationService(self.session, self.settings).get_persisted_analysis(
            stored.id
        )
        if (
            analysis.stale
            or analysis.mask_revision != mask.revision
            or not analysis.is_latest_revision
        ):
            raise ConflictError("Create a skeleton analysis from the current mask and calibration")
        if canonical_json_sha256(analysis.result.model_dump(mode="json")) != analysis.result_sha256:
            raise ValidationError("Source skeleton checksum does not match")

        base = None
        graph_id = str(uuid5(NAMESPACE_URL, f"reefvision:{project_id}:coral:{mask.id}"))
        if payload.base_revision_id is not None:
            base = self.owned(CoralGraphRevision, project_id, str(payload.base_revision_id))
            base_analysis = self.session.get(SkeletonAnalysisRevision, base.analysis_id)
            base_identity = self.owned(
                EcologyIdentityRevision, project_id, base.identity_revision_id
            )
            active = self._active_graph(base.graph_id)
            if (
                base_analysis is None
                or base_analysis.mask_annotation_id != mask.id
                or base_identity.organism_key != identity.organism_key
                or active is None
                or active.id != base.id
            ):
                raise ConflictError("Select the latest accepted revision for this mask and colony")
            if (base.analysis_id != stored.id or base.identity_revision_id != identity.id) and (
                payload.edit is not None
            ):
                raise ValidationError(
                    "Review the new source evidence before applying another branch edit"
                )
            graph_id = base.graph_id
        else:
            previous_graph = self.session.scalar(
                select(CoralGraphRevision)
                .join(
                    SkeletonAnalysisRevision,
                    CoralGraphRevision.analysis_id == SkeletonAnalysisRevision.id,
                )
                .where(
                    CoralGraphRevision.project_id == project_id,
                    SkeletonAnalysisRevision.mask_annotation_id == mask.id,
                    CoralGraphRevision.decision == "accepted",
                )
                .limit(1)
            )
            if previous_graph is not None:
                raise ConflictError(
                    "This mask already has a reviewed graph. Select its latest accepted revision."
                )
        prior = self.graph_record(base).snapshot if base is not None else None
        if prior is not None and prior.observed_at != payload.observed_at:
            raise ValidationError("A graph edit must preserve the recorded observation timestamp")
        lineage: list[BranchSupersession] = []
        if prior is None:
            nodes, edges, _ = assign_ids(*source_skeleton_graph(analysis, image))
        elif (
            base is not None
            and base.analysis_id != stored.id
            and prior.mask_sha256 != stored.input_mask_sha256
        ):
            nodes, edges, lineage = match_unchanged_geometry(
                *source_skeleton_graph(analysis, image), prior
            )
        else:
            nodes, edges = restore_graph(prior)

        points = [point for gap in payload.gaps for point in gap.points]
        if payload.edit:
            points.extend(payload.edit.points)
        if any(point.x >= image.width_px or point.y >= image.height_px for point in points):
            raise ValidationError("Branch or gap geometry extends outside the source image")

        attachment = None
        qc: list[str] = []
        try:
            if payload.edit is not None:
                nodes, edges, lineage, attachment = apply_graph_edit(nodes, edges, payload.edit)
            validate_branch_graph(nodes, edges, require_connected=False)
        except BranchEditError as exc:
            if payload.decision != "rejected":
                raise ValidationError(str(exc)) from exc
            qc.append(str(exc))
        connected = False
        try:
            validate_branch_graph(nodes, edges)
            connected = bool(edges)
        except BranchEditError:
            pass
        gaps = payload.gaps or (prior.gaps if prior is not None else [])
        if (
            any(gap.disposition == "observed_attachment" for gap in payload.gaps)
            and attachment is None
        ):
            raise ValidationError(
                "Record the observed attachment with an explicit geometry operation"
            )
        unresolved = any(gap.disposition != "observed_attachment" for gap in gaps)
        if not connected and payload.decision == "accepted" and not unresolved:
            raise ValidationError(
                "Record an unresolved gap disposition before retaining disconnected evidence"
            )
        if unresolved:
            qc.append("reviewed_gap_excludes_growth")
        if not connected:
            qc.append("disconnected_or_unmeasurable")
        if analysis.result.removed_spur_count:
            qc.append("source_spur_pruning")
        if not analysis.result.topology_preserved:
            qc.append("source_topology_warning")
        if (
            payload.edit
            and payload.edit.kind == "add"
            and attachment is not None
            and attachment != pixel(payload.edit.points[0])
        ):
            qc.append("reviewer_authorized_attachment_snap")

        calibration = skeleton_calibration_payload(image)
        physical = skeleton_edge_physical_lengths(
            nodes, edges, calibration, reject_projective_horizon=True
        )
        if not all(isfinite(value) and value > 0 for value in physical.values()):
            raise ValidationError("Branch calibration produced an invalid physical length")
        if calibration is None:
            qc.append("pixel_only")
        elif not is_ecological_physical_length_unit(calibration.unit):
            qc.append("unsupported_physical_length_unit")
        snapshot = GraphSnapshot(
            organism_key=identity.organism_key,
            image_id=image.id,
            image_sha256=image.sha256,
            mask_annotation_id=mask.id,
            mask_revision=mask.revision,
            mask_sha256=stored.input_mask_sha256,
            analysis_sha256=stored.result_sha256,
            analysis_algorithm=stored.algorithm,
            analysis_algorithm_version=stored.algorithm_version,
            observed_at=payload.observed_at,
            nodes=[
                ConnectedBranchNodeResponse(
                    id=node.id,
                    kind=node.kind,
                    x=node.x,
                    y=node.y,
                    source_pixels=[SkeletonPixelEdit(x=x, y=y) for x, y in node.source_pixels],
                    external_connection_count=node.external_connection_count,
                )
                for node in nodes
            ],
            edges=[
                ConnectedBranchEdgeResponse(
                    id=edge.id,
                    source_node_id=edge.source_node_id,
                    target_node_id=edge.target_node_id,
                    pixels=[SkeletonPixelEdit(x=x, y=y) for x, y in edge.pixels],
                    boundary_to_boundary_length_pixels=edge.boundary_to_boundary_length_pixels,
                    node_to_node_length_pixels=edge.node_to_node_length_pixels,
                    is_cycle=edge.is_cycle,
                    length_physical=physical.get(edge.id),
                )
                for edge in edges
            ],
            total_pixels=sum(edge.node_to_node_length_pixels for edge in edges),
            total_physical=sum(physical.values()) if calibration else None,
            calibration=calibration,
            calibration_sha256=stored.calibration_sha256,
            edit=payload.edit,
            attached_pixel=SkeletonPixelEdit(x=attachment[0], y=attachment[1])
            if attachment
            else None,
            gaps=gaps,
            supersession=lineage,
            qc=qc,
            connected=connected,
            eligible_for_growth=(
                payload.decision == "accepted"
                and connected
                and not unresolved
                and calibration is not None
                and calibration.reference_plane_only
                and is_ecological_physical_length_unit(calibration.unit)
            ),
            source_reviewed=True,
        )
        maximum = self.session.scalar(
            select(func.max(CoralGraphRevision.revision)).where(
                CoralGraphRevision.graph_id == graph_id
            )
        )
        data = snapshot.model_dump(mode="json")
        row = CoralGraphRevision(
            project_id=project_id,
            graph_id=graph_id,
            revision=(maximum or 0) + 1,
            identity_revision_id=identity.id,
            analysis_id=stored.id,
            supersedes_id=base.id if base else None,
            decision=payload.decision,
            reviewer=payload.reviewer,
            reason=payload.reason,
            payload_json=data,
            content_sha256=canonical_json_sha256(data),
        )
        self.session.add(row)
        self._commit()
        return self.graph_record(row)

    def _latest_correspondence(self, series_id: str) -> str | None:
        return self.session.scalar(
            select(CoralBranchCorrespondenceRevision.id)
            .where(CoralBranchCorrespondenceRevision.correspondence_id == series_id)
            .order_by(CoralBranchCorrespondenceRevision.revision.desc())
            .limit(1)
        )

    def correspondence_record(self, row: CoralBranchCorrespondenceRevision) -> CorrespondenceRecord:
        snapshot = CorrespondenceSnapshot.model_validate(checked_snapshot(row))
        earlier, later = self._pair(
            row.project_id, row.earlier_graph_revision_id, row.later_graph_revision_id
        )
        stale = [
            f"{side}_{reason}"
            for side, graph in (("earlier", earlier), ("later", later))
            for reason in graph.stale_reasons
        ]
        if (
            earlier.content_sha256 != snapshot.earlier_graph_sha256
            or later.content_sha256 != snapshot.later_graph_sha256
        ):
            stale.append("graph_snapshot_changed")
        if self._latest_correspondence(row.correspondence_id) != row.id:
            stale.append("superseded_correspondence")
        return CorrespondenceRecord(
            id=row.id,
            project_id=row.project_id,
            correspondence_id=row.correspondence_id,
            earlier_graph_revision_id=row.earlier_graph_revision_id,
            later_graph_revision_id=row.later_graph_revision_id,
            supersedes_id=row.supersedes_id,
            revision=row.revision,
            reviewer=row.reviewer,
            reason=row.reason,
            created_at=utc(row.created_at),
            content_sha256=row.content_sha256,
            snapshot=snapshot,
            stale_reasons=stale,
        )

    def _pair(self, project_id: str, earlier: str, later: str) -> tuple[GraphRecord, GraphRecord]:
        return (
            self.graph_record(self.owned(CoralGraphRevision, project_id, earlier)),
            self.graph_record(self.owned(CoralGraphRevision, project_id, later)),
        )

    def list_correspondences(
        self, project_id: str, *, limit: int, offset: int
    ) -> list[CorrespondenceRecord]:
        self._project(project_id)
        rows = self.session.scalars(
            select(CoralBranchCorrespondenceRevision)
            .where(CoralBranchCorrespondenceRevision.project_id == project_id)
            .order_by(
                CoralBranchCorrespondenceRevision.created_at.desc(),
                CoralBranchCorrespondenceRevision.id,
            )
            .limit(limit)
            .offset(offset)
        )
        return [self.correspondence_record(row) for row in rows]

    def review_correspondence(
        self, project_id: str, payload: CorrespondenceReview
    ) -> CorrespondenceRecord:
        self._start_write()
        earlier, later = self._pair(
            project_id, str(payload.earlier_graph_revision_id), str(payload.later_graph_revision_id)
        )
        if not earlier.current or not later.current:
            raise ConflictError("Select current accepted graph revisions at both dates")
        if earlier.snapshot.organism_key != later.snapshot.organism_key:
            raise ValidationError("Both observations must be of the same registered colony")
        if (
            earlier.snapshot.image_sha256 == later.snapshot.image_sha256
            or earlier.snapshot.observed_at >= later.snapshot.observed_at
        ):
            raise ValidationError("Use distinct source images in chronological order")
        for key, graph in (("earlier_branch_ids", earlier), ("later_branch_ids", later)):
            selected = [
                identifier for match in payload.matches for identifier in getattr(match, key)
            ]
            if len(set(selected)) != len(selected) or set(selected) != {
                edge.id for edge in graph.snapshot.edges
            }:
                raise ValidationError(
                    "Review each branch exactly once, including missing or ambiguous observations"
                )
        series_id = str(
            uuid5(
                NAMESPACE_URL, f"reefvision:{project_id}:coral:{earlier.graph_id}:{later.graph_id}"
            )
        )
        revision = 1
        supersedes = None
        if payload.base_revision_id:
            base = self.owned(
                CoralBranchCorrespondenceRevision, project_id, str(payload.base_revision_id)
            )
            old_earlier, old_later = self._pair(
                project_id, base.earlier_graph_revision_id, base.later_graph_revision_id
            )
            if self._latest_correspondence(base.correspondence_id) != base.id or (
                old_earlier.graph_id,
                old_later.graph_id,
            ) != (earlier.graph_id, later.graph_id):
                raise ConflictError(
                    "Review must supersede the latest correspondence for these observation graphs"
                )
            series_id, revision, supersedes = base.correspondence_id, base.revision + 1, base.id
        else:
            existing = self.session.scalar(
                select(CoralBranchCorrespondenceRevision.id)
                .where(
                    CoralBranchCorrespondenceRevision.project_id == project_id,
                    CoralBranchCorrespondenceRevision.earlier_graph_revision_id == earlier.id,
                    CoralBranchCorrespondenceRevision.later_graph_revision_id == later.id,
                )
                .limit(1)
            )
            if existing:
                raise ConflictError("A correspondence already exists. Revise the current review.")
        data = CorrespondenceSnapshot(
            earlier_graph_sha256=earlier.content_sha256,
            later_graph_sha256=later.content_sha256,
            matches=payload.matches,
        ).model_dump(mode="json")
        row = CoralBranchCorrespondenceRevision(
            project_id=project_id,
            correspondence_id=series_id,
            revision=revision,
            supersedes_id=supersedes,
            earlier_graph_revision_id=earlier.id,
            later_graph_revision_id=later.id,
            payload_json=data,
            content_sha256=canonical_json_sha256(data),
            reviewer=payload.reviewer,
            reason=payload.reason,
        )
        self.session.add(row)
        self._commit()
        return self.correspondence_record(row)

    def calculate_growth(self, project_id: str, correspondence_id: str) -> GrowthSnapshot:
        row = self.owned(CoralBranchCorrespondenceRevision, project_id, correspondence_id)
        correspondence = self.correspondence_record(row)
        if correspondence.stale_reasons:
            raise ConflictError("Evidence changed. Review correspondence before recalculating.")
        earlier_record, later_record = self._pair(
            project_id, row.earlier_graph_revision_id, row.later_graph_revision_id
        )
        earlier, later = earlier_record.snapshot, later_record.snapshot
        if (
            earlier.calibration is None
            or later.calibration is None
            or not (earlier.eligible_for_growth and later.eligible_for_growth)
        ):
            raise ValidationError(
                "Growth requires calibrated, connected observations with reviewed visibility"
            )
        if earlier.calibration.unit.casefold() != later.calibration.unit.casefold() or (
            (earlier.calibration.perspective_homography is None)
            != (later.calibration.perspective_homography is None)
        ):
            raise ValidationError(
                "Growth requires the same physical unit and reference-plane method"
            )
        elapsed = (later.observed_at - earlier.observed_at).total_seconds() / 86400
        if elapsed <= 0:
            raise ValidationError("Later observation must follow earlier observation")

        def change(before: float | None, after: float | None) -> GrowthChange:
            if before is None or after is None:
                raise ValidationError("A referenced branch has no calibrated length")
            difference = after - before
            rate = difference / elapsed
            if not all(isfinite(value) for value in (difference, rate)):
                raise ValidationError("Growth change is outside supported numeric precision")
            return GrowthChange(
                earlier_length=before,
                later_length=after,
                absolute_change=difference,
                change_per_day=rate,
            )

        old = {edge.id: edge.length_physical for edge in earlier.edges}
        new = {edge.id: edge.length_physical for edge in later.edges}
        limitations = [
            "Projected centerline lengths in a common reference-plane method; no depth correction.",
            "Imaging orientation and visibility can affect measured change.",
            "Calibration and tracing uncertainty were not quantified.",
        ]
        complete = not any(
            match.status in {"missing", "ambiguous", "occluded"}
            for match in correspondence.snapshot.matches
        )
        if not complete:
            limitations.append(
                "Colony total change withheld because some branches were unresolved."
            )
        return GrowthSnapshot(
            organism_key=earlier.organism_key,
            correspondence_sha256=row.content_sha256,
            earlier_graph_sha256=earlier_record.content_sha256,
            later_graph_sha256=later_record.content_sha256,
            earlier_observed_at=earlier.observed_at,
            later_observed_at=later.observed_at,
            elapsed_days=elapsed,
            unit=earlier.calibration.unit,
            total=change(earlier.total_physical, later.total_physical) if complete else None,
            branches=[
                GrowthBranch(
                    status=match.status,
                    earlier_branch_ids=match.earlier_branch_ids,
                    later_branch_ids=match.later_branch_ids,
                    change=change(old[match.earlier_branch_ids[0]], new[match.later_branch_ids[0]])
                    if match.status == "matched"
                    else None,
                    reason=match.reason,
                )
                for match in correspondence.snapshot.matches
            ],
            limitations=limitations,
        )

    def save_growth(self, project_id: str, correspondence_id: str) -> GrowthRecord:
        self._start_write()
        snapshot = self.calculate_growth(project_id, correspondence_id).model_dump(mode="json")
        row = CoralGrowthRecord(
            project_id=project_id,
            correspondence_revision_id=correspondence_id,
            payload_json=snapshot,
            content_sha256=canonical_json_sha256(snapshot),
        )
        self.session.add(row)
        self._commit()
        return self.growth_record(row)

    def growth_record(self, row: CoralGrowthRecord) -> GrowthRecord:
        snapshot = GrowthSnapshot.model_validate(checked_snapshot(row))
        correspondence = self.correspondence_record(
            self.owned(
                CoralBranchCorrespondenceRevision, row.project_id, row.correspondence_revision_id
            )
        )
        stale = list(correspondence.stale_reasons)
        if snapshot.correspondence_sha256 != correspondence.content_sha256:
            stale.append("correspondence_snapshot_changed")
        return GrowthRecord(
            id=row.id,
            project_id=row.project_id,
            correspondence_revision_id=row.correspondence_revision_id,
            content_sha256=row.content_sha256,
            created_at=utc(row.created_at),
            snapshot=snapshot,
            stale_reasons=stale,
        )

    def list_growth(self, project_id: str, *, limit: int, offset: int) -> list[GrowthRecord]:
        self._project(project_id)
        rows = self.session.scalars(
            select(CoralGrowthRecord)
            .where(CoralGrowthRecord.project_id == project_id)
            .order_by(CoralGrowthRecord.created_at.desc(), CoralGrowthRecord.id)
            .limit(limit)
            .offset(offset)
        )
        return [self.growth_record(row) for row in rows]
