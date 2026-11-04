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
    session: DbSession,
) -> TrainingRunResponse:
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
    text = re.sub(r"\x1b[\]PX^_][\s\S]*?(?:\x07|\x9c|\x1b\\|$)", "", text)
    text = re.sub(r"[\x90\x98\x9d\x9e\x9f][\s\S]*?(?:\x07|\x9c|\x1b\\|$)", "", text)
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
    root = data_dir.resolve()
    candidate = Path(log_path)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        path = candidate.resolve(strict=True)
    except (OSError, RuntimeError):
        return empty
    if not path.is_relative_to(root) or path.suffix.lower() not in {".log", ".txt"}:
        raise HTTPException(status_code=403, detail="Training log path is not permitted")
    if not path.is_file():
        return empty
    try:
        # Anchor the read to the validated file identity. A local process may
        # replace the resolved log between path validation and open; without
        # this check the read-only monitor could display another job's data.
        expected_identity = path.stat()
        with path.open("rb") as handle:
            opened_identity = os.fstat(handle.fileno())
            # Recheck after opening: a substituted symlink or a replaced file
            # must never be read, even when its name still ends in .log.
            if path.resolve(strict=True) != path or (
                opened_identity.st_dev,
                opened_identity.st_ino,
            ) != (expected_identity.st_dev, expected_identity.st_ino):
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
    except OSError:
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
        settings.resolved_data_dir,
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
