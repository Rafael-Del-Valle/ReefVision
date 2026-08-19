"""Install CoralVision 1.0 workflow extensions without forking the M10 engine."""

from __future__ import annotations

from reefvision.services import workflow_graphs
from reefvision.services.workflow_node_registry_v1 import workflow_node_registry


def install_workflow_v1_extensions() -> None:
    """Make the extended registry visible to the existing validator/planner service."""

    workflow_graphs.workflow_node_registry = workflow_node_registry
