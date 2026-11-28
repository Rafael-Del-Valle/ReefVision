"""Ensure every executable ecology node has a typed and runnable workflow contract."""

from typing import get_args

from reefvision.schemas.workflow_graphs import WorkflowDataType
from reefvision.services.workflow_graphs import _ACTIONS
from reefvision.services.workflow_node_registry_v1 import workflow_node_registry
from reefvision.services.workflow_runtime_adapters import RUNTIME_ADAPTER_NODE_TYPES


def test_all_executable_ecology_nodes_have_planner_actions_and_runtime_adapters() -> None:
    """A missing planner action must not silently break a saved ecology graph."""
    registry = workflow_node_registry()
    ecology_nodes = {
        node_type
        for node_type, definition in registry.items()
        if node_type.startswith("ecology_") and definition.executable
    }
    # Require the known 1.2 operations as well as checking future ecology nodes.
    assert ecology_nodes >= {
        "ecology_connected_branch_preview",
        "ecology_identity_registry_source",
        "ecology_population_csv_export",
        "ecology_measurement_csv_export",
        "ecology_longitudinal_analysis",
        "ecology_paired_count_comparison",
        "ecology_paired_count_csv_export",
    }
    assert ecology_nodes <= _ACTIONS.keys()
    assert ecology_nodes <= RUNTIME_ADAPTER_NODE_TYPES

    supported_types = set(get_args(WorkflowDataType))
    for node_type in sorted(ecology_nodes):
        definition = registry[node_type]
        assert definition.execution_state == "executable"
        assert _ACTIONS[node_type].strip()
        assert definition.output_ports
        for port in (*definition.input_ports, *definition.output_ports):
            assert port.accepted_types
            assert set(port.accepted_types) <= supported_types


def test_no_orphan_ecology_runtime_adapter_or_planner_action() -> None:
    """Do not advertise ecology execution without a matching node definition."""
    registry = workflow_node_registry()
    ecology_adapters = {
        node_type for node_type in RUNTIME_ADAPTER_NODE_TYPES if node_type.startswith("ecology_")
    }
    ecology_actions = {node_type for node_type in _ACTIONS if node_type.startswith("ecology_")}
    assert ecology_adapters <= registry.keys()
    assert ecology_actions <= registry.keys()
    assert ecology_adapters == ecology_actions
