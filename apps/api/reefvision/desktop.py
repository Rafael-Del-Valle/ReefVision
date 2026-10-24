"""Desktop sidecar entrypoint for the packaged ReefVision backend."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import subprocess
import sys
import threading
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, TextIO, cast

import uvicorn
from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

from reefvision.config import Settings, clear_settings_cache, get_settings
from reefvision.db.migration_lineage_guard import assert_compatible_revision_0038
from reefvision.logging_utils import configure_rotating_json_logging

LOGGER = logging.getLogger("reefvision.desktop")
_WINDOWED_STREAMS: list[TextIO] = []
SELF_TEST_RESULT_FILENAME = "self-test-result.json"


class SupportsShouldExit(Protocol):
    should_exit: bool


@dataclass(frozen=True)
class DesktopLaunchOptions:
    host: str
    port: int
    data_dir: Path
    log_file: Path | None
    context_file: Path | None
    run_migrations: bool
    safe_mode: bool = False
    self_test: bool = False
    provider_hardware_acceptance: bool = False
    video_tracking_job: str | None = None
    annotated_video_export_job: str | None = None


def parse_args(argv: Sequence[str] | None = None) -> DesktopLaunchOptions:
    parser = argparse.ArgumentParser(description="Run the ReefVision desktop API sidecar")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--data-dir", type=Path, default=Path(".reefvision"))
    parser.add_argument("--log-file", type=Path, default=None)
    parser.add_argument("--context-file", type=Path, default=None)
    parser.add_argument("--skip-migrations", action="store_false", dest="run_migrations")
    parser.add_argument(
        "--safe-mode",
        action="store_true",
        help="Start without background job processing",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help=(
            "Validate packaged migrations, ML provider imports, Scale Assistant marker "
            "runtime, and FastAPI/OpenAPI construction, then exit without starting the "
            "API server"
        ),
    )
    parser.add_argument(
        "--provider-hardware-acceptance",
        action="store_true",
        help=(
            "Run packaged CPU/CUDA provider acceptance using installer-bundled "
            "checkpoints, write evidence into the selected data directory, and exit"
        ),
    )
    parser.add_argument(
        "--video-tracking-job",
        default=None,
        help="Process one queued video-tracking job and exit",
    )
    parser.add_argument(
        "--annotated-video-export-job",
        default=None,
        help="Process one queued annotated-video export job and exit",
    )
    namespace = parser.parse_args(argv)
    return DesktopLaunchOptions(
        host=namespace.host,
        port=namespace.port,
        data_dir=namespace.data_dir,
        log_file=namespace.log_file,
        context_file=namespace.context_file,
        run_migrations=namespace.run_migrations,
        safe_mode=namespace.safe_mode,
        self_test=namespace.self_test,
        provider_hardware_acceptance=namespace.provider_hardware_acceptance,
        video_tracking_job=namespace.video_tracking_job,
        annotated_video_export_job=namespace.annotated_video_export_job,
    )


def project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def is_frozen_bundle() -> bool:
    return bool(vars(sys).get("frozen", False))


def configure_windows_event_loop_policy() -> None:
    """Use the selector event loop for the frozen Windows API sidecar."""
    if sys.platform != "win32" or not is_frozen_bundle():
        return

    policy_factory = getattr(asyncio, "WindowsSelectorEventLoopPolicy", None)
    if policy_factory is None:
        LOGGER.warning("Windows selector event loop policy is unavailable")
        return

    asyncio.set_event_loop_policy(policy_factory())


def resolve_alembic_paths(resource_root: Path | None = None) -> tuple[Path, Path]:
    root = resource_root or (
        Path(str(vars(sys)["_MEIPASS"])).resolve() if is_frozen_bundle() else project_root()
    )
    if is_frozen_bundle():
        alembic_root = root / "alembic"
        return alembic_root / "alembic.ini", alembic_root / "migrations"
    api_root = root / "apps" / "api"
    return api_root / "alembic.ini", api_root / "migrations"


def configure_logging(log_file: Path | None) -> None:
    if log_file is None:
        return
    configure_rotating_json_logging(
        log_file,
        default_component="desktop",
        max_bytes=1_048_576,
        backup_count=5,
    )


def ensure_standard_streams() -> None:
    for stream_name in ("stdout", "stderr"):
        if getattr(sys, stream_name, None) is None:
            stream = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
            _WINDOWED_STREAMS.append(stream)
            setattr(sys, stream_name, stream)


def apply_desktop_environment(options: DesktopLaunchOptions) -> None:
    os.environ["REEFVISION_ENV"] = "desktop"
    os.environ["REEFVISION_API_HOST"] = options.host
    os.environ["REEFVISION_API_PORT"] = str(options.port)
    os.environ["REEFVISION_DATA_DIR"] = str(options.data_dir)
    os.environ["REEFVISION_SAFE_MODE"] = "true" if options.safe_mode else "false"
    os.environ["REEFVISION_BACKGROUND_WORKER_ENABLED"] = "false" if options.safe_mode else "true"
    clear_settings_cache()


def build_settings(options: DesktopLaunchOptions) -> Settings:
    apply_desktop_environment(options)
    return get_settings()


def write_runtime_port(context_file: Path | None, port: int) -> None:
    if context_file is None:
        return
    context_file.parent.mkdir(parents=True, exist_ok=True)
    temporary = context_file.with_suffix(context_file.suffix + ".tmp")
    temporary.write_text(f"{port}\n", encoding="utf-8")
    os.replace(temporary, context_file)


def request_server_shutdown(server: object, reason: str) -> None:
    managed_server = cast(SupportsShouldExit, server)
    if getattr(managed_server, "should_exit", False):
        return
    LOGGER.info(reason)
    managed_server.should_exit = True


def watch_shutdown_stream(stream: TextIO, server: object) -> None:
    while not getattr(server, "should_exit", False):
        line = stream.readline()
        if line == "":
            request_server_shutdown(
                server,
                "ReefVision desktop closed the sidecar control channel; requesting shutdown",
            )
            return
        if line.strip().lower() == "shutdown":
            request_server_shutdown(server, "ReefVision desktop requested backend shutdown")
            return


def start_shutdown_monitor(
    server: uvicorn.Server,
    stream: TextIO | None = None,
) -> threading.Thread | None:
    shutdown_stream = stream or sys.stdin
    if shutdown_stream is None:
        return None

    thread = threading.Thread(
        target=watch_shutdown_stream,
        args=(shutdown_stream, server),
        name="reefvision-desktop-shutdown",
        daemon=True,
    )
    thread.start()
    return thread


def preload_frozen_windows_scipy_native() -> None:
    """Initialize native SciPy BLAS and ARPACK before starting the API server.

    Frozen Windows SAM2 imports have stalled while loading native extensions
    lazily from a request worker. Preload both observed problematic modules
    on the desktop main thread, before the shutdown-pipe reader starts.
    Non-frozen and non-Windows Python runtimes remain unchanged.
    """
    if sys.platform != "win32" or not is_frozen_bundle():
        return

    LOGGER.info("Preloading SciPy BLAS on Windows before shutdown reader starts")
    from scipy.linalg import blas as scipy_blas  # type: ignore[import-untyped]

    LOGGER.info("SciPy BLAS preloaded: %s", scipy_blas.__name__)
    LOGGER.info("Preloading SciPy sparse.linalg ARPACK on Windows")
    from scipy.sparse.linalg import eigsh  # type: ignore[import-untyped]

    LOGGER.info("SciPy ARPACK preloaded: %s", eigsh.__name__)


def run_pending_migrations(settings: Settings) -> None:
    alembic_ini, migrations_dir = resolve_alembic_paths()
    config = Config(str(alembic_ini))
    config.attributes["configure_logger"] = False
    # Pin Alembic to the exact database that the desktop preflight and
    # post-upgrade checks inspect; env.py must not re-resolve this URL.
    config.attributes["desktop_database_url"] = settings.resolved_database_url
    config.set_main_option("script_location", str(migrations_dir))
    config.set_main_option("sqlalchemy.url", settings.resolved_database_url)

    from reefvision.db.session import create_database_engine

    script = ScriptDirectory.from_config(config)
    expected_revision = script.get_current_head()
    if expected_revision is None:
        raise RuntimeError(
            "ReefVision desktop has no packaged Alembic migration head; "
            "refusing to start with an unverifiable database schema."
        )

    engine = create_database_engine(settings)
    try:
        with engine.connect() as connection:
            # A matching revision number alone cannot distinguish the two 0038 lineages.
            # Check even when no upgrade would otherwise be attempted.
            assert_compatible_revision_0038(connection)
            current_revision = MigrationContext.configure(connection).get_current_revision()
    finally:
        engine.dispose()

    if expected_revision is not None and current_revision == expected_revision:
        LOGGER.info(
            "Database schema already at Alembic head %s; skipping upgrade",
            expected_revision,
        )
        return

    command.upgrade(config, "head")

    # An upgrade call is not proof that the intended database was migrated.
    # Reopen the desktop database and verify the exact revision before serving
    # write requests. Never stamp or mutate a mismatched database here.
    verification_engine = create_database_engine(settings)
    try:
        with verification_engine.connect() as connection:
            assert_compatible_revision_0038(connection)
            verified_revision = MigrationContext.configure(connection).get_current_revision()
    finally:
        verification_engine.dispose()
    if verified_revision != expected_revision:
        raise RuntimeError(
            "ReefVision desktop migration did not reach the expected Alembic "
            f"revision {expected_revision!r} (observed {verified_revision!r}); "
            "refusing to start the API until the database is reconciled."
        )


def require_scale_assistant_marker_runtime() -> None:
    """Require the packaged OpenCV contrib marker module used by Scale Assistant."""

    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError(
            "Packaged ReefVision is missing OpenCV required by Scale Assistant"
        ) from exc
    if not hasattr(cv2, "aruco"):
        raise RuntimeError(
            "Packaged OpenCV does not expose cv2.aruco; ReefVision requires the "
            "opencv-contrib runtime for ArUco/ChArUco Scale Assistant calibration"
        )


def write_self_test_result(
    data_dir: Path,
    *,
    version: str,
    openapi_path_count: int,
) -> Path:
    """Write deterministic machine-readable evidence for packaged self-test success."""
    result_path = data_dir / SELF_TEST_RESULT_FILENAME
    result_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = result_path.with_suffix(result_path.suffix + ".tmp")
    payload = {
        "status": "PASS",
        "application_version": version,
        "openapi_path_count": openapi_path_count,
    }
    temporary.write_text(
        json.dumps(payload, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, result_path)
    return result_path


def run_single_video_tracking_job(
    settings: Settings,
    job_id: str,
) -> int:
    """Process one isolated video-tracking job and exit."""

    from reefvision.db.session import (
        create_database_engine,
        create_session_factory,
    )
    from reefvision.jobs.video_tracking import process_video_tracking_job
    from reefvision.ml.dependencies import configure_provider_runtime

    configure_provider_runtime(settings)

    engine = create_database_engine(settings)
    factory = create_session_factory(engine)

    try:
        LOGGER.info(
            "Starting isolated video tracking job %s",
            job_id,
        )
        processed = process_video_tracking_job(
            settings,
            factory,
            job_id,
        )
        LOGGER.info(
            "Isolated video tracking job %s exited; processed=%s",
            job_id,
            processed,
        )
        return 0 if processed else 1
    finally:
        engine.dispose()


def run_single_annotated_video_export_job(
    settings: Settings,
    job_id: str,
) -> int:
    """Process one isolated annotated-video export job and exit."""

    from reefvision.db.session import create_database_engine, create_session_factory
    from reefvision.jobs.video_annotated_export import process_video_annotated_export_job

    engine = create_database_engine(settings)
    factory = create_session_factory(engine)
    try:
        LOGGER.info("Starting isolated annotated-video export job %s", job_id)
        processed = process_video_annotated_export_job(settings, factory, job_id)
        LOGGER.info(
            "Isolated annotated-video export job %s exited; processed=%s",
            job_id,
            processed,
        )
        return 0 if processed else 1
    finally:
        engine.dispose()


def require_annotated_video_encoder_runtime() -> None:
    """Require ReefVision's packaged libx264 annotated-video encoder."""

    try:
        import imageio_ffmpeg  # type: ignore[import-untyped]
    except ImportError as exc:
        raise RuntimeError(
            "Packaged ReefVision is missing imageio-ffmpeg required "
            "for H.264 annotated-video exports"
        ) from exc

    executable = Path(imageio_ffmpeg.get_ffmpeg_exe())

    if not executable.is_file():
        raise RuntimeError(
            f"Packaged ReefVision could not locate its FFmpeg executable: {executable}"
        )

    creationflags = (
        int(getattr(subprocess, "CREATE_NO_WINDOW", 0)) if sys.platform == "win32" else 0
    )

    result = subprocess.run(
        [
            str(executable),
            "-hide_banner",
            "-encoders",
        ],
        capture_output=True,
        text=True,
        check=False,
        creationflags=creationflags,
    )

    inventory = f"{result.stdout}\n{result.stderr}"

    if result.returncode != 0:
        raise RuntimeError(
            "Packaged ReefVision FFmpeg encoder inventory failed "
            f"with exit code {result.returncode}"
        )

    if "libx264" not in inventory:
        raise RuntimeError("Packaged ReefVision FFmpeg runtime does not provide libx264")

    LOGGER.info(
        "Annotated-video encoder runtime validated: %s",
        executable,
    )


def run_self_test(settings: Settings) -> int:
    """Exercise packaged resources and providers without opening a server socket."""

    self_test_result = settings.resolved_data_dir / SELF_TEST_RESULT_FILENAME
    self_test_result.unlink(missing_ok=True)

    alembic_ini, migrations_dir = resolve_alembic_paths()
    if not alembic_ini.is_file():
        raise RuntimeError(f"Packaged Alembic configuration is missing: {alembic_ini}")
    if not migrations_dir.is_dir():
        raise RuntimeError(f"Packaged Alembic migrations are missing: {migrations_dir}")

    from reefvision.ml.dependencies import (
        configure_provider_runtime,
        require_all_implemented_providers_ready,
    )
    from reefvision.ml.video_depth_anything import (
        _source_root as resolve_video_depth_anything_source,
    )

    provider_runtime = settings.resolved_data_dir / "provider-runtime-self-test"
    configure_provider_runtime(data_dir=provider_runtime)
    require_all_implemented_providers_ready()
    require_scale_assistant_marker_runtime()
    require_annotated_video_encoder_runtime()
    resolve_video_depth_anything_source(settings)

    from reefvision.main import create_app

    app = create_app(settings)
    schema = app.openapi()
    paths = schema.get("paths")
    if not isinstance(paths, dict) or not paths:
        raise RuntimeError("Packaged FastAPI application produced no OpenAPI paths")
    write_self_test_result(
        settings.resolved_data_dir,
        version=str(schema["info"]["version"]),
        openapi_path_count=len(paths),
    )
    LOGGER.info(
        "Desktop self-test validated ReefVision version %s; %s OpenAPI paths",
        schema["info"]["version"],
        len(paths),
    )
    return 0


def resolve_server_port(server: object, requested_port: int) -> int:
    servers = getattr(server, "servers", ())
    for active_server in servers:
        sockets = getattr(active_server, "sockets", ()) or ()
        for listener in sockets:
            sockname = listener.getsockname()
            if isinstance(sockname, tuple) and len(sockname) >= 2:
                port = int(sockname[1])
                if port > 0:
                    return port

    if requested_port > 0:
        return requested_port

    raise RuntimeError("ReefVision desktop API did not expose its loopback port")


async def publish_runtime_port_when_ready(
    server: uvicorn.Server,
    context_file: Path | None,
    requested_port: int,
) -> None:
    while not server.started:
        if server.should_exit:
            raise RuntimeError("ReefVision desktop API exited before startup completed")
        await asyncio.sleep(0.05)
    write_runtime_port(context_file, resolve_server_port(server, requested_port))


async def run_api_server(settings: Settings, options: DesktopLaunchOptions) -> int:
    from reefvision.main import create_app

    LOGGER.info("Creating FastAPI application instance")
    app = create_app(settings)
    config = uvicorn.Config(
        app,
        host=settings.api_host,
        port=settings.api_port,
        access_log=False,
    )
    server = uvicorn.Server(config)
    start_shutdown_monitor(server)
    port_publisher = asyncio.create_task(
        publish_runtime_port_when_ready(server, options.context_file, settings.api_port)
    )

    try:
        LOGGER.info("Launching Uvicorn server")
        await server.serve()
        if not server.started:
            raise RuntimeError("ReefVision desktop API failed before reporting readiness")
        await port_publisher
        return 0
    finally:
        if not port_publisher.done():
            port_publisher.cancel()
            with suppress(asyncio.CancelledError):
                await port_publisher


def main(argv: Sequence[str] | None = None) -> int:
    options = parse_args(argv)
    ensure_standard_streams()
    configure_logging(options.log_file)
    try:
        settings = build_settings(options)
        settings.ensure_directories()
        LOGGER.info("Starting ReefVision desktop API on %s:%s", options.host, options.port)
        if options.run_migrations:
            LOGGER.info("Applying pending Alembic migrations")
            run_pending_migrations(settings)
        if options.self_test:
            LOGGER.info("Running packaged ReefVision desktop self-test")
            return run_self_test(settings)
        if options.provider_hardware_acceptance:
            LOGGER.info("Running packaged ReefVision provider hardware acceptance")
            from reefvision.packaged_provider_acceptance import (
                run_packaged_provider_acceptance,
            )

            return run_packaged_provider_acceptance(settings)
        if options.video_tracking_job is not None:
            LOGGER.info(
                "Running isolated video-tracking worker for job %s",
                options.video_tracking_job,
            )
            return run_single_video_tracking_job(
                settings,
                options.video_tracking_job,
            )
        if options.annotated_video_export_job is not None:
            LOGGER.info(
                "Running isolated annotated-video export worker for job %s",
                options.annotated_video_export_job,
            )
            return run_single_annotated_video_export_job(
                settings,
                options.annotated_video_export_job,
            )
        preload_frozen_windows_scipy_native()
        configure_windows_event_loop_policy()
        LOGGER.info("Loading FastAPI application factory")
        return asyncio.run(run_api_server(settings, options))
    except Exception:
        LOGGER.exception("ReefVision desktop API failed to start")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
