"""Training workspace API routes."""

import os
import re
import unicodedata
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.config import Settings
from reefvision.schemas.bootstrap import TrainingWorkspaceBootstrapResponse
from reefvision.schemas.models import UltralyticsTrainingRegistryResponse
from reefvision.schemas.results_packages import (
    ResultsPackageOptions,
    ResultsPackageResponse,
    ResultsPackageVerificationResponse,
)
from reefvision.schemas.training import (
    ExperimentCompareRequest,
    ExperimentCompareResponse,
    ExperimentRecordResponse,
    TrainingDraftPatchRequest,
    TrainingDraftResponse,
    TrainingDraftSummaryResponse,
    TrainingDraftWriteRequest,
    TrainingPreflightResponse,
    TrainingProviderResponse,
    TrainingRunCreateRequest,
    TrainingRunResponse,
    TrainingTilingEstimateResponse,
    TrainingTilingRequest,
)
from reefvision.services.bootstrap import BootstrapService
from reefvision.services.results_packages import ResultsPackageService
from reefvision.services.segmentation_catalog import SegmentationModelCatalogService
from reefvision.services.semantic_training import SemanticTrainingService

router = APIRouter(tags=["training"])
DbSession = Annotated[Session, Depends(get_db_session)]


def service(request: Request, session: Session) -> SemanticTrainingService:
    settings: Settings = request.app.state.settings
    result = SemanticTrainingService(session, settings)
    result.catalog = SegmentationModelCatalogService(session, settings)
    return result


def bootstrap_service(request: Request, session: Session) -> BootstrapService:
    settings: Settings = request.app.state.settings
    return BootstrapService(session, settings)


def results_package_service(request: Request, session: Session) -> ResultsPackageService:
    settings: Settings = request.app.state.settings
    return ResultsPackageService(session, settings)


@router.get(
    "/projects/{project_id}/training/bootstrap",
    response_model=TrainingWorkspaceBootstrapResponse,
)
def get_training_workspace_bootstrap(
    project_id: str,
    request: Request,
    session: DbSession,
) -> TrainingWorkspaceBootstrapResponse:
    return bootstrap_service(request, session).training_workspace_bootstrap(project_id)


@router.get("/training/providers", response_model=list[TrainingProviderResponse])
def list_training_providers(
    request: Request,
    session: DbSession,
) -> list[TrainingProviderResponse]:
    return service(request, session).list_providers()


@router.get(
    "/training/providers/{provider_id}/parameters",
    response_model=UltralyticsTrainingRegistryResponse,
)
def get_training_provider_parameters(
    provider_id: str,
    request: Request,
    session: DbSession,
) -> UltralyticsTrainingRegistryResponse:
    snapshot = service(request, session).get_provider_parameters(provider_id)
    return UltralyticsTrainingRegistryResponse.model_validate(snapshot, from_attributes=True)


@router.get(
    "/projects/{project_id}/training-drafts",
    response_model=list[TrainingDraftResponse],
)
def list_training_drafts(
    project_id: str,
    request: Request,
    session: DbSession,
) -> list[TrainingDraftResponse]:
    return service(request, session).list_drafts(project_id)


@router.get(
    "/projects/{project_id}/training-draft-summaries",
    response_model=list[TrainingDraftSummaryResponse],
)
def list_training_draft_summaries(
    project_id: str,
    request: Request,
    session: DbSession,
) -> list[TrainingDraftSummaryResponse]:
    return service(request, session).list_draft_summaries(project_id)


@router.post(
    "/projects/{project_id}/training-drafts",
    response_model=TrainingDraftResponse,
)
def create_training_draft(
    project_id: str,
    payload: TrainingDraftWriteRequest,
    request: Request,
    session: DbSession,
) -> TrainingDraftResponse:
    return service(request, session).create_draft(project_id, payload)


@router.get("/training-drafts/{draft_id}", response_model=TrainingDraftResponse)
def get_training_draft(
    draft_id: str,
    request: Request,
    session: DbSession,
) -> TrainingDraftResponse:
    return service(request, session).get_draft(draft_id)


@router.patch("/training-drafts/{draft_id}", response_model=TrainingDraftResponse)
def patch_training_draft(
    draft_id: str,
    payload: TrainingDraftPatchRequest,
    request: Request,
    session: DbSession,
) -> TrainingDraftResponse:
    return service(request, session).update_draft(draft_id, payload)


@router.delete("/training-drafts/{draft_id}", status_code=204)
def delete_training_draft(
    draft_id: str,
    request: Request,
    session: DbSession,
) -> None:
    service(request, session).delete_draft(draft_id)


@router.post(
    "/projects/{project_id}/training-preflight",
    response_model=TrainingPreflightResponse,
)
def run_training_preflight(
    project_id: str,
    payload: TrainingDraftWriteRequest,
    request: Request,
    session: DbSession,
) -> TrainingPreflightResponse:
    return service(request, session).preflight(project_id, payload)


@router.post(
    "/projects/{project_id}/training-tiling/estimate",
    response_model=TrainingTilingEstimateResponse,
)
def estimate_training_tiling(
    project_id: str,
    payload: TrainingTilingRequest,
    request: Request,
    session: DbSession,
) -> TrainingTilingEstimateResponse:
    return service(request, session).estimate_tiling(project_id, payload)


@router.post(
    "/projects/{project_id}/training-runs",
    response_model=TrainingRunResponse,
)
def create_training_run(
    project_id: str,
    payload: TrainingRunCreateRequest,
    request: Request,
    session: DbSession,
) -> TrainingRunResponse:
    return service(request, session).create_run(project_id, payload)


@router.get(
    "/projects/{project_id}/training-runs",
    response_model=list[TrainingRunResponse],
)
def list_training_runs(
    project_id: str,
    request: Request,
    session: DbSession,
) -> list[TrainingRunResponse]:
    return service(request, session).list_runs(project_id)


@router.get("/training-runs/{run_id}", response_model=TrainingRunResponse)
def get_training_run(
    run_id: str,
    request: Request,
    response: Response,
    session: DbSession,
) -> TrainingRunResponse:
    # This endpoint is polled by the read-only PowerShell training observer.
    # Do not allow a cached epoch/status snapshot to masquerade as live losses
    # or conceal a completed/failed training job.
    response.headers["Cache-Control"] = "no-store"
    return service(request, session).get_run(run_id)


def _safe_terminal_log_text(payload: bytes) -> str:
    """Render training logs without terminal escape/control side effects."""
    # UTF-8 training logs can also contain raw 8-bit C1 terminal controls.
    # Keep those controls recognizable to the sanitizer; render other invalid
    # bytes as replacement characters rather than exposing surrogate codepoints.
    text = payload.decode("utf-8", errors="surrogateescape")

    def normalize_invalid_byte(match: re.Match[str]) -> str:
        byte = ord(match.group()) - 0xDC00
        return chr(byte) if 0x80 <= byte <= 0x9F else "\ufffd"

    text = re.sub(r"[\udc80-\udcff]", normalize_invalid_byte, text)

    # Strip entire OSC (title/hyperlink), DCS, SOS, PM, and APC strings.
    # Removing just ESC would expose their printable payload as fake log data.
    # A truncated terminal string is discarded through the end of the tail.
    # Erasing OSC/DCS/APC strings can concatenate two fragments of the same
    # metric or loss label (0.25 + OSC + 99 -> 0.2599). Treat a control
    # embedded between token characters as a terminal edit, rather than
    # manufacturing a measurement. The backspace sentinel is consumed by
    # omit_rewritten_record below; no source log bytes are changed.
    def token_character(char: str) -> bool:
        return bool(char) and char.isascii() and (char.isalnum() or char in "._/+-%")

    def strip_terminal_string(match: re.Match[str]) -> str:
        before = text[match.start() - 1] if match.start() else ""
        after = text[match.end()] if match.end() < len(text) else ""
        if token_character(before) and token_character(after):
            return "\x08"
        return ""

    text = re.sub(
        r"\x1b[\]PX^_][\s\S]*?(?:\x07|\x9c|\x1b\\|$)",
        strip_terminal_string,
        text,
    )
    text = re.sub(
        r"[\x90\x98\x9d\x9e\x9f][\s\S]*?(?:\x07|\x9c|\x1b\\|$)",
        strip_terminal_string,
        text,
    )

    # Backspaces and cursor-edit/erase CSI sequences can rewrite an earlier
    # digit in a loss record. Simply deleting the control bytes would join
    # distinct fragments (0.25 + BS + 99 -> 0.2599), fabricating a metric.
    # Retain ordinary SGR color and leading progress-bar clear sequences, but
    # quarantine any physical record edited between two printable fragments.
    def omit_rewritten_record(record: str) -> str:
        # Dropping zero-width, directional, or Unicode separator characters
        # inside a metric token would splice fragments into fabricated losses.
        # Quarantine the entire display record, never change the source log.
        for offset, char in enumerate(record):
            if unicodedata.category(char) not in {"Cf", "Zl", "Zp"}:
                continue
            before = record[offset - 1 : offset]
            after = record[offset + 1 : offset + 2]
            if token_character(before) and token_character(after):
                return "[terminal-edited training log record omitted]"

        controls = re.finditer(r"\x08|(?:\x1b\[|\x9b)[0-?]*[ -/]*[@-~]", record)
        # SGR colors are display-only, but removing them *inside* a loss
        # token can splice two numbers (0.25 + SGR + 99 -> 0.2599).
        # Ignore adjacent SGRs when checking the printed neighbors so a
        # sequence of color resets cannot hide the join.
        # Trim adjacent CSI controls when finding *printed* token neighbors.
        # A legitimate leading clear (ESC[2J) followed by an SGR color should
        # not look like the literal token "J" adjoining the colored epoch.
        # Cursor/erase edits are still rejected by their own branch below.
        csi = r"(?:\x1b\[|\x9b)[0-?]*[ -/]*[@-~]"
        for control in controls:
            value = control.group()
            if value != "\x08" and value.endswith("m"):
                before_sgr = re.sub(rf"(?:{csi})+$", "", record[: control.start()])
                after_sgr = re.sub(rf"^(?:{csi})+", "", record[control.end() :])
                if token_character(before_sgr[-1:]) and token_character(after_sgr[:1]):
                    return "[terminal-edited training log record omitted]"
                continue
            before = record[: control.start()]
            after = record[control.end() :]
            # A trailing or leading backspace still edits terminal state;
            # never report an unverified loss when no new glyph follows.
            if value == "\x08" and (before.strip() or after.strip()):
                return "[terminal-edited training log record omitted]"
            # Non-SGR terminal actions after printed content can erase the
            # last loss even without any following printable characters.
            # Keep leading progress-bar clears but reject altered metrics.
            if value != "\x08" and before.strip():
                return "[terminal-edited training log record omitted]"
        return record

    records = re.split(r"(\r\n|\r|\n)", text)
    text = "".join(
        omit_rewritten_record(record) if index % 2 == 0 else record
        for index, record in enumerate(records)
    )
    text = re.sub(r"(?:\x1b\[|\x9b)[0-?]*[ -/]*[@-~]", "", text)
    # A worker can flush an incomplete color/control sequence before a newline
    # or EOF. Removing only ESC[ leaves its digits appended to real losses
    # (for example 0.25 + ESC[31 becomes a fabricated 0.2531).
    text = re.sub(r"(?:\x1b\[|\x9b)[0-?]*[ -/]*(?=[\r\n]|$)", "", text)
    text = re.sub(r"\x1b[ -/]*[@-_]", "", text)
    # Progress bars use carriage returns to overwrite the current line.
    # Show each update on a new line instead of allowing terminal rewrites.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Unicode format controls (including zero-width joins, bidi overrides,
    # isolates and BOMs) can invisibly alter loss labels or terminal display.
    # Unicode line/paragraph separators can visually create fake records.
    # Preserve printable scientific units while removing those spoofing forms.
    return "".join(
        char
        for char in text
        if (char in "\t\n" or (ord(char) >= 32 and not 127 <= ord(char) <= 159))
        and unicodedata.category(char) not in {"Cf", "Zl", "Zp"}
    )


def _training_log_tail(
    log_path: str | None, data_dir: Path, *, finalized: bool = False
) -> dict[str, bool | str]:
    """Read a bounded persisted log tail; include EOF only after run termination."""
    empty: dict[str, bool | str] = {"available": False, "text": ""}
    if not log_path:
        return empty
    try:
        # The configured data root can itself be offline or unresolvable (for
        # example a temporarily disconnected research drive). Treat that as
        # an unavailable observer snapshot, not a failure of the training job.
        root = data_dir.resolve()
        candidate = Path(log_path)
        if not candidate.is_absolute():
            candidate = root / candidate
        path = candidate.resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        # A damaged persisted path can contain a NUL character. Path.resolve
        # raises ValueError for it; the read-only observer must remain usable
        # without changing or interrupting the underlying training job.
        return empty
    if not path.is_relative_to(root) or path.suffix.lower() not in {".log", ".txt"}:
        raise HTTPException(status_code=403, detail="Training log path is not permitted")
    try:
        # The file may disappear or become unreadable between resolution and
        # inspection. Monitor failures must not interrupt the training worker.
        if not path.is_file():
            return empty
        # Anchor the read to the validated file identity. A local process may
        # replace the resolved log between path validation and open; without
        # this check the read-only monitor could display another job's data.
        expected_identity = path.stat()
        with path.open("rb") as handle:
            opened_identity = os.fstat(handle.fileno())
            # Recheck after opening: a substituted symlink or a replaced file
            # must never be read, even when its name still ends in .log.
            # In-root hard links can disguise unrelated scientific data as a
            # .log file: extension and containment alone do not authenticate
            # the underlying inode. Reject multiply linked files before any
            # bytes are read, including a link added between stat and open.
            if (
                expected_identity.st_nlink != 1
                or opened_identity.st_nlink != 1
                # An append between validation and open is normal, but a
                # same-size rewrite would invalidate the pre-open snapshot.
                or (
                    expected_identity.st_size == opened_identity.st_size
                    and expected_identity.st_mtime_ns != opened_identity.st_mtime_ns
                )
                or path.resolve(strict=True) != path
                or (
                    opened_identity.st_dev,
                    opened_identity.st_ino,
                )
                != (expected_identity.st_dev, expected_identity.st_ino)
            ):
                raise HTTPException(status_code=403, detail="Training log changed during open")
            handle.seek(0, 2)
            size = handle.tell()
            start = max(0, size - 16384)
            handle.seek(start)
            payload = handle.read(16384)
            if start:
                # Never present the middle of a truncated line as a complete
                # epoch or loss value in the read-only PowerShell monitor.
                handle.seek(start - 1)
                previous = handle.read(1)
                if previous not in {b"\n", b"\r"}:
                    boundary = next(
                        (index for index, byte in enumerate(payload) if byte in (10, 13)),
                        -1,
                    )
                    payload = payload[boundary + 1 :] if boundary >= 0 else b""
            # Training workers may still be appending the final epoch/loss
            # record. Never display a partially written value as complete.
            # CR-terminated progress updates are complete records too.
            if payload and payload[-1] not in (10, 13) and not finalized:
                boundary = max(payload.rfind(b"\n"), payload.rfind(b"\r"))
                payload = payload[: boundary + 1] if boundary >= 0 else b""
            # The worker may rotate its log or another local process may swap
            # the path while the tail is being read. Reject that stale snapshot
            # rather than attributing its metrics to the current run. Ordinary
            # in-place worker appends retain the same file identity and pass.
            read_finished = os.fstat(handle.fileno())
            current_path = path.resolve(strict=True)
            current_identity = current_path.stat()
            if (
                current_path != path
                or read_finished.st_nlink != 1
                or current_identity.st_nlink != 1
                or (read_finished.st_dev, read_finished.st_ino)
                != (opened_identity.st_dev, opened_identity.st_ino)
                or (current_identity.st_dev, current_identity.st_ino)
                != (opened_identity.st_dev, opened_identity.st_ino)
                # In-place truncation keeps the inode but invalidates a
                # bounded snapshot; never present mixed or stale loss values.
                or read_finished.st_size < size
                or current_identity.st_size < size
                # A same-length rewrite can also preserve the inode. Compare
                # modification times only when no append occurred since open,
                # so ordinary live worker appends remain observable.
                or (
                    size == opened_identity.st_size
                    and read_finished.st_size == size
                    and read_finished.st_mtime_ns != opened_identity.st_mtime_ns
                )
                or (
                    size == opened_identity.st_size
                    and current_identity.st_size == size
                    and current_identity.st_mtime_ns != opened_identity.st_mtime_ns
                )
            ):
                raise HTTPException(status_code=403, detail="Training log changed during read")
    except (OSError, RuntimeError, ValueError):
        # Transient filesystem failures or a symlink loop after the initial
        # validation are unavailable snapshots, not training-job failures.
        return empty
    text = _safe_terminal_log_text(payload)
    # Trainer logs may use Windows CRLF while the API is also exercised from
    # Linux runners. Normalize line endings so the browser and PowerShell
    # monitor receive the same bounded text contract on every platform.
    return {"available": True, "text": text.replace("\r\n", "\n").replace("\r", "\n")}


@router.get("/training-runs/{run_id}/logs/tail")
def get_training_log_tail(
    run_id: str,
    request: Request,
    response: Response,
    session: DbSession,
) -> dict[str, bool | str]:
    """Expose a bounded, read-only log tail for the desktop PowerShell monitor."""
    response.headers["Cache-Control"] = "no-store"
    run = service(request, session).get_run(run_id)
    settings: Settings = request.app.state.settings
    return _training_log_tail(
        run.logs_path,
        # Pass the configured path without resolving it here. A disconnected
        # data drive must be handled by the bounded read-only helper, rather
        # than raising before its unavailable-snapshot fallback can run.
        settings.data_dir,
        finalized=getattr(run, "status", None) in {"completed", "failed", "cancelled"},
    )


@router.get("/training-runs/{run_id}/artifacts/{artifact_index}", response_class=FileResponse)
def get_training_artifact(
    run_id: str,
    artifact_index: int,
    request: Request,
    session: DbSession,
) -> FileResponse:
    path = service(request, session).artifact_file(run_id, artifact_index)
    return FileResponse(path, filename=path.name)


@router.post(
    "/training-runs/{run_id}/results-packages",
    response_model=ResultsPackageResponse,
)
def create_results_package(
    run_id: str,
    payload: ResultsPackageOptions,
    request: Request,
    session: DbSession,
) -> ResultsPackageResponse:
    return results_package_service(request, session).create(run_id, payload)


@router.get(
    "/training-runs/{run_id}/results-packages/{archive_name}",
    response_class=FileResponse,
)
def download_results_package(
    run_id: str,
    archive_name: str,
    request: Request,
    session: DbSession,
) -> FileResponse:
    path = results_package_service(request, session).archive(run_id, archive_name)
    return FileResponse(path, filename=path.name, media_type="application/zip")


@router.post(
    "/training-runs/{run_id}/results-packages/{package_name}/verify",
    response_model=ResultsPackageVerificationResponse,
)
def verify_results_package_route(
    run_id: str,
    package_name: str,
    request: Request,
    session: DbSession,
) -> ResultsPackageVerificationResponse:
    return results_package_service(request, session).verify(run_id, package_name)


@router.post("/training-runs/{run_id}/cancel", response_model=TrainingRunResponse)
def cancel_training_run(
    run_id: str,
    request: Request,
    session: DbSession,
) -> TrainingRunResponse:
    return service(request, session).cancel_run(run_id)


@router.get(
    "/projects/{project_id}/experiments",
    response_model=list[ExperimentRecordResponse],
)
def list_project_experiments(
    project_id: str,
    request: Request,
    session: DbSession,
) -> list[ExperimentRecordResponse]:
    return service(request, session).list_experiments(project_id)


@router.post("/experiments/compare", response_model=ExperimentCompareResponse)
def compare_experiments(
    payload: ExperimentCompareRequest,
    request: Request,
    session: DbSession,
) -> ExperimentCompareResponse:
    return service(request, session).compare_experiments(payload)
