"""System-information and migration-status services."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from reefvision import __version__
from reefvision.config import Settings
from reefvision.db.models import Job
from reefvision.desktop import resolve_alembic_paths
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.logging_utils import default_logs_dir
from reefvision.schemas.jobs import JobResponse
from reefvision.schemas.system import (
    SchemaStatus,
    SystemCompatibilityResponse,
    SystemCommandShortcutRepairResponse,
    SystemCommandShortcutStatusResponse,
    SystemDiagnosticsCreateRequest,
    SystemDiagnosticsCreateResponse,
    SystemDiagnosticsStatusResponse,
    SystemLogFileResponse,
    SystemLogsLocationResponse,
    SystemMigrationPreflightResponse,
    SystemMigrationStatusResponse,
    SystemVersionResponse,
)
from reefvision.storage.backups import BACKUP_FORMAT_VERSION
from reefvision.storage.diagnostics import (
    DIAGNOSTIC_BUNDLE_VERSION,
    default_diagnostic_bundle_path,
)


@dataclass(frozen=True)
class MigrationSnapshot:
    schema_status: SchemaStatus
    database_exists: bool
    current_schema_revision: str | None
    expected_schema_revision: str | None
    pending_revisions: list[str]


class SystemService:
    def __init__(self, settings: Settings, engine: Engine) -> None:
        self.settings = settings
        self.engine = engine

    def version(self) -> SystemVersionResponse:
        snapshot = self._migration_snapshot()
        database_path = self._database_path()
        return SystemVersionResponse(
            application_version=__version__,
            backup_format_version=BACKUP_FORMAT_VERSION,
            environment=self.settings.env,
            data_dir=str(self.settings.resolved_data_dir),
            safe_mode=self.settings.safe_mode,
            database_path=str(database_path) if database_path else None,
            current_schema_revision=snapshot.current_schema_revision,
            expected_schema_revision=snapshot.expected_schema_revision,
        )

    def compatibility(self) -> SystemCompatibilityResponse:
        snapshot = self._migration_snapshot()
        return SystemCompatibilityResponse(
            application_version=__version__,
            schema_status=snapshot.schema_status,
            compatible_for_read_write=snapshot.schema_status != "database_newer_than_code",
            current_schema_revision=snapshot.current_schema_revision,
            expected_schema_revision=snapshot.expected_schema_revision,
            pending_revisions=snapshot.pending_revisions,
            details=self._compatibility_details(snapshot),
        )

    def migration_status(self) -> SystemMigrationStatusResponse:
        snapshot = self._migration_snapshot()
        return SystemMigrationStatusResponse(
            schema_status=snapshot.schema_status,
            database_exists=snapshot.database_exists,
            current_schema_revision=snapshot.current_schema_revision,
            expected_schema_revision=snapshot.expected_schema_revision,
            pending_revisions=snapshot.pending_revisions,
        )

    def migration_preflight(self) -> SystemMigrationPreflightResponse:
        snapshot = self._migration_snapshot()
        database_path = self._database_path()
        warnings: list[str] = []
        blocking_issues: list[str] = []

        if snapshot.schema_status == "migration_required":
            warnings.append(
                "The database schema is behind the application code and must be upgraded."
            )
        if snapshot.schema_status == "uninitialized":
            warnings.append("The database has not been initialized with an Alembic revision yet.")
        if snapshot.schema_status == "database_newer_than_code":
            blocking_issues.append(
                "The database revision is not recognized by this ReefVision build."
            )

        disk_free_bytes: int | None = None
        try:
            disk_free_bytes = shutil.disk_usage(self.settings.resolved_data_dir).free
        except OSError:
            warnings.append(
                "Free disk space could not be determined for the current data directory."
            )

        return SystemMigrationPreflightResponse(
            schema_status=snapshot.schema_status,
            compatible_for_upgrade=not blocking_issues,
            requires_backup=snapshot.database_exists
            and snapshot.schema_status == "migration_required",
            database_exists=snapshot.database_exists,
            data_dir=str(self.settings.resolved_data_dir),
            database_path=str(database_path) if database_path else None,
            current_schema_revision=snapshot.current_schema_revision,
            expected_schema_revision=snapshot.expected_schema_revision,
            pending_revisions=snapshot.pending_revisions,
            disk_free_bytes=disk_free_bytes,
            warnings=warnings,
            blocking_issues=blocking_issues,
        )

    def logs_location(self) -> SystemLogsLocationResponse:
        logs_dir = default_logs_dir(self.settings)
        logs_dir.mkdir(parents=True, exist_ok=True)
        log_files: list[SystemLogFileResponse] = []
        for path in sorted(logs_dir.glob("*.log*")):
            stat = path.stat()
            log_files.append(
                SystemLogFileResponse(
                    name=path.name,
                    path=str(path),
                    size_bytes=stat.st_size,
                    modified_at=self._modified_at(path),
                )
            )
        return SystemLogsLocationResponse(logs_dir=str(logs_dir), files=log_files)

    def create_diagnostics(
        self,
        payload: SystemDiagnosticsCreateRequest,
    ) -> SystemDiagnosticsCreateResponse:
        job_id = str(uuid4())
        with Session(self.engine) as session:
            job = Job(
                id=job_id,
                project_id=None,
                job_type="diagnostics",
                status="queued",
                progress_total=1,
                request_json={
                    "strict_redaction": payload.strict_redaction,
                    "notes": payload.notes,
                    "bundle_path": default_diagnostic_bundle_path(
                        job_id=job_id,
                        created_at_label=datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"),
                    ),
                },
                result_json={"stage": "queued"},
            )
            session.add(job)
            session.commit()
            session.refresh(job)
            return SystemDiagnosticsCreateResponse(job=JobResponse.model_validate(job))

    def diagnostics_status(self, job_id: str) -> SystemDiagnosticsStatusResponse:
        with Session(self.engine) as session:
            job = session.get(Job, job_id)
            if job is None or job.job_type != "diagnostics":
                raise NotFoundError("Diagnostic bundle job not found")
            result_json = job.result_json or {}
            return SystemDiagnosticsStatusResponse(
                job=JobResponse.model_validate(job),
                bundle_path=self._string_value(result_json.get("bundle_path")),
                bundle_size_bytes=self._int_value(result_json.get("bundle_size_bytes")),
                diagnostic_bundle_version=self._string_value(
                    result_json.get("diagnostic_bundle_version")
                )
                or (DIAGNOSTIC_BUNDLE_VERSION if job.status == "succeeded" else None),
            )

    def command_shortcut_status(self) -> SystemCommandShortcutStatusResponse:
        root = self._command_root()
        command_dir = root / "bin"
        support_dir = root / "commands"
        config = self._command_config()
        repo_path = self._command_repo_path(config)
        user_path_entries = self._user_path_entries()

        start_wrapper = command_dir / "start-reefvision.cmd"
        update_wrapper = command_dir / "update-reefvision.cmd"
        support_start = support_dir / "start-reefvision.ps1"
        support_update = support_dir / "update-reefvision.ps1"

        notes: list[str] = []
        path_contains = str(command_dir) in user_path_entries
        if not path_contains:
            notes.append("The ReefVision command directory is not present in the current user's PATH.")
        if repo_path is None:
            notes.append("No ReefVision repository path is configured for update workflows.")

        start_exists = start_wrapper.is_file()
        update_exists = update_wrapper.is_file()
        support_start_exists = support_start.is_file()
        support_update_exists = support_update.is_file()
        start_managed = self._managed_wrapper(start_wrapper)
        update_managed = self._managed_wrapper(update_wrapper)

        if (
            path_contains
            and start_exists
            and update_exists
            and support_start_exists
            and support_update_exists
            and start_managed
            and update_managed
        ):
            verification = "ready"
        elif (start_exists and not start_managed) or (update_exists and not update_managed):
            verification = "conflict"
            notes.append("One or more command wrapper names are already in use by a non-ReefVision file.")
        else:
            verification = "repair_required"

        return SystemCommandShortcutStatusResponse(
            command_version=__version__,
            command_directory=str(command_dir),
            support_directory=str(support_dir),
            repo_path=str(repo_path) if repo_path else None,
            path_contains_command_directory=path_contains,
            start_command_exists=start_exists,
            update_command_exists=update_exists,
            support_start_exists=support_start_exists,
            support_update_exists=support_update_exists,
            start_command_managed=start_managed,
            update_command_managed=update_managed,
            verification_result=verification,
            notes=notes,
        )

    def repair_command_shortcuts(self) -> SystemCommandShortcutRepairResponse:
        repo_path = self._command_repo_path(self._command_config())
        if repo_path is None:
            raise NotFoundError(
                "Command shortcut repair requires a local ReefVision repository path."
            )

        script_path = repo_path / "scripts" / "install-reefvision-commands.ps1"
        if not script_path.is_file():
            raise NotFoundError(
                f"Command shortcut installer not found in the configured repository: {script_path}"
            )

        completed = subprocess.run(
            [
                "powershell.exe",
                "-NoLogo",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script_path),
                "-RepoPath",
                str(repo_path),
                "-Force",
            ],
            capture_output=True,
            check=False,
            text=True,
        )
        output = completed.stdout.strip() or completed.stderr.strip()
        if completed.returncode != 0:
            raise ValidationError(output or "ReefVision command shortcut repair failed")

        return SystemCommandShortcutRepairResponse(
            status=self.command_shortcut_status(),
            output=output,
        )

    def _database_path(self) -> Path | None:
        url = make_url(self.settings.resolved_database_url)
        if url.get_backend_name() != "sqlite":
            return None
        database = url.database
        if database in (None, "", ":memory:"):
            return None
        assert database is not None
        database_path = database
        return Path(database_path).resolve()

    def _alembic_script_directory(self) -> ScriptDirectory:
        alembic_ini, migrations_dir = resolve_alembic_paths()
        config = Config(str(alembic_ini))
        config.attributes["configure_logger"] = False
        config.set_main_option("script_location", str(migrations_dir))
        return ScriptDirectory.from_config(config)

    def _migration_snapshot(self) -> MigrationSnapshot:
        script = self._alembic_script_directory()
        head_revision = script.get_current_head()
        ordered_revisions = (
            [
                revision.revision
                for revision in reversed(
                    list(script.walk_revisions(base="base", head=head_revision))
                )
            ]
            if head_revision is not None
            else []
        )
        database_path = self._database_path()
        database_exists = bool(database_path and database_path.is_file())
        with self.engine.connect() as connection:
            context = MigrationContext.configure(connection)
            current_revision = context.get_current_revision()

        if current_revision == head_revision:
            status: SchemaStatus = "up_to_date"
            pending = []
        elif current_revision is None:
            status = "uninitialized"
            pending = ordered_revisions
        elif current_revision in ordered_revisions:
            status = "migration_required"
            pending = ordered_revisions[ordered_revisions.index(current_revision) + 1 :]
        else:
            status = "database_newer_than_code"
            pending = []

        return MigrationSnapshot(
            schema_status=status,
            database_exists=database_exists,
            current_schema_revision=current_revision,
            expected_schema_revision=head_revision,
            pending_revisions=pending,
        )

    def _compatibility_details(self, snapshot: MigrationSnapshot) -> list[str]:
        if snapshot.schema_status == "up_to_date":
            return ["The database schema matches the current ReefVision code."]
        if snapshot.schema_status == "uninitialized":
            return ["The database does not yet have an Alembic revision record."]
        if snapshot.schema_status == "migration_required":
            return [
                "The database schema can be upgraded by this ReefVision build.",
                f"Pending revisions: {', '.join(snapshot.pending_revisions)}",
            ]
        return [
            "This ReefVision build does not recognize the current database revision.",
            "Normal write operations should remain blocked until a compatible build is used.",
        ]

    def _modified_at(self, path: Path) -> datetime:
        return datetime.fromtimestamp(path.stat().st_mtime, UTC)

    def _string_value(self, value: object) -> str | None:
        return value if isinstance(value, str) else None

    def _int_value(self, value: object) -> int | None:
        return value if isinstance(value, int) else None

    def _command_root(self) -> Path:
        local_app_data = os.environ.get("LOCALAPPDATA")
        if not local_app_data:
            return self.settings.resolved_data_dir / "command-shortcuts"
        return Path(local_app_data) / "ReefVision"

    def _command_config(self) -> dict[str, object]:
        config_path = self._command_root() / "config" / "commands.json"
        if not config_path.is_file():
            return {}
        try:
            loaded = json.loads(config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        return loaded if isinstance(loaded, dict) else {}

    def _command_repo_path(self, config: dict[str, object]) -> Path | None:
        configured = config.get("repo_path")
        if isinstance(configured, str) and configured:
            repo_path = Path(configured)
            if repo_path.is_dir():
                return repo_path

        candidate = Path(__file__).resolve().parents[4]
        if (candidate / "pyproject.toml").is_file():
            return candidate
        return None

    def _user_path_entries(self) -> set[str]:
        raw = os.environ.get("Path") or ""
        return {entry.strip() for entry in raw.split(";") if entry.strip()}

    def _managed_wrapper(self, path: Path) -> bool:
        if not path.is_file():
            return False
        first_line = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        if not first_line:
            return False
        return "ReefVision managed command wrapper" in first_line[0]
