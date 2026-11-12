"""Recoverable worker for provider-neutral pose evaluation comparisons."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import Job, ModelRegistration, PoseEvaluationRun
from reefvision.ml.pose_evaluation import PoseEvaluationProviderExclusion
from reefvision.schemas.pose_evaluation import PoseEvaluationCreateRequest
from reefvision.services.pose_evaluation import PoseEvaluationService
from reefvision.storage.datasets import canonical_json_sha256


class _ComparisonCancelled(Exception):
    pass


def _report(
    job: Job,
    *,
    stage: str,
    models: list[dict[str, Any]],
    exclusions: list[dict[str, Any]],
    warnings: list[str],
) -> dict[str, Any]:
    payload = {
        "schema_version": "reefvision-pose-comparison-0001",
        "stage": stage,
        "request_sha256": str(job.request_json.get("request_sha256") or ""),
        "project_id": job.project_id,
        "evaluation_dataset_id": str(job.request_json.get("evaluation_dataset_id") or ""),
        "dataset_manifest_sha256": str(
            job.request_json.get("dataset_manifest_sha256") or ""
        ),
        "configuration": {
            key: value
            for key, value in dict(job.request_json or {}).items()
            if key
            in {
                "device",
                "pck_thresholds",
                "calibration_threshold",
                "calibration_bins",
                "confidence_thresholds",
                "oks_sigmas",
            }
        },
        "evaluation_run_ids": [str(item["evaluation_run_id"]) for item in models],
        "models": models,
        "exclusions": exclusions,
        "warnings": warnings,
    }
    return {**payload, "report_sha256": canonical_json_sha256(payload)}


def _completed_child_is_reusable(
    session: Session,
    request: dict[str, Any],
    identity: dict[str, Any],
    existing: dict[str, Any],
) -> bool:
    run_id = str(existing.get("evaluation_run_id") or "")
    run = session.get(PoseEvaluationRun, run_id) if run_id else None
    if run is None or run.status != "completed":
        return False
    expected_configuration = {
        "model_id": str(identity["model_id"]),
        "evaluation_dataset_id": str(request["evaluation_dataset_id"]),
        "device": request.get("device", "auto"),
        "pck_thresholds": request.get("pck_thresholds", [0.05, 0.1, 0.2]),
        "calibration_threshold": request.get("calibration_threshold", 0.1),
        "calibration_bins": request.get("calibration_bins", 10),
        "confidence_thresholds": request.get(
            "confidence_thresholds", [0.0, 0.25, 0.5, 0.75, 0.9]
        ),
        "oks_sigmas": request.get("oks_sigmas"),
    }
    provenance = dict(run.provenance_json or {})
    return (
        run.model_id == identity["model_id"]
        and run.evaluation_dataset_id == request["evaluation_dataset_id"]
        and dict(run.configuration_json or {}) == expected_configuration
        and provenance.get("checkpoint_sha256") == identity.get("checkpoint_sha256")
        and provenance.get("dataset_manifest_sha256") == request.get("dataset_manifest_sha256")
        and run.result_sha256 == existing.get("result_sha256")
    )


def _model_result(
    model: ModelRegistration,
    identity: dict[str, Any],
    run: Any,
) -> dict[str, Any]:
    return {
        "model_id": model.id,
        "display_name": model.display_name,
        "provider_name": model.provider_name,
        "provider_version": model.provider_version,
        "checkpoint_sha256": identity.get("checkpoint_sha256"),
        "checkpoint_size_bytes": identity.get("checkpoint_size_bytes"),
        "evaluation_run_id": run.id,
        "result_sha256": run.result_sha256,
        "metrics": dict(run.metrics_json or {}),
        "metric_availability": dict((run.metrics_json or {}).get("availability") or {}),
        "warnings": list(run.warnings_json or []),
        "performance": {
            "inference_latency_ms": run.inference_latency_ms,
            "images_per_second": run.images_per_second,
        },
        "provenance": dict(run.provenance_json or {}),
    }


def process_pose_evaluation_job(
    settings: Settings,
    factory: sessionmaker[Session],
    job_id: str,
) -> bool:
    with factory() as session:
        job = session.get(Job, job_id)
        if job is None or job.job_type != "pose_evaluation" or job.status != "queued":
            return False
        if job.project_id is None:
            job.status = "failed"
            job.error_message = "Pose comparison job lacks a project identity"
            job.deduplication_key = None
            job.completed_at = datetime.now(UTC)
            session.commit()
            return True
        project_id = job.project_id
        request = dict(job.request_json or {})
        identities = [
            dict(item)
            for item in list(request.get("model_identities") or [])
            if isinstance(item, dict)
        ]
        job.status = "running"
        job.started_at = job.started_at or datetime.now(UTC)
        job.completed_at = None
        job.error_message = None
        session.commit()

        prior = dict(job.result_json or {})
        prior_models = {
            str(item.get("model_id")): dict(item)
            for item in list(prior.get("models") or [])
            if isinstance(item, dict) and item.get("model_id")
        }
        models: list[dict[str, Any]] = []
        exclusions: list[dict[str, Any]] = []
        warnings: list[str] = []

        def cancellation_check() -> None:
            session.expire(job)
            if job.status == "cancel_requested":
                raise _ComparisonCancelled

        try:
            for model_index, identity in enumerate(identities):
                cancellation_check()
                model_id = str(identity["model_id"])
                existing = prior_models.get(model_id)
                if existing is not None and _completed_child_is_reusable(
                    session, request, identity, existing
                ):
                    models.append(existing)
                    job.progress_current = min(
                        job.progress_total,
                        (model_index + 1) * int(job.progress_total / len(identities)),
                    )
                    job.result_json = _report(
                        job,
                        stage="running",
                        models=models,
                        exclusions=exclusions,
                        warnings=warnings,
                    )
                    session.commit()
                    continue
                model = session.get(ModelRegistration, model_id)
                if model is None:
                    raise RuntimeError(f"Registered comparison model disappeared: {model_id}")
                base_progress = model_index * int(job.progress_total / len(identities))

                def progress(
                    current: int,
                    total: int,
                    base_progress: int = base_progress,
                ) -> None:
                    cancellation_check()
                    model_span = int(job.progress_total / len(identities))
                    completed = round((current / max(total, 1)) * model_span)
                    job.progress_current = min(job.progress_total, base_progress + completed)
                    job.result_json = _report(
                        job,
                        stage="running",
                        models=models,
                        exclusions=exclusions,
                        warnings=warnings,
                    )
                    session.commit()

                payload = PoseEvaluationCreateRequest(
                    model_id=model_id,
                    evaluation_dataset_id=str(request["evaluation_dataset_id"]),
                    device=str(request.get("device", "auto")),
                    pck_thresholds=list(request.get("pck_thresholds") or [0.05, 0.1, 0.2]),
                    calibration_threshold=float(request.get("calibration_threshold", 0.1)),
                    calibration_bins=int(request.get("calibration_bins", 10)),
                    confidence_thresholds=list(
                        request.get("confidence_thresholds")
                        or [0.0, 0.25, 0.5, 0.75, 0.9]
                    ),
                    oks_sigmas=request.get("oks_sigmas"),
                )
                try:
                    run = PoseEvaluationService(session, settings).create(
                        project_id,
                        payload,
                        provider_neutral=True,
                        cancellation_check=cancellation_check,
                        progress_callback=progress,
                    )
                except PoseEvaluationProviderExclusion as exc:
                    exclusions.append(
                        {
                            "model_id": model.id,
                            "display_name": model.display_name,
                            "provider_name": model.provider_name,
                            "code": exc.code,
                            "reason": str(exc),
                        }
                    )
                    job.progress_current = min(
                        job.progress_total,
                        base_progress + int(job.progress_total / len(identities)),
                    )
                    continue
                models.append(_model_result(model, identity, run))
                job.result_json = _report(
                    job,
                    stage="running",
                    models=models,
                    exclusions=exclusions,
                    warnings=warnings,
                )
                session.commit()

            job.status = "succeeded"
            job.progress_current = job.progress_total
            stage = "completed"
        except _ComparisonCancelled:
            job.status = "cancelled"
            stage = "cancelled"
            job.error_message = "Pose comparison was cancelled"
        except Exception as exc:
            job.status = "failed"
            stage = "failed"
            job.error_message = f"Pose comparison failed: {exc}"
            warnings.append(job.error_message)

        job.result_json = _report(
            job,
            stage=stage,
            models=models,
            exclusions=exclusions,
            warnings=warnings,
        )
        job.deduplication_key = None
        job.completed_at = datetime.now(UTC)
        session.commit()
        return True
