"""Technical image observations must not masquerade as ecological replicates."""

from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError as SchemaValidationError

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.schemas.longitudinal_monitoring import LongitudinalAnalysisRequest
from reefvision.schemas.model_agreement import PairedCountComparisonRequest
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_workflow_ecology_1_2 import _graph as longitudinal_graph
from reefvision.tests.test_workflow_ecology_1_2 import _observations
from reefvision.tests.test_workflow_model_agreement_1_2 import (
    _graph as comparison_graph,
)


@pytest.mark.parametrize(
    "technical_type",
    [
        "image",
        "video_frame",
        "per-image",
        "photograph",
        "tile",
        "annotation",
        "camera",
        "roi",
        "bounding_box",
        "segmentation",
        "model_prediction",
        "augmented_view",
        "keyframe",
        "pose_keypoint",
        "tracking_tracklet",
        "prediction_heatmap",
        "segmentation_polygon",
        "screenshot",
        "subframe",
    ],
)
def test_technical_unit_is_rejected_in_both_schema_contracts(
    technical_type: str,
) -> None:
    observations = [
        {
            "organism_id": "frag-A",
            "metric_name": "polyp_count",
            "source_record_id": f"source-{day}",
            "observed_at": f"2026-04-0{day}T12:00:00Z",
            "value": 10 + day,
            "unit": "count",
            "experimental_unit_id": "tank-A",
            "experimental_unit_type": technical_type,
        }
        for day in (1, 2)
    ]
    pairs = [
        {
            "observation_id": f"image-{idx}",
            "organism_id": f"frag-{idx}",
            "metric_name": "polyp_count",
            "reference_source_record_id": f"human-{idx}",
            "model_source_record_id": f"model-{idx}",
            "reference_count": 10,
            "model_count": 12,
            "experimental_unit_id": "tank-A",
            "experimental_unit_type": technical_type,
        }
        for idx in (1, 2)
    ]
    with pytest.raises(SchemaValidationError, match="technical replicates"):
        LongitudinalAnalysisRequest(observations=observations)
    with pytest.raises(SchemaValidationError, match="technical replicates"):
        PairedCountComparisonRequest(reference_kind="human_consensus", pairs=pairs)


@pytest.mark.parametrize(
    "technical_type",
    ["image", "roi", "model_prediction", "pose_keypoint", "tracking_tracklet"],
)
@pytest.mark.parametrize(
    ("node_type", "artifact_type"),
    [
        ("ecology_longitudinal_analysis", "longitudinal_analysis"),
        ("ecology_paired_count_comparison", "paired_count_comparison"),
    ],
)
def test_saved_workflow_refuses_technical_pseudoreplicates(
    client: TestClient, node_type: str, artifact_type: str, technical_type: str
) -> None:
    project = create_project(client, "Technical-unit rejection")
    project_id = str(project["id"])
    graph = (
        longitudinal_graph(_observations())
        if node_type == "ecology_longitudinal_analysis"
        else comparison_graph()
    )
    node = next(row for row in graph["nodes"] if row["node_type"] == node_type)
    node["parameters"]["experimental_unit_type"] = technical_type
    saved = client.post(
        f"/api/v1/projects/{project_id}/workflow-graphs",
        json={"graph": graph, "create_new_revision": True},
    )
    assert saved.status_code == 201, saved.text
    queued = client.post(
        f"/api/v1/projects/{project_id}/workflow-runs",
        json={"graph_record_id": saved.json()["id"]},
    )
    assert queued.status_code == 202, queued.text
    app = cast(FastAPI, client.app)
    assert (
        process_workflow_run_job(
            app.state.settings,
            app.state.session_factory,
            str(queued.json()["job_id"]),
        )
        is False
    )
    detail = client.get(f"/api/v1/workflow-runs/{queued.json()['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["run"]["status"] == "failed"
    assert all(row["data_type"] != artifact_type for row in detail.json()["artifacts"])


@pytest.mark.parametrize(
    ("endpoint", "payload"),
    [
        (
            "/api/v1/ecology/longitudinal-analysis",
            {
                "observations": [
                    {
                        "organism_id": "frag-A",
                        "metric_name": "polyp_count",
                        "source_record_id": f"source-{day}",
                        "observed_at": f"2026-04-0{day}T12:00:00Z",
                        "value": 10,
                        "unit": "count",
                        "experimental_unit_id": "photo-1",
                        "experimental_unit_type": "image",
                    }
                    for day in (1, 2)
                ]
            },
        ),
        (
            "/api/v1/ecology/paired-count-comparison",
            {
                "reference_kind": "human_consensus",
                "pairs": [
                    {
                        "observation_id": f"image-{idx}",
                        "organism_id": f"frag-{idx}",
                        "metric_name": "polyp_count",
                        "reference_source_record_id": f"human-{idx}",
                        "model_source_record_id": f"model-{idx}",
                        "reference_count": 10,
                        "model_count": 12,
                        "experimental_unit_id": f"image-{idx}",
                        "experimental_unit_type": "frame",
                    }
                    for idx in (1, 2)
                ],
            },
        ),
    ],
)
def test_standalone_api_rejects_technical_units(
    client: TestClient, endpoint: str, payload: dict[str, object]
) -> None:
    response = client.post(endpoint, json=payload)
    assert response.status_code == 422, response.text
    assert "technical replicates" in response.text
