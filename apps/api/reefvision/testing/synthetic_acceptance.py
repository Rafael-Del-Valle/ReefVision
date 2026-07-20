"""Generate deterministic, repository-owned acceptance fixtures.

The generated data intentionally uses simple geometry with known measurements so tests
can verify import/export, annotation, measurement, tracking, depth, and classification
workflows without relying on Rafael's research images or videos.
"""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import struct
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from xml.etree.ElementTree import Element, ElementTree, SubElement

import numpy as np
from PIL import Image, ImageDraw

_CLASS_NAMES = ("MC", "TC", "MO", "SO", "SC", "TO")
_WIDTH = 256
_HEIGHT = 192


@dataclass(frozen=True)
class SyntheticAcceptanceManifest:
    root: str
    manifest_path: str
    files: tuple[str, ...]
    checksums: dict[str, str]
    expected: dict[str, Any]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def _coral_image(index: int) -> Image.Image:
    image = Image.new("RGB", (_WIDTH, _HEIGHT), (18 + index * 4, 42, 58))
    draw = ImageDraw.Draw(image)
    for y in range(_HEIGHT):
        shade = int(18 + 32 * y / max(_HEIGHT - 1, 1))
        draw.line((0, y, _WIDTH, y), fill=(shade, 46 + index * 3, 68))
    base_x = 78 + index * 48
    draw.line((base_x, 175, base_x, 54), fill=(232, 148, 101), width=12)
    branches = (
        ((base_x, 120), (base_x - 44, 86)),
        ((base_x, 110), (base_x + 42, 73)),
        ((base_x, 82), (base_x - 26, 51)),
        ((base_x, 72), (base_x + 28, 40)),
    )
    for start, end in branches:
        draw.line((*start, *end), fill=(239, 164, 111), width=9)
    for point_index, (x, y) in enumerate(
        [(base_x - 44, 86), (base_x + 42, 73), (base_x - 26, 51), (base_x + 28, 40)]
    ):
        radius = 7 if point_index % 2 == 0 else 5
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=(246, 190, 137))
    return image


def _known_masks(root: Path) -> dict[str, Any]:
    masks_root = root / "masks"
    masks_root.mkdir(parents=True, exist_ok=True)
    rectangle = Image.new("L", (_WIDTH, _HEIGHT), 0)
    ImageDraw.Draw(rectangle).rectangle((40, 50, 119, 109), fill=255)
    rectangle_path = masks_root / "known-area-rectangle.png"
    rectangle.save(rectangle_path, format="PNG")

    centerline = Image.new("L", (_WIDTH, _HEIGHT), 0)
    centerline_draw = ImageDraw.Draw(centerline)
    centerline_draw.line((30, 160, 100, 90), fill=255, width=1)
    centerline_draw.line((100, 90, 180, 90), fill=255, width=1)
    centerline_path = masks_root / "known-centerline.png"
    centerline.save(centerline_path, format="PNG")

    polygon_points = [[30, 30], [130, 30], [130, 80], [30, 80]]
    _write_json(
        masks_root / "known-polygon.json",
        {
            "label": "synthetic coral",
            "points": polygon_points,
            "expected_area_pixels": 5000,
            "expected_perimeter_pixels": 300,
        },
    )
    return {
        "rectangle": {
            "bounds_inclusive": [40, 50, 119, 109],
            "area_pixels": 4800,
            "perimeter_pixels": 280,
        },
        "polygon": {"area_pixels": 5000, "perimeter_pixels": 300},
        "centerline": {
            "segments": [math.sqrt(70**2 + 70**2), 80.0],
            "total_length_pixels": math.sqrt(70**2 + 70**2) + 80.0,
        },
    }


def _classification_crops(root: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    six_class_root = root / "classification" / "six-class"
    for class_index, class_name in enumerate(_CLASS_NAMES):
        class_root = six_class_root / class_name
        class_root.mkdir(parents=True, exist_ok=True)
        counts[class_name] = 4
        for sample in range(4):
            crop = Image.new(
                "RGB",
                (64, 64),
                (
                    40 + class_index * 28,
                    60 + sample * 14,
                    150 - class_index * 11,
                ),
            )
            draw = ImageDraw.Draw(crop)
            inset = 7 + sample * 2
            if class_index % 2 == 0:
                draw.ellipse(
                    (inset, inset, 63 - inset, 63 - inset),
                    outline=(248, 236, 190),
                    width=4,
                )
            else:
                draw.rectangle(
                    (inset, inset, 63 - inset, 63 - inset),
                    outline=(248, 236, 190),
                    width=4,
                )
            crop.save(class_root / f"{class_name.lower()}-{sample:02d}.png", format="PNG")

    binary_root = root / "classification" / "binary-state"
    for state_index, state in enumerate(("open", "closed")):
        state_root = binary_root / state
        state_root.mkdir(parents=True, exist_ok=True)
        counts[state] = 6
        for sample in range(6):
            crop = Image.new("RGB", (64, 64), (35, 63 + sample * 6, 88))
            draw = ImageDraw.Draw(crop)
            radius = 20 if state_index == 0 else 8
            draw.ellipse(
                (32 - radius, 32 - radius, 32 + radius, 32 + radius),
                fill=(226, 145, 112),
            )
            crop.save(state_root / f"{state}-{sample:02d}.png", format="PNG")
    return counts


def _riff_chunk(tag: bytes, payload: bytes) -> bytes:
    padding = b"\x00" if len(payload) % 2 else b""
    return tag + struct.pack("<I", len(payload)) + payload + padding


def _riff_list(kind: bytes, payload: bytes) -> bytes:
    return _riff_chunk(b"LIST", kind + payload)


def _write_mjpeg_avi(path: Path, frames: list[Image.Image], *, fps: int = 8) -> None:
    if not frames:
        raise ValueError("At least one frame is required")
    width, height = frames[0].size
    encoded: list[bytes] = []
    for frame in frames:
        if frame.size != (width, height):
            raise ValueError("All AVI frames must share dimensions")
        from io import BytesIO

        buffer = BytesIO()
        frame.convert("RGB").save(buffer, format="JPEG", quality=90, optimize=False)
        encoded.append(buffer.getvalue())

    maximum_frame = max(len(frame) for frame in encoded)
    main_header = struct.pack(
        "<IIIIIIIIII4I",
        int(1_000_000 / fps),
        maximum_frame * fps,
        0,
        0x10,
        len(encoded),
        0,
        1,
        maximum_frame,
        width,
        height,
        0,
        0,
        0,
        0,
    )
    stream_header = struct.pack(
        "<4s4sIHHIIIIIIIIhhhh",
        b"vids",
        b"MJPG",
        0,
        0,
        0,
        0,
        1,
        fps,
        0,
        len(encoded),
        maximum_frame,
        0xFFFFFFFF,
        0,
        0,
        0,
        width,
        height,
    )
    bitmap_info = struct.pack(
        "<IiiHH4sIiiII",
        40,
        width,
        height,
        1,
        24,
        b"MJPG",
        width * height * 3,
        0,
        0,
        0,
        0,
    )
    stream_list = _riff_list(
        b"strl",
        _riff_chunk(b"strh", stream_header) + _riff_chunk(b"strf", bitmap_info),
    )
    header_list = _riff_list(b"hdrl", _riff_chunk(b"avih", main_header) + stream_list)

    movie_payload = bytearray()
    index_entries = bytearray()
    for encoded_frame in encoded:
        offset = len(movie_payload)
        chunk = _riff_chunk(b"00dc", encoded_frame)
        movie_payload.extend(chunk)
        index_entries.extend(struct.pack("<4sIII", b"00dc", 0x10, offset, len(encoded_frame)))
    movie_list = _riff_list(b"movi", bytes(movie_payload))
    avi_payload = b"AVI " + header_list + movie_list + _riff_chunk(b"idx1", bytes(index_entries))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"RIFF" + struct.pack("<I", len(avi_payload)) + avi_payload)


def _video_fixtures(root: Path) -> dict[str, Any]:
    video_root = root / "video"
    video_root.mkdir(parents=True, exist_ok=True)
    simple_frames: list[Image.Image] = []
    simple_tracks: dict[str, list[dict[str, float | int]]] = {"fish-1": []}
    for frame_index in range(24):
        image = Image.new("RGB", (192, 128), (18, 45, 65))
        draw = ImageDraw.Draw(image)
        x = 12 + frame_index * 6
        y = 54 + round(8 * math.sin(frame_index / 4))
        draw.ellipse((x, y, x + 28, y + 14), fill=(238, 182, 81))
        draw.polygon([(x, y + 7), (x - 10, y), (x - 10, y + 14)], fill=(238, 182, 81))
        simple_tracks["fish-1"].append(
            {"frame": frame_index, "x": x + 14, "y": y + 7, "depth": 1.0 + frame_index * 0.01}
        )
        simple_frames.append(image)
    _write_mjpeg_avi(video_root / "single-fish.avi", simple_frames)
    _write_json(video_root / "single-fish-trajectories.json", simple_tracks)

    crossing_frames: list[Image.Image] = []
    crossing_tracks: dict[str, list[dict[str, float | int]]] = {"fish-a": [], "fish-b": []}
    for frame_index in range(30):
        image = Image.new("RGB", (192, 128), (22, 40, 58))
        draw = ImageDraw.Draw(image)
        ax, ay = 12 + frame_index * 5, 46
        bx, by = 164 - frame_index * 5, 66
        draw.ellipse((ax, ay, ax + 24, ay + 12), fill=(232, 160, 72))
        draw.ellipse((bx, by, bx + 24, by + 12), fill=(94, 194, 221))
        crossing_tracks["fish-a"].append(
            {"frame": frame_index, "x": ax + 12, "y": ay + 6, "depth": 0.8}
        )
        crossing_tracks["fish-b"].append(
            {"frame": frame_index, "x": bx + 12, "y": by + 6, "depth": 1.8}
        )
        crossing_frames.append(image)
    _write_mjpeg_avi(video_root / "identity-crossing.avi", crossing_frames)
    _write_json(video_root / "identity-crossing-trajectories.json", crossing_tracks)
    return {
        "single_fish_frames": len(simple_frames),
        "identity_crossing_frames": len(crossing_frames),
        "identity_crossing_depths": {"fish-a": 0.8, "fish-b": 1.8},
    }


def _depth_fixtures(root: Path) -> dict[str, Any]:
    depth_root = root / "depth"
    depth_root.mkdir(parents=True, exist_ok=True)
    x = np.linspace(0.6, 1.8, _WIDTH, dtype=np.float32)
    metric = np.repeat(x[None, :], _HEIGHT, axis=0)
    relative = (metric - float(metric.min())) / float(metric.max() - metric.min())
    metric_path = depth_root / "metric-depth-metres.npy"
    relative_path = depth_root / "relative-depth.npy"
    np.save(metric_path, metric, allow_pickle=False)
    np.save(relative_path, relative.astype(np.float32), allow_pickle=False)
    preview = np.round((1.0 - relative) * 255).astype(np.uint8)
    Image.fromarray(preview, mode="L").save(depth_root / "relative-depth-preview.png")
    _write_json(
        depth_root / "camera-intrinsics.json",
        {
            "fx_px": 230.0,
            "fy_px": 232.0,
            "cx_px": _WIDTH / 2,
            "cy_px": _HEIGHT / 2,
            "underwater_calibration": False,
        },
    )
    return {
        "shape": [_HEIGHT, _WIDTH],
        "metric_min_metres": float(metric.min()),
        "metric_max_metres": float(metric.max()),
    }


def _interoperability_fixtures(root: Path) -> None:
    exchange = root / "interoperability"
    image_name = "synthetic-coral-00.png"
    coco = {
        "images": [{"id": 1, "file_name": image_name, "width": _WIDTH, "height": _HEIGHT}],
        "categories": [{"id": 1, "name": "synthetic coral"}],
        "annotations": [
            {
                "id": 1,
                "image_id": 1,
                "category_id": 1,
                "bbox": [40, 50, 80, 60],
                "area": 4800,
                "iscrowd": 0,
                "segmentation": [[40, 50, 120, 50, 120, 110, 40, 110]],
            }
        ],
    }
    _write_json(exchange / "coco" / "instances_validation.json", coco)

    labelme = {
        "version": "5.0.0",
        "imagePath": image_name,
        "imageHeight": _HEIGHT,
        "imageWidth": _WIDTH,
        "shapes": [
            {
                "label": "synthetic coral",
                "shape_type": "polygon",
                "points": [[40, 50], [120, 50], [120, 110], [40, 110]],
                "flags": {},
            }
        ],
    }
    _write_json(exchange / "labelme" / "synthetic-coral-00.json", labelme)

    yolo_root = exchange / "yolo"
    (yolo_root / "images" / "validation").mkdir(parents=True, exist_ok=True)
    (yolo_root / "labels" / "validation").mkdir(parents=True, exist_ok=True)
    shutil.copy2(root / "images" / image_name, yolo_root / "images" / "validation" / image_name)
    (yolo_root / "labels" / "validation" / "synthetic-coral-00.txt").write_text(
        "0 0.312500 0.416667 0.312500 0.312500\n",
        encoding="utf-8",
    )
    (yolo_root / "data.yaml").write_text(
        "path: .\ntrain: images/validation\nval: images/validation\nnames:\n  0: synthetic coral\n",
        encoding="utf-8",
    )

    annotations = Element("annotations")
    meta = SubElement(annotations, "meta")
    task = SubElement(meta, "task")
    labels = SubElement(task, "labels")
    label = SubElement(labels, "label")
    SubElement(label, "name").text = "synthetic coral"
    image = SubElement(
        annotations,
        "image",
        {"id": "0", "name": image_name, "width": str(_WIDTH), "height": str(_HEIGHT)},
    )
    SubElement(
        image,
        "polygon",
        {
            "label": "synthetic coral",
            "points": "40,50;120,50;120,110;40,110",
            "occluded": "0",
            "z_order": "0",
        },
    )
    cvat_path = exchange / "cvat" / "annotations.xml"
    cvat_path.parent.mkdir(parents=True, exist_ok=True)
    ElementTree(annotations).write(cvat_path, encoding="utf-8", xml_declaration=True)


def generate_synthetic_acceptance_dataset(
    root: Path,
    *,
    replace: bool = True,
) -> SyntheticAcceptanceManifest:
    """Generate all deterministic acceptance fixtures below *root*."""

    root = root.resolve()
    if replace and root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    images_root = root / "images"
    images_root.mkdir(parents=True, exist_ok=True)
    for index in range(3):
        _coral_image(index).save(images_root / f"synthetic-coral-{index:02d}.png", format="PNG")

    expected = {
        "geometry": _known_masks(root),
        "classification_counts": _classification_crops(root),
        "video": _video_fixtures(root),
        "depth": _depth_fixtures(root),
    }
    _interoperability_fixtures(root)

    files = tuple(
        path.relative_to(root).as_posix()
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name != "manifest.json"
    )
    checksums = {relative: _sha256(root / relative) for relative in files}
    manifest_payload = {
        "schema_version": 1,
        "generator": "reefvision.testing.synthetic_acceptance",
        "files": list(files),
        "checksums": checksums,
        "expected": expected,
    }
    manifest_path = root / "manifest.json"
    _write_json(manifest_path, manifest_payload)
    return SyntheticAcceptanceManifest(
        root=root.as_posix(),
        manifest_path=manifest_path.as_posix(),
        files=files,
        checksums=checksums,
        expected=expected,
    )


def manifest_as_dict(manifest: SyntheticAcceptanceManifest) -> dict[str, Any]:
    return asdict(manifest)
