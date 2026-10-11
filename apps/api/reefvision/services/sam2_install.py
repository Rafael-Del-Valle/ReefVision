"""Explicit opt-in SAM 2.1 model installation with immutable source provenance.

No network operation occurs during status/preflight/inference. Only the explicit
install job may access the allowlisted Meta SAM 2.1 Hugging Face repositories.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import Job, Project
from reefvision.domain.errors import NotFoundError, ValidationError

SAM2_REPOSITORIES = {
    "tiny": "facebook/sam2.1-hiera-tiny",
    "small": "facebook/sam2.1-hiera-small",
    "base-plus": "facebook/sam2.1-hiera-base-plus",
    "large": "facebook/sam2.1-hiera-large",
}
# These are complete upstream checkpoints, never bundled in the Windows MSI.
ALLOWED_FILES = frozenset(
    {
        "config.json",
        "model.safetensors",
        "preprocessor_config.json",
        "processor_config.json",
        "video_preprocessor_config.json",
    }
)
LICENSE = "Apache-2.0 (Meta SAM 2.1 model repository)"


def variant_repo(variant: str) -> str:
    if variant not in SAM2_REPOSITORIES:
        raise ValidationError("Choose an official SAM 2.1 size: tiny, small, base-plus, large")
    return SAM2_REPOSITORIES[variant]


def model_directory(settings: Settings, variant: str) -> Path:
    variant_repo(variant)
    return settings.resolved_data_dir / "provider-models" / "sam2" / variant


@lru_cache(maxsize=128)
def _hashed_file(path_str: str, size: int, modification_ns: int) -> str:
    path = Path(path_str)
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256(path: Path) -> str:
    stat = path.stat()
    return _hashed_file(str(path.resolve()), stat.st_size, stat.st_mtime_ns)


def _materialize_staged_download(downloaded: Path, stage: Path, filename: str) -> Path:
    """Store a pinned Hugging Face download as a regular file inside stage.

    Some Windows Hub/cache configurations return a file backed by a link or a
    cache path outside local_dir. Keep the trusted, allowlisted filename and
    immutable-revision download while ensuring that the final model tree has
    no external links that would break when the partial directory is renamed.
    """
    if filename not in ALLOWED_FILES or downloaded.name != filename:
        raise ValidationError("Unexpected SAM 2.1 checkpoint filename")
    if not downloaded.is_file():
        raise ValidationError("SAM 2.1 checkpoint download produced no file")

    expected = stage / filename
    if downloaded.resolve().parent != stage.resolve() or downloaded.is_symlink():
        temporary = stage / f".{filename}.materializing"
        with downloaded.open("rb") as source, temporary.open("xb") as destination:
            shutil.copyfileobj(source, destination, length=1024 * 1024)
        os.replace(temporary, expected)
    if (
        not expected.is_file()
        or expected.is_symlink()
        or expected.resolve().parent != stage.resolve()
    ):
        raise ValidationError("SAM 2.1 checkpoint was not safely staged")
    return expected


def sam2_status(settings: Settings, variant: str) -> dict[str, Any]:
    repo_id = variant_repo(variant)
    target = model_directory(settings, variant)
    manifest_path = target / ".reefvision-model.json"
    result: dict[str, Any] = {
        "variant": variant,
        "repo_id": repo_id,
        "license_summary": LICENSE,
        "ready": False,
        "installed": False,
        "revision": None,
        "weight_sha256": None,
        "path": None,
        "reason": "Use Install to explicitly download the SAM 2.1 checkpoint.",
    }
    if not manifest_path.is_file():
        return result
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("repo_id") != repo_id:
            raise ValueError("Repository mismatch")
        revision = manifest.get("revision")
        if (
            not isinstance(revision, str)
            or len(revision) != 40
            or any(c not in "0123456789abcdef" for c in revision)
        ):
            raise ValueError("Missing immutable source commit")
        files = manifest.get("files")
        if (
            not isinstance(files, dict)
            or "model.safetensors" not in files
            or "config.json" not in files
        ):
            raise ValueError("Incomplete manifest")
        if any(name not in ALLOWED_FILES for name in files):
            raise ValueError("Unexpected model file")
        for filename, checksum in files.items():
            if not isinstance(checksum, str) or _sha256(target / filename) != checksum:
                raise ValueError(f"Missing or modified file: {filename}")
        from importlib.util import find_spec

        runtime_ready = find_spec("transformers") is not None and find_spec("torch") is not None
        result.update(
            installed=True,
            ready=runtime_ready,
            revision=revision,
            weight_sha256=files["model.safetensors"],
            path=str(target),
            reason=None
            if runtime_ready
            else "Checkpoint installed, but Transformers/PyTorch runtime is unavailable.",
        )
    except (OSError, ValueError, TypeError, ImportError, AttributeError) as exc:
        result["reason"] = f"Checkpoint is not ready: {exc}"
    return result


def queue_sam2_install(session: Session, project_id: str, variant: str) -> Job:
    variant_repo(variant)
    if session.get(Project, project_id) is None:
        raise NotFoundError("Project not found")
    pending = list(
        session.scalars(
            select(Job).where(
                Job.job_type == "sam2_install",
                Job.status.in_(("queued", "running", "cancel_requested")),
            )
        )
    )
    existing = next(
        (job for job in pending if dict(job.request_json or {}).get("variant") == variant),
        None,
    )
    if existing is not None:
        # Model downloads are shared by the local ReefVision installation.
        # Both the editor hotkey and Provider Lab can follow the same job.
        return existing
    job = Job(
        id=str(uuid4()),
        project_id=project_id,
        job_type="sam2_install",
        status="queued",
        request_json={
            "variant": variant,
            "repo_id": variant_repo(variant),
            "auto_install_on_model_selection": True,
        },
        progress_current=0,
        progress_total=0,
        result_json={"stage": "queued"},
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def process_sam2_install(settings: Settings, factory: sessionmaker[Session], job_id: str) -> bool:
    """Only a verified user-approved queue item is eligible to download."""
    with factory() as session:
        row = session.execute(
            update(Job)
            .where(Job.id == job_id, Job.job_type == "sam2_install", Job.status == "queued")
            .values(
                status="running",
                started_at=datetime.now(UTC),
                result_json={"stage": "resolving_revision"},
            )
        )
        session.commit()
        if getattr(row, "rowcount", 0) != 1:
            return False
        job = session.get(Job, job_id)
        if job is None:
            return False
        data = job.request_json or {}
        variant = str(data.get("variant", ""))
        repo_id = variant_repo(variant)
        if data.get("repo_id") != repo_id:
            job.status = "failed"
            job.error_message = "SAM 2.1 install requires an allowlisted repository"
            job.completed_at = datetime.now(UTC)
            session.commit()
            return True

    target = model_directory(settings, variant)
    stage = target.parent / f".{variant}-{job_id}.partial"
    try:
        from huggingface_hub import HfApi, hf_hub_download

        # Resolve main ONCE, then download files from the immutable 40-hex commit.
        info = HfApi().model_info(repo_id, revision="main", files_metadata=True)
        revision = info.sha
        if (
            not isinstance(revision, str)
            or len(revision) != 40
            or any(c not in "0123456789abcdef" for c in revision)
        ):
            raise ValidationError("Hugging Face did not return a pinned commit SHA")
        siblings = {f.rfilename: f for f in (info.siblings or [])}
        filenames = sorted(ALLOWED_FILES.intersection(siblings))
        if "config.json" not in filenames or "model.safetensors" not in filenames:
            raise ValidationError("The upstream SAM 2.1 checkpoint is missing required files")
        total = sum(int(siblings[name].size or 0) for name in filenames)
        stage.mkdir(parents=True, exist_ok=False)
        with factory() as session:
            job = session.get(Job, job_id)
            if job is None:
                return False
            job.progress_total = total if total > 0 else len(filenames)
            job.result_json = {"stage": "downloading", "repo_id": repo_id, "revision": revision}
            session.commit()

        files: dict[str, str] = {}
        completed = 0
        for index, filename in enumerate(filenames):
            with factory() as session:
                job = session.get(Job, job_id)
                if job is None or job.status == "cancel_requested":
                    raise ValidationError("SAM 2.1 download cancelled")
            local = Path(
                hf_hub_download(
                    repo_id=repo_id,
                    filename=filename,
                    revision=revision,
                    local_dir=stage,
                )
            )
            # Local Hub storage on Windows may resolve to a shared cache.
            # Materialize it into our private stage before hashing/publishing.
            staged_file = _materialize_staged_download(local, stage, filename)
            files[filename] = _sha256(staged_file)
            completed += staged_file.stat().st_size if total > 0 else 1
            with factory() as session:
                job = session.get(Job, job_id)
                if job is None:
                    return False
                job.progress_current = min(completed, job.progress_total)
                job.result_json = {
                    "stage": "downloading",
                    "completed_files": index + 1,
                    "total_files": len(filenames),
                    "repo_id": repo_id,
                    "revision": revision,
                }
                session.commit()

        manifest = {
            "provider": "sam2",
            "variant": variant,
            "repo_id": repo_id,
            "revision": revision,
            "files": files,
            "license": LICENSE,
            "installed_at": datetime.now(UTC).isoformat(),
            "source": "huggingface_hub_explicit_opt_in",
        }
        (stage / ".reefvision-model.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
        )
        # Preserve existing installations until a complete staged download exists.
        if target.exists():
            if sam2_status(settings, variant)["installed"]:
                shutil.rmtree(stage)
                stage = target
            else:
                raise ValidationError(
                    "A damaged SAM 2.1 installation exists. Remove or repair it before retrying."
                )
        else:
            os.replace(stage, target)
            stage = target
        if not sam2_status(settings, variant)["ready"]:
            raise ValidationError("Downloaded model failed post-install integrity/readiness checks")
        with factory() as session:
            job = session.get(Job, job_id)
            if job is None:
                return False
            job.status = "succeeded"
            job.progress_current = job.progress_total
            job.result_json = {
                "stage": "ready",
                "repo_id": repo_id,
                "revision": revision,
                "variant": variant,
                "weight_sha256": files["model.safetensors"],
                "path": str(target),
            }
            job.completed_at = datetime.now(UTC)
            session.commit()
    except Exception as exc:
        if stage.name.endswith(".partial"):
            shutil.rmtree(stage, ignore_errors=True)
        with factory() as session:
            job = session.get(Job, job_id)
            if job is not None:
                job.status = "cancelled" if job.status == "cancel_requested" else "failed"
                job.error_message = str(exc)
                job.result_json = {"stage": "failed", "variant": variant}
                job.completed_at = datetime.now(UTC)
                session.commit()
    return True
