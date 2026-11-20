"""Strict OBJ scalar grammar and persisted scientific workflow parity."""

from __future__ import annotations

from decimal import Decimal
from json import dumps
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.spatial_mesh_obj_v14 import parse_obj_triangles
from reefvision.tests.test_annotations import create_project

OBJ = "v 0 0 0\nv 2 0 0\nv 0 3 0\nf 1 2 3\n"
PARAMS = {
    "meters_per_unit": 0.01,
    "calibration_method": "ruler",
    "calibration_evidence": "Unverified ruler scale",
    "relative_scale_uncertainty": 0.05,
}


def _source_with_scalar(line: str) -> str:
    if line.startswith("v "):
        return OBJ.replace("v 0 0 0\n", line + "\n", 1)
    return OBJ.replace("f 1 2 3\n", line + "\nf 1 2 3\n")


def _run_saved(client: TestClient, project_id: str, obj_text: str) -> dict:
    base = f"/api/v1/projects/{project_id}"
    graph = {
        "graph_id": "obj-strict-scalars-v14",
        "name": "Provisional OBJ measurement with source integrity",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "mesh",
                "node_type": "mesh_surface_preview",
                "parameters": {**PARAMS, "obj_text": obj_text},
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
    run = client.post(f"{base}/workflow-runs", json={"graph_record_id": saved.json()["id"]})
    assert run.status_code == 202, run.text
    app = cast(FastAPI, client.app)
    process_workflow_run_job(
        app.state.settings, app.state.session_factory, str(run.json()["job_id"])
    )
    detail = client.get(f"/api/v1/workflow-runs/{run.json()['id']}")
    assert detail.status_code == 200, detail.text
    return detail.json()


@pytest.mark.parametrize(
    "line",
    [
        "v 1_0 0 0",
        "v 1e3_0 0 0",
        "v 1e-9999 0 0",
        "v 1e9999 0 0",
        "v \uff12 0 0",
        "v 0 0 0 1_0",
        "v 0 0 0 1e-9999",
        "v 1e-200 0 0 1e200",
        "v -1e-200 0 0 1e200",
        "v 0 0 0 1 0.1 1e-9999 0.2",
        "vt 1_0 0",
        "vt 1e-9999 0",
        "vn 0 1e-9999 0",
        "vn 0 1_0 0",
    ],
)
def test_invalid_obj_scalars_rejected_before_measurement(line: str) -> None:
    with pytest.raises(ValueError):
        parse_obj_triangles(_source_with_scalar(line))


@pytest.mark.parametrize(
    "line",
    [
        "v 1_0 0 0",
        "v 1e-9999 0 0",
        "v 0 0 0 1_0",
        "v 1e-200 0 0 1e200",
        "v 0 0 0 1 0.1 1e-9999 0.2",
        "vt 1e-9999 0",
        "vn 0 1_0 0",
    ],
)
def test_invalid_obj_source_rejected_by_api_and_saved_workflow(
    client: TestClient, line: str
) -> None:
    project_id = str(create_project(client, "OBJ numeric rejection")["id"])
    obj_text = _source_with_scalar(line)
    standalone = client.post(
        f"/api/v1/projects/{project_id}/spatial/mesh-preview",
        json={**PARAMS, "obj_text": obj_text},
    )
    assert standalone.status_code in (400, 422), standalone.text
    detail = _run_saved(client, project_id, obj_text)
    assert detail["run"]["status"] == "failed"
    assert not any(item["data_type"] == "mesh_measurement_preview" for item in detail["artifacts"])


@pytest.mark.parametrize(
    "separator",
    [
        "\x00",
        "\x0b",
        "\x0c",
        "\x1b",
        "\x7f",
        "\x85",
        "\xa0",
        "\u2003",
        "\u2028",
        "\ufeff",
    ],
)
def test_obj_bad_separators_rejected_before_parsing(separator: str) -> None:
    obj_text = OBJ.replace("v 0 0 0\n", f"v 0{separator}0 0\n", 1)
    with pytest.raises(ValueError, match="unsupported control"):
        parse_obj_triangles(obj_text)


@pytest.mark.parametrize("separator", ["\x00", "\xa0", "\u2028", "\ufeff"])
def test_obj_control_separators_fail_standalone_and_saved_workflow(
    client: TestClient, separator: str
) -> None:
    project_id = str(create_project(client, "OBJ separator integrity")["id"])
    obj_text = OBJ.replace("v 0 0 0\n", f"v 0{separator}0 0\n", 1)
    standalone = client.post(
        f"/api/v1/projects/{project_id}/spatial/mesh-preview",
        json={**PARAMS, "obj_text": obj_text},
    )
    assert standalone.status_code in (400, 422), standalone.text
    detail = _run_saved(client, project_id, obj_text)
    assert detail["run"]["status"] == "failed"
    assert not any(item["data_type"] == "mesh_measurement_preview" for item in detail["artifacts"])


def test_obj_ascii_tabs_crlf_and_unicode_comment_replay_identically(
    client: TestClient,
) -> None:
    valid = (
        "# Unicode comment: caf\u00e9\r\nv\t0\t0\t0\r\nv\t2\t0\t0\r\nv\t0\t3\t0\r\nf\t1\t2\t3\r\n"
    )
    vertices, faces = parse_obj_triangles(valid)
    assert vertices == [[0.0, 0.0, 0.0], [2.0, 0.0, 0.0], [0.0, 3.0, 0.0]]
    assert faces == [[0, 1, 2]]
    project_id = str(create_project(client, "OBJ ASCII separator parity")["id"])
    standalone = client.post(
        f"/api/v1/projects/{project_id}/spatial/mesh-preview",
        json={**PARAMS, "obj_text": valid},
    )
    assert standalone.status_code == 200, standalone.text
    expected = standalone.json()
    assert expected["provenance"]["calibration_verified"] is False
    detail = _run_saved(client, project_id, valid)
    assert detail["run"]["status"] == "succeeded"
    artifact = next(
        item for item in detail["artifacts"] if item["data_type"] == "mesh_measurement_preview"
    )
    assert artifact["payload_json"] == expected


def test_valid_obj_decimals_and_true_zero_replay_identically(client: TestClient) -> None:
    valid = (
        "v 0e-9999 0 0 2\n"
        "v +4.0 0 0 2\n"
        "v 0 6e0 0 2\n"
        "vt .5 0e-9999\n"
        "vn 0 0 +1.0\n"
        "f 1/1/1 2/1/1 3/1/1\n"
    )
    vertices, faces = parse_obj_triangles(valid)
    assert vertices == [[0.0, 0.0, 0.0], [2.0, 0.0, 0.0], [0.0, 3.0, 0.0]]
    assert faces == [[0, 1, 2]]
    project_id = str(create_project(client, "OBJ numeric parity")["id"])
    standalone = client.post(
        f"/api/v1/projects/{project_id}/spatial/mesh-preview",
        json={**PARAMS, "obj_text": valid},
    )
    assert standalone.status_code == 200, standalone.text
    expected = standalone.json()
    assert expected["surface_area_m2"] == pytest.approx(0.0003)
    assert expected["measurement_status"] == "caller_supplied_unverified"
    assert expected["provenance"]["calibration_verified"] is False
    detail = _run_saved(client, project_id, valid)
    assert detail["run"]["status"] == "succeeded"
    artifact = next(
        item for item in detail["artifacts"] if item["data_type"] == "mesh_measurement_preview"
    )
    assert artifact["payload_json"] == expected
    assert len(artifact["payload_sha256"]) == 64


def test_representable_weighted_coordinate_preserves_standalone_workflow_parity(
    client: TestClient,
) -> None:
    valid = "v 1e-200 0 0 1e100\nv 2 0 0\nv 0 3 0\nf 1 2 3\n"
    vertices, faces = parse_obj_triangles(valid)
    assert vertices[0][0] == pytest.approx(1e-300, rel=1e-12, abs=0)
    assert faces == [[0, 1, 2]]
    project_id = str(create_project(client, "OBJ weighted coordinate parity")["id"])
    standalone = client.post(
        f"/api/v1/projects/{project_id}/spatial/mesh-preview",
        json={**PARAMS, "obj_text": valid},
    )
    assert standalone.status_code == 200, standalone.text
    expected = standalone.json()
    assert expected["measurement_status"] == "caller_supplied_unverified"
    assert expected["provenance"]["calibration_verified"] is False
    detail = _run_saved(client, project_id, valid)
    assert detail["run"]["status"] == "succeeded"
    artifact = next(
        item for item in detail["artifacts"] if item["data_type"] == "mesh_measurement_preview"
    )
    assert artifact["payload_json"] == expected
    assert len(artifact["payload_sha256"]) == 64


def _precision_collision_obj(axis: int, *, weighted: bool, sign: int) -> str:
    rows = [["0", "0", "0"], ["2", "0", "0"], ["0", "3", "0"]]
    rows[0][axis] = "1" if sign > 0 else "-1"
    rows[1][axis] = "1.00000000000000001" if sign > 0 else "-1.00000000000000001"
    if weighted:
        # Decimal multiplication preserves the source difference before OBJ
        # homogeneous division, whereas binary64 would erase it.
        vertices = [
            "v " + " ".join(str(Decimal(value) * 2) for value in row) + " 2" for row in rows
        ]
    else:
        vertices = ["v " + " ".join(row) for row in rows]
    return "\n".join([*vertices, "f 1 2 3", ""])


@pytest.mark.parametrize("axis", [0, 1, 2], ids=["x", "y", "z"])
@pytest.mark.parametrize("weighted", [False, True], ids=["plain", "homogeneous"])
@pytest.mark.parametrize("sign", [1, -1], ids=["positive", "negative"])
def test_distinct_obj_source_decimals_fail_standalone_and_saved_workflow(
    client: TestClient, axis: int, weighted: bool, sign: int
) -> None:
    invalid = _precision_collision_obj(axis, weighted=weighted, sign=sign)
    with pytest.raises(ValueError, match="distinct source coordinates collapse"):
        parse_obj_triangles(invalid)

    project_id = str(create_project(client, "OBJ source-decimal precision integrity")["id"])
    standalone = client.post(
        f"/api/v1/projects/{project_id}/spatial/mesh-preview",
        json={**PARAMS, "obj_text": invalid},
    )
    assert standalone.status_code == 400, standalone.text
    assert "distinct source coordinates collapse" in standalone.json()["detail"]

    detail = _run_saved(client, project_id, invalid)
    assert detail["run"]["status"] == "failed"
    assert not any(
        artifact["data_type"] == "mesh_measurement_preview" for artifact in detail["artifacts"]
    )


@pytest.mark.parametrize(
    "valid",
    [
        "v 1 0 0\nv +1e0 2 0\nv 0 0 3\nf 1 2 3\n",
        "v 1 0 0\nv 2 4 0 2\nv 0 0 3\nf 1 2 3\n",
    ],
    ids=["equivalent-decimal-spellings", "equivalent-homogeneous-coordinates"],
)
def test_equivalent_obj_sources_preserve_two_replays_and_provisional_provenance(
    client: TestClient, valid: str
) -> None:
    vertices, faces = parse_obj_triangles(valid)
    assert vertices == [[1.0, 0.0, 0.0], [1.0, 2.0, 0.0], [0.0, 0.0, 3.0]]
    assert faces == [[0, 1, 2]]
    project_id = str(create_project(client, "OBJ equivalent exact source coordinates")["id"])
    base = f"/api/v1/projects/{project_id}"
    standalone = client.post(f"{base}/spatial/mesh-preview", json={**PARAMS, "obj_text": valid})
    assert standalone.status_code == 200, standalone.text
    expected = standalone.json()
    assert expected["measurement_status"] == "caller_supplied_unverified"
    assert expected["provenance"]["calibration_verified"] is False
    assert expected["provenance"]["coordinate_registration_verified"] is False

    graph = {
        "graph_id": "obj-source-decimal-replay-v14",
        "name": "Reproducible provisional OBJ source precision",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "mesh",
                "node_type": "mesh_surface_preview",
                "parameters": {**PARAMS, "obj_text": valid},
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
        artifact = next(
            item
            for item in detail.json()["artifacts"]
            if item["data_type"] == "mesh_measurement_preview"
        )
        assert artifact["payload_json"] == expected
        hashes.append(artifact["payload_sha256"])
    assert len(hashes[0]) == 64
    assert hashes[0] == hashes[1]


@pytest.mark.parametrize(
    "directive",
    [
        "p 1",
        "l 1 2",
        "vp 0 0 0",
        "cstype bspline",
        "curv 0 1 1 2 3",
        "surf 0 1 0 1 1 2 3",
        "call other.obj",
    ],
)
def test_obj_unsupported_geometry_cannot_be_silently_dropped(directive: str) -> None:
    # A face-only preview of a mixed primitive/free-form reconstruction would
    # be an incomplete scientific surface even when its triangles are sound.
    obj_text = OBJ.replace("f 1 2 3\n", f"{directive}\nf 1 2 3\n")
    with pytest.raises(ValueError, match="unsupported geometry directive"):
        parse_obj_triangles(obj_text)


@pytest.mark.parametrize("directive", ["l 1 2", "surf 0 1 0 1 1 2 3"])
def test_unsupported_obj_geometry_rejected_by_api_and_saved_workflow(
    client: TestClient, directive: str
) -> None:
    project_id = str(create_project(client, "Mixed-primitive OBJ source rejection")["id"])
    obj_text = OBJ.replace("f 1 2 3\n", f"{directive}\nf 1 2 3\n")
    standalone = client.post(
        f"/api/v1/projects/{project_id}/spatial/mesh-preview",
        json={**PARAMS, "obj_text": obj_text},
    )
    assert standalone.status_code in (400, 422), standalone.text
    detail = _run_saved(client, project_id, obj_text)
    assert detail["run"]["status"] == "failed"
    assert not any(item["data_type"] == "mesh_measurement_preview" for item in detail["artifacts"])


@pytest.mark.parametrize(
    "directive",
    [
        "vertex 9 8 7",
        "triangle 1 2 3",
        "custom_surface 1 2 3 4",
    ],
)
@pytest.mark.parametrize("after_faces", [False, True])
def test_unknown_obj_directives_cannot_disappear_from_measurements(
    directive: str, after_faces: bool
) -> None:
    # Both a prefix and a trailing custom geometry record must fail closed.
    # Ignoring them would make the triangular subset appear complete.
    obj_text = (
        OBJ + directive + "\n"
        if after_faces
        else OBJ.replace("f 1 2 3\n", f"{directive}\nf 1 2 3\n")
    )
    with pytest.raises(ValueError, match="unsupported directive"):
        parse_obj_triangles(obj_text)


@pytest.mark.parametrize("directive", ["vertex 9 8 7", "custom_surface 1 2 3 4"])
def test_unknown_obj_directives_fail_standalone_and_persisted_workflow(
    client: TestClient, directive: str
) -> None:
    project_id = str(create_project(client, "Unknown OBJ directive rejection")["id"])
    obj_text = OBJ + directive + "\n"
    standalone = client.post(
        f"/api/v1/projects/{project_id}/spatial/mesh-preview",
        json={**PARAMS, "obj_text": obj_text},
    )
    assert standalone.status_code in (400, 422), standalone.text
    detail = _run_saved(client, project_id, obj_text)
    assert detail["run"]["status"] == "failed"
    assert not any(item["data_type"] == "mesh_measurement_preview" for item in detail["artifacts"])


def test_inert_obj_metadata_keeps_standalone_and_workflow_measurements_identical(
    client: TestClient,
) -> None:
    decorated = (
        "mtllib coral.mtl\n"
        "o coral_fragment\n"
        "g branch_A\n"
        "s off\n"
        "usemtl tissue\n"
        "v 0 0 0\n"
        "v 2 0 0\n"
        "v 0 3 0\n"
        "f 1 2 3\n"
    )
    assert parse_obj_triangles(decorated) == parse_obj_triangles(OBJ)
    project_id = str(create_project(client, "OBJ metadata replay")["id"])
    standalone = client.post(
        f"/api/v1/projects/{project_id}/spatial/mesh-preview",
        json={**PARAMS, "obj_text": decorated},
    )
    assert standalone.status_code == 200, standalone.text
    result = standalone.json()
    assert result["surface_area_m2"] == pytest.approx(0.0003)
    assert result["measurement_status"] == "caller_supplied_unverified"
    assert result["provenance"]["calibration_verified"] is False
    detail = _run_saved(client, project_id, decorated)
    assert detail["run"]["status"] == "succeeded"
    artifact = next(
        item for item in detail["artifacts"] if item["data_type"] == "mesh_measurement_preview"
    )
    assert artifact["payload_json"] == result


@pytest.mark.parametrize(
    "obj_text",
    [
        "# source has malformed \ud800 scalar\n" + OBJ,
        "o coral-\udfff\n" + OBJ,
        OBJ + "# trailing malformed \ud800\n",
    ],
)
def test_unpaired_obj_unicode_surrogates_fail_closed(client: TestClient, obj_text: str) -> None:
    """Escaped invalid UTF-16 cannot become immutable UTF-8 mesh source bytes."""
    with pytest.raises(ValueError, match="unpaired Unicode surrogate"):
        parse_obj_triangles(obj_text)

    project_id = str(create_project(client, "Malformed OBJ Unicode source")["id"])
    # Ensure the invalid JSON string reaches the API as an escaped scalar.
    # Depending on JSON-schema validation it can fail before or during OBJ parsing.
    response = client.post(
        f"/api/v1/projects/{project_id}/spatial/mesh-preview",
        content=dumps({**PARAMS, "obj_text": obj_text}, ensure_ascii=True),
        headers={"content-type": "application/json"},
    )
    assert response.status_code in (400, 422), response.text
    assert "unicode" in response.text.lower()


def test_obj_non_bmp_unicode_comment_remains_supported_in_saved_graph(
    client: TestClient,
) -> None:
    """Valid Unicode labels remain inert; source identity stays provisional."""
    obj_text = "# deepwater coral \U0001f419\n" + OBJ
    assert parse_obj_triangles(obj_text) == parse_obj_triangles(OBJ)
    project_id = str(create_project(client, "OBJ non-BMP metadata")["id"])
    standalone = client.post(
        f"/api/v1/projects/{project_id}/spatial/mesh-preview",
        json={**PARAMS, "obj_text": obj_text},
    )
    assert standalone.status_code == 200, standalone.text
    expected = standalone.json()
    assert expected["provenance"]["calibration_verified"] is False
    assert expected["provenance"]["specimen_identity_verified"] is False
    detail = _run_saved(client, project_id, obj_text)
    assert detail["run"]["status"] == "succeeded"
    artifact = next(
        item for item in detail["artifacts"] if item["data_type"] == "mesh_measurement_preview"
    )
    assert artifact["payload_json"] == expected
