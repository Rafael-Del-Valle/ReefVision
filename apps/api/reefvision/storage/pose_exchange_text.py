"""Strict, loss-aware text pose interchange without optional imports at startup.

Coordinates always come from the external artifact. Supplementary information is
accepted only when its digest matches that artifact; edited artifacts require an
explicit re-export instead of silently restoring stale scientific observations.
"""

from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
import math
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from reefvision.domain.errors import ValidationError
from reefvision.storage import pose_text_records as records

_KEY = "reefvision_pose_interoperability"


def _json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, allow_nan=False, separators=(",", ":")).encode()


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _safe(name: str) -> str:
    path = PurePosixPath(name)
    if not name or "\\" in name or ":" in name or path.is_absolute() or ".." in path.parts:
        raise ValidationError("Pose archive contains an unsafe relative path")
    return name


def _nodes(nodes: Any) -> list[str]:
    if (
        not isinstance(nodes, list)
        or not nodes
        or any(not isinstance(n, str) or not n.strip() for n in nodes)
        or len(set(nodes)) != len(nodes)
    ):
        raise ValidationError("Pose skeleton requires nonempty, unique node names")
    return nodes


def _dimensions(width: Any, height: Any) -> tuple[int, int]:
    if any(type(v) is not int or v <= 0 for v in (width, height)):
        raise ValidationError("Real positive integer image dimensions are required")
    return width, height


def _points(points: list[list[float]], width: int, height: int, count: int) -> None:
    if len(points) != count:
        raise ValidationError("Pose node count does not match the skeleton")
    for x, y, visibility in points:
        if visibility not in (0, 1, 2):
            raise ValidationError("Pose visibility must be 0, 1 or 2")
        if visibility and (
            not math.isfinite(x)
            or not math.isfinite(y)
            or not 0 <= x < width
            or not 0 <= y < height
        ):
            raise ValidationError("Pose coordinate is outside image bounds")


def _collect(labels: Any) -> dict[str, Any]:
    if len(labels.skeletons) != 1 or len(labels.videos) != 1:
        raise ValidationError("Text pose export requires one video and one skeleton")
    nodes = _nodes(list(labels.skeletons[0].node_names))
    video = labels.videos[0]
    shape = video.shape
    if shape is None or len(shape) < 3:
        raise ValidationError("Source video dimensions are unavailable")
    width, height = _dimensions(int(shape[2]), int(shape[1]))
    frames = []
    categories = list(
        dict.fromkeys(
            getattr(getattr(inst, "category", None), "name", None) or "animal"
            for frame in labels.labeled_frames
            for inst in frame.instances
        )
    )
    if not categories:
        raise ValidationError("Text pose export requires at least one instance")
    for frame in labels.labeled_frames:
        index = int(frame.frame_idx)
        if index < 0 or index >= shape[0]:
            raise ValidationError("Source frame index is outside the video")
        instances = []
        seen_tracks: set[str] = set()
        for instance in frame.instances:
            if list(instance.skeleton.node_names) != nodes:
                raise ValidationError("Instances have incompatible skeletons")
            track = getattr(getattr(instance, "track", None), "name", None)
            if track is not None:
                if track in seen_tracks:
                    raise ValidationError("Multiple instances share one track in a frame")
                seen_tracks.add(track)
            points = []
            scores = []
            for point in instance.points:
                x, y = (float(v) for v in point["xy"])
                present = math.isfinite(x) and math.isfinite(y)
                if math.isfinite(x) != math.isfinite(y):
                    raise ValidationError("Partially missing pose coordinate is ambiguous")
                points.append(
                    [
                        x if present else 0.0,
                        y if present else 0.0,
                        (2 if point["visible"] else 1) if present else 0,
                    ]
                )
                score = float(point["score"]) if "score" in point.dtype.names else 1.0
                scores.append(score if math.isfinite(score) else None)
            _points(points, width, height, len(nodes))
            score = float(getattr(instance, "score", 1.0))
            instances.append(
                {
                    "points": points,
                    "scores": scores,
                    "track": track,
                    "score": score if math.isfinite(score) else None,
                    "category": getattr(getattr(instance, "category", None), "name", None)
                    or "animal",
                }
            )
        frames.append(
            {
                "frame_idx": index,
                "width": width,
                "height": height,
                "reference": f"references/frame_{index:09d}.png",
                "instances": instances,
            }
        )
    if len({f["frame_idx"] for f in frames}) != len(frames):
        raise ValidationError("Duplicate source frame indices")
    provenance = copy.deepcopy(labels.provenance)
    source = provenance.get(_KEY, {})
    return {
        "nodes": nodes,
        "categories": categories,
        "frames": frames,
        "provenance": provenance,
        "source_filename": source.get("source_filename", ""),
        "source_video_sha256": source.get("source_video_sha256"),
        "edges": [list(edge) for edge in labels.skeletons[0].edge_inds],
    }


def _metadata(document: dict[str, Any], media: str) -> dict[str, Any]:
    result = copy.deepcopy(document)
    for frame in result["frames"]:
        for instance in frame["instances"]:
            instance["visibility"] = [int(p[2]) for p in instance.pop("points")]
    result["media_contract"] = media
    result["version"] = 1
    result["losses"] = [
        "Native history, repeated-landmark semantics and temporal identity "
        "are supplementary metadata.",
        "Point confidence and occlusion not supported by a target field are retained in metadata.",
    ]
    return result


def _bbox(points: list[list[float]], width: int, height: int) -> list[float]:
    present = [p for p in points if p[2]]
    if not present:
        return [0.0, 0.0, float(width), float(height)]
    x0, y0 = min(p[0] for p in present), min(p[1] for p in present)
    x1, y1 = max(p[0] for p in present), max(p[1] for p in present)
    # A single visible point still needs a nonzero training box; never move keypoints.
    x0, y0 = max(0.0, x0 - 0.5), max(0.0, y0 - 0.5)
    x1, y1 = min(float(width), x1 + 0.5), min(float(height), y1 + 0.5)
    return [x0, y0, x1 - x0, y1 - y0]


def _write_coco(document: dict[str, Any], root: Path) -> tuple[Path, str]:
    content: dict[str, Any] = {"images": [], "annotations": [], "categories": []}
    track_ids: dict[str, int] = {}
    for idx, name in enumerate(document["categories"], 1):
        content["categories"].append(
            {
                "id": idx,
                "name": name,
                "keypoints": document["nodes"],
                "skeleton": [[a + 1, b + 1] for a, b in document["edges"]],
            }
        )
    for image_id, frame in enumerate(document["frames"], 1):
        content["images"].append(
            {
                "id": image_id,
                "file_name": frame["reference"],
                "width": frame["width"],
                "height": frame["height"],
                "reefvision_source_frame": frame["frame_idx"],
                "reefvision_asset_available": False,
            }
        )
        for instance in frame["instances"]:
            bbox = _bbox(instance["points"], frame["width"], frame["height"])
            annotation = {
                "id": len(content["annotations"]) + 1,
                "image_id": image_id,
                "category_id": document["categories"].index(instance["category"]) + 1,
                "keypoints": [v for point in instance["points"] for v in point],
                "num_keypoints": sum(p[2] > 0 for p in instance["points"]),
                "bbox": bbox,
                "area": bbox[2] * bbox[3],
                "iscrowd": 0,
            }
            if instance["track"] is not None:
                track_id = track_ids.setdefault(instance["track"], len(track_ids) + 1)
                annotation["attributes"] = {"object_id": track_id}
            if instance["score"] is not None:
                annotation["score"] = instance["score"]
            content["annotations"].append(annotation)
    metadata = _metadata(
        document, "referenced_images_unavailable; source video SHA/frame mapping supplied"
    )
    metadata["artifact_sha256"] = _digest(_json(content))
    content["reefvision"] = metadata
    output = root / "pose.coco.json"
    output.write_bytes(_json(content))
    return output, "application/json"


def _write_dlc(document: dict[str, Any], root: Path, filename: str) -> tuple[Path, str]:
    identities = list(
        dict.fromkeys(
            instance["track"]
            for frame in document["frames"]
            for instance in frame["instances"]
            if instance["track"] is not None
        )
    )
    for frame in document["frames"]:
        for idx, instance in enumerate(frame["instances"]):
            name = instance["track"]
            if name is None:
                name = f"untracked_frame_{frame['frame_idx']}_instance_{idx}"
                while name in identities:
                    name += "_"
            instance["dlc_individual"] = name
            if instance["dlc_individual"] not in identities:
                identities.append(instance["dlc_individual"])
    columns = [
        (identity, node, coord)
        for identity in identities
        for node in document["nodes"]
        for coord in ("x", "y", "likelihood")
    ]
    output_csv = io.StringIO(newline="")
    writer = csv.writer(output_csv, lineterminator="\n")
    writer.writerows(
        [
            ["scorer", *["ReefVision"] * len(columns)],
            ["individuals", *[identity for identity, _, _ in columns]],
            ["bodyparts", *[node for _, node, _ in columns]],
            ["coords", *[coord for _, _, coord in columns]],
        ]
    )
    for frame in document["frames"]:
        cells: dict[tuple[str, str, str], float | None] = {}
        for instance in frame["instances"]:
            for idx, node in enumerate(document["nodes"]):
                x, y, visibility = instance["points"][idx]
                values = (x, y, instance["scores"][idx]) if visibility else (None, None, 0.0)
                for coord, value in zip(("x", "y", "likelihood"), values, strict=True):
                    cells[instance["dlc_individual"], node, coord] = value
        writer.writerow([frame["reference"], *[cells.get(column) for column in columns]])
    payload = output_csv.getvalue().encode()
    metadata = _metadata(
        document, "referenced_images_unavailable; source video SHA/frame mapping supplied"
    )
    metadata["artifact_sha256"] = _digest(payload)
    output = root / "pose.dlc.zip"
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(_safe(filename), payload)
        archive.writestr("reefvision.json", _json(metadata))
    return output, "application/zip"


def _write_yolo(labels: Any, document: dict[str, Any], root: Path) -> tuple[Path, str]:
    import numpy as np
    import yaml
    from PIL import Image

    source_hash = document.get("source_video_sha256")
    if (
        not isinstance(source_hash, str)
        or len(source_hash) != 64
        or any(c not in "0123456789abcdefABCDEF" for c in source_hash)
    ):
        raise ValidationError("YOLO export requires the original source video SHA-256")
    payloads: dict[str, bytes] = {}
    metadata = _metadata(document, "lossless_PNG_of_original_decoded_source_frames")
    metadata["bbox_policy"] = "Keypoint extent padded by half a pixel and clipped to image bounds"
    for frame, sidecar in zip(document["frames"], metadata["frames"], strict=True):
        stem = f"frame_{frame['frame_idx']:09d}"
        image_path, label_path = f"images/train/{stem}.png", f"labels/train/{stem}.txt"
        pixels = labels.videos[0][frame["frame_idx"]]
        if pixels.dtype != np.uint8 or pixels.shape[:2] != (frame["height"], frame["width"]):
            raise ValidationError("YOLO requires original uint8 decoded frames without resizing")
        buffer = io.BytesIO()
        if pixels.ndim == 3 and pixels.shape[2] == 1:
            pixels = pixels[:, :, 0]
        Image.fromarray(pixels).save(buffer, format="PNG")
        payloads[image_path] = buffer.getvalue()
        sidecar["reference"] = image_path
        sidecar["label"] = label_path
        lines = []
        for instance in frame["instances"]:
            width, height = frame["width"], frame["height"]
            x, y, w, h = _bbox(instance["points"], width, height)
            values = [
                float(document["categories"].index(instance["category"])),
                (x + w / 2) / width,
                (y + h / 2) / height,
                w / width,
                h / height,
            ]
            for px, py, v in instance["points"]:
                values.extend([px / width, py / height, v])
            lines.append(" ".join(format(v, ".17g") for v in values))
        payloads[label_path] = ("\n".join(lines) + "\n").encode()
    payloads["data.yaml"] = yaml.safe_dump(
        {
            "train": "images/train",
            "val": "images/train",
            "names": dict(enumerate(document["categories"])),
            "kpt_shape": [len(document["nodes"]), 3],
            "kpt_names": {idx: document["nodes"] for idx in range(len(document["categories"]))},
            "reefvision_skeleton_edges": document["edges"],
            "reefvision_split_note": (
                "One exchange set; train and val alias it. "
                "Create leakage-safe splits before training."
            ),
        }
    ).encode()
    metadata["files_sha256"] = {name: _digest(data) for name, data in payloads.items()}
    output = root / "pose.ultralytics.zip"
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in payloads.items():
            archive.writestr(name, data)
        archive.writestr("reefvision.json", _json(metadata))
    return output, "application/zip"


def write_text(
    labels: Any, root: Path, fmt: str, *, dlc_filename: str = "CollectedData_ReefVision.csv"
) -> tuple[Path, str]:
    """Write a validated text exchange artifact inside the caller-owned directory."""
    document = _collect(labels)
    root.mkdir(parents=True, exist_ok=True)
    if fmt == "coco":
        return _write_coco(document, root)
    if fmt == "dlc_csv":
        return _write_dlc(document, root, dlc_filename)
    if fmt == "ultralytics_pose":
        return _write_yolo(labels, document, root)
    raise ValidationError("Unsupported text pose format")


def _archive(path: Path) -> dict[str, bytes]:
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if len(entries) > 100000 or sum(e.file_size for e in entries) > 512 * 1024 * 1024:
                raise ValidationError("Pose archive exceeds the uncompressed size limit")
            files: dict[str, bytes] = {}
            for entry in entries:
                _safe(entry.filename)
                if entry.is_dir():
                    continue
                if entry.filename in files or (entry.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValidationError("Pose archive contains duplicate paths or symbolic links")
                files[entry.filename] = archive.read(entry)
            return files
    except (zipfile.BadZipFile, OSError, RuntimeError) as exc:
        raise ValidationError("Corrupt or unsupported pose ZIP archive") from exc


def _verify(expected: Any, payload: bytes) -> None:
    if expected != _digest(payload):
        raise ValidationError(
            "Pose artifact digest mismatch: external data was modified; metadata is stale"
        )


def _read_coco(path: Path) -> dict[str, Any]:
    content = json.loads(path.read_bytes())
    metadata = content.pop("reefvision", None)
    if metadata is not None:
        _verify(metadata.get("artifact_sha256"), _json(content))
    categories = content["categories"]
    nodes = _nodes(categories[0]["keypoints"])
    if any(c.get("keypoints") != nodes for c in categories):
        raise ValidationError("COCO categories contain incompatible skeletons")
    category_names = {c["id"]: c["name"] for c in categories}
    if len(category_names) != len(categories):
        raise ValidationError("Duplicate COCO category identifiers")
    frames = []
    image_ids = set()
    annotation_ids = set()
    for idx, image in enumerate(content["images"]):
        if image["id"] in image_ids:
            raise ValidationError("Duplicate COCO image identifier")
        image_ids.add(image["id"])
        width, height = _dimensions(image.get("width"), image.get("height"))
        reference = _safe(image["file_name"])
        base = copy.deepcopy(metadata["frames"][idx]) if metadata else {}
        frame_index = base.get("frame_idx", image.get("reefvision_source_frame", idx))
        instances: list[dict[str, Any]] = []
        for annotation in content["annotations"]:
            if annotation["image_id"] != image["id"]:
                continue
            if annotation["id"] in annotation_ids:
                raise ValidationError("Duplicate COCO annotation identifier")
            annotation_ids.add(annotation["id"])
            raw = annotation["keypoints"]
            if len(raw) != 3 * len(nodes):
                raise ValidationError("COCO keypoint count does not match skeleton")
            points = [raw[i : i + 3] for i in range(0, len(raw), 3)]
            _points(points, width, height, len(nodes))
            if annotation.get("num_keypoints", sum(p[2] > 0 for p in points)) != sum(
                p[2] > 0 for p in points
            ):
                raise ValidationError("COCO num_keypoints contradicts visibility values")
            if annotation.get("iscrowd", 0) != 0:
                raise ValidationError("COCO crowd annotations cannot represent one pose instance")
            bbox = annotation.get("bbox")
            if bbox is not None:
                if len(bbox) != 4 or any(not math.isfinite(v) for v in bbox):
                    raise ValidationError("Malformed COCO bounding box")
                x, y, box_width, box_height = bbox
                if (
                    min(x, y, box_width, box_height) < 0
                    or x + box_width > width
                    or y + box_height > height
                ):
                    raise ValidationError("COCO bounding box is outside image bounds")
            extra = copy.deepcopy(base["instances"][len(instances)]) if metadata else {}
            if metadata is None:
                attributes = annotation.get("attributes")
                track_id = attributes.get("object_id") if isinstance(attributes, dict) else None
                if track_id is None:
                    track_id = annotation.get("track_id")
                if type(track_id) in (int, str) and str(track_id).strip():
                    extra["track"] = f"track_{track_id}"
                if annotation.get("score") is not None:
                    extra["score"] = annotation["score"]
            extra.update(points=points, category=category_names[annotation["category_id"]])
            instances.append(extra)
        frames.append(
            {
                "frame_idx": frame_index,
                "width": width,
                "height": height,
                "reference": reference,
                "instances": instances,
            }
        )
    if len(annotation_ids) != len(content["annotations"]):
        raise ValidationError("COCO annotation references an absent image")
    result: dict[str, Any] = metadata or {"provenance": {}, "edges": []}
    result.update(nodes=nodes, categories=list(category_names.values()), frames=frames)
    result["media_contract"] = "referenced_images_unavailable; no image assets bundled in JSON"
    result["warnings"] = [
        "COCO bounding boxes, areas and segmentation are not pose observations; "
        "ReefVision derives pose boxes unless native metadata supplies canonical boxes. "
        "Other external COCO tracking fields are not imported."
    ]
    return result


def _read_dlc_table(
    payload: bytes, *, legacy: bool = False
) -> tuple[list[str], dict[str | None, dict[tuple[str, str], int]], dict[str, list[str]]]:
    rows = list(csv.reader(io.StringIO(payload.decode("utf-8-sig")), strict=True))
    if len(rows) < 4 or not rows[0] or not rows[1] or rows[0][0] != "scorer":
        raise ValidationError("DeepLabCut CSV requires scorer, bodyparts and coords headers")
    header_count = 4 if rows[1][0] == "individuals" else 3
    if legacy and all(row[1:3] == ["", ""] for row in rows[:header_count]):
        headers = [[row[0], *row[3:]] for row in rows[:header_count]]
        frames = [
            ["/".join(row[:3]), *row[3:]] if row and any(row) else row
            for row in rows[header_count:]
        ]
        rows = headers + frames
    scorers, bodyparts, coords = rows[0], rows[header_count - 2], rows[header_count - 1]
    if (
        not bodyparts
        or not coords
        or bodyparts[0] != "bodyparts"
        or coords[0] != "coords"
        or not all(len(row) == len(scorers) for row in rows[:header_count])
        or len(set(scorers[1:])) != 1
    ):
        raise ValidationError("DeepLabCut CSV requires one scorer and consistent headers")
    columns: dict[str | None, dict[tuple[str, str], int]] = {}
    for index, (node, coordinate) in enumerate(zip(bodyparts[1:], coords[1:], strict=True), 1):
        individual = rows[1][index] if header_count == 4 else None
        keys = columns.setdefault(individual, {})
        if (
            not node.strip()
            or coordinate not in {"x", "y", "likelihood"}
            or (node, coordinate) in keys
        ):
            raise ValidationError("DeepLabCut CSV has invalid or duplicate landmark columns")
        keys[node, coordinate] = index
    nodes = _nodes(list(dict.fromkeys(bodyparts[1:])))
    if any(
        (node, coordinate) not in keys
        for keys in columns.values()
        for node in nodes
        for coordinate in ("x", "y")
    ):
        raise ValidationError("DeepLabCut CSV landmark columns require paired coordinates")
    images: dict[str, list[str]] = {}
    for row in rows[header_count:]:
        if not row or not any(row):
            continue
        reference = _safe(row[0].replace("\\", "/") if legacy else row[0])
        if len(row) != len(scorers) or reference in images:
            raise ValidationError("DeepLabCut CSV rows have duplicate names or invalid columns")
        images[reference] = row
    return nodes, columns, images


def _dlc_coordinates(
    row: list[str], keys: dict[tuple[str, str], int], node: str
) -> tuple[float, float, float]:
    def read(column: str) -> float:
        index = keys.get((node, column))
        return float(row[index]) if index is not None and row[index].strip() else float("nan")

    x, y, confidence = read("x"), read("y"), read("likelihood")
    if math.isinf(x) or math.isinf(y) or math.isnan(x) != math.isnan(y):
        raise ValidationError("DeepLabCut coordinates must be finite pairs or absent pairs")
    return x, y, confidence


def read_legacy_dlc(path: Path, width: int, height: int) -> records.Labels:
    """Decode historical DLC tables with dimensions from the target video."""
    try:
        nodes, columns, images = _read_dlc_table(path.read_bytes(), legacy=True)
        frames = []
        for frame_index, (reference, row) in enumerate(images.items()):
            instances = []
            for individual, keys in columns.items():
                values = [_dlc_coordinates(row, keys, node) for node in nodes]
                if all(math.isnan(x) for x, _, _ in values):
                    continue
                instances.append(
                    {
                        "track": individual,
                        "category": "animal",
                        "points": [
                            [x, y, 2] if math.isfinite(x) else [0.0, 0.0, 0] for x, y, _ in values
                        ],
                        "scores": [
                            score if math.isfinite(score) else None for _, _, score in values
                        ],
                    }
                )
            frames.append(
                {
                    "frame_idx": frame_index,
                    "reference": reference,
                    "width": width,
                    "height": height,
                    "instances": instances,
                }
            )
        return _to_labels(
            {
                "nodes": nodes,
                "frames": frames,
                "categories": ["animal"],
                "media_contract": "referenced_images_unavailable; dimensions from target video",
            }
        )
    except (OSError, ValueError, IndexError, csv.Error) as exc:
        raise ValidationError(f"DeepLabCut pose CSV is malformed: {exc}") from exc


def _read_dlc(files: dict[str, bytes]) -> dict[str, Any]:
    metadata: dict[str, Any] = json.loads(files["reefvision.json"])
    csv_files = [payload for name, payload in files.items() if name.casefold().endswith(".csv")]
    if len(csv_files) != 1:
        raise ValidationError("DLC ZIP requires exactly one pose CSV")
    payload = csv_files[0]
    _verify(metadata.get("artifact_sha256"), payload)
    nodes, columns, images = _read_dlc_table(payload)
    if nodes != _nodes(metadata["nodes"]) or list(images) != [
        f["reference"] for f in metadata["frames"]
    ]:
        raise ValidationError("DLC rows or landmarks do not match source references")
    for frame in metadata["frames"]:
        for instance in frame["instances"]:
            points, scores = [], []
            for idx, node in enumerate(nodes):
                x, y, confidence = _dlc_coordinates(
                    images[frame["reference"]], columns[instance["dlc_individual"]], node
                )
                visibility = instance["visibility"][idx]
                if visibility == 0 and math.isfinite(x):
                    raise ValidationError("DLC coordinates conflict with missing-point metadata")
                points.append([x if visibility else 0.0, y if visibility else 0.0, visibility])
                scores.append(confidence if math.isfinite(confidence) else None)
            instance.update(points=points, scores=scores)
    return metadata


def _yolo_instance(
    line: str, node_count: int, categories: list[str], width: int, height: int, dimensions: int = 3
) -> dict[str, Any]:
    values = [float(v) for v in line.split()]
    if len(values) != 5 + dimensions * node_count or not all(map(math.isfinite, values)):
        raise ValidationError("Malformed YOLO pose label")
    class_index = int(values[0])
    if values[0] != class_index or not 0 <= class_index < len(categories):
        raise ValidationError("Invalid YOLO class index")
    if not all(0 <= v <= 1 for v in values[1:5]) or min(values[3:5]) <= 0:
        raise ValidationError("Invalid normalized YOLO bounding box")
    points = []
    for index in range(5, len(values), dimensions):
        x, y = values[index : index + 2]
        visibility = values[index + 2] if dimensions == 3 else 2
        if not 0 <= x <= 1 or not 0 <= y <= 1:
            raise ValidationError("YOLO keypoint coordinate is not normalized")
        points.append([x * width, y * height, visibility])
    return {"points": points, "category": categories[class_index]}


def read_legacy_yolo(root: Path) -> records.Labels:
    """Decode historical ULtralytics training-split images and pose labels."""
    import yaml
    from PIL import Image

    try:
        config = yaml.safe_load((root / "data.yaml").read_bytes())
        names = config["names"]
        categories = [names[i] for i in range(len(names))]
        count, dimensions = config["kpt_shape"]
        if type(count) is not int or count < 1 or dimensions not in (2, 3):
            raise ValidationError("Invalid YOLO pose shape")
        if not categories or any(not isinstance(name, str) or not name for name in categories):
            raise ValidationError("YOLO class names are required")
        kpt_names = config.get("kpt_names")
        nodes = _nodes(
            config.get("node_names")
            or (kpt_names.get(0) if isinstance(kpt_names, dict) else kpt_names)
            or [f"keypoint_{i}" for i in range(count)]
        )
        if len(nodes) != count:
            raise ValidationError("YOLO keypoint names do not match the shape")
        path = _safe(config.get("path", "."))
        images = root / path / _safe(config["train"])
        frames = []
        for index, image in enumerate(
            sorted(
                file
                for file in images.rglob("*")
                if file.suffix.casefold() in {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}
            )
        ):
            parts = list(image.relative_to(root).parts)
            image_component = parts.index("images")
            parts[image_component] = "labels"
            label = root.joinpath(*parts).with_suffix(".txt")
            if not label.is_file():
                raise ValidationError("YOLO pose image is missing its paired label file")
            with Image.open(image) as pixels:
                width, height = pixels.size
            instances = [
                _yolo_instance(line, count, categories, width, height, dimensions)
                for line in label.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            frames.append(
                {
                    "frame_idx": index,
                    "reference": image.relative_to(root).as_posix(),
                    "width": width,
                    "height": height,
                    "instances": instances,
                }
            )
        return _to_labels(
            {
                "nodes": nodes,
                "categories": categories,
                "frames": frames,
                "media_contract": "historical_paired_image_dataset",
            }
        )
    except (OSError, KeyError, IndexError, TypeError, ValueError, yaml.YAMLError) as exc:
        raise ValidationError(f"Malformed historical YOLO pose dataset: {exc}") from exc


def _read_yolo(files: dict[str, bytes]) -> dict[str, Any]:
    import yaml
    from PIL import Image

    metadata: dict[str, Any] = json.loads(files["reefvision.json"])
    expected = metadata["files_sha256"]
    if set(expected) != set(files) - {"reefvision.json"}:
        raise ValidationError("YOLO image/label correspondence differs from the manifest")
    for name, digest in expected.items():
        _verify(digest, files[name])
    config = yaml.safe_load(files["data.yaml"])
    nodes = _nodes(metadata["nodes"])
    if config["kpt_shape"] != [len(nodes), 3]:
        raise ValidationError("YOLO keypoint shape does not match skeleton")
    if config["names"] != dict(enumerate(metadata["categories"])):
        raise ValidationError("YOLO class indices do not match the manifest")
    used = {"data.yaml", "reefvision.json"}
    for frame in metadata["frames"]:
        reference, label = _safe(frame["reference"]), _safe(frame["label"])
        if label != reference.replace("images/", "labels/", 1).removesuffix(".png") + ".txt":
            raise ValidationError("YOLO image/label correspondence is invalid")
        if reference in used or label in used:
            raise ValidationError("Duplicate YOLO image/label correspondence")
        used.update([reference, label])
        with Image.open(io.BytesIO(files[reference])) as image:
            image.load()
            if image.size != (frame["width"], frame["height"]):
                raise ValidationError("YOLO image dimensions do not match metadata")
        lines = [line for line in files[label].decode().splitlines() if line.strip()]
        if len(lines) != len(frame["instances"]):
            raise ValidationError("YOLO instance count does not match metadata")
        for line, instance in zip(lines, frame["instances"], strict=True):
            instance.update(
                _yolo_instance(
                    line, len(nodes), metadata["categories"], frame["width"], frame["height"]
                )
            )
    if used != set(files):
        raise ValidationError("YOLO archive contains unpaired images or labels")
    return metadata


def _to_labels(document: dict[str, Any]) -> records.Labels:
    import numpy as np

    nodes = _nodes(document["nodes"])
    skeleton = records.Skeleton(nodes=nodes, edges=document.get("edges", []))
    frames = document["frames"]
    if not frames:
        raise ValidationError("Pose artifact has no labeled frames")
    indices = [f["frame_idx"] for f in frames]
    if any(type(i) is not int or i < 0 for i in indices) or len(set(indices)) != len(indices):
        raise ValidationError("Invalid or duplicate source frame index")
    width, height = _dimensions(frames[0]["width"], frames[0]["height"])
    video = records.Video(
        filename=document.get("source_filename") or "unavailable-source-video",
        shape=(max(indices) + 1, height, width, 3),
    )
    tracks: dict[str, Any] = {}
    categories = {name: records.Category(name) for name in document["categories"]}
    labeled_frames = []
    for frame in frames:
        if _dimensions(frame["width"], frame["height"]) != (width, height):
            raise ValidationError("A source video cannot have inconsistent image dimensions")
        instances = []
        seen_tracks = set()
        for instance in frame["instances"]:
            points = instance["points"]
            _points(points, width, height, len(nodes))
            name = instance.get("track")
            track = None
            if name is not None:
                if name in seen_tracks:
                    raise ValidationError("Multiple instances share one track in a frame")
                seen_tracks.add(name)
                track = tracks.setdefault(name, records.Track(name))
            xy = np.asarray([[x, y] if v else [np.nan, np.nan] for x, y, v in points])
            scores = instance.get("scores", [None] * len(nodes))
            restored = records.Instance.from_arrays(
                xy,
                skeleton=skeleton,
                visible=np.asarray([p[2] == 2 for p in points]),
                scores=(
                    np.asarray([np.nan if score is None else score for score in scores])
                    if any(score is not None for score in scores)
                    else None
                ),
                score=instance["score"] if instance.get("score") is not None else float("nan"),
                track=track,
                category=categories[instance["category"]],
            )
            instances.append(restored)
        labeled_frames.append(records.LabeledFrame(video, frame["frame_idx"], instances))
    provenance = copy.deepcopy(document.get("provenance", {}))
    source = provenance.get(_KEY)
    if isinstance(source, dict):
        source["reefvision_frame_manifest"] = [
            {
                "reefvision_frame_index": frame["frame_idx"],
                "instances": [
                    {"external_track_name": instance.get("track")}
                    for instance in frame["instances"]
                ],
            }
            for frame in frames
        ]
    provenance["reefvision_text_exchange"] = {
        "media_contract": document.get("media_contract"),
        "warnings": ["Source video is a reference only and is not opened during import."]
        + (
            [
                "Referenced image assets are unavailable; "
                "reconstruct from the source video and frame map."
            ]
            if "unavailable" in document.get("media_contract", "")
            else []
        ),
        "source_video_sha256": document.get("source_video_sha256"),
        "frame_mapping": [
            {k: f[k] for k in ("frame_idx", "reference", "width", "height")} for f in frames
        ],
        "losses": document.get("losses", []),
    }
    provenance.setdefault("reefvision_warnings", []).extend(
        provenance["reefvision_text_exchange"]["warnings"] + document.get("warnings", [])
    )
    return records.Labels(labeled_frames, [video], [skeleton], provenance)


def read_text(path: Path, fmt: str) -> records.Labels:
    """Parse actual coordinate payloads into native pose records."""
    try:
        if fmt == "coco":
            document = _read_coco(path)
        elif fmt == "dlc_csv":
            if path.suffix.casefold() == ".csv" and not zipfile.is_zipfile(path):
                raise ValidationError(
                    "DLC CSV requires source-frame, dimensions and visibility metadata. "
                    "Import the ReefVision DLC ZIP containing the CSV and reefvision.json sidecar."
                )
            document = _read_dlc(_archive(path))
        elif fmt == "ultralytics_pose":
            files = _archive(path)
            files.pop("reefvision-pose-manifest.json", None)
            document = _read_yolo(files)
        else:
            raise ValidationError("Unsupported text pose format")
        return _to_labels(document)
    except ValidationError:
        raise
    except (
        KeyError,
        IndexError,
        TypeError,
        ValueError,
        OSError,
        AttributeError,
        OverflowError,
        csv.Error,
    ) as exc:
        raise ValidationError(
            f"Malformed {fmt} pose artifact or missing required metadata: {exc}"
        ) from exc
