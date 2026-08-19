"""CoralVision 1.0 project-exchange extensions.

The Phase 9 exporter predates executable workflow graphs. This subclass keeps the
stable archive builder while extending the record inventory with the provenance
objects required to reproduce 1.0 workflows.
"""

from __future__ import annotations

import json
import zipfile

from sqlalchemy import select

from reefvision.db.models import (
    Job,
    Project,
    WorkflowArtifact,
    WorkflowGraphRecord,
    WorkflowNodeRun,
    WorkflowRun,
)
from reefvision.schemas.project_exchange import ProjectExchangePackageResponse
from reefvision.services.project_exchange import MANIFEST_NAME, ProjectExchangeService
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.storage.projects import resolve_managed_project_path


class ProjectExchangeV1Service(ProjectExchangeService):
    """Project exchange service with executable-workflow provenance included."""

    def _records(self, project: Project) -> dict[str, list[object]]:
        sections = super()._records(project)
        workflow_runs = list(
            self.session.scalars(
                select(WorkflowRun).where(WorkflowRun.project_id == project.id)
            )
        )
        workflow_run_ids = [item.id for item in workflow_runs]
        workflow_node_runs = (
            list(
                self.session.scalars(
                    select(WorkflowNodeRun).where(
                        WorkflowNodeRun.workflow_run_id.in_(workflow_run_ids)
                    )
                )
            )
            if workflow_run_ids
            else []
        )
        sections.update(
            {
                "jobs": list(
                    self.session.scalars(
                        select(Job).where(
                            Job.project_id == project.id,
                            Job.job_type != "project_exchange_export",
                        )
                    )
                ),
                "workflow_graphs": list(
                    self.session.scalars(
                        select(WorkflowGraphRecord).where(
                            WorkflowGraphRecord.project_id == project.id
                        )
                    )
                ),
                "workflow_runs": workflow_runs,
                "workflow_node_runs": workflow_node_runs,
                "workflow_artifacts": (
                    list(
                        self.session.scalars(
                            select(WorkflowArtifact).where(
                                WorkflowArtifact.workflow_run_id.in_(workflow_run_ids)
                            )
                        )
                    )
                    if workflow_run_ids
                    else []
                ),
            }
        )
        return sections

    def build_export(self, package_id: str) -> ProjectExchangePackageResponse:
        """Build the base archive, then advertise the 1.0 round-trip import policy."""

        super().build_export(package_id)
        package = self._package(package_id)
        manifest = dict(package.manifest_json)
        manifest["import_policy"] = {
            "mode": "import_as_new_project",
            "id_remapping_required": True,
            "existing_projects_must_not_be_overwritten": True,
            "source_ids_are_preserved_in_import_provenance": True,
        }

        archive_path = resolve_managed_project_path(self.settings, package.archive_path)
        temporary = archive_path.with_suffix(archive_path.suffix + ".manifest.part")
        temporary.unlink(missing_ok=True)
        try:
            with zipfile.ZipFile(archive_path, "r") as source_archive:
                with zipfile.ZipFile(
                    temporary, "w", compression=zipfile.ZIP_DEFLATED
                ) as target_archive:
                    for info in source_archive.infolist():
                        if info.filename == MANIFEST_NAME:
                            continue
                        target_archive.writestr(info, source_archive.read(info.filename))
                    target_archive.writestr(
                        MANIFEST_NAME,
                        json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8"),
                    )
            temporary.replace(archive_path)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

        package.manifest_json = manifest
        package.manifest_sha256 = canonical_json_sha256(manifest)
        self.session.commit()
        self.session.refresh(package)
        return ProjectExchangePackageResponse.model_validate(package)
