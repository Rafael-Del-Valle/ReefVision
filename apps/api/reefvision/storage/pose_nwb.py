"""NWB storage bridge for the pinned SLEAP-IO 0.9.2 prediction codec.

SLEAP-IO omits visibility and original track names on read, reindexes sparse
frames, drops points with unknown confidence, and misreads regular time rates.
The standard ndx-pose series below carry the observations; NWB scratch metadata
preserves the missing semantics and is checksum-bound to the scientific payload.
Changed artifacts are rejected instead of silently restoring stale observations.
Only labeled decoded source frames are embedded, losslessly, in an ImageSeries.
External NWB without this mapping envelope is rejected: the pinned reader alone
cannot safely recover source-frame association from arbitrary NWB time series.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import math
import warnings
from pathlib import Path
from typing import Any

_METADATA = "reefvision_pose_interoperability"
_IMAGES = "reefvision_labeled_frames"


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _number(value: Any) -> float | None:
    return float(value) if value is not None and math.isfinite(float(value)) else None


def _checksum(path: Path, metadata: dict[str, Any]) -> str:
    """Bind restoration fields to all native scientific datasets and their units."""
    h5py = importlib.import_module("h5py")
    digest = hashlib.sha256(_json(metadata).encode())
    with h5py.File(path, "r") as handle:

        def visit(name: str, item: Any) -> None:
            if not isinstance(item, h5py.Dataset):
                return
            digest.update(name.encode())
            digest.update(str(item.shape).encode())
            digest.update(str(item.dtype).encode())
            data = item[()]
            if item.dtype.kind in {"O", "S", "U"}:
                digest.update(repr(data.tolist() if hasattr(data, "tolist") else data).encode())
            else:
                digest.update(data.tobytes())
            for key in sorted(item.attrs):
                digest.update(f"{key}={item.attrs[key]!r}".encode())

        for group in ("processing", "acquisition"):
            if group in handle:
                handle[group].visititems(visit)
    return digest.hexdigest()


def _replace(group: Any, name: str, values: Any, **attributes: Any) -> None:
    existing = dict(group[name].attrs) if name in group else {}
    if name in group:
        del group[name]
    dataset = group.create_dataset(name, data=values)
    dataset.attrs.update(existing | attributes)


def write_nwb(sio: Any, labels: Any, path: Path) -> None:
    """Write real ndx-pose NWB plus checksum-bound ReefVision semantics and media."""
    np = importlib.import_module("numpy")
    h5py = importlib.import_module("h5py")
    pynwb = importlib.import_module("pynwb")
    image_module = importlib.import_module("pynwb.image")
    if len(labels.videos) != 1 or len(labels.skeletons) != 1:
        raise ValueError("NWB export requires one source video and one skeleton")
    video, skeleton = labels.videos[0], labels.skeletons[0]
    fps = video.fps
    if fps is None or not math.isfinite(fps) or fps <= 0:
        raise ValueError("NWB export requires the source video's measured frame rate")
    frames = sorted(labels.labeled_frames, key=lambda frame: frame.frame_idx)
    if not frames or len({frame.frame_idx for frame in frames}) != len(frames):
        raise ValueError("NWB export requires nonempty, unique labeled source frames")
    records = []
    dense_frames = []
    images = []
    for index, frame in enumerate(frames):
        images.append(np.asarray(video[frame.frame_idx]))
        instances = []
        seen_tracks = set()
        for instance in frame.instances:
            if not isinstance(instance, sio.PredictedInstance) or instance.track is None:
                raise ValueError("NWB export requires tracked predicted instances")
            name = instance.track.name
            if name in seen_tracks:
                raise ValueError("NWB export cannot encode multiple instances of a track per frame")
            seen_tracks.add(name)
            instances.append(
                {
                    "track": name,
                    "xy": [[_number(x), _number(y)] for x, y in instance.points["xy"]],
                    "confidence": [_number(value) for value in instance.points["score"]],
                    "visible": instance.points["visible"].tolist(),
                    "complete": instance.points["complete"].tolist(),
                    "score": _number(instance.score),
                    "tracking_score": _number(instance.tracking_score),
                    "category": instance.category.name if instance.category else None,
                    "category_score": _number(instance.category_score),
                }
            )
        records.append({"frame": frame.frame_idx, "instances": instances})
        dense_frames.append(sio.LabeledFrame(video, index, frame.instances))
    metadata: dict[str, Any] = {
        "version": 1,
        "provenance": labels.provenance,
        "skeleton": {
            "name": skeleton.name,
            "nodes": skeleton.node_names,
            "edges": skeleton.edge_inds,
        },
        "records": records,
        "fps": fps,
        "source_filename": str(video.filename),
        "losses": [
            "NWB ndx-pose has no ReefVision visibility or repeated-landmark identity fields; "
            "these are preserved in checksum-bound NWB scratch metadata.",
            "SLEAP-IO 0.9.2 readers reindex sparse frames and discard original track names; "
            "ReefVision restores these only after verifying the scientific payload checksum.",
            "Only labeled decoded source frames are embedded; the original encoded video "
            "is not included. Association/correction audit survives only when supplied "
            "in provenance.",
            "Instance/category scores are retained in scratch metadata, outside ndx-pose series.",
        ],
    }
    dense_labels = sio.Labels(dense_frames, provenance=labels.provenance)
    # Pynwb 4 deprecates the legacy Device.manufacturer argument still supplied
    # by sleap-io 0.9.2. Restrict compatibility filtering to this exact warning
    # during the upstream writer call; all other dependency warnings remain live.
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="The 'manufacturer' field is deprecated.*",
            category=DeprecationWarning,
        )
        # ndx-pose 0.4 retains these legacy fields for reading 0.9.2 files.
        warnings.filterwarnings(
            "ignore",
            message="The '(devices|original_videos|labeled_videos)' "
            "constructor argument is deprecated.*",
            category=DeprecationWarning,
            module=r"ndx_pose\.pose",
        )
        sio.save_nwb(dense_labels, str(path), nwb_format="predictions")
    # Repair 0.9.2's sparse-frame/unknown-confidence conversion using native NWB
    # datasets, with explicit timestamps in seconds (never an invented sample rate).
    with h5py.File(path, "r+") as handle:
        # The upstream writer invents manufacturer="Unknown". Omit that optional
        # placeholder so modern pynwb readers do not need a deprecation filter.
        for device in handle["general/devices"].values():
            if device.attrs.get("manufacturer") == "Unknown":
                del device.attrs["manufacturer"]
        module = next(
            value for key, value in handle["processing"].items() if key.startswith("SLEAP_VIDEO")
        )
        for track_group in module.values():
            track_name = track_group.name.rsplit("/", 1)[-1].removeprefix("track=")
            for node_index, node_name in enumerate(skeleton.node_names):
                observations = [
                    (record["frame"], instance)
                    for record in records
                    for instance in record["instances"]
                    if instance["track"] == track_name
                    and all(value is not None for value in instance["xy"][node_index])
                ]
                series = track_group[node_name]
                xy = np.array(
                    [instance["xy"][node_index] for _, instance in observations], dtype=float
                ).reshape(-1, 2)
                confidence = np.array(
                    [instance["confidence"][node_index] for _, instance in observations],
                    dtype=float,
                )
                _replace(series, "data", xy)
                _replace(series, "confidence", confidence)
                if "starting_time" in series:
                    del series["starting_time"]
                _replace(
                    series,
                    "timestamps",
                    np.array([frame / fps for frame, _ in observations]),
                    interval=1,
                    unit="seconds",
                )
    with pynwb.NWBHDF5IO(str(path), "a", load_namespaces=True) as io:
        nwb = io.read()
        nwb.add_acquisition(
            image_module.ImageSeries(
                name=_IMAGES,
                data=np.stack(images),
                unit="pixels",
                format="raw",
                timestamps=np.array([frame.frame_idx / fps for frame in frames]),
                description="Losslessly stored decoded source frames; source indices in "
                + _METADATA,
            )
        )
        io.write(nwb)
    envelope = {"metadata": metadata, "sha256": _checksum(path, metadata)}
    with pynwb.NWBHDF5IO(str(path), "a", load_namespaces=True) as io:
        nwb = io.read()
        nwb.add_scratch(
            _json(envelope),
            name=_METADATA,
            description="Checksum-bound ReefVision pose semantics and conversion losses",
        )
        io.write(nwb)


def read_nwb(sio: Any, path: Path) -> Any:
    """Read with SLEAP-IO and restore only verified ReefVision mapping metadata."""
    np = importlib.import_module("numpy")
    pynwb = importlib.import_module("pynwb")
    with pynwb.NWBHDF5IO(str(path), "r", load_namespaces=True) as io:
        nwb = io.read()
        envelope = json.loads(nwb.scratch[_METADATA].data) if _METADATA in nwb.scratch else None
    if envelope is None:
        raise ValueError(
            "NWB import requires checksum-bound ReefVision source frame mapping metadata. "
            "SLEAP-IO 0.9.2 reindexes external NWB frames, so generic frame confirmation "
            "cannot safely restore them. Export NWB from ReefVision, or convert the source "
            "to SLP with verified frame indices before importing. Nothing was imported."
        )
    metadata = envelope["metadata"]
    if metadata.get("version") != 1:
        raise ValueError("Unsupported ReefVision NWB metadata version")
    if _checksum(path, metadata) != envelope["sha256"]:
        raise ValueError(
            "NWB scientific payload checksum differs from ReefVision metadata; "
            "refusing to restore stale observations"
        )
    sio.load_nwb(str(path))
    skeleton_data = metadata["skeleton"]
    skeleton = sio.Skeleton(
        nodes=skeleton_data["nodes"], edges=skeleton_data["edges"], name=skeleton_data["name"]
    )
    # Standard ImageSeries is directly readable by SLEAP's HDF5 backend. Supply
    # its sparse source-frame map in memory, without adding nonstandard NWB fields.
    video_module = importlib.import_module("sleap_io.io.video_reading")
    backend = video_module.HDF5Video(
        str(path), dataset=f"acquisition/{_IMAGES}/data", keep_open=False, grayscale=False
    )
    backend.frame_map = {record["frame"]: index for index, record in enumerate(metadata["records"])}
    backend.source_inds = np.array(list(backend.frame_map))
    backend.fps = metadata["fps"]
    video = sio.Video(filename=str(path), backend=backend)
    tracks: dict[str, Any] = {}
    categories: dict[str, Any] = {}
    frames = []
    for record in metadata["records"]:
        instances = []
        for stored in record["instances"]:
            track = tracks.setdefault(stored["track"], sio.Track(name=stored["track"]))
            category_name = stored["category"]
            category = (
                categories.setdefault(category_name, sio.Category(name=category_name))
                if category_name is not None
                else None
            )
            instance = sio.PredictedInstance.from_numpy(
                np.array(stored["xy"], dtype=float),
                skeleton=skeleton,
                point_scores=np.array(stored["confidence"], dtype=float),
                score=stored["score"] if stored["score"] is not None else float("nan"),
                track=track,
                tracking_score=stored["tracking_score"],
                category=category,
                category_score=stored["category_score"],
            )
            instance.points["visible"] = stored["visible"]
            instance.points["complete"] = stored["complete"]
            instances.append(instance)
        frames.append(sio.LabeledFrame(video, record["frame"], instances))
    provenance = dict(metadata["provenance"])
    provenance["reefvision_warnings"] = (
        list(provenance.get("reefvision_warnings", [])) + metadata["losses"]
    )
    return sio.Labels(frames, provenance=provenance)
