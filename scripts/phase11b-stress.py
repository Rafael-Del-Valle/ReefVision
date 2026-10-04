"""Phase 11B offline, persistence, and large-media acceptance.

The harness uses an isolated ReefVision data root under .artifacts, generates
deterministic synthetic media locally, blocks non-loopback Python socket access,
and verifies that persisted scientific/project state survives an application
restart. It is software/runtime evidence, not biological-performance evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import socket
import subprocess
import time
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from types import TracebackType
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from reefvision.config import Settings
from reefvision.db.base import Base
from reefvision.db.models import Job, ModelRegistration
from reefvision.jobs.project_exchange import process_project_exchange_export_job
from reefvision.jobs.worker import process_thumbnail_job, recover_interrupted_jobs
from reefvision.main import create_app
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.storage.results_packages import build_results_package, verify_results_package

SCHEMA_VERSION = "reefvision-phase11b-stress-0001"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require(response: Any, status: int) -> dict[str, Any]:
    if response.status_code != status:
        raise RuntimeError(
            f"API {response.request.method} {response.url} returned "
            f"{response.status_code}: {response.text}"
        )
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError(f"Expected object response from {response.request.url}")
    return dict(payload)


def is_loopback_host(host: object) -> bool:
    text = str(host).strip().strip("[]")
    if text.casefold() in {"localhost", "localhost.localdomain"}:
        return True
    try:
        return ipaddress.ip_address(text).is_loopback
    except ValueError:
        return False


class OfflineSocketGuard(AbstractContextManager["OfflineSocketGuard"]):
    """Reject non-loopback Python socket resolution/connections and record attempts."""

    def __init__(self) -> None:
        self.attempts: list[str] = []
        self._connect = socket.socket.connect
        self._create_connection = socket.create_connection
        self._getaddrinfo = socket.getaddrinfo

    def _reject(self, target: object) -> None:
        message = f"Blocked non-loopback network access during Phase 11B: {target!r}"
        self.attempts.append(message)
        raise OSError(message)

    def __enter__(self) -> "OfflineSocketGuard":
        guard = self

        def guarded_connect(sock: socket.socket, address: object) -> Any:
            if isinstance(address, tuple) and address:
                if not is_loopback_host(address[0]):
                    guard._reject(address)
            return guard._connect(sock, address)  # type: ignore[arg-type]

        def guarded_create_connection(
            address: tuple[str, int],
            timeout: float | object = socket._GLOBAL_DEFAULT_TIMEOUT,
            source_address: tuple[str, int] | None = None,
            *,
            all_errors: bool = False,
        ) -> socket.socket:
            if not is_loopback_host(address[0]):
                guard._reject(address)
            return guard._create_connection(
                address,
                timeout,  # type: ignore[arg-type]
                source_address,
                all_errors=all_errors,
            )

        def guarded_getaddrinfo(
            host: str | bytes | None,
            port: str | int | None,
            family: int = 0,
            type: int = 0,
            proto: int = 0,
            flags: int = 0,
        ) -> list[tuple[Any, ...]]:
            if host is not None and not is_loopback_host(host):
                guard._reject(host)
            return guard._getaddrinfo(host, port, family, type, proto, flags)

        socket.socket.connect = guarded_connect  # type: ignore[method-assign]
        socket.create_connection = guarded_create_connection
        socket.getaddrinfo = guarded_getaddrinfo
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool | None:
        socket.socket.connect = self._connect  # type: ignore[method-assign]
        socket.create_connection = self._create_connection
        socket.getaddrinfo = self._getaddrinfo
        return None


def generate_large_image(path: Path) -> dict[str, Any]:
    width = 6000
    height = 4000
    started = time.perf_counter()
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (width, height), (20, 90, 120)).save(
        path,
        format="TIFF",
        compression="raw",
    )
    return {
        "path": str(path),
        "width_px": width,
        "height_px": height,
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "generation_seconds": time.perf_counter() - started,
    }


def generate_large_video(path: Path) -> dict[str, Any]:
    import imageio_ffmpeg

    width = 2560
    height = 1440
    fps = 30
    duration = 12
    expected_frames = fps * duration
    executable = Path(imageio_ffmpeg.get_ffmpeg_exe())
    if not executable.is_file():
        raise RuntimeError(f"FFmpeg runtime is missing: {executable}")

    path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        str(executable),
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"testsrc2=size={width}x{height}:rate={fps}",
        "-t",
        str(duration),
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-crf",
        "30",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        "-y",
        str(path),
    ]
    started = time.perf_counter()
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not path.is_file():
        raise RuntimeError(
            "Synthetic stress video generation failed: "
            + (result.stderr.strip() or f"exit code {result.returncode}")
        )
    return {
        "path": str(path),
        "width_px": width,
        "height_px": height,
        "fps": fps,
        "duration_seconds": duration,
        "expected_frames": expected_frames,
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "generation_seconds": time.perf_counter() - started,
        "ffmpeg": str(executable),
    }


def small_png() -> bytes:
    stream = BytesIO()
    Image.new("RGB", (64, 48), (80, 30, 140)).save(stream, format="PNG")
    return stream.getvalue()


def results_run(project_id: str) -> dict[str, object]:
    return {
        "id": "phase11b-training-run",
        "project_id": project_id,
        "run_name": "Phase 11B persistence package",
        "status": "completed",
        "stage": "completed",
        "task": "detect",
        "provider_id": "ultralytics",
        "architecture": "yolo11n.yaml",
        "dataset_version_id": "phase11b-dataset",
        "dataset_manifest_sha256": "a" * 64,
        "split_manifest_sha256": "b" * 64,
        "initial_checkpoint_source": "scratch",
        "initial_checkpoint_model_id": None,
        "resolved_model_asset_id": "builtin_architecture:yolo11n.yaml",
        "resolved_model_checksum": None,
        "device": "cpu",
        "precision": "fp32",
        "random_seed": 42,
        "training_config": {"epochs": 3},
        "tuning_config": {"mode": "disabled"},
        "evaluation_config": {"split": "validation"},
        "tiling_config": {"mode": "none"},
        "resource_limits": {},
        "preflight_report": {"resource_snapshot": {"phase11b": True}},
        "draft_snapshot": {},
        "metrics": {"map50_95": 0.25},
        "metrics_history": {
            "epoch": [0, 1, 2],
            "metrics/mAP50-95(B)": [0.1, 0.2, 0.25],
        },
        "native_results_rows": [
            {"epoch": 0, "train/box_loss": 2.0, "metrics/mAP50-95(B)": 0.1},
            {"epoch": 1, "train/box_loss": 1.0, "metrics/mAP50-95(B)": 0.2},
            {"epoch": 2, "train/box_loss": 0.7, "metrics/mAP50-95(B)": 0.25},
        ],
        "tuning_results": None,
        "result_checkpoint_path": None,
        "warnings": [],
        "created_at": datetime.now(UTC).isoformat(),
        "started_at": datetime.now(UTC).isoformat(),
        "completed_at": datetime.now(UTC).isoformat(),
    }


def process_rss_bytes() -> int | None:
    try:
        import psutil

        return int(psutil.Process().memory_info().rss)
    except Exception:
        return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    output = args.output.resolve()
    if output.exists():
        raise RuntimeError(f"Phase 11B output already exists: {output}")
    output.mkdir(parents=True)

    state = output / "reefvision-data"
    source_root = output / "source-media"
    state.mkdir()
    source_root.mkdir()

    large_image = generate_large_image(source_root / "phase11b-large.tiff")
    large_video = generate_large_video(source_root / "phase11b-large.mp4")

    settings = Settings(
        env="acceptance",
        data_dir=state,
        database_url=f"sqlite:///{(state / 'reefvision.db').as_posix()}",
        web_origin="http://testserver",
        background_worker_enabled=False,
    )

    previous_offline = {
        key: os.environ.get(key)
        for key in (
            "HF_HUB_OFFLINE",
            "TRANSFORMERS_OFFLINE",
            "NO_PROXY",
            "no_proxy",
        )
    }
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["NO_PROXY"] = "*"
    os.environ["no_proxy"] = "*"

    started = time.perf_counter()
    rss_before = process_rss_bytes()
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            text=True,
        ).strip(),
        "isolated_data_root": str(state),
        "synthetic_media": {
            "establishes_biological_accuracy": False,
            "image": large_image,
            "video": large_video,
        },
        "checks": {},
    }

    try:
        with OfflineSocketGuard() as network_guard:
            app = create_app(settings)
            Base.metadata.create_all(app.state.engine)

            with TestClient(app) as client:
                health = client.get("/api/v1/health")
                if health.status_code != 200:
                    raise RuntimeError(f"Offline health check failed: {health.text}")

                project = require(
                    client.post(
                        "/api/v1/projects",
                        json={
                            "name": "Phase 11B isolated stress",
                            "template": "octocoral",
                        },
                    ),
                    201,
                )
                project_id = str(project["id"])

                image_started = time.perf_counter()
                with Path(large_image["path"]).open("rb") as stream:
                    image_response = client.post(
                        f"/api/v1/projects/{project_id}/imports/images",
                        files=[
                            (
                                "files",
                                (
                                    "phase11b-large.tiff",
                                    stream,
                                    "image/tiff",
                                ),
                            )
                        ],
                        data={"relative_paths": "stress/phase11b-large.tiff"},
                    )
                image_report = require(image_response, 200)
                if len(image_report["successful"]) != 1:
                    raise RuntimeError(f"Large image import failed: {image_report}")
                image_item = image_report["successful"][0]
                image_id = str(image_item["image_id"])
                image_record = require(client.get(f"/api/v1/images/{image_id}"), 200)
                if image_record["width_px"] != large_image["width_px"]:
                    raise RuntimeError("Large image width changed during import")
                if image_record["height_px"] != large_image["height_px"]:
                    raise RuntimeError("Large image height changed during import")

                managed_image = resolve_managed_project_path(
                    settings,
                    str(image_record["managed_path"]),
                )
                if sha256_file(managed_image) != large_image["sha256"]:
                    raise RuntimeError("Managed large image checksum differs from source")

                if not process_thumbnail_job(
                    settings,
                    app.state.session_factory,
                    str(image_item["thumbnail_job_id"]),
                ):
                    raise RuntimeError("Large image thumbnail generation failed")
                thumbnail = client.get(f"/api/v1/images/{image_id}/thumbnail")
                if thumbnail.status_code != 200:
                    raise RuntimeError("Large image thumbnail is not readable")

                annotation_session = require(
                    client.get(f"/api/v1/images/{image_id}/annotations"),
                    200,
                )
                label_id = str(project["label_classes"][0]["id"])
                annotation_id = str(uuid4())
                saved_annotation = require(
                    client.put(
                        f"/api/v1/images/{image_id}/annotations",
                        json={
                            "base_revision": annotation_session["image"]["annotation_revision"],
                            "annotation_status": "in_progress",
                            "annotations": [
                                {
                                    "id": annotation_id,
                                    "label_class_id": label_id,
                                    "x_min": 100.0,
                                    "y_min": 100.0,
                                    "x_max": 500.0,
                                    "y_max": 500.0,
                                }
                            ],
                            "mask_annotations": [],
                            "deleted_mask_annotation_ids": [],
                        },
                    ),
                    200,
                )
                if not any(
                    item["id"] == annotation_id
                    for item in saved_annotation["annotations"]
                ):
                    raise RuntimeError("Large-image annotation did not save")
                report["checks"]["large_image"] = {
                    "status": "PASS",
                    "import_seconds": time.perf_counter() - image_started,
                    "managed_size_bytes": managed_image.stat().st_size,
                    "source_sha256": large_image["sha256"],
                    "managed_sha256": sha256_file(managed_image),
                    "thumbnail_bytes": len(thumbnail.content),
                    "annotation_id": annotation_id,
                }

                video_started = time.perf_counter()
                with Path(large_video["path"]).open("rb") as stream:
                    video_response = client.post(
                        f"/api/v1/projects/{project_id}/imports/videos",
                        files={
                            "file": (
                                "phase11b-large.mp4",
                                stream,
                                "video/mp4",
                            )
                        },
                    )
                video_record = require(video_response, 201)
                video_id = str(video_record["id"])
                if video_record["width_px"] != large_video["width_px"]:
                    raise RuntimeError("Large video width changed during import")
                if video_record["height_px"] != large_video["height_px"]:
                    raise RuntimeError("Large video height changed during import")
                if video_record["frame_count"] < int(large_video["expected_frames"]) - 2:
                    raise RuntimeError("Large video frame count is unexpectedly low")
                managed_video = resolve_managed_project_path(
                    settings,
                    str(video_record["managed_path"]),
                )
                if sha256_file(managed_video) != large_video["sha256"]:
                    raise RuntimeError("Managed large video checksum differs from source")
                report["checks"]["large_video"] = {
                    "status": "PASS",
                    "import_seconds": time.perf_counter() - video_started,
                    "managed_size_bytes": managed_video.stat().st_size,
                    "source_sha256": large_video["sha256"],
                    "managed_sha256": sha256_file(managed_video),
                    "frame_count": video_record["frame_count"],
                    "fps": video_record["fps"],
                    "duration_seconds": video_record["duration_seconds"],
                }

                interruption = client.post(
                    f"/api/v1/projects/{project_id}/imports/images",
                    files=[
                        (
                            "files",
                            (
                                "restart-probe.png",
                                small_png(),
                                "image/png",
                            ),
                        )
                    ],
                    data={"relative_paths": "restart/restart-probe.png"},
                )
                interruption_report = require(interruption, 200)
                interrupted_job_id = str(
                    interruption_report["successful"][0]["thumbnail_job_id"]
                )
                with app.state.session_factory() as session:
                    interrupted_job = session.get(Job, interrupted_job_id)
                    if interrupted_job is None:
                        raise RuntimeError("Restart probe job disappeared")
                    interrupted_job.status = "running"
                    session.commit()

                model_id = str(uuid4())
                model_payload = b"phase11b-model-checkpoint"
                model_relative = (
                    f"{project['storage_root']}/models/{model_id}.pt"
                )
                model_path = resolve_managed_project_path(
                    settings,
                    model_relative,
                )
                model_path.parent.mkdir(parents=True, exist_ok=True)
                model_path.write_bytes(model_payload)
                model_sha = hashlib.sha256(model_payload).hexdigest()
                with app.state.session_factory() as session:
                    session.add(
                        ModelRegistration(
                            id=model_id,
                            project_id=project_id,
                            purpose="detector",
                            display_name="Phase 11B persistence model",
                            source_filename="phase11b.pt",
                            managed_path=model_relative,
                            sha256=model_sha,
                            file_size_bytes=len(model_payload),
                            framework="ultralytics",
                            task="detect",
                            provider_name="ultralytics",
                            provider_version="8.3.228",
                            class_map_json={
                                "labels": ["phase11b"],
                                "mapping": {},
                            },
                            input_size_json={"width": 640, "height": 640},
                            metadata_json={
                                "phase11b": True,
                                "trusted_fixture": True,
                            },
                        )
                    )
                    session.commit()

                native_artifact = output / "native" / "results.txt"
                native_artifact.parent.mkdir()
                native_artifact.write_text(
                    "phase11b native artifact\n",
                    encoding="utf-8",
                )
                package_result = build_results_package(
                    export_root=output / "results-packages",
                    run=results_run(project_id),
                    project={
                        "id": project_id,
                        "name": project["name"],
                        "slug": "phase11b",
                    },
                    dataset={
                        "id": "phase11b-dataset",
                        "name": "Phase 11B dataset",
                        "class_map": [
                            {
                                "class_index": 0,
                                "name": "phase11b",
                            }
                        ],
                    },
                    dataset_items=[
                        {
                            "image_id": image_id,
                            "original_filename": "phase11b-large.tiff",
                            "split": "train",
                            "group_key": "stress",
                        }
                    ],
                    source_artifacts=[
                        (
                            {
                                "name": "results.txt",
                                "category": "log",
                            },
                            native_artifact,
                        )
                    ],
                    options={
                        "include_excel": True,
                        "include_machine_data": True,
                        "include_native_artifacts": True,
                        "include_logs": True,
                        "checkpoint_mode": "none",
                    },
                )
                package_dir = (
                    output
                    / "results-packages"
                    / str(package_result["package_name"])
                )
                package_verification = verify_results_package(package_dir)
                if package_verification["valid"] is not True:
                    raise RuntimeError(
                        f"Results Package verification failed: {package_verification}"
                    )

                exchange_response = client.post(
                    f"/api/v1/projects/{project_id}/exchange-packages",
                    json={
                        "include_media": True,
                        "include_model_weights": False,
                        "include_generated_artifacts": True,
                        "notes": "Phase 11B restart stress",
                    },
                )
                exchange = require(exchange_response, 202)
                if not process_project_exchange_export_job(
                    settings,
                    app.state.session_factory,
                    str(exchange["job_id"]),
                ):
                    raise RuntimeError("Project Exchange export failed")
                package_record = require(
                    client.get(
                        f"/api/v1/exchange-packages/{exchange['package']['id']}"
                    ),
                    200,
                )
                exchange_archive = (
                    settings.resolved_data_dir
                    / Path(str(package_record["archive_path"]))
                )
                if not exchange_archive.is_file():
                    raise RuntimeError("Project Exchange archive is missing")
                exchange_sha = sha256_file(exchange_archive)

            app.state.engine.dispose()

            restart_app = create_app(settings)
            with TestClient(restart_app) as restart_client:
                recovered_count = recover_interrupted_jobs(
                    restart_app.state.session_factory,
                    settings,
                )
                if recovered_count < 1:
                    raise RuntimeError("Interrupted job was not recovered")
                recovered_job = require(
                    restart_client.get(f"/api/v1/jobs/{interrupted_job_id}"),
                    200,
                )
                if recovered_job["status"] != "queued":
                    raise RuntimeError(
                        f"Interrupted job recovery state was {recovered_job['status']}"
                    )

                persisted_project = require(
                    restart_client.get(f"/api/v1/projects/{project_id}"),
                    200,
                )
                if str(persisted_project["id"]) != project_id:
                    raise RuntimeError("Project ID changed after restart")

                persisted_image = require(
                    restart_client.get(f"/api/v1/images/{image_id}"),
                    200,
                )
                if persisted_image["sha256"] != large_image["sha256"]:
                    raise RuntimeError("Large image identity changed after restart")

                persisted_annotations = require(
                    restart_client.get(f"/api/v1/images/{image_id}/annotations"),
                    200,
                )
                if not any(
                    item["id"] == annotation_id
                    for item in persisted_annotations["annotations"]
                ):
                    raise RuntimeError("Annotation did not persist after restart")

                persisted_video = require(
                    restart_client.get(f"/api/v1/videos/{video_id}"),
                    200,
                )
                if persisted_video["sha256"] != large_video["sha256"]:
                    raise RuntimeError("Large video identity changed after restart")

                with restart_app.state.session_factory() as session:
                    persisted_model = session.get(ModelRegistration, model_id)
                    if persisted_model is None:
                        raise RuntimeError("Registered model did not persist after restart")
                    if persisted_model.sha256 != model_sha:
                        raise RuntimeError("Registered model checksum changed after restart")
                    persisted_model_path = resolve_managed_project_path(
                        settings,
                        persisted_model.managed_path,
                    )
                    if sha256_file(persisted_model_path) != model_sha:
                        raise RuntimeError(
                            "Registered model file changed after restart"
                        )

                restarted_package = verify_results_package(package_dir)
                if restarted_package["valid"] is not True:
                    raise RuntimeError(
                        "Results Package failed verification after restart"
                    )

                with exchange_archive.open("rb") as stream:
                    inspected = restart_client.post(
                        "/api/v1/exchange-packages/inspect",
                        files={
                            "file": (
                                "phase11b.reefvision.zip",
                                stream,
                                "application/zip",
                            )
                        },
                    )
                inspection = require(inspected, 200)
                if inspection["compatible"] is not True:
                    raise RuntimeError(
                        f"Project Exchange failed inspection after restart: {inspection}"
                    )
                if sha256_file(exchange_archive) != exchange_sha:
                    raise RuntimeError(
                        "Project Exchange archive checksum changed after restart"
                    )

                report["checks"]["restart_persistence"] = {
                    "status": "PASS",
                    "recovered_job_id": interrupted_job_id,
                    "recovered_job_status": recovered_job["status"],
                    "recovered_count": recovered_count,
                    "project_id": project_id,
                    "image_id": image_id,
                    "annotation_id": annotation_id,
                    "video_id": video_id,
                    "model_id": model_id,
                    "model_sha256": model_sha,
                }
                report["checks"]["results_package"] = {
                    "status": "PASS",
                    "package_directory": str(package_dir),
                    "archive_path": package_result.get("archive_path"),
                    "verification_checked_files": restarted_package.get(
                        "checked_files"
                    ),
                }
                report["checks"]["project_exchange"] = {
                    "status": "PASS",
                    "archive_path": str(exchange_archive),
                    "archive_size_bytes": exchange_archive.stat().st_size,
                    "archive_sha256": exchange_sha,
                    "inspection_compatible": inspection["compatible"],
                }

            restart_app.state.engine.dispose()

            if network_guard.attempts:
                raise RuntimeError(
                    "Local Phase 11B workflow attempted external network access: "
                    + "; ".join(network_guard.attempts)
                )
            report["checks"]["offline_local_workflow"] = {
                "status": "PASS",
                "non_loopback_socket_attempts": 0,
                "guard": (
                    "Python socket connect/create_connection/getaddrinfo blocked "
                    "for non-loopback hosts"
                ),
                "hf_hub_offline": True,
                "transformers_offline": True,
            }

        report["status"] = "PASS"
    finally:
        for key, value in previous_offline.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    report["rss_before_bytes"] = rss_before
    report["rss_after_bytes"] = process_rss_bytes()
    report["total_seconds"] = time.perf_counter() - started
    report_path = output / "report.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(report_path)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("status") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
