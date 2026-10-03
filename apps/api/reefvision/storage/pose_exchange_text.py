"""Strict, loss-aware text pose interchange without optional imports at startup.

Coordinates always come from the external artifact. Supplementary information is
accepted only when its digest matches that artifact; edited artifacts require an
explicit re-export instead of silently restoring stale scientific observations.
"""

from __future__ import annotations

import copy
import hashlib
import io
import json
import math
import zipfile
from importlib import import_module
from pathlib import Path, PurePosixPath
from typing import Any

from reefvision.domain.errors import ValidationError

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
            content["annotations"].append(
                {
                    "id": len(content["annotations"]) + 1,
                    "image_id": image_id,
                    "category_id": document["categories"].index(instance["category"]) + 1,
                    "keypoints": [v for point in instance["points"] for v in point],
                    "num_keypoints": sum(p[2] > 0 for p in instance["points"]),
                    "bbox": bbox,
                    "area": bbox[2] * bbox[3],
                    "iscrowd": 0,
                }
            )
    metadata = _metadata(
        document, "referenced_images_unavailable; source video SHA/frame mapping supplied"
    )
    metadata["artifact_sha256"] = _digest(_json(content))
    content["reefvision"] = metadata
    output = root / "pose.coco.json"
    output.write_bytes(_json(content))
    return output, "application/json"


def _write_dlc(document: dict[str, Any], root: Path) -> tuple[Path, str]:
    pd = import_module("pandas")

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
    columns = pd.MultiIndex.from_product(
        [["ReefVision"], identities, document["nodes"], ["x", "y", "likelihood"]],
        names=["scorer", "individuals", "bodyparts", "coords"],
    )
    table = pd.DataFrame(
        float("nan"), columns=columns, index=[f["reference"] for f in document["frames"]]
    )
    for frame in document["frames"]:
        for instance in frame["instances"]:
            for idx, node in enumerate(document["nodes"]):
                x, y, visibility = instance["points"][idx]
                score = instance["scores"][idx]
                values = (
                    [x, y, score if score is not None else float("nan")]
                    if visibility
                    else [float("nan"), float("nan"), 0.0]
                )
                for coord, value in zip(["x", "y", "likelihood"], values, strict=True):
                    table.at[
                        frame["reference"], ("ReefVision", instance["dlc_individual"], node, coord)
                    ] = value
    payload = table.to_csv().encode()
    metadata = _metadata(
        document, "referenced_images_unavailable; source video SHA/frame mapping supplied"
    )
    metadata["artifact_sha256"] = _digest(payload)
    output = root / "pose.dlc.zip"
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("CollectedData_ReefVision.csv", payload)
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


def write_text(sio: Any, labels: Any, root: Path, fmt: str) -> tuple[Path, str]:
    """Write a validated text exchange artifact inside the caller-owned directory."""
    del sio
    document = _collect(labels)
    root.mkdir(parents=True, exist_ok=True)
    if fmt == "coco":
        return _write_coco(document, root)
    if fmt == "dlc_csv":
        return _write_dlc(document, root)
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
        "Unknown external COCO fields, including external tracking extensions, are not imported."
    ]
    return result


def _read_dlc(files: dict[str, bytes]) -> dict[str, Any]:
    pd = import_module("pandas")

    metadata: dict[str, Any] = json.loads(files["reefvision.json"])
    payload = files["CollectedData_ReefVision.csv"]
    _verify(metadata.get("artifact_sha256"), payload)
    nodes = _nodes(metadata["nodes"])
    table = pd.read_csv(io.BytesIO(payload), header=[0, 1, 2, 3], index_col=0)
    if table.index.has_duplicates or table.columns.has_duplicates:
        raise ValidationError("Duplicate DLC row or column names")
    if list(table.index) != [f["reference"] for f in metadata["frames"]]:
        raise ValidationError("DLC rows do not match source frame references")
    for frame in metadata["frames"]:
        _safe(frame["reference"])
        for instance in frame["instances"]:
            points, scores = [], []
            for idx, node in enumerate(nodes):
                x, y, confidence = (
                    float(
                        table.at[
                            frame["reference"],
                            ("ReefVision", instance["dlc_individual"], node, coord),
                        ]
                    )
                    for coord in ["x", "y", "likelihood"]
                )
                visibility = instance["visibility"][idx]
                if visibility == 0 and (math.isfinite(x) or math.isfinite(y)):
                    raise ValidationError("DLC coordinates conflict with missing-point metadata")
                points.append([x if visibility else 0.0, y if visibility else 0.0, visibility])
                scores.append(confidence if math.isfinite(confidence) else None)
            instance.update(points=points, scores=scores)
    return metadata


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
            values = [float(v) for v in line.split()]
            if len(values) != 5 + 3 * len(nodes) or any(not math.isfinite(v) for v in values):
                raise ValidationError("Malformed YOLO pose label")
            class_index = int(values[0])
            if values[0] != class_index or not 0 <= class_index < len(metadata["categories"]):
                raise ValidationError("Invalid YOLO class index")
            if any(not 0 <= v <= 1 for v in values[1:5]) or min(values[3:5]) <= 0:
                raise ValidationError("Invalid normalized YOLO bounding box")
            points = []
            for idx in range(5, len(values), 3):
                x, y, visibility = values[idx : idx + 3]
                if not 0 <= x <= 1 or not 0 <= y <= 1:
                    raise ValidationError("YOLO keypoint coordinate is not normalized")
                points.append([x * frame["width"], y * frame["height"], visibility])
            instance.update(points=points, category=metadata["categories"][class_index])
    if used != set(files):
        raise ValidationError("YOLO archive contains unpaired images or labels")
    return metadata


def _to_labels(sio: Any, document: dict[str, Any]) -> Any:
    import numpy as np

    nodes = _nodes(document["nodes"])
    skeleton = sio.Skeleton(nodes=nodes, edges=document.get("edges", []))
    frames = document["frames"]
    if not frames:
        raise ValidationError("Pose artifact has no labeled frames")
    indices = [f["frame_idx"] for f in frames]
    if any(type(i) is not int or i < 0 for i in indices) or len(set(indices)) != len(indices):
        raise ValidationError("Invalid or duplicate source frame index")
    width, height = _dimensions(frames[0]["width"], frames[0]["height"])
    video = sio.Video(
        filename=document.get("source_filename") or "unavailable-source-video",
        backend_metadata={"shape": [max(indices) + 1, height, width, 3]},
        open_backend=False,
    )
    tracks: dict[str, Any] = {}
    categories = {name: sio.Category(name) for name in document["categories"]}
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
                track = tracks.setdefault(name, sio.Track(name))
            xy = np.asarray([[x, y] if v else [np.nan, np.nan] for x, y, v in points])
            scores = [
                np.nan if v is None else v for v in instance.get("scores", [None] * len(nodes))
            ]
            restored = sio.PredictedInstance.from_numpy(
                xy,
                skeleton=skeleton,
                point_scores=np.asarray(scores),
                score=instance["score"] if instance.get("score") is not None else float("nan"),
                track=track,
                category=categories[instance["category"]],
            )
            restored.points["visible"] = [p[2] == 2 for p in points]
            instances.append(restored)
        labeled_frames.append(sio.LabeledFrame(video, frame["frame_idx"], instances))
    provenance = copy.deepcopy(document.get("provenance", {}))
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
    return sio.Labels(labeled_frames, provenance=provenance)


def read_text(sio: Any, path: Path, fmt: str) -> Any:
    """Parse actual coordinate payloads, validating before constructing SLEAP models."""
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
            document = _read_yolo(_archive(path))
        else:
            raise ValidationError("Unsupported text pose format")
        return _to_labels(sio, document)
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
    ) as exc:
        raise ValidationError(
            f"Malformed {fmt} pose artifact or missing required metadata: {exc}"
        ) from exc
