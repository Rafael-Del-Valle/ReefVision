"""Ensure executable ecology nodes are wired through the workflow planner."""

from reefvision.services.workflow_graphs import _ACTIONS
from reefvision.services.workflow_node_registry_v1 import workflow_node_registry
from reefvision.services.workflow_runtime_adapters import RUNTIME_ADAPTER_NODE_TYPES


def test_ecology_nodes_have_planner_actions_and_runtime_adapters() -> None:
    registry = workflow_node_registry()
    for node_type in ("ecology_longitudinal_analysis", "ecology_paired_count_comparison"):
        assert registry[node_type].executable is True
        assert node_type in _ACTIONS
        assert node_type in RUNTIME_ADAPTER_NODE_TYPES
