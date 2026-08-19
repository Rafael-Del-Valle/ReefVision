"""CoralVision 1.0 project-exchange extensions.

The Phase 9 exporter predates executable workflow graphs. This subclass keeps the
stable archive builder while extending the record inventory with the provenance
objects required to reproduce 1.0 workflows.
"""

from __future__ import annotations

from sqlalchemy import select

from reefvision.db.models import (
    Job,
    Project,
    WorkflowArtifact,
    WorkflowGraphRecord,
    WorkflowNodeRun,
    WorkflowRun,
)
from reefvision.services.project_exchange import ProjectExchangeService


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
                    self.session.scalars(select(Job).where(Job.project_id == project.id))
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
