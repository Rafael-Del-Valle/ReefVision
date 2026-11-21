from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFilter
from PIL.PngImagePlugin import PngInfo

from reefvision.config import Settings
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_quality_control import run_quality_control
from reefvision.tests.test_scientific_project_exchange import export_archive, import_archive
from reefvision.tests.test_workflow_connected_branch_preview_1_2 import _run


def upload(client: TestClient, project_id: str, name: str, image: Image.Image) -> str:
    payload = BytesIO()
    metadata = PngInfo()
    metadata.add_text("Fixture", name)
    image.save(payload, format="PNG", pnginfo=metadata)
    response = client.post(
        f"/api/v1/projects/{project_id}/imports/images",
        files={"files": (name, payload.getvalue(), "image/png")},
        data={"relative_paths": name},
    )
    assert response.status_code == 200, response.text
    return response.json()["successful"][0]["image_id"]


def test_acquisition_evidence_detects_degradation_and_preserves_archive(
    client: TestClient, test_settings: Settings
) -> None:
    project_id = create_project(client, "Acquisition controls")["id"]
    target = Image.new("RGB", (64, 64), (30, 30, 30))
    draw = ImageDraw.Draw(target)
    for x in range(2, 62, 8):
        draw.rectangle((x, 1, x + 2, 62), fill=(210, 210, 210))
    focused_id = upload(client, project_id, "focused.png", target)
    duplicate_id = upload(client, project_id, "same-pixels.png", target)
    blurred = target.filter(ImageFilter.GaussianBlur(4))
    upload(client, project_id, "blurred.png", blurred)
    clipped = Image.new("RGB", (32, 60), "white")
    clipped.paste("black", (0, 0, 16, 60))
    upload(client, project_id, "clipped.png", clipped)

    url = f"/api/v1/images/{focused_id}/measurement-calibration"
    calibrated = client.put(
        url,
        json={
            "distance_per_pixel": 0.25,
            "unit": "mm",
            "source": "manual",
        },
    )
    assert calibrated.status_code == 200, calibrated.text

    run = run_quality_control(
        client,
        project_id,
        {
            "rule_categories": ["acquisition"],
            "thresholds": {
                "acquisition": {
                    "min_width_px": 40,
                    "min_height_px": 40,
                    "min_sharpness": 200,
                    "max_clipped_fraction": 0.2,
                    "require_capture_time": True,
                    "require_calibration": True,
                }
            },
        },
    )
    results = run["summary_json"]["acquisition"]
    rows = {row["filename"]: row for row in results["images"]}
    assert results["method"] == "acquisition-luminance-0001"
    assert results["evaluated_image_count"] == 4
    assert rows["focused.png"]["measurements"]["sharpness"] > 2000
    assert rows["blurred.png"]["measurements"]["sharpness"] < 200
    clip = rows["clipped.png"]["measurements"]
    assert clip["dark_fraction"] == 0.5 and clip["bright_fraction"] == 0.5
    assert rows["focused.png"]["source_sha256"] != rows["same-pixels.png"]["source_sha256"]
    assert (
        rows["focused.png"]["measurements"]["decoded_pixels_sha256"]
        == rows["same-pixels.png"]["measurements"]["decoded_pixels_sha256"]
    )
    findings = client.get(f"/api/v1/quality-control-runs/{run['id']}/issues").json()["items"]
    checks = {item["measured_values_json"]["check"] for item in findings}
    assert {
        "low_detail",
        "dark_clipping",
        "bright_clipping",
        "dimensions",
        "duplicate_pixels",
        "capture_time",
        "calibration_missing",
    } <= checks
    assert all(item["status"] == "open" for item in findings)
    assert client.get(f"/api/v1/images/{duplicate_id}").json()["annotation_status"] == "unannotated"

    original = client.get(f"/api/v1/quality-control-runs/{run['id']}")
    assert original.json()["acquisition_stale_reasons"] == []
    recalibrated = client.put(url, json={"distance_per_pixel": 0.5, "unit": "mm"})
    assert recalibrated.status_code == 200
    stale = client.get(f"/api/v1/quality-control-runs/{run['id']}").json()
    assert stale["acquisition_stale_reasons"] == ["acquisition_metadata_changed"]
    assert stale["summary_json"]["acquisition"] == results

    archived = import_archive(client, export_archive(client, test_settings, project_id))
    assert archived.status_code == 201, archived.text
    mapping = archived.json()["package"]["options_json"]["id_map"]
    copied = client.get(f"/api/v1/quality-control-runs/{mapping[run['id']]}").json()
    assert copied["summary_json"]["acquisition"] == results
    assert copied["acquisition_stale_reasons"] == ["acquisition_metadata_changed"]


def test_acquisition_rejects_inverted_luminance_thresholds(client: TestClient) -> None:
    project_id = create_project(client, "Acquisition thresholds")["id"]
    response = client.post(
        f"/api/v1/projects/{project_id}/quality-control-runs",
        json={
            "rule_categories": ["acquisition"],
            "thresholds": {
                "acquisition": {
                    "dark_luma_max": 25,
                    "bright_luma_min": 12,
                }
            },
        },
    )
    assert response.status_code == 422


def test_saved_acquisition_workflow_matches_standalone_and_replays_after_exchange(
    client: TestClient,
    test_settings: Settings,
) -> None:
    project_id = create_project(client, "Workflow QC")["id"]
    upload(client, project_id, "highlights.png", Image.new("RGB", (60, 44), "white"))
    thresholds = {"min_width_px": 70, "max_clipped_fraction": 0.3}
    standalone = run_quality_control(
        client,
        project_id,
        {"rule_categories": ["acquisition"], "thresholds": {"acquisition": thresholds}},
    )
    graph = {
        "graph_id": "acquisition-study",
        "name": "Acquisition checks",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "qc",
                "node_type": "image_acquisition_quality",
                "parameters": {"thresholds": thresholds},
            },
        ],
        "edges": [
            {
                "edge_id": "project-qc",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "qc",
                "target_port_id": "project",
            }
        ],
    }

    def artifact(detail):
        assert detail["run"]["status"] == "succeeded", detail
        return next(
            row["payload_json"]
            for row in detail["artifacts"]
            if row["data_type"] == "acquisition_quality_result"
        )

    first = artifact(_run(client, project_id, graph))
    assert first["report"] == standalone["summary_json"]["acquisition"]
    assert artifact(_run(client, project_id, graph))["report"] == first["report"]
    archive = import_archive(client, export_archive(client, test_settings, project_id))
    assert archive.status_code == 201, archive.text
    new_project = archive.json()["project_id"]
    replay = artifact(_run(client, new_project, graph))
    assert replay["report"] == first["report"]
    assert replay["quality_control_run_id"] != first["quality_control_run_id"]
