"""Queue, reopen and import portable, offline reproducibility packages."""

from pathlib import Path
from typing import Any, BinaryIO
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import Job, Project, ProjectExchangePackage
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.schemas.project_exchange import ProjectExchangeCreateRequest
from reefvision.schemas.reproducibility_v15 import (
    ReproducibilityCreate,
    ReproducibilityImport,
    ReproducibilityInspection,
    ReproducibilityManifest,
    ReproducibilityPackage,
    ReproducibilityQueued,
    ReproducibilitySelection,
)
from reefvision.services.paired_models_v15 import read_report
from reefvision.services.reproducibility_lineage_v15 import PACKAGE_OPTION
from reefvision.services.reviewer_lab_v15 import ReviewerLabService
from reefvision.services.study_design import StudyDesignService
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.storage.reproducibility_v15 import (
    copy_uploaded_bundle,
    open_verified_bundle,
    write_bundle,
)


class ResearchExchangeRequest(ProjectExchangeCreateRequest):
    reproducibility: dict[str, Any]


def _options(row: ProjectExchangePackage) -> dict[str, Any]:
    scope = row.options_json.get(PACKAGE_OPTION)
    return dict(scope) if isinstance(scope, dict) else {}


def _response(row: ProjectExchangePackage) -> ReproducibilityPackage:
    scope = _options(row)
    manifest = (
        ReproducibilityManifest.model_validate(scope["manifest"])
        if row.status == "complete" and scope.get("manifest")
        else None
    )
    status = "running" if row.status == "complete" and manifest is None else row.status
    return ReproducibilityPackage.model_validate(
        {
            "id": row.id,
            "project_id": row.project_id,
            "direction": row.direction,
            "status": status,
            "job_id": row.job_id,
            "manifest": manifest,
            "manifest_sha256": scope.get("manifest_sha256") if manifest else None,
            "proof_sha256": manifest.proof.proof_sha256 if manifest else None,
            "error_message": row.error_message,
        }
    )


def _destination(settings: Settings, row: ProjectExchangePackage) -> Path:
    return resolve_managed_project_path(settings, row.archive_path).with_name(
        f"{row.id}.reproducibility.zip",
    )


def _attach_manifest(row: ProjectExchangePackage, manifest: ReproducibilityManifest) -> None:
    raw = manifest.model_dump(mode="json")
    row.options_json = {
        **row.options_json,
        PACKAGE_OPTION: {
            **_options(row),
            "manifest": raw,
            "manifest_sha256": canonical_json_sha256(raw),
        },
    }


class ReproducibilityService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def queue(self, project_id: str, request: ReproducibilityCreate) -> ReproducibilityQueued:
        from reefvision.services.project_exchange_v1 import ProjectExchangeV1Service

        StudyDesignService(self.session).get(project_id, str(request.study_design_id))
        ReviewerLabService(self.session, project_id).report(str(request.reviewer_report_id))
        read_report(self.session, project_id, str(request.comparison_id))
        selection = request.model_dump(
            mode="json",
            exclude={"include_media", "include_model_weights"},
        )
        queued = ProjectExchangeV1Service(self.session, self.settings).queue_export(
            project_id,
            ResearchExchangeRequest(
                include_media=request.include_media,
                include_model_weights=request.include_model_weights,
                include_generated_artifacts=True,
                reproducibility={"selection": selection},
            ),
        )
        return ReproducibilityQueued(
            package=self.get(queued.package.id),
            job_id=UUID(queued.job_id),
        )

    def _package(self, package_id: str) -> ProjectExchangePackage:
        row = self.session.get(ProjectExchangePackage, package_id)
        if row is None or not _options(row):
            raise NotFoundError("Reproducibility package not found")
        return row

    def list(self, project_id: str) -> list[ReproducibilityPackage]:
        if self.session.get(Project, project_id) is None:
            raise NotFoundError("Project not found")
        return [
            _response(row)
            for row in self.session.scalars(
                select(ProjectExchangePackage)
                .where(ProjectExchangePackage.project_id == project_id)
                .order_by(ProjectExchangePackage.created_at.desc(), ProjectExchangePackage.id)
            )
            if _options(row)
        ]

    def get(self, package_id: str) -> ReproducibilityPackage:
        return _response(self._package(package_id))

    def download(self, package_id: str) -> Path:
        row = self._package(package_id)
        if _response(row).status != "complete":
            raise ConflictError("Wait for the reproducibility package to finish")
        path = _destination(self.settings, row)
        if not path.is_file():
            raise NotFoundError("Reproducibility archive is unavailable")
        return path

    def restore(self, source: BinaryIO, project_name: str | None) -> ReproducibilityImport:
        from reefvision.services.project_exchange_import_v1 import import_project_exchange_v1

        with open_verified_bundle(source) as verified:

            def attach(project: Project, package: ProjectExchangePackage) -> None:
                if project.id != package.project_id:
                    raise ValidationError("Research package destination project does not match")
                copy_uploaded_bundle(source, _destination(self.settings, package))
                _attach_manifest(package, verified.manifest)

            restored = import_project_exchange_v1(
                verified.native,
                self.session,
                self.settings,
                project_name=project_name,
                after_restore=attach,
            )
        return ReproducibilityImport(
            **restored.model_dump(),
            reproducibility_package_id=restored.package.id,
            proof_sha256=verified.manifest.proof.proof_sha256,
            omitted_sources=verified.manifest.omitted_sources,
        )


def inspect_bundle(source: BinaryIO) -> ReproducibilityInspection:
    try:
        with open_verified_bundle(source) as verified:
            return ReproducibilityInspection(
                compatible=True,
                project_name=verified.project_name,
                manifest=verified.manifest,
                manifest_sha256=canonical_json_sha256(verified.manifest.model_dump(mode="json")),
            )
    except ValidationError as exc:
        return ReproducibilityInspection(compatible=False, errors=[str(exc)])


def complete_research_export(
    session: Session,
    settings: Settings,
    package_id: str,
    job: Job,
) -> None:
    row = session.get(ProjectExchangePackage, package_id)
    if row is None or not (scope := _options(row)):
        return
    selection = ReproducibilitySelection.model_validate(scope["selection"])
    native = resolve_managed_project_path(settings, row.archive_path)
    with native.open("rb") as stream:
        manifest = write_bundle(stream, _destination(settings, row), selection)
    _attach_manifest(row, manifest)
    job.result_json = {
        **(job.result_json or {}),
        "proof_sha256": manifest.proof.proof_sha256,
        "reproducibility_manifest_sha256": _options(row)["manifest_sha256"],
    }
