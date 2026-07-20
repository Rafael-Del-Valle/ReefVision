"""Managed SAM 2 video-mask propagation job execution."""

from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np
from numpy.typing import NDArray
from PIL import Image
from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import Job, ModelRegistration, Project, VideoAsset
from reefvision.domain.errors import ValidationError
from reefvision.ml.sam_adapters import infer_sam2_config
from reefvision.storage.projects import resolve_managed_project_path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _device(requested: str) -> str:
    normalized = requested.strip().casefold()
    try:
        import torch
    except Exception as exc:
        raise ValidationError(f"SAM 2 requires torch: {exc}") from exc
    if normalized in {"", "auto", "cuda", "gpu"}:
        return "cuda:0" if torch.cuda.is_available() else "cpu"
    if normalized.startswith("cuda") and not torch.cuda.is_available():
        raise ValidationError("CUDA was requested but is unavailable")
    return requested


def _extract_frames(
    source: Path,
    destination: Path,
    *,
    every_n_frames: int,
    maximum_frames: int | None,
) -> list[int]:
    try:
        import cv2
    except Exception as exc:
        raise ValidationError(f"SAM 2 video propagation requires OpenCV: {exc}") from exc
    destination.mkdir(parents=True, exist_ok=True)
    capture = cv2.VideoCapture(str(source))
    if not capture.isOpened():
        raise ValidationError("The managed video could not be opened")
    original_indices: list[int] = []
    source_index = 0
    written = 0
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            if source_index % every_n_frames == 0:
                output = destination / f"{written:06d}.jpg"
                if not cv2.imwrite(str(output), frame):
                    raise ValidationError("A temporary SAM 2 frame could not be written")
                original_indices.append(source_index)
                written += 1
                if maximum_frames is not None and written >= maximum_frames:
                    break
            source_index += 1
    finally:
        capture.release()
    if not original_indices:
        raise ValidationError("No frames were extracted from the managed video")
    return original_indices


def _seed_predictor(
    predictor: Any,
    state: Any,
    *,
    frame_index: int,
    object_id: int,
    positive_points: list[dict[str, float]],
    negative_points: list[dict[str, float]],
    prompt_box: dict[str, float] | None,
) -> None:
    points = np.asarray(
        [[point["x"], point["y"]] for point in [*positive_points, *negative_points]],
        dtype=np.float32,
    )
    labels = np.asarray(
        [1] * len(positive_points) + [0] * len(negative_points),
        dtype=np.int32,
    )
    box = (
        np.asarray(
            [
                prompt_box["x_min"],
                prompt_box["y_min"],
                prompt_box["x_max"],
                prompt_box["y_max"],
            ],
            dtype=np.float32,
        )
        if prompt_box is not None
        else None
    )
    kwargs = {
        "inference_state": state,
        "frame_idx": frame_index,
        "obj_id": object_id,
        "points": points,
        "labels": labels,
    }
    if box is not None:
        kwargs["box"] = box
    try:
        predictor.add_new_points_or_box(**kwargs)
    except TypeError:
        kwargs.pop("box", None)
        predictor.add_new_points_or_box(**kwargs)


def _write_mask(path: Path, mask: NDArray[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(mask.astype(np.uint8) * 255, mode="L").save(path, format="PNG")


def process_sam2_video_propagation_job(
    settings: Settings,
    factory: sessionmaker[Session],
    job_id: str,
) -> bool:
    with factory() as session:
        job = session.get(Job, job_id)
        if job is None or job.job_type != "sam2_video_propagation" or job.status != "queued":
            return False
        request = dict(job.request_json)
        video = session.get(VideoAsset, str(request.get("video_id", "")))
        model = session.get(ModelRegistration, str(request.get("model_id", "")))
        project = session.get(Project, video.project_id) if video is not None else None
        if video is None or model is None or project is None:
            job.status = "failed"
            job.error_message = "SAM 2 propagation references missing records"
            job.completed_at = datetime.now(UTC)
            session.commit()
            return False
        job.status = "running"
        job.started_at = datetime.now(UTC)
        job.heartbeat_at = job.started_at
        job.error_message = None
        job.result_json = {"stage": "extracting_frames"}
        session.commit()
        video_path = resolve_managed_project_path(settings, video.managed_path)
        model_path = resolve_managed_project_path(settings, model.managed_path)
        relative_root = f"{project.storage_root}/video-propagation/{job.id}"
        output_root = resolve_managed_project_path(settings, relative_root)

    temporary_root = output_root.with_name(f".{output_root.name}.{uuid4().hex[:8]}.tmp")
    frames_dir = temporary_root / "frames"
    try:
        if not video_path.is_file() or not model_path.is_file():
            raise ValidationError("The managed video or SAM 2 checkpoint is missing")
        temporary_root.mkdir(parents=True, exist_ok=False)
        original_indices = _extract_frames(
            video_path,
            frames_dir,
            every_n_frames=int(request.get("every_n_frames", 1)),
            maximum_frames=(
                int(request["maximum_frames"])
                if request.get("maximum_frames") is not None
                else None
            ),
        )
        sampled_seed_index = min(
            range(len(original_indices)),
            key=lambda index: abs(
                original_indices[index] - int(request.get("seed_frame_index", 0))
            ),
        )
        with factory() as session:
            job = session.get(Job, job_id)
            if job is None:
                return False
            job.progress_total = len(original_indices)
            job.result_json = {
                "stage": "loading_model",
                "extracted_frame_count": len(original_indices),
            }
            session.commit()

        try:
            from sam2.build_sam import build_sam2_video_predictor
        except Exception as exc:
            raise ValidationError(f"SAM 2 video predictor is unavailable: {exc}") from exc
        resolved_device = _device(str(request.get("device", "auto")))
        config = infer_sam2_config(model_path)
        predictor = build_sam2_video_predictor(
            config,
            str(model_path),
            device=resolved_device,
        )
        state = predictor.init_state(video_path=str(frames_dir))
        if hasattr(predictor, "reset_state"):
            predictor.reset_state(state)
        _seed_predictor(
            predictor,
            state,
            frame_index=sampled_seed_index,
            object_id=int(request.get("object_id", 1)),
            positive_points=list(request.get("positive_points") or []),
            negative_points=list(request.get("negative_points") or []),
            prompt_box=(
                dict(request["prompt_box"]) if isinstance(request.get("prompt_box"), dict) else None
            ),
        )

        manifest_frames: list[dict[str, Any]] = []
        preview_every = int(request.get("preview_every_n_frames", 30))
        object_id = int(request.get("object_id", 1))
        for completed, item in enumerate(predictor.propagate_in_video(state), start=1):
            sampled_index, object_ids, mask_logits = item
            object_ids_list = [int(value) for value in np.asarray(object_ids).reshape(-1)]
            if object_id not in object_ids_list:
                continue
            object_position = object_ids_list.index(object_id)
            logits = mask_logits[object_position]
            if hasattr(logits, "detach"):
                logits = logits.detach().float().cpu().numpy()
            mask = np.asarray(logits).squeeze() > 0.0
            original_index = original_indices[int(sampled_index)]
            relative_mask = f"masks/frame-{original_index:08d}.png"
            mask_path = temporary_root / relative_mask
            _write_mask(mask_path, mask)
            preview_path: str | None = None
            if completed == 1 or completed % preview_every == 0:
                preview_path = f"previews/frame-{original_index:08d}.png"
                _write_mask(temporary_root / preview_path, mask)
            manifest_frames.append(
                {
                    "sampled_frame_index": int(sampled_index),
                    "source_frame_index": original_index,
                    "mask_path": relative_mask,
                    "mask_sha256": _sha256(mask_path),
                    "area_pixels": int(mask.sum()),
                    "preview_path": preview_path,
                }
            )
            with factory() as session:
                job = session.get(Job, job_id)
                if job is None:
                    return False
                if job.status == "cancel_requested":
                    job.status = "cancelled"
                    job.completed_at = datetime.now(UTC)
                    job.result_json = {"stage": "cancelled"}
                    session.commit()
                    shutil.rmtree(temporary_root, ignore_errors=True)
                    return True
                job.progress_current = min(completed, len(original_indices))
                job.heartbeat_at = datetime.now(UTC)
                job.checkpoint_json = {
                    "last_sampled_frame_index": int(sampled_index),
                    "mask_count": len(manifest_frames),
                }
                job.result_json = {
                    "stage": "propagating",
                    "mask_count": len(manifest_frames),
                    "device": resolved_device,
                }
                session.commit()

        manifest = {
            "format": "reefvision-sam2-video-masks",
            "format_version": "1.0",
            "created_at": datetime.now(UTC).isoformat(),
            "job_id": job_id,
            "video_id": video.id,
            "video_sha256": video.sha256,
            "model_id": model.id,
            "model_sha256": model.sha256,
            "provider": "sam2",
            "configuration": config,
            "device": resolved_device,
            "object_id": object_id,
            "seed_source_frame_index": int(request.get("seed_frame_index", 0)),
            "seed_sampled_frame_index": sampled_seed_index,
            "every_n_frames": int(request.get("every_n_frames", 1)),
            "frames": manifest_frames,
        }
        manifest_path = temporary_root / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
        archive_path = temporary_root / "sam2-video-masks.zip"
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(manifest_path, "manifest.json")
            for frame in manifest_frames:
                archive.write(temporary_root / frame["mask_path"], frame["mask_path"])
                if frame["preview_path"]:
                    archive.write(temporary_root / frame["preview_path"], frame["preview_path"])
        shutil.rmtree(frames_dir, ignore_errors=True)
        output_root.parent.mkdir(parents=True, exist_ok=True)
        if output_root.exists():
            shutil.rmtree(output_root)
        temporary_root.replace(output_root)
        archive_relative = f"{relative_root}/sam2-video-masks.zip"
        manifest_relative = f"{relative_root}/manifest.json"
        final_archive = output_root / "sam2-video-masks.zip"
        with factory() as session:
            job = session.get(Job, job_id)
            if job is None:
                return False
            job.status = "succeeded"
            job.progress_current = len(original_indices)
            job.progress_total = len(original_indices)
            job.completed_at = datetime.now(UTC)
            job.heartbeat_at = job.completed_at
            job.result_json = {
                "stage": "completed",
                "archive_path": archive_relative,
                "archive_sha256": _sha256(final_archive),
                "archive_size_bytes": final_archive.stat().st_size,
                "manifest_path": manifest_relative,
                "mask_count": len(manifest_frames),
                "sampled_frame_count": len(original_indices),
                "device": resolved_device,
            }
            session.commit()
        return True
    except Exception as exc:
        shutil.rmtree(temporary_root, ignore_errors=True)
        with factory() as session:
            job = session.get(Job, job_id)
            if job is not None:
                job.status = "failed"
                job.error_message = str(exc)
                job.completed_at = datetime.now(UTC)
                job.result_json = {"stage": "failed", "error": str(exc)}
                session.commit()
        return False
