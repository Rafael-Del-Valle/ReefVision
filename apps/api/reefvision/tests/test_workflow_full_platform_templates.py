from reefvision.services.workflow_definition_extensions import (
    install_workflow_definition_extensions,
)
from reefvision.services.workflow_full_platform_templates import (
    classification_uncertainty_review_template,
    depth_aware_coral_measurement_template,
)
from reefvision.services.workflows import NODE_DEFINITIONS


def test_full_platform_extensions_expose_optional_depth_and_embedding_ports() -> None:
    install_workflow_definition_extensions()

    measurement = NODE_DEFINITIONS["measurement"]
    active_learning = NODE_DEFINITIONS["active_learning"]

    assert measurement.inputs["depth_maps"] == ("depth_maps", False)
    assert active_learning.inputs["embeddings"] == ("embeddings", False)


def test_classification_uncertainty_template_uses_probability_only_active_learning() -> None:
    template = classification_uncertainty_review_template()
    nodes = {node.id: node for node in template.workflow.nodes}

    assert nodes["review"].node_type == "active_learning"
    assert nodes["review"].configuration["strategy"] == "entropy"
    assert "embedding_model_id" not in nodes["review"].configuration
    assert any(
        edge.source_node_id == "classify"
        and edge.source_port == "classifications"
        and edge.target_node_id == "review"
        and edge.target_port == "predictions"
        for edge in template.workflow.edges
    )


def test_depth_aware_measurement_template_connects_depth_maps_to_measurement() -> None:
    install_workflow_definition_extensions()
    template = depth_aware_coral_measurement_template()
    nodes = {node.id: node for node in template.workflow.nodes}

    assert nodes["depth"].node_type == "depth_estimation"
    assert nodes["measure"].node_type == "measurement"
    assert any(
        edge.source_node_id == "depth"
        and edge.source_port == "depth_maps"
        and edge.target_node_id == "measure"
        and edge.target_port == "depth_maps"
        for edge in template.workflow.edges
    )
