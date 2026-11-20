"""Scientific volume gating and persisted Workflow Builder parity for 1.4."""

from __future__ import annotations

from fractions import Fraction
from math import sqrt
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.spatial_mesh_surface_v14 import measure_mesh_preview
from reefvision.services.spatial_mesh_volume_v14 import (
    signed_enclosed_volume_mesh_units,
)
from reefvision.tests.test_annotations import create_project

TETRA_FACES = [[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]]
TETRA_VERTICES = [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]]


def _params(
    *,
    vertices: list[list[float]] | None = None,
    faces: list[list[int]] | None = None,
    uncertainty: float | None = 0.1,
) -> dict:
    return {
        "vertices": vertices if vertices is not None else TETRA_VERTICES,
        "faces": faces if faces is not None else TETRA_FACES,
        "meters_per_unit": 0.01,
        "calibration_method": "ruler",
        "calibration_evidence": "Unreviewed field scale",
        "relative_scale_uncertainty": uncertainty,
    }


def test_closed_tetrahedron_volume_and_exact_cubic_scale_bounds() -> None:
    result = measure_mesh_preview(**_params())
    volume = 0.01**3 / 6
    assert result["enclosed_volume_m3"] == pytest.approx(volume)
    assert result["edge_connected_patch_enclosed_volumes_m3"] == pytest.approx([volume])
    assert result["enclosed_volume_scale_interval_m3"] == pytest.approx(
        [volume * 0.9**3, volume * 1.1**3]
    )
    assert result["edge_connected_patch_enclosed_volume_scale_intervals_m3"][0] == pytest.approx(
        [volume * 0.9**3, volume * 1.1**3]
    )
    assert result["enclosed_volume_is_provisional"] is True
    assert result["measurement_status"] == "caller_supplied_unverified"
    assert result["provenance"]["calibration_verified"] is False


def test_closed_tetrahedron_surface_volume_ratio_and_inverse_scale_bounds() -> None:
    result = measure_mesh_preview(**_params())
    expected = (3 + sqrt(3)) * 3 / 0.01
    assert result["surface_to_enclosed_volume_ratio_per_m"] == pytest.approx(expected)
    assert result["edge_connected_patch_surface_to_enclosed_volume_ratios_per_m"] == pytest.approx(
        [expected]
    )
    assert result["surface_to_enclosed_volume_ratio_scale_interval_per_m"] == pytest.approx(
        [expected / 1.1, expected / 0.9]
    )
    assert result["edge_connected_patch_surface_to_enclosed_volume_ratio_scale_intervals_per_m"][
        0
    ] == pytest.approx([expected / 1.1, expected / 0.9])
    assert result["measurement_status"] == "caller_supplied_unverified"
    assert result["provenance"]["calibration_verified"] is False


@pytest.mark.parametrize("uncertainty", [None, 0.0, 1.0])
def test_surface_volume_ratio_bounds_do_not_invent_finite_uncertainty(
    uncertainty: float | None,
) -> None:
    result = measure_mesh_preview(**_params(uncertainty=uncertainty))
    ratio = result["surface_to_enclosed_volume_ratio_per_m"]
    assert ratio is not None
    interval = result["surface_to_enclosed_volume_ratio_scale_interval_per_m"]
    if uncertainty == 0:
        assert interval == pytest.approx([ratio, ratio])
    else:
        assert interval is None
    patch_intervals = result[
        "edge_connected_patch_surface_to_enclosed_volume_ratio_scale_intervals_per_m"
    ]
    if uncertainty is None:
        assert patch_intervals is None
    elif uncertainty == 1:
        assert patch_intervals == [None]
    else:
        assert patch_intervals[0] == pytest.approx([ratio, ratio])


def test_open_and_inconsistent_meshes_withhold_volume() -> None:
    for faces in (TETRA_FACES[:-1], [[0, 1, 2], *TETRA_FACES[1:]]):
        result = measure_mesh_preview(**_params(faces=faces))
        assert result["enclosed_volume_m3"] is None
        assert result["edge_connected_patch_enclosed_volumes_m3"] == [None]
        assert result["enclosed_volume_scale_interval_m3"] is None
        assert result["surface_to_enclosed_volume_ratio_per_m"] is None
        assert result["surface_to_enclosed_volume_ratio_scale_interval_per_m"] is None
        assert result["edge_connected_patch_surface_to_enclosed_volume_ratios_per_m"] == [None]
        assert (
            "enclosed_volume_requires_closed_oriented_nondegenerate_patch"
            in (result["qc_warnings"])
        )


def test_translation_and_inward_winding_preserve_unsigned_volume() -> None:
    shifted = [[v + 100_000_000 for v in point] for point in TETRA_VERTICES]
    result = measure_mesh_preview(
        **_params(vertices=shifted, faces=[list(reversed(face)) for face in TETRA_FACES])
    )
    assert result["enclosed_volume_m3"] == pytest.approx(0.01**3 / 6)


def test_open_patch_does_not_hide_valid_disconnected_patch_volume() -> None:
    vertices = [*TETRA_VERTICES, [3, 0, 0], [4, 0, 0], [3, 1, 0]]
    faces = [*TETRA_FACES, [4, 5, 6]]
    result = measure_mesh_preview(**_params(vertices=vertices, faces=faces))
    assert result["edge_connected_patch_enclosed_volumes_m3"][0] == pytest.approx(0.01**3 / 6)
    assert result["edge_connected_patch_enclosed_volumes_m3"][1] is None
    assert result["enclosed_volume_m3"] is None
    assert result["surface_to_enclosed_volume_ratio_per_m"] is None
    assert result["edge_connected_patch_surface_to_enclosed_volume_ratios_per_m"][0] is not None
    assert result["edge_connected_patch_surface_to_enclosed_volume_ratios_per_m"][1] is None


def test_open_disconnected_patch_preserves_volume_and_topology_qc() -> None:
    vertices = [*TETRA_VERTICES, [3, 0, 0], [4, 0, 0], [3, 1, 0]]
    faces = [*TETRA_FACES, [4, 5, 6]]
    result = measure_mesh_preview(**_params(vertices=vertices, faces=faces))
    warnings = result["qc_warnings"]
    assert "enclosed_volume_requires_closed_oriented_nondegenerate_patch" in warnings
    assert "open_mesh_surface_not_enclosed" in warnings
    assert "disconnected_mesh_patches" in warnings
    assert len(warnings) == len(set(warnings))
    assert result["enclosed_volume_m3"] is None
    assert result["edge_connected_patch_enclosed_volumes_m3"][0] == pytest.approx(0.01**3 / 6)


def test_mesh_patch_euler_counts_are_source_topology_not_genus() -> None:
    for faces, expected_euler in ((TETRA_FACES, 2), (TETRA_FACES[:-1], 1)):
        result = measure_mesh_preview(**_params(faces=faces))
        assert result["edge_connected_patch_vertex_counts"] == [4]
        assert result["edge_connected_patch_edge_counts"] == [6]
        assert result["edge_connected_patch_face_counts"] == [len(faces)]
        assert result["edge_connected_patch_euler_characteristics"] == [expected_euler]
        assert result["measurement_status"] == "caller_supplied_unverified"


def test_vertex_touching_patches_keep_separate_euler_diagnostics() -> None:
    vertices = [*TETRA_VERTICES, [2, 0, 0], [0, 2, 0]]
    faces = [*TETRA_FACES, [0, 4, 5]]
    result = measure_mesh_preview(**_params(vertices=vertices, faces=faces))
    assert result["edge_connected_patch_count"] == 2
    assert result["edge_connected_patch_vertex_counts"] == [4, 3]
    assert result["edge_connected_patch_edge_counts"] == [6, 3]
    assert result["edge_connected_patch_euler_characteristics"] == [2, 1]
    assert result["enclosed_volume_m3"] is None


def test_missing_scale_uncertainty_does_not_invent_bounds() -> None:
    result = measure_mesh_preview(**_params(uncertainty=None))
    assert result["enclosed_volume_m3"] == pytest.approx(0.01**3 / 6)
    assert result["enclosed_volume_scale_interval_m3"] is None
    assert result["edge_connected_patch_enclosed_volume_scale_intervals_m3"] is None


@pytest.mark.parametrize("faces", [TETRA_FACES, TETRA_FACES[:-1]], ids=["closed", "open"])
def test_standalone_and_persisted_workflow_volume_parity(
    client: TestClient, faces: list[list[int]]
) -> None:
    project_id = str(create_project(client, "Mesh volume parity")["id"])
    params = _params(faces=faces)
    params.update(
        specimen_id="swiftia-001",
        observation_id="survey-2026-10-24-001",
        observed_at_utc="2026-10-24T10:00:00-04:00",
    )
    base = f"/api/v1/projects/{project_id}"
    standalone = client.post(f"{base}/spatial/mesh-preview", json=params)
    assert standalone.status_code == 200, standalone.text
    graph = {
        "graph_id": "mesh-enclosed-volume-v14",
        "name": "Provisional enclosed volume",
        "nodes": [
            {"node_id": "p", "node_type": "project_source"},
            {"node_id": "m", "node_type": "mesh_surface_preview", "parameters": params},
        ],
        "edges": [
            {
                "edge_id": "e",
                "source_node_id": "p",
                "source_port_id": "project",
                "target_node_id": "m",
                "target_port_id": "project",
            }
        ],
    }
    saved = client.post(f"{base}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    run = client.post(f"{base}/workflow-runs", json={"graph_record_id": saved.json()["id"]})
    assert run.status_code == 202, run.text
    app = cast(FastAPI, client.app)
    assert process_workflow_run_job(
        app.state.settings, app.state.session_factory, str(run.json()["job_id"])
    )
    detail = client.get(f"/api/v1/workflow-runs/{run.json()['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["run"]["status"] == "succeeded"
    artifact = next(
        item["payload_json"]
        for item in detail.json()["artifacts"]
        if item["data_type"] == "mesh_measurement_preview"
    )
    for key in (
        "enclosed_volume_m3",
        "edge_connected_patch_enclosed_volumes_m3",
        "enclosed_volume_scale_interval_m3",
        "edge_connected_patch_enclosed_volume_scale_intervals_m3",
        "enclosed_volume_is_provisional",
        "surface_to_enclosed_volume_ratio_per_m",
        "surface_to_enclosed_volume_ratio_scale_interval_per_m",
        "edge_connected_patch_surface_to_enclosed_volume_ratios_per_m",
        "edge_connected_patch_surface_to_enclosed_volume_ratio_scale_intervals_per_m",
        "edge_connected_patch_vertex_counts",
        "edge_connected_patch_edge_counts",
        "edge_connected_patch_euler_characteristics",
        "qc_warnings",
    ):
        assert artifact[key] == standalone.json()[key]
    assert artifact["measurement_status"] == "caller_supplied_unverified"
    assert artifact["provenance"]["calibration_verified"] is False
    assert artifact["provenance"] == standalone.json()["provenance"]
    assert artifact["provenance"]["specimen_id"] == "swiftia-001"
    assert artifact["provenance"]["observation_id"] == "survey-2026-10-24-001"
    assert artifact["provenance"]["observed_at_utc"] == "2026-10-24T14:00:00Z"
    assert artifact["provenance"]["specimen_identity_verified"] is False
    assert artifact["provenance"]["observation_metadata_verified"] is False
    if len(faces) == 3:
        assert artifact["enclosed_volume_m3"] is None
        assert (
            "enclosed_volume_requires_closed_oriented_nondegenerate_patch"
            in artifact["qc_warnings"]
        )


def test_mesh_observation_metadata_rejects_naive_time_and_invalid_identity(
    client: TestClient,
) -> None:
    project_id = str(create_project(client, "Mesh observation metadata")["id"])
    endpoint = f"/api/v1/projects/{project_id}/spatial/mesh-preview"
    for invalid in (
        {"observed_at_utc": "2026-10-24T14:00:00"},
        {"specimen_id": "   "},
    ):
        response = client.post(endpoint, json={**_params(), **invalid})
        assert response.status_code == 422, response.text


def test_nonzero_volume_lost_to_float_cancellation_replays_saved_graph(
    client: TestClient,
) -> None:
    """Exact source-float orientation recovers finite volume, never identity."""
    # Each small transverse offset is one binary64 ULP at 1e8. Summed
    # floating-point face determinants cancel to zero, but the volume is real.
    vertices = [
        [0.0, 0.0, 0.0],
        [-1e8, -1e8, 1e8],
        [-100000000.00000001, -1e8, 1e8],
        [-1e8, -99999999.99999999, 1e8],
    ]
    expected_volume = 1e8 * (2.0**-26) ** 2 / 6
    expected_faces = TETRA_FACES
    signed = signed_enclosed_volume_mesh_units(
        [tuple(vertex) for vertex in vertices], expected_faces
    )
    assert signed == pytest.approx(-expected_volume, rel=1e-12, abs=0)
    inward = signed_enclosed_volume_mesh_units(
        [tuple(vertex) for vertex in vertices],
        [list(reversed(face)) for face in expected_faces],
    )
    assert inward == pytest.approx(expected_volume, rel=1e-12, abs=0)
    # Select each of the four *distinct vertex origins*. Cyclically rotating
    # a triangle preserves its winding but changes the first-face origin.
    for source_origin in range(len(vertices)):
        for reversed_winding in (False, True):
            ordered_faces = [
                list(reversed(face)) if reversed_winding else list(face)
                for face in expected_faces
            ]
            root_face_index = next(
                index for index, face in enumerate(ordered_faces) if source_origin in face
            )
            first_face = ordered_faces.pop(root_face_index)
            first_offset = first_face.index(source_origin)
            first_face = first_face[first_offset:] + first_face[:first_offset]
            oriented_faces = [first_face, *ordered_faces]
            expected_signed = expected_volume if reversed_winding else -expected_volume
            assert signed_enclosed_volume_mesh_units(
                [tuple(vertex) for vertex in vertices], oriented_faces
            ) == pytest.approx(expected_signed, rel=1e-12, abs=0)
    # Exactly planar, nondegenerate coordinates must not invent an enclosed volume.
    assert (
        signed_enclosed_volume_mesh_units(
            [
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (0.0, 1.0, 0.0),
                (1.0, 1.0, 0.0),
            ],
            expected_faces,
        )
        == 0.0
    )

    # This winding previously produced a nonzero but incorrect floating
    # residual; persist and replay it through the actual API/workflow paths.
    parameters = _params(
        vertices=vertices, faces=[list(reversed(face)) for face in expected_faces]
    )
    parameters["meters_per_unit"] = 1.0
    direct = measure_mesh_preview(**parameters)
    assert direct["enclosed_volume_m3"] == pytest.approx(expected_volume, rel=1e-12, abs=0)
    assert direct["edge_connected_patch_enclosed_volumes_m3"] == pytest.approx(
        [expected_volume], rel=1e-12, abs=0
    )
    assert "enclosed_volume_zero_or_underflow" not in direct["qc_warnings"]
    assert direct["measurement_status"] == "caller_supplied_unverified"
    assert direct["provenance"]["calibration_verified"] is False

    project_id = str(create_project(client, "Cancellation-stable volume QC")["id"])
    base = f"/api/v1/projects/{project_id}"
    request = {
        **parameters,
        "specimen_id": "cancellation-synthetic-unverified",
        "observation_id": "synthetic-not-field-validation",
    }
    standalone = client.post(f"{base}/spatial/mesh-preview", json=request)
    assert standalone.status_code == 200, standalone.text
    payload = standalone.json()
    assert payload["enclosed_volume_m3"] == pytest.approx(expected_volume, rel=1e-12, abs=0)
    assert payload["provenance"]["specimen_identity_verified"] is False

    graph = {
        "graph_id": "mesh-nonzero-volume-cancellation-v14",
        "name": "Finite source volume cancellation regression",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "mesh",
                "node_type": "mesh_surface_preview",
                "parameters": request,
            },
        ],
        "edges": [
            {
                "edge_id": "project-mesh",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "mesh",
                "target_port_id": "project",
            }
        ],
    }
    saved = client.post(f"{base}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    app = cast(FastAPI, client.app)
    hashes: list[str] = []
    for _ in range(2):
        run = client.post(f"{base}/workflow-runs", json={"graph_record_id": saved.json()["id"]})
        assert run.status_code == 202, run.text
        assert process_workflow_run_job(
            app.state.settings, app.state.session_factory, str(run.json()["job_id"])
        )
        detail = client.get(f"/api/v1/workflow-runs/{run.json()['id']}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["run"]["status"] == "succeeded"
        artifacts = [
            artifact
            for artifact in detail.json()["artifacts"]
            if artifact["data_type"] == "mesh_measurement_preview"
        ]
        assert len(artifacts) == 1
        assert artifacts[0]["payload_json"] == payload
        hashes.append(artifacts[0]["payload_sha256"])
    assert len(hashes[0]) == 64
    assert hashes[0] == hashes[1]


@pytest.mark.parametrize("reverse_winding", [False, True])
def test_unrepresentable_positive_volume_fails_standalone_and_saved_graph(
    client: TestClient, reverse_winding: bool
) -> None:
    """Do not publish a false zero for closed volume below binary64 range."""
    edge = 1e-110
    exact_volume = Fraction(edge) ** 3 / 6
    assert exact_volume > 0
    assert float(exact_volume) == 0.0
    vertices = [
        [0.0, 0.0, 0.0],
        [edge, 0.0, 0.0],
        [0.0, edge, 0.0],
        [0.0, 0.0, edge],
    ]
    faces = [list(reversed(face)) for face in TETRA_FACES] if reverse_winding else TETRA_FACES
    with pytest.raises(ValueError, match="volume underflowed numeric precision"):
        signed_enclosed_volume_mesh_units([tuple(vertex) for vertex in vertices], faces)

    # A truly zero-volume source must still be allowed through the direct kernel.
    planar = [
        (0.0, 0.0, 0.0),
        (edge, 0.0, 0.0),
        (0.0, edge, 0.0),
        (edge, edge, 0.0),
    ]
    assert signed_enclosed_volume_mesh_units(planar, faces) == 0.0
    representable_edge = 1e-100
    representable = [
        (0.0, 0.0, 0.0),
        (representable_edge, 0.0, 0.0),
        (0.0, representable_edge, 0.0),
        (0.0, 0.0, representable_edge),
    ]
    assert abs(signed_enclosed_volume_mesh_units(representable, faces)) == pytest.approx(
        float(Fraction(representable_edge) ** 3 / 6), rel=1e-12, abs=0
    )

    project_id = str(create_project(client, "Subnormal volume integrity")["id"])
    base = f"/api/v1/projects/{project_id}"
    params = _params(vertices=vertices, faces=faces)
    params["meters_per_unit"] = 1.0
    params["specimen_id"] = "synthetic-unverified-volume-limit"
    response = client.post(f"{base}/spatial/mesh-preview", json=params)
    assert response.status_code == 400, response.text
    assert "volume underflowed numeric precision" in response.text

    graph = {
        "graph_id": "mesh-volume-underflow-integrity-v14",
        "name": "Reject unrepresentable positive source volume",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "mesh", "node_type": "mesh_surface_preview", "parameters": params},
        ],
        "edges": [
            {
                "edge_id": "project-mesh",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "mesh",
                "target_port_id": "project",
            }
        ],
    }
    saved = client.post(f"{base}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    app = cast(FastAPI, client.app)
    for _ in range(2):
        run = client.post(f"{base}/workflow-runs", json={"graph_record_id": saved.json()["id"]})
        assert run.status_code == 202, run.text
        assert not process_workflow_run_job(
            app.state.settings, app.state.session_factory, str(run.json()["job_id"])
        )
        detail = client.get(f"/api/v1/workflow-runs/{run.json()['id']}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["run"]["status"] == "failed"
        assert not any(
            artifact["data_type"] == "mesh_measurement_preview"
            for artifact in detail.json()["artifacts"]
        )


@pytest.mark.parametrize("reverse_winding", [False, True])
def test_representable_subnormal_volume_replays_saved_graph(
    client: TestClient, reverse_winding: bool
) -> None:
    """Keep finite tiny volumes measurable without asserting biological validity."""
    edge = 1e-103
    vertices = [
        [0.0, 0.0, 0.0],
        [edge, 0.0, 0.0],
        [0.0, edge, 0.0],
        [0.0, 0.0, edge],
    ]
    faces = [list(reversed(face)) for face in TETRA_FACES] if reverse_winding else TETRA_FACES
    expected_volume = float(Fraction(edge) ** 3 / 6)
    assert 0 < expected_volume < float.fromhex("0x1.0p-1022")
    assert abs(
        signed_enclosed_volume_mesh_units([tuple(vertex) for vertex in vertices], faces)
    ) == pytest.approx(expected_volume, rel=1e-12, abs=0)

    project_id = str(create_project(client, "Representable subnormal volume QC")["id"])
    base = f"/api/v1/projects/{project_id}"
    parameters = _params(vertices=vertices, faces=faces)
    parameters["meters_per_unit"] = 1.0
    parameters["specimen_id"] = "synthetic-subnormal-volume-unverified"
    standalone = client.post(f"{base}/spatial/mesh-preview", json=parameters)
    assert standalone.status_code == 200, standalone.text
    payload = standalone.json()
    assert payload["enclosed_volume_m3"] == pytest.approx(expected_volume, rel=1e-12, abs=0)
    assert payload["edge_connected_patch_enclosed_volumes_m3"] == pytest.approx(
        [expected_volume], rel=1e-12, abs=0
    )
    assert payload["enclosed_volume_scale_interval_m3"] is not None
    assert "enclosed_volume_zero_or_underflow" not in payload["qc_warnings"]
    assert payload["measurement_status"] == "caller_supplied_unverified"
    assert payload["enclosed_volume_is_provisional"] is True
    assert payload["provenance"]["calibration_verified"] is False
    assert payload["provenance"]["specimen_identity_verified"] is False

    graph = {
        "graph_id": "mesh-representable-subnormal-volume-v14",
        "name": "Representable tiny provisional enclosed volume",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "mesh",
                "node_type": "mesh_surface_preview",
                "parameters": parameters,
            },
        ],
        "edges": [
            {
                "edge_id": "project-mesh",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "mesh",
                "target_port_id": "project",
            }
        ],
    }
    saved = client.post(f"{base}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    app = cast(FastAPI, client.app)
    hashes: list[str] = []
    for _ in range(2):
        run = client.post(f"{base}/workflow-runs", json={"graph_record_id": saved.json()["id"]})
        assert run.status_code == 202, run.text
        assert process_workflow_run_job(
            app.state.settings, app.state.session_factory, str(run.json()["job_id"])
        )
        detail = client.get(f"/api/v1/workflow-runs/{run.json()['id']}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["run"]["status"] == "succeeded"
        artifacts = [
            item
            for item in detail.json()["artifacts"]
            if item["data_type"] == "mesh_measurement_preview"
        ]
        assert len(artifacts) == 1
        assert artifacts[0]["payload_json"] == payload
        hashes.append(artifacts[0]["payload_sha256"])
    assert len(hashes[0]) == 64
    assert hashes[0] == hashes[1]


@pytest.mark.parametrize("reverse_winding", [False, True])
def test_source_volume_below_binary64_recovers_after_large_calibration(
    client: TestClient, reverse_winding: bool
) -> None:
    """A provisional scale can recover a real but unrepresentable source volume."""
    edge = 1e-110
    scale = 1_000_000.0
    vertices = [
        [0.0, 0.0, 0.0],
        [edge, 0.0, 0.0],
        [0.0, edge, 0.0],
        [0.0, 0.0, edge],
    ]
    faces = [list(reversed(face)) for face in TETRA_FACES] if reverse_winding else TETRA_FACES
    with pytest.raises(ValueError, match="volume underflowed numeric precision"):
        signed_enclosed_volume_mesh_units([tuple(vertex) for vertex in vertices], faces)

    expected_volume = float(Fraction(edge) ** 3 * 1_000_000**3 / 6)
    assert expected_volume > 0
    direct_params = _params(vertices=vertices, faces=faces)
    direct_params["meters_per_unit"] = scale
    direct = measure_mesh_preview(**direct_params)
    assert direct["enclosed_volume_m3"] == pytest.approx(expected_volume, rel=1e-8, abs=0)
    params = {**direct_params, "specimen_id": "synthetic-recovered-volume-unverified"}

    project_id = str(create_project(client, "Recovered calibrated volume QC")["id"])
    base = f"/api/v1/projects/{project_id}"
    standalone = client.post(f"{base}/spatial/mesh-preview", json=params)
    assert standalone.status_code == 200, standalone.text
    payload = standalone.json()
    assert payload["enclosed_volume_m3"] == pytest.approx(expected_volume, rel=1e-8, abs=0)
    assert payload["edge_connected_patch_enclosed_volumes_m3"] == pytest.approx(
        [expected_volume], rel=1e-8, abs=0
    )
    assert "enclosed_volume_source_unit_numeric_recovery" in payload["qc_warnings"]
    assert "enclosed_volume_numeric_overflow" not in payload["qc_warnings"]
    assert payload["enclosed_volume_scale_interval_m3"] is not None
    assert payload["measurement_status"] == "caller_supplied_unverified"
    assert payload["provenance"]["calibration_verified"] is False
    assert payload["provenance"]["specimen_identity_verified"] is False

    graph = {
        "graph_id": "mesh-source-volume-calibration-recovery-v14",
        "name": "Provisional source-volume underflow recovery",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "mesh", "node_type": "mesh_surface_preview", "parameters": params},
        ],
        "edges": [
            {
                "edge_id": "project-mesh",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "mesh",
                "target_port_id": "project",
            }
        ],
    }
    saved = client.post(f"{base}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    app = cast(FastAPI, client.app)
    hashes: list[str] = []
    for _ in range(2):
        run = client.post(f"{base}/workflow-runs", json={"graph_record_id": saved.json()["id"]})
        assert run.status_code == 202, run.text
        assert process_workflow_run_job(
            app.state.settings, app.state.session_factory, str(run.json()["job_id"])
        )
        detail = client.get(f"/api/v1/workflow-runs/{run.json()['id']}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["run"]["status"] == "succeeded"
        artifacts = [
            item
            for item in detail.json()["artifacts"]
            if item["data_type"] == "mesh_measurement_preview"
        ]
        assert len(artifacts) == 1
        assert artifacts[0]["payload_json"] == payload
        hashes.append(artifacts[0]["payload_sha256"])
    assert len(hashes[0]) == 64
    assert hashes[0] == hashes[1]


@pytest.mark.parametrize(
    ("offsets", "axis_signs"),
    [
        ((100_000_000.0,) * 3, (1, 1, 1)),
        ((-100_000_000.0,) * 3, (-1, 1, 1)),
        ((100_000_000.0, -100_000_000.0, 100_000_000.0), (-1, 1, -1)),
    ],
)
@pytest.mark.parametrize("reverse_winding", [False, True])
def test_large_source_translation_preserves_volume_and_saved_workflow(
    client: TestClient,
    reverse_winding: bool,
    offsets: tuple[float, float, float],
    axis_signs: tuple[int, int, int],
) -> None:
    """Signed source origins and axis reflections must not invent volume changes."""
    vertices = [
        [offsets[axis] + axis_signs[axis] * point[axis] for axis in range(3)]
        for point in TETRA_VERTICES
    ]
    faces = [list(reversed(face)) for face in TETRA_FACES] if reverse_winding else TETRA_FACES
    signed = signed_enclosed_volume_mesh_units([tuple(vertex) for vertex in vertices], faces)
    handedness = axis_signs[0] * axis_signs[1] * axis_signs[2]
    assert signed == pytest.approx(handedness * (-1 if reverse_winding else 1) / 6)

    parameters = _params(vertices=vertices, faces=faces)
    expected_volume_m3 = 0.01**3 / 6
    direct = measure_mesh_preview(**parameters)
    assert direct["enclosed_volume_m3"] == pytest.approx(expected_volume_m3)
    assert direct["edge_connected_patch_enclosed_volumes_m3"] == pytest.approx([expected_volume_m3])
    assert direct["axis_aligned_dimensions_m"] == pytest.approx([0.01, 0.01, 0.01])
    assert direct["enclosed_volume_scale_interval_m3"] == pytest.approx(
        [expected_volume_m3 * 0.9**3, expected_volume_m3 * 1.1**3]
    )

    parameters["specimen_id"] = "synthetic-translated-unverified"
    project_id = str(create_project(client, "Source translation volume integrity")["id"])
    base = f"/api/v1/projects/{project_id}"
    response = client.post(f"{base}/spatial/mesh-preview", json=parameters)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["enclosed_volume_m3"] == pytest.approx(expected_volume_m3)
    assert payload["axis_aligned_dimensions_m"] == pytest.approx([0.01, 0.01, 0.01])
    assert payload["enclosed_volume_scale_interval_m3"] == pytest.approx(
        [expected_volume_m3 * 0.9**3, expected_volume_m3 * 1.1**3]
    )
    assert "enclosed_volume_zero_or_underflow" not in payload["qc_warnings"]
    assert payload["measurement_status"] == "caller_supplied_unverified"
    assert payload["provenance"]["calibration_verified"] is False
    assert payload["provenance"]["specimen_identity_verified"] is False

    graph = {
        "graph_id": f"mesh-large-origin-volume-{reverse_winding}",
        "name": "Unverified translated source volume",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "mesh",
                "node_type": "mesh_surface_preview",
                "parameters": parameters,
            },
        ],
        "edges": [
            {
                "edge_id": "project-mesh",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "mesh",
                "target_port_id": "project",
            }
        ],
    }
    saved = client.post(f"{base}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    app = cast(FastAPI, client.app)
    hashes: list[str] = []
    for _ in range(2):
        run = client.post(f"{base}/workflow-runs", json={"graph_record_id": saved.json()["id"]})
        assert run.status_code == 202, run.text
        assert process_workflow_run_job(
            app.state.settings, app.state.session_factory, str(run.json()["job_id"])
        )
        detail = client.get(f"/api/v1/workflow-runs/{run.json()['id']}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["run"]["status"] == "succeeded"
        artifacts = [
            item
            for item in detail.json()["artifacts"]
            if item["data_type"] == "mesh_measurement_preview"
        ]
        assert len(artifacts) == 1
        assert artifacts[0]["payload_json"] == payload
        hashes.append(artifacts[0]["payload_sha256"])
    assert len(hashes[0]) == 64
    assert hashes[0] == hashes[1]
