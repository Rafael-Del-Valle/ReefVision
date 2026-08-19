from reefvision.services.workflow_definition_extensions import (
    install_workflow_definition_extensions,
)
from reefvision.services.workflow_full_platform_templates import (
    classification_uncertainty_review_template,
    configurable_fish_behavior_template,
    depth_aware_coral_measurement_template,
    metric_coral_visible_surface_template,
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


def test_relative_depth_template_connects_depth_without_physical_mode() -> None:
    install_workflow_definition_extensions()
    template = depth_aware_coral_measurement_template()
    nodes = {node.id: node for node in template.workflow.nodes}

    assert nodes["depth"].node_type == "depth_estimation"
    assert nodes["depth"].configuration["depth_kind"] == "relative"
    assert nodes["measure"].node_type == "measurement"
    assert nodes["measure"].configuration.get("measurement_mode") is None
    assert any(
        edge.source_node_id == "depth"
        and edge.source_port == "depth_maps"
        and edge.target_node_id == "measure"
        and edge.target_port == "depth_maps"
        for edge in template.workflow.edges
    )


def test_metric_coral_surface_template_is_fail_closed_for_physical_depth() -> None:
    template = metric_coral_visible_surface_template()
    nodes = {node.id: node for node in template.workflow.nodes}
    depth = nodes["depth"].configuration
    measurement = nodes["measure"].configuration

    assert depth["provider_id"] == "depth_anything_v2_metric"
    assert depth["depth_kind"] == "metric"
    assert depth["unit"] == "m"
    assert "camera_intrinsics" in depth
    assert measurement["measurement_mode"] == "coral_metric_surface"
    assert "relative_monocular" not in measurement["allowed_depth_source_kinds"]
    assert "rgbd_metric" in measurement["allowed_depth_source_kinds"]
    assert "stereo_metric" in measurement["allowed_depth_source_kinds"]
    assert any(
        edge.source_node_id == "segment"
        and edge.source_port == "masks"
        and edge.target_node_id == "measure"
        and edge.target_port == "masks"
        for edge in template.workflow.edges
    )
    assert any(
        edge.source_node_id == "depth"
        and edge.source_port == "depth_maps"
        and edge.target_node_id == "measure"
        and edge.target_port == "depth_maps"
        for edge in template.workflow.edges
    )


def test_configurable_behavior_template_exposes_research_controls() -> None:
    template = configurable_fish_behavior_template()
    nodes = {node.id: node for node in template.workflow.nodes}
    configuration = nodes["behavior"].configuration

    assert nodes["behavior"].node_type == "behavior_analysis"
    assert configuration["sampling"] == "interpolated"
    assert configuration["heatmap_bins_x"] == 20
    assert configuration["heatmap_bins_y"] == 20
    assert configuration["include_saved_zones"] is True
    assert configuration["zones"] == []
    assert "activity_speed_threshold_pixels_per_second" in configuration
    assert "start_frame" in configuration
    assert "end_frame" in configuration
    assert "start_time_seconds" in configuration
    assert "end_time_seconds" in configuration
    assert any(
        edge.source_node_id == "track"
        and edge.source_port == "tracks"
        and edge.target_node_id == "behavior"
        and edge.target_port == "tracks"
        for edge in template.workflow.edges
    )
