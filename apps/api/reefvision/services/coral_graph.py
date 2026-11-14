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
    GrowthRecord,
    GrowthSnapshot,
    TraceCoverage,
)
from reefvision.schemas.skeletonization import SkeletonPixelEdit
from reefvision.services.connected_branch_editing import BranchEditError, validate_branch_graph
from reefvision.services.connected_branch_preview import source_skeleton_graph
from reefvision.services.coral_graph_geometry import (
    apply_graph_edit,
    assign_ids,
    frozen_skeleton_digest,
    match_unchanged_geometry,
    merge_gap_reviews,
    pixel,
    restore_graph,
)
from reefvision.services.coral_growth import calculate_pinned_growth, validate_branch_correspondence
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
            analysis_digest = frozen_skeleton_digest(
                analysis.result_json,
                snapshot.image_id,
                snapshot.mask_annotation_id,
                row.source_id_map_json,
            )
            if (
                latest != row.analysis_id
                or analysis.result_sha256 != snapshot.analysis_sha256
                or analysis_digest != analysis.result_sha256
            ):
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
        skeletons = SkeletonizationService(self.session, self.settings)
        analysis = skeletons.get_persisted_analysis(stored.id)
        if (
            analysis.stale
            or analysis.mask_revision != mask.revision
            or not analysis.is_latest_revision
        ):
            raise ConflictError("Create a skeleton analysis from the current mask and calibration")
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
        payload_json = analysis.result.model_dump(mode="json")
        current_digest = canonical_json_sha256(payload_json)
        source_ids: dict[str, str] = {}
        if current_digest != analysis.result_sha256:
            if (
                base is None
                or prior is None
                or frozen_skeleton_digest(
                    payload_json, prior.image_id, prior.mask_annotation_id, base.source_id_map_json
                )
                != analysis.result_sha256
            ):
                raise ValidationError("Source skeleton checksum does not match")
            source_ids = {
                origin: base.source_id_map_json[origin]
                for origin in (prior.image_id, prior.mask_annotation_id)
                if origin in base.source_id_map_json
            }
            profile = prior.calibration.profile_source_image_id if prior.calibration else None
            if profile is not None and profile in base.source_id_map_json:
                source_ids[profile] = base.source_id_map_json[profile]
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

        restored_from = None
        if payload.restore_revision_id is not None and base is not None and prior is not None:
            restored = self.owned(CoralGraphRevision, project_id, str(payload.restore_revision_id))
            historical = self.graph_record(restored).snapshot
            if (
                restored.graph_id != base.graph_id
                or restored.decision != "accepted"
                or restored.analysis_id != stored.id
                or restored.identity_revision_id != identity.id
            ):
                raise ValidationError(
                    "Restore an accepted revision using the same source and colony"
                )
            nodes, edges = restore_graph(historical)
            removed = {edge.id for edge in prior.edges} - {edge.id for edge in edges}
            if removed:
                lineage = [
                    BranchSupersession(previous_branch_ids=sorted(removed), successor_branch_ids=[])
                ]
            restored_from = restored.content_sha256

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
        gaps = merge_gap_reviews(
            prior.gaps if prior is not None else [],
            payload.gaps,
            performed_path=(
                (attachment, *[pixel(point) for point in payload.edit.points[1:]])
                if payload.edit
                and payload.edit.kind in {"add", "reconnect"}
                and attachment is not None
                else ()
            ),
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
        if any(edge.node_to_node_length_pixels < 3 for edge in edges):
            qc.append("short_centerline_segments")
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
        source_pixels = {(point.x, point.y) for point in analysis.result.final_skeleton_pixels}
        trace = {point for edge in edges for point in edge.pixels}
        mask_pixels, width, _ = skeletons._binary_mask(mask, image)
        outside = sum(not mask_pixels[y * width + x] for x, y in trace)
        if outside:
            qc.append("trace_extends_outside_source_mask")
        coverage = TraceCoverage(
            source_skeleton_pixels=len(source_pixels),
            retained_source_skeleton_pixels=len(source_pixels & trace),
            reviewed_trace_pixels=len(trace),
            reviewed_trace_outside_mask_pixels=outside,
        )
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
            restored_from_sha256=restored_from,
            coverage=coverage,
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
        if source_ids and prior is not None:
            # The source analysis retains its canonical digest after exchange.
            snapshot.image_id = prior.image_id
            snapshot.mask_annotation_id = prior.mask_annotation_id
            if snapshot.calibration is not None and prior.calibration is not None:
                profile = prior.calibration.profile_source_image_id
                if (
                    profile
                    and source_ids.get(profile) == snapshot.calibration.profile_source_image_id
                ):
                    snapshot.calibration = snapshot.calibration.model_copy(
                        update={"profile_source_image_id": profile}
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
            source_id_map_json=source_ids,
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
        validate_branch_correspondence(earlier.snapshot, later.snapshot, payload.matches)
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
        return calculate_pinned_growth(
            earlier_record.snapshot,
            later_record.snapshot,
            correspondence.snapshot,
            row.content_sha256,
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
