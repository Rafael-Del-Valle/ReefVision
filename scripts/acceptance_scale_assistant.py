"""Validate ReefVision Scale Assistant against independently measured real images.

The caller supplies a JSON manifest plus real ruler, ArUco, ChArUco, or repeated-setup
images. The harness imports each image into an isolated ReefVision project and exercises
the production calibration endpoints. It compares detected scale and optional calibrated
polygon/centerline geometry with independent expected values under explicit tolerances.

Ruler cases must provide the known physical length of one detected interval; ReefVision
is required to keep ``unit_inferred`` false. Marker cases use known printed geometry.
Profile cases may reuse a previously accepted profile only after explicit same-setup
confirmation. Perspective-corrected evidence is accepted only for polygon/centerline
geometry on the marker or board reference plane. Raster masks are intentionally outside
this harness because ReefVision keeps them on scalar calibration unless explicitly
resampled by a future workflow.

This is release validation infrastructure. A PASS requires real independent reference
measurements; synthetic images alone do not establish physical accuracy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient

from reefvision.config import Settings
from reefvision.db.base import Base
from reefvision.main import create_app

SCHEMA_VERSION = "reefvision-scale-assistant-validation-0001"
SUPPORTED_METHODS = {"ruler", "aruco", "charuco", "profile"}
SUPPORTED_UNITS = {"mm", "cm", "m"}


def require(response: Any, status: int) -> dict[str, Any]:
    if response.status_code != status:
        raise RuntimeError(f"API {response.request.method} {response.url}: {response.text}")
    return dict(response.json())


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def finite_number(value: Any, *, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"{name} must be numeric") from exc
    if not math.isfinite(result):
        raise RuntimeError(f"{name} must be finite")
    return result


def positive_number(value: Any, *, name: str) -> float:
    result = finite_number(value, name=name)
    if result <= 0:
        raise RuntimeError(f"{name} must be positive")
    return result


def positive_integer(value: Any, *, name: str) -> int:
    result = positive_number(value, name=name)
    if not float(result).is_integer():
        raise RuntimeError(f"{name} must be a whole number")
    return int(result)


def measurement_error(
    observed: float,
    expected: float,
    *,
    relative_tolerance: float,
    absolute_tolerance: float,
) -> dict[str, Any]:
    absolute_error = abs(observed - expected)
    relative_error = (
        absolute_error / abs(expected) if not math.isclose(expected, 0.0) else math.inf
    )
    within_tolerance = absolute_error <= max(
        absolute_tolerance,
        abs(expected) * relative_tolerance,
    )
    return {
        "observed": observed,
        "expected": expected,
        "absolute_error": absolute_error,
        "relative_error": relative_error,
        "within_tolerance": within_tolerance,
    }


def _points(value: Any, *, name: str, minimum: int) -> list[dict[str, float]]:
    if not isinstance(value, list) or len(value) < minimum:
        raise RuntimeError(f"{name} requires at least {minimum} [x, y] points")
    points: list[dict[str, float]] = []
    for index, raw in enumerate(value):
        if not isinstance(raw, list) or len(raw) != 2:
            raise RuntimeError(f"{name}[{index}] must contain [x, y]")
        x = finite_number(raw[0], name=f"{name}[{index}].x")
        y = finite_number(raw[1], name=f"{name}[{index}].y")
        if x < 0 or y < 0:
            raise RuntimeError(f"{name} points cannot use negative image coordinates")
        points.append({"x": x, "y": y})
    return points


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Scale Assistant manifest could not be read: {path}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        raise RuntimeError(f"Manifest must use schema_version {SCHEMA_VERSION!r}")

    unit = str(payload.get("unit", "")).strip()
    if unit not in SUPPORTED_UNITS:
        raise RuntimeError("Manifest unit must be one of mm, cm, or m")
    tolerance = payload.get("tolerance", {})
    if not isinstance(tolerance, dict):
        raise RuntimeError("tolerance must be an object")
    relative = finite_number(tolerance.get("relative", 0.03), name="tolerance.relative")
    absolute = finite_number(tolerance.get("absolute", 0.0), name="tolerance.absolute")
    scale_relative = finite_number(
        tolerance.get("scale_relative", relative),
        name="tolerance.scale_relative",
    )
    if relative < 0 or absolute < 0 or scale_relative < 0:
        raise RuntimeError("Scale Assistant tolerances cannot be negative")

    raw_cases = payload.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise RuntimeError("Manifest requires at least one validation case")
    names: set[str] = set()
    cases: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_cases):
        if not isinstance(raw, dict):
            raise RuntimeError(f"cases[{index}] must be an object")
        case = dict(raw)
        name = str(case.get("name", "")).strip()
        if not name or name in names:
            raise RuntimeError("Every validation case requires a unique nonblank name")
        names.add(name)
        method = str(case.get("method", "")).strip().casefold()
        if method not in SUPPORTED_METHODS:
            raise RuntimeError(f"Unsupported Scale Assistant method for {name}: {method}")
        image_value = str(case.get("image", "")).strip()
        if not image_value:
            raise RuntimeError(f"Case {name} requires an image path")
        image_path = Path(image_value)
        if not image_path.is_absolute():
            image_path = (path.parent / image_path).resolve()
        if not image_path.is_file():
            raise RuntimeError(f"Case {name} image does not exist: {image_path}")
        case["name"] = name
        case["method"] = method
        case["image_path"] = image_path
        expected_hash = str(case.get("image_sha256", "")).strip().casefold() or None
        if expected_hash and expected_hash != sha256(image_path):
            raise RuntimeError(f"Case {name} image_sha256 does not match the supplied image")

        if case.get("expected_distance_per_pixel") is not None:
            case["expected_distance_per_pixel"] = positive_number(
                case["expected_distance_per_pixel"],
                name=f"{name}.expected_distance_per_pixel",
            )
        elif method in {"ruler", "profile"}:
            raise RuntimeError(
                f"Case {name} requires expected_distance_per_pixel for {method} validation"
            )

        if method == "ruler":
            case["reference_length"] = positive_number(
                case.get("reference_length"),
                name=f"{name}.reference_length",
            )
            orientation = str(case.get("orientation", "auto")).strip().casefold()
            if orientation not in {"auto", "horizontal", "vertical"}:
                raise RuntimeError(f"Case {name} has invalid ruler orientation")
            case["orientation"] = orientation
            roi = case.get("roi")
            if roi is not None:
                if not isinstance(roi, dict):
                    raise RuntimeError(f"Case {name} roi must be an object")
                case["roi"] = {
                    key: finite_number(roi.get(key), name=f"{name}.roi.{key}")
                    for key in ("x_min", "y_min", "x_max", "y_max")
                }
        elif method in {"aruco", "charuco"}:
            case["marker_length"] = positive_number(
                case.get("marker_length"),
                name=f"{name}.marker_length",
            )
            case["dictionary"] = str(
                case.get("dictionary", "DICT_4X4_50")
            ).strip()
            if not case["dictionary"]:
                raise RuntimeError(f"Case {name} dictionary cannot be blank")
            if case.get("marker_id") is not None:
                marker_id = finite_number(case["marker_id"], name=f"{name}.marker_id")
                if marker_id < 0 or not marker_id.is_integer():
                    raise RuntimeError(f"Case {name} marker_id must be a nonnegative integer")
                case["marker_id"] = int(marker_id)
            if method == "charuco":
                case["charuco_squares_x"] = positive_integer(
                    case.get("charuco_squares_x"),
                    name=f"{name}.charuco_squares_x",
                )
                case["charuco_squares_y"] = positive_integer(
                    case.get("charuco_squares_y"),
                    name=f"{name}.charuco_squares_y",
                )
                case["charuco_square_length"] = positive_number(
                    case.get("charuco_square_length"),
                    name=f"{name}.charuco_square_length",
                )
                if case["marker_length"] >= case["charuco_square_length"]:
                    raise RuntimeError(
                        f"Case {name} marker_length must be smaller than ChArUco square length"
                    )
        else:
            source_case = str(case.get("source_case", "")).strip()
            if not source_case or source_case == name:
                raise RuntimeError(f"Profile case {name} requires an earlier source_case")
            case["source_case"] = source_case

        probe = case.get("probe")
        if probe is not None:
            if not isinstance(probe, dict):
                raise RuntimeError(f"Case {name} probe must be an object")
            normalized_probe = dict(probe)
            normalized_probe["polygon"] = _points(
                probe.get("polygon"),
                name=f"{name}.probe.polygon",
                minimum=3,
            )
            if probe.get("centerline") is not None:
                normalized_probe["centerline"] = _points(
                    probe.get("centerline"),
                    name=f"{name}.probe.centerline",
                    minimum=2,
                )
            expected = probe.get("expected")
            if not isinstance(expected, dict) or not expected:
                raise RuntimeError(f"Case {name} probe requires expected physical values")
            normalized_expected: dict[str, float] = {}
            for key in (
                "area",
                "perimeter",
                "centroid_x",
                "centroid_y",
                "centerline_length",
            ):
                if expected.get(key) is not None:
                    normalized_expected[key] = finite_number(
                        expected[key],
                        name=f"{name}.probe.expected.{key}",
                    )
            if not normalized_expected:
                raise RuntimeError(f"Case {name} probe has no supported expected values")
            normalized_probe["expected"] = normalized_expected
            case["probe"] = normalized_probe
        cases.append(case)

    return {
        "schema_version": SCHEMA_VERSION,
        "unit": unit,
        "tolerance": {
            "relative": relative,
            "absolute": absolute,
            "scale_relative": scale_relative,
        },
        "cases": cases,
        "notes": str(payload.get("notes", "")).strip() or None,
    }


def _scale_comparison(
    calibration: dict[str, Any],
    case: dict[str, Any],
    tolerance: dict[str, float],
) -> dict[str, Any] | None:
    expected = case.get("expected_distance_per_pixel")
    if expected is None:
        return None
    return measurement_error(
        float(calibration["distance_per_pixel"]),
        float(expected),
        relative_tolerance=tolerance["scale_relative"],
        absolute_tolerance=tolerance["absolute"],
    )


def _save_probe(
    client: TestClient,
    *,
    image_id: str,
    label_class_id: str,
    probe: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    mask_id = str(uuid4())
    saved = require(
        client.put(
            f"/api/v1/images/{image_id}/annotations",
            json={
                "base_revision": 0,
                "annotation_status": "reviewed",
                "annotations": [],
                "mask_annotations": [
                    {
                        "id": mask_id,
                        "label_class_id": label_class_id,
                        "geometry_kind": "polygon",
                        "points": probe["polygon"],
                    }
                ],
            },
        ),
        200,
    )
    if probe.get("centerline") is not None:
        require(
            client.put(
                f"/api/v1/mask-annotations/{mask_id}/measurement-profile",
                json={
                    "base_revision": 1,
                    "centerline_points": probe["centerline"],
                    "surface_model": "none",
                },
            ),
            200,
        )
    measured = require(
        client.get(f"/api/v1/mask-annotations/{mask_id}/measurements"),
        200,
    )
    return mask_id, {"annotation_session": saved, "measurement": measured}


def _probe_comparisons(
    measurement: dict[str, Any],
    probe: dict[str, Any],
    tolerance: dict[str, float],
) -> dict[str, dict[str, Any]]:
    field_map = {
        "area": "area_physical",
        "perimeter": "perimeter_physical",
        "centroid_x": "centroid_x_physical",
        "centroid_y": "centroid_y_physical",
        "centerline_length": "total_linear_extension_physical",
    }
    comparisons: dict[str, dict[str, Any]] = {}
    for expected_key, response_key in field_map.items():
        if expected_key not in probe["expected"]:
            continue
        observed = measurement.get(response_key)
        if observed is None:
            raise RuntimeError(
                f"Calibrated probe did not produce physical field {response_key}"
            )
        comparisons[expected_key] = measurement_error(
            float(observed),
            float(probe["expected"][expected_key]),
            relative_tolerance=tolerance["relative"],
            absolute_tolerance=tolerance["absolute"],
        )
    return comparisons


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--state", type=Path)
    args = parser.parse_args()

    manifest_path = args.manifest.resolve()
    output = args.output.resolve()
    state = args.state.resolve() if args.state else output / "reefvision-data"
    if not manifest_path.is_file():
        raise RuntimeError(f"Scale Assistant manifest does not exist: {manifest_path}")
    if output.exists():
        raise RuntimeError(f"Acceptance output already exists: {output}")
    output.mkdir(parents=True)
    state.mkdir(parents=True, exist_ok=False)
    manifest = load_manifest(manifest_path)

    settings = Settings(
        env="acceptance",
        data_dir=state,
        database_url=f"sqlite:///{(state / 'reefvision.db').as_posix()}",
        web_origin="http://testserver",
        background_worker_enabled=False,
    )
    app = create_app(settings)
    Base.metadata.create_all(app.state.engine)
    started = time.perf_counter()
    results: list[dict[str, Any]] = []
    case_images: dict[str, str] = {}

    with TestClient(app) as client:
        project = require(
            client.post(
                "/api/v1/projects",
                json={"name": "Scale Assistant physical validation", "template": "blank"},
            ),
            201,
        )
        label = require(
            client.post(
                f"/api/v1/projects/{project['id']}/classes",
                json={
                    "class_index": 0,
                    "display_order": 0,
                    "name": "Independent calibration probe",
                    "description": "Physical reference-plane validation geometry",
                    "display_color": "#4C9A8A",
                },
            ),
            201,
        )

        for case in manifest["cases"]:
            image_path = case["image_path"]
            imported = require(
                client.post(
                    f"/api/v1/projects/{project['id']}/imports/images",
                    files=[
                        (
                            "files",
                            (
                                image_path.name,
                                image_path.read_bytes(),
                                "application/octet-stream",
                            ),
                        )
                    ],
                    data={"relative_paths": f"scale-validation/{case['name']}/{image_path.name}"},
                ),
                200,
            )
            image_id = str(imported["successful"][0]["image_id"])
            case_images[case["name"]] = image_id
            method = case["method"]
            candidate: dict[str, Any] | None = None

            if method == "ruler":
                detect_payload: dict[str, Any] = {"orientation": case["orientation"]}
                if case.get("roi") is not None:
                    detect_payload["roi"] = case["roi"]
                candidate = require(
                    client.post(
                        f"/api/v1/images/{image_id}/measurement-calibration/ruler-detect",
                        json=detect_payload,
                    ),
                    200,
                )
                if candidate["unit_inferred"] is not False:
                    raise RuntimeError(
                        f"Ruler case {case['name']} incorrectly inferred a physical unit"
                    )
                if candidate["reference_length_required"] is not True:
                    raise RuntimeError(
                        f"Ruler case {case['name']} did not require researcher reference length"
                    )
                calibration_payload = {
                    "distance_per_pixel": (
                        case["reference_length"] / candidate["base_interval_pixels"]
                    ),
                    "unit": manifest["unit"],
                    "source": "automatic_ruler",
                    "reference_length": case["reference_length"],
                    "reference_pixel_length": candidate["base_interval_pixels"],
                    "confidence": candidate["confidence"],
                    "detector": "reefvision-ruler-periodicity-v1",
                    "profile_name": case.get("profile_name"),
                    "reference_plane_only": False,
                    "notes": "Real-image Scale Assistant release validation.",
                }
                calibration = require(
                    client.put(
                        f"/api/v1/images/{image_id}/measurement-calibration",
                        json=calibration_payload,
                    ),
                    200,
                )
            elif method in {"aruco", "charuco"}:
                marker_payload: dict[str, Any] = {
                    "kind": method,
                    "unit": manifest["unit"],
                    "dictionary": case["dictionary"],
                    "marker_length": case["marker_length"],
                    "marker_id": case.get("marker_id"),
                }
                if method == "charuco":
                    marker_payload.update(
                        {
                            "charuco_squares_x": case["charuco_squares_x"],
                            "charuco_squares_y": case["charuco_squares_y"],
                            "charuco_square_length": case["charuco_square_length"],
                        }
                    )
                candidate = require(
                    client.post(
                        f"/api/v1/images/{image_id}/measurement-calibration/marker-detect",
                        json=marker_payload,
                    ),
                    200,
                )
                calibration_payload = dict(candidate["calibration"])
                calibration_payload["profile_name"] = case.get("profile_name")
                calibration = require(
                    client.put(
                        f"/api/v1/images/{image_id}/measurement-calibration",
                        json=calibration_payload,
                    ),
                    200,
                )
            else:
                source_case = case["source_case"]
                source_image_id = case_images.get(source_case)
                if source_image_id is None:
                    raise RuntimeError(
                        f"Profile case {case['name']} references source_case {source_case!r} "
                        "before it was processed"
                    )
                calibration = require(
                    client.post(
                        f"/api/v1/images/{image_id}/measurement-calibration/apply-profile",
                        json={
                            "source_image_id": source_image_id,
                            "confirm_same_setup": True,
                        },
                    ),
                    200,
                )
                if calibration["source"] != "camera_profile":
                    raise RuntimeError(
                        f"Profile case {case['name']} did not persist camera_profile provenance"
                    )
                if calibration["profile_source_image_id"] != source_image_id:
                    raise RuntimeError(
                        f"Profile case {case['name']} did not preserve source-image provenance"
                    )
                if calibration["perspective_homography"] is not None:
                    raise RuntimeError(
                        f"Profile case {case['name']} incorrectly reused a view-specific homography"
                    )

            scale_comparison = _scale_comparison(
                calibration,
                case,
                manifest["tolerance"],
            )
            probe_result: dict[str, Any] | None = None
            probe_comparisons: dict[str, dict[str, Any]] = {}
            if case.get("probe") is not None:
                mask_id, probe_result = _save_probe(
                    client,
                    image_id=image_id,
                    label_class_id=label["id"],
                    probe=case["probe"],
                )
                probe_result["mask_annotation_id"] = mask_id
                probe_comparisons = _probe_comparisons(
                    probe_result["measurement"],
                    case["probe"],
                    manifest["tolerance"],
                )
                perspective_expected = method in {"aruco", "charuco"}
                if (
                    probe_result["measurement"]["perspective_corrected"]
                    is not perspective_expected
                ):
                    raise RuntimeError(
                        f"Case {case['name']} returned unexpected perspective-correction state"
                    )

            case_ok = (
                scale_comparison is None or scale_comparison["within_tolerance"]
            ) and all(item["within_tolerance"] for item in probe_comparisons.values())
            results.append(
                {
                    "name": case["name"],
                    "method": method,
                    "image": str(image_path),
                    "image_sha256": sha256(image_path),
                    "reefvision_image_id": image_id,
                    "candidate": candidate,
                    "calibration": calibration,
                    "scale_comparison": scale_comparison,
                    "probe": probe_result,
                    "probe_comparisons": probe_comparisons,
                    "passed": case_ok,
                }
            )

    app.state.engine.dispose()

    restart_app = create_app(settings)
    restart_checks: list[dict[str, Any]] = []
    with TestClient(restart_app) as client:
        for result in results:
            calibration = require(
                client.get(
                    f"/api/v1/images/{result['reefvision_image_id']}/measurement-calibration"
                ),
                200,
            )
            expected = result["calibration"]
            stable = (
                calibration["distance_per_pixel"] == expected["distance_per_pixel"]
                and calibration["unit"] == expected["unit"]
                and calibration["source"] == expected["source"]
                and calibration["profile_source_image_id"]
                == expected["profile_source_image_id"]
                and calibration["perspective_homography"]
                == expected["perspective_homography"]
            )
            restart_checks.append(
                {
                    "case": result["name"],
                    "passed": stable,
                    "calibration": calibration,
                }
            )
    restart_app.state.engine.dispose()

    acceptance = (
        "PASS"
        if all(result["passed"] for result in results)
        and all(item["passed"] for item in restart_checks)
        else "FAIL"
    )
    report = {
        "acceptance": acceptance,
        "commit_sha": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip(),
        "created_at": datetime.now(UTC).isoformat(),
        "scope": (
            "Real-image ReefVision Scale Assistant physical validation against independent "
            "reference measurements. Synthetic fixtures alone are insufficient."
        ),
        "manifest": str(manifest_path),
        "manifest_sha256": sha256(manifest_path),
        "unit": manifest["unit"],
        "tolerance": manifest["tolerance"],
        "cases": results,
        "restart": restart_checks,
        "duration_seconds": time.perf_counter() - started,
    }
    (output / "report.json").write_text(
        json.dumps(report, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, default=str))
    return 0 if acceptance == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
