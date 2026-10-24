"""Versioned ecological identities; never promote registry metadata to verified data."""

from __future__ import annotations

from collections.abc import Mapping

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from reefvision.db.models.annotation import Annotation
from reefvision.db.models.ecology_identity_annotation_evidence import (
    EcologyIdentityAnnotationEvidence,
)
from reefvision.db.models.ecology_identity_image_evidence import EcologyIdentityImageEvidence
from reefvision.db.models.ecology_identity_revision import EcologyIdentityRevision
from reefvision.db.models.image import ImageAsset
from reefvision.db.models.mask_annotation import MaskAnnotation
from reefvision.db.models.project import Project
from reefvision.domain.ecology_lineage_policy import classify_ecological_unit_level
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.domain.experimental_unit_policy import require_ecological_unit_type
from reefvision.schemas.ecology_identity import (
    EcologyAnnotationEvidenceCreate,
    EcologyAnnotationEvidenceRow,
    EcologyIdentityCreate,
    EcologyIdentityFields,
    EcologyIdentityRegistryResponse,
    EcologyIdentityRevisionCreate,
    EcologyIdentityRow,
    EcologyImageEvidenceCreate,
    EcologyImageEvidenceRow,
)
from reefvision.services.annotations import annotation_snapshot, mask_annotation_snapshot
from reefvision.storage.datasets import canonical_json_sha256


class EcologyIdentityService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _project(self, project_id: str) -> None:
        if self.session.get(Project, project_id) is None:
            raise NotFoundError("Project not found")

    def _latest(self, project_id: str) -> dict[str, EcologyIdentityRevision]:
        """Reject missing or out-of-order imported identity revisions.

        The registry is an append-only scientific audit trail. Selecting only
        the highest revision would silently conceal missing earlier records.
        Both API reads and saved Workflow Builder sources use this check.
        """
        records = self.session.scalars(
            select(EcologyIdentityRevision)
            .where(EcologyIdentityRevision.project_id == project_id)
            .order_by(
                EcologyIdentityRevision.organism_key,
                EcologyIdentityRevision.revision,
            )
        )
        latest: dict[str, EcologyIdentityRevision] = {}
        expected_revision: dict[str, int] = {}
        for record in records:
            expected = expected_revision.get(record.organism_key, 1)
            if record.revision != expected:
                raise ValidationError("Ecological identity revision history is not contiguous")
            expected_revision[record.organism_key] = expected + 1
            latest[record.organism_key] = record
        return latest

    @staticmethod
    def _parent_valid(
        key: str,
        payload: EcologyIdentityFields,
        latest: dict[str, EcologyIdentityRevision],
    ) -> None:
        parent_key = payload.parent_colony_key
        if parent_key is None:
            return
        if parent_key == key:
            raise ValidationError("An organism cannot be its own parent colony")
        parent = latest.get(parent_key)
        if parent is None or parent.kind != "colony":
            raise ValidationError("Parent colony must be registered in the same project")

    @staticmethod
    def _assert_parent_links(
        latest: dict[str, EcologyIdentityRevision],
    ) -> None:
        """Reject broken biological lineage before publishing registry snapshots.

        Imported or externally modified revision histories may bypass the API.
        An invalid latest parent cannot become a workflow science artifact.
        """
        for record in latest.values():
            if record.parent_colony_key is None:
                continue
            parent = latest.get(record.parent_colony_key)
            if record.kind != "fragment" or parent is None or parent.kind != "colony":
                raise ValidationError(
                    "Ecological identity registry contains an invalid parent-colony link"
                )

    @staticmethod
    def _assert_experimental_units(
        latest: Mapping[str, EcologyIdentityRevision | EcologyIdentityFields],
    ) -> None:
        """Fail closed on contradictory independent-unit registrations.

        This validates declared identifiers, not the independence of the
        biological design. Tank/site units may contain multiple organisms.
        """
        single_organism_units: dict[tuple[str, str], str] = {}
        colony_units: dict[tuple[str, str], str] = {}
        lineage_units: dict[str, str] = {}
        for key, record in sorted(latest.items()):
            unit_type = record.experimental_unit_type
            unit_id = record.experimental_unit_id
            if (unit_type is None) != (unit_id is None):
                raise ValidationError(
                    "Ecological identity registry contains an incomplete experimental unit"
                )
            if unit_type is None or unit_id is None:
                continue
            # API schemas reject technical units, but imported database revisions
            # can bypass Pydantic. Validate again before exposing registry artifacts.
            try:
                require_ecological_unit_type(unit_type)
            except ValueError as exc:
                raise ValidationError(
                    "Ecological identity registry contains an invalid experimental unit type"
                ) from exc
            normalized_type = classify_ecological_unit_level(unit_type)
            if normalized_type == "organism":
                unit_key = (normalized_type, unit_id)
                prior = single_organism_units.setdefault(unit_key, key)
                if prior != key:
                    raise ValidationError(
                        "An organism-level experimental unit cannot contain multiple organisms"
                    )
            if normalized_type == "colony":
                lineage = (
                    key
                    if record.kind == "colony"
                    else record.parent_colony_key
                    if record.kind == "fragment"
                    else None
                )
                if lineage is None:
                    raise ValidationError("Colony-level units require a registered parent colony")
                parent = latest.get(lineage)
                if parent is None or parent.kind != "colony":
                    raise ValidationError("Colony-level units require a registered parent colony")
                unit_key = (normalized_type, unit_id)
                prior = colony_units.setdefault(unit_key, lineage)
                if prior != lineage:
                    raise ValidationError(
                        "A colony-level experimental unit cannot mix parent colonies"
                    )
                prior_unit = lineage_units.setdefault(lineage, unit_id)
                if prior_unit != unit_id:
                    raise ValidationError("Parent colony split across colony-level units")

    def _append(
        self,
        project_id: str,
        key: str,
        revision: int,
        payload: EcologyIdentityFields,
    ) -> EcologyIdentityRow:
        record = EcologyIdentityRevision(
            project_id=project_id,
            organism_key=key,
            revision=revision,
            kind=payload.kind,
            parent_colony_key=payload.parent_colony_key,
            experimental_unit_type=payload.experimental_unit_type,
            experimental_unit_id=payload.experimental_unit_id,
            reason=payload.reason,
        )
        self.session.add(record)
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise ConflictError("Concurrent or duplicate ecological identity revision") from exc
        self.session.refresh(record)
        return EcologyIdentityRow.model_validate(record)

    def register(self, project_id: str, payload: EcologyIdentityCreate) -> EcologyIdentityRow:
        self._project(project_id)
        latest = self._latest(project_id)
        self._assert_parent_links(latest)
        self._assert_experimental_units(latest)
        if payload.organism_key in latest:
            raise ConflictError("Organism key already registered in this project")
        self._parent_valid(payload.organism_key, payload, latest)
        self._assert_experimental_units({**latest, payload.organism_key: payload})
        return self._append(project_id, payload.organism_key, 1, payload)

    def revise(
        self,
        project_id: str,
        organism_key: str,
        payload: EcologyIdentityRevisionCreate,
    ) -> EcologyIdentityRow:
        self._project(project_id)
        latest = self._latest(project_id)
        self._assert_parent_links(latest)
        self._assert_experimental_units(latest)
        current = latest.get(organism_key)
        if current is None:
            raise NotFoundError("Ecological organism not found in project")
        if current.revision != payload.expected_revision:
            raise ConflictError("Stale organism revision; reload before changing identity")
        if (
            current.kind == "colony"
            and payload.kind != "colony"
            and any(row.parent_colony_key == organism_key for row in latest.values())
        ):
            raise ValidationError("Cannot reclassify a parent colony while fragments reference it")
        self._parent_valid(organism_key, payload, latest)
        self._assert_experimental_units({**latest, organism_key: payload})
        return self._append(project_id, organism_key, current.revision + 1, payload)

    @staticmethod
    def _assert_image_source_metadata(image: ImageAsset) -> None:
        """Reject malformed imported source metadata before publishing evidence.

        This validates database metadata only; it does not read the managed
        file or establish a reviewed biological observation.
        """
        digest = image.sha256
        if len(digest) != 64 or any(
            character not in "0123456789abcdefABCDEF" for character in digest
        ):
            raise ValidationError("Ecological image evidence has an invalid source SHA-256")
        if image.width_px <= 0 or image.height_px <= 0 or image.file_size_bytes <= 0:
            raise ValidationError("Ecological image evidence has invalid source dimensions or size")

    def link_image(
        self,
        project_id: str,
        organism_key: str,
        payload: EcologyImageEvidenceCreate,
    ) -> EcologyImageEvidenceRow:
        """Record a project-owned source image without claiming biological verification."""
        self._project(project_id)
        latest = self._latest(project_id)
        self._assert_parent_links(latest)
        self._assert_experimental_units(latest)
        current = latest.get(organism_key)
        if current is None:
            raise NotFoundError("Ecological organism not found in project")
        if current.revision != payload.expected_identity_revision:
            raise ConflictError("Stale organism revision; reload before linking image")
        image = self.session.get(ImageAsset, payload.image_id)
        if image is None or image.project_id != project_id:
            raise ValidationError("Image evidence must belong to the current project")
        self._assert_image_source_metadata(image)
        existing = self.session.scalar(
            select(EcologyIdentityImageEvidence).where(
                EcologyIdentityImageEvidence.project_id == project_id,
                EcologyIdentityImageEvidence.organism_key == organism_key,
                EcologyIdentityImageEvidence.image_id == payload.image_id,
            )
        )
        if existing is not None:
            raise ConflictError("Image already linked to this organism")
        link = EcologyIdentityImageEvidence(
            project_id=project_id,
            organism_key=organism_key,
            identity_revision=current.revision,
            image_id=image.id,
            image_sha256=image.sha256,
            reason=payload.reason,
        )
        self.session.add(link)
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise ConflictError("Concurrent or duplicate ecological image link") from exc
        self.session.refresh(link)
        return EcologyImageEvidenceRow.model_validate(link)

    def _annotation_source(
        self, kind: str, annotation_id: str, image_id: str
    ) -> tuple[int, str]:
        """Resolve a current source revision, never a verified research observation."""
        if kind == "box":
            annotation = self.session.get(Annotation, annotation_id)
            snapshot = annotation_snapshot(annotation) if annotation is not None else None
        elif kind == "mask":
            annotation = self.session.get(MaskAnnotation, annotation_id)
            snapshot = mask_annotation_snapshot(annotation) if annotation is not None else None
        else:
            raise ValidationError("Ecological annotation evidence has an invalid annotation kind")
        if (
            annotation is None
            or annotation.image_id != image_id
            or annotation.deleted_at is not None
            or annotation.revision < 1
            or snapshot is None
        ):
            raise ValidationError("Ecological annotation source is missing, deleted or mismatched")
        return annotation.revision, canonical_json_sha256(
            {
                "algorithm_version": "ecology-annotation-source-0001",
                "kind": kind,
                "snapshot": snapshot,
            }
        )

    def link_annotation(
        self,
        project_id: str,
        organism_key: str,
        payload: EcologyAnnotationEvidenceCreate,
    ) -> EcologyAnnotationEvidenceRow:
        """Link one frozen annotation revision to a project-owned organism image."""
        self._project(project_id)
        latest = self._latest(project_id)
        self._assert_parent_links(latest)
        self._assert_experimental_units(latest)
        if organism_key not in latest:
            raise NotFoundError("Ecological organism not found in project")
        image_links = self._image_evidence(project_id, latest)
        image_link = next(
            (
                link
                for link in image_links
                if link.id == payload.image_evidence_id and link.organism_key == organism_key
            ),
            None,
        )
        if image_link is None:
            raise ValidationError("Annotation evidence requires an organism-owned image link")
        revision, fingerprint = self._annotation_source(
            payload.annotation_kind, payload.annotation_id, image_link.image_id
        )
        if revision != payload.expected_annotation_revision:
            raise ConflictError("Stale annotation revision; reload before linking")
        existing = self.session.scalar(
            select(EcologyIdentityAnnotationEvidence).where(
                EcologyIdentityAnnotationEvidence.project_id == project_id,
                EcologyIdentityAnnotationEvidence.annotation_kind == payload.annotation_kind,
                EcologyIdentityAnnotationEvidence.annotation_id == payload.annotation_id,
            )
        )
        if existing is not None:
            raise ConflictError("Annotation already linked to an ecological organism")
        evidence = EcologyIdentityAnnotationEvidence(
            project_id=project_id,
            image_evidence_id=image_link.id,
            annotation_kind=payload.annotation_kind,
            annotation_id=payload.annotation_id,
            annotation_revision=revision,
            annotation_sha256=fingerprint,
            reason=payload.reason,
        )
        self.session.add(evidence)
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise ConflictError("Concurrent or duplicate ecological annotation link") from exc
        self.session.refresh(evidence)
        return EcologyAnnotationEvidenceRow.model_validate(evidence)

    def _annotation_evidence(
        self, project_id: str, image_links: list[EcologyIdentityImageEvidence]
    ) -> list[EcologyIdentityAnnotationEvidence]:
        linked_images = {link.id: link for link in image_links}
        records = list(
            self.session.scalars(
                select(EcologyIdentityAnnotationEvidence)
                .where(EcologyIdentityAnnotationEvidence.project_id == project_id)
                .order_by(
                    EcologyIdentityAnnotationEvidence.annotation_kind,
                    EcologyIdentityAnnotationEvidence.annotation_id,
                    EcologyIdentityAnnotationEvidence.id,
                )
            )
        )
        for evidence in records:
            image_link = linked_images.get(evidence.image_evidence_id)
            if image_link is None:
                raise ValidationError("Ecological annotation evidence has an invalid image link")
            revision, fingerprint = self._annotation_source(
                evidence.annotation_kind, evidence.annotation_id, image_link.image_id
            )
            if revision != evidence.annotation_revision or fingerprint != evidence.annotation_sha256:
                raise ValidationError("Ecological annotation source revision is missing or changed")
        return records

    def _image_evidence(
        self,
        project_id: str,
        latest: dict[str, EcologyIdentityRevision],
    ) -> list[EcologyIdentityImageEvidence]:
        links = list(
            self.session.scalars(
                select(EcologyIdentityImageEvidence)
                .where(EcologyIdentityImageEvidence.project_id == project_id)
                .order_by(
                    EcologyIdentityImageEvidence.organism_key,
                    EcologyIdentityImageEvidence.image_id,
                    EcologyIdentityImageEvidence.id,
                )
            )
        )
        for link in links:
            organism = latest.get(link.organism_key)
            if organism is None or not 1 <= link.identity_revision <= organism.revision:
                raise ValidationError("Ecological image evidence references an invalid identity")
            image = self.session.get(ImageAsset, link.image_id)
            if image is None or image.project_id != project_id or image.sha256 != link.image_sha256:
                raise ValidationError("Ecological image evidence source is missing or changed")
            self._assert_image_source_metadata(image)
        return links

    def registry(self, project_id: str) -> EcologyIdentityRegistryResponse:
        self._project(project_id)
        latest = self._latest(project_id)
        self._assert_parent_links(latest)
        self._assert_experimental_units(latest)
        image_links = self._image_evidence(project_id, latest)
        image_link_rows = [EcologyImageEvidenceRow.model_validate(link) for link in image_links]
        annotation_links = self._annotation_evidence(project_id, image_links)
        annotation_rows = [
            EcologyAnnotationEvidenceRow.model_validate(link) for link in annotation_links
        ]
        annotation_fingerprint = [
            {
                "id": row.id,
                "image_evidence_id": row.image_evidence_id,
                "annotation_kind": row.annotation_kind,
                "annotation_id": row.annotation_id,
                "annotation_revision": row.annotation_revision,
                "annotation_sha256": row.annotation_sha256,
                "reason": row.reason,
                "created_at": row.created_at.isoformat(),
            }
            for row in annotation_rows
        ]
        image_link_fingerprint = [
            {
                "id": row.id,
                "organism_key": row.organism_key,
                "identity_revision": row.identity_revision,
                "image_id": row.image_id,
                "image_sha256": row.image_sha256,
                "reason": row.reason,
                "created_at": row.created_at.isoformat(),
            }
            for row in image_link_rows
        ]
        identities = [
            EcologyIdentityRow.model_validate(record) for _, record in sorted(latest.items())
        ]
        # The latest-only snapshot intentionally remains backward compatible.
        # Separately fingerprint the *entire* append-only revision chain so
        # earlier identity corrections cannot disappear from provenance.
        history = list(
            self.session.scalars(
                select(EcologyIdentityRevision)
                .where(EcologyIdentityRevision.project_id == project_id)
                .order_by(
                    EcologyIdentityRevision.organism_key,
                    EcologyIdentityRevision.revision,
                )
            )
        )
        history_rows = [
            {
                "id": row.id,
                "organism_key": row.organism_key,
                "revision": row.revision,
                "kind": row.kind,
                "parent_colony_key": row.parent_colony_key,
                "experimental_unit_type": row.experimental_unit_type,
                "experimental_unit_id": row.experimental_unit_id,
                "reason": row.reason,
                "created_at": row.created_at.isoformat(),
            }
            for row in history
        ]
        fingerprint_rows = [
            {
                "id": row.id,
                "organism_key": row.organism_key,
                "revision": row.revision,
                "kind": row.kind,
                "parent_colony_key": row.parent_colony_key,
                "experimental_unit_type": row.experimental_unit_type,
                "experimental_unit_id": row.experimental_unit_id,
            }
            for row in identities
        ]
        return EcologyIdentityRegistryResponse(
            project_id=project_id,
            identities=identities,
            image_evidence_links=image_link_rows,
            annotation_evidence_links=annotation_rows,
            annotation_evidence_count=len(annotation_rows),
            annotation_evidence_sha256=canonical_json_sha256(
                {
                    "algorithm_version": "ecology-annotation-evidence-0001",
                    "project_id": project_id,
                    "links": annotation_fingerprint,
                }
            ),
            image_evidence_count=len(image_link_rows),
            image_evidence_sha256=canonical_json_sha256(
                {
                    "algorithm_version": "ecology-image-evidence-0001",
                    "project_id": project_id,
                    "links": image_link_fingerprint,
                }
            ),
            history_revision_count=len(history_rows),
            history_sha256=canonical_json_sha256(
                {
                    "algorithm_version": "ecology-identity-history-0001",
                    "project_id": project_id,
                    "revisions": history_rows,
                }
            ),
            snapshot_sha256=canonical_json_sha256(
                {
                    "schema_version": "ecology-identity-registry-0001",
                    "project_id": project_id,
                    "identities": fingerprint_rows,
                }
            ),
        )
