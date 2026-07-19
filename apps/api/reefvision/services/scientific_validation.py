"""Frozen coral measurement acceptance, reliability, and report generation."""

from __future__ import annotations

import csv
import hashlib
import html
import math
import shutil
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any
from uuid import uuid4

import numpy as np
from sqlalchemy.orm import Session

from reefvision import __version__
from reefvision.config import Settings
from reefvision.db.models import ArtifactRecord, ImageAsset, MaskAnnotation, Project
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.schemas.measurements import MaskMeasurementResponse
from reefvision.schemas.scientific_validation import (
    ScientificMetricResult,
    ScientificObservationResult,
    ScientificReferenceObservation,
    ScientificValidationRequest,
    ScientificValidationResponse,
)
from reefvision.services.mask_measurements import MaskMeasurementService
from reefvision.storage.datasets import canonical_json_bytes, canonical_json_sha256
from reefvision.storage.projects import resolve_managed_project_path

_DEPTH_METRIC_PREFIXES = (
    "projected_",
    "centroid_depth_",
    "depth_",
    "surface_area_m2",
    "volume_m3",
    "3d_",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _finite(value: Any) -> float | None:
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    return None


def _measurement_value(measurement: MaskMeasurementResponse, metric: str) -> float | None:
    aliases = {
        "area": "area_pixels",
        "area_px": "area_pixels",
        "perimeter": "perimeter_pixels",
        "perimeter_px": "perimeter_pixels",
        "tle": "total_linear_extension_pixels",
        "tle_px": "total_linear_extension_pixels",
        "density": "contained_box_density_per_1000_pixels",
        "area_m2": "area_physical",
        "perimeter_m": "perimeter_physical",
        "tle_m": "total_linear_extension_physical",
        "surface_area_m2": "surface_area_physical",
    }
    return _finite(getattr(measurement, aliases.get(metric, metric), None))


def _pearson(reference: np.ndarray, predicted: np.ndarray) -> float | None:
    if reference.size < 2 or np.std(reference) == 0 or np.std(predicted) == 0:
        return None
    value = float(np.corrcoef(reference, predicted)[0, 1])
    return value if math.isfinite(value) else None


def _icc_absolute_agreement(ratings: np.ndarray) -> float | None:
    """Return two-way random absolute-agreement single-measure ICC(A,1)."""

    if ratings.ndim != 2:
        return None
    targets, raters = ratings.shape
    if targets < 2 or raters < 2 or not np.all(np.isfinite(ratings)):
        return None
    grand_mean = float(ratings.mean())
    target_means = ratings.mean(axis=1)
    rater_means = ratings.mean(axis=0)
    ss_targets = raters * float(np.sum((target_means - grand_mean) ** 2))
    ss_raters = targets * float(np.sum((rater_means - grand_mean) ** 2))
    residuals = ratings - target_means[:, None] - rater_means[None, :] + grand_mean
    ss_error = float(np.sum(residuals * residuals))
    ms_targets = ss_targets / (targets - 1)
    ms_raters = ss_raters / (raters - 1)
    ms_error = ss_error / ((targets - 1) * (raters - 1))
    denominator = ms_targets + (raters - 1) * ms_error + raters * (ms_raters - ms_error) / targets
    if math.isclose(denominator, 0.0, abs_tol=1e-15):
        return 1.0 if np.allclose(ratings, ratings[:, :1]) else None
    return float(np.clip((ms_targets - ms_error) / denominator, -1.0, 1.0))


def _complete_icc(rows: dict[str, dict[str, list[float]]]) -> float | None:
    raters = sorted({rater for values in rows.values() for rater in values})
    complete = [
        [mean(values[rater]) for rater in raters]
        for _specimen, values in sorted(rows.items())
        if raters and all(rater in values for rater in raters)
    ]
    if len(raters) < 2 or len(complete) < 2:
        return None
    return _icc_absolute_agreement(np.asarray(complete, dtype=np.float64))


def _observer_reliability(
    observations: list[ScientificReferenceObservation],
) -> tuple[float | None, float | None]:
    interobserver_rows: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    by_observer: dict[str, list[ScientificReferenceObservation]] = defaultdict(list)
    for observation in observations:
        interobserver_rows[observation.specimen_id][observation.observer_id].append(
            observation.reference_value
        )
        by_observer[observation.observer_id].append(observation)
    interobserver = _complete_icc(interobserver_rows)
    intraobserver_values: list[float] = []
    for observer_rows in by_observer.values():
        matrix: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
        for row in observer_rows:
            matrix[row.specimen_id][row.session_id].append(row.reference_value)
        value = _complete_icc(matrix)
        if value is not None:
            intraobserver_values.append(value)
    return interobserver, mean(intraobserver_values) if intraobserver_values else None


def _metric_html(result: ScientificMetricResult) -> str:
    failures = "<br>".join(html.escape(item) for item in result.failures) or "None"
    warnings = "<br>".join(html.escape(item) for item in result.warnings) or "None"
    return (
        "<tr>"
        f"<td>{html.escape(result.metric)}</td>"
        f"<td>{html.escape(result.unit)}</td>"
        f"<td>{result.sample_count}</td>"
        f"<td>{result.mae:.6g}</td>"
        f"<td>{result.rmse:.6g}</td>"
        f"<td>{result.bias:.6g}</td>"
        f"<td>{result.relative_mae_percent if result.relative_mae_percent is not None else 'NA'}</td>"
        f"<td>{result.pearson_r if result.pearson_r is not None else 'NA'}</td>"
        f"<td>{result.icc_absolute_agreement if result.icc_absolute_agreement is not None else 'NA'}</td>"
        f"<td>{'PASS' if result.passed else 'FAIL'}</td>"
        f"<td>{failures}</td>"
        f"<td>{warnings}</td>"
        "</tr>"
    )


class ScientificValidationService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.measurements = MaskMeasurementService(session, settings)

    def _project(self, project_id: str) -> Project:
        project = self.session.get(Project, project_id)
        if project is None:
            raise NotFoundError("Project not found")
        return project

    def _mask(self, project_id: str, mask_id: str) -> MaskAnnotation | None:
        mask = self.session.get(MaskAnnotation, mask_id)
        if mask is None or mask.deleted_at is not None:
            return None
        image = self.session.get(ImageAsset, mask.image_id)
        if image is None or image.project_id != project_id:
            return None
        return mask

    def run(
        self,
        project_id: str,
        request: ScientificValidationRequest,
    ) -> ScientificValidationResponse:
        project = self._project(project_id)
        report_id = str(uuid4())
        created = datetime.now(UTC)
        report_version = f"1.0-{created.strftime('%Y%m%dT%H%M%SZ')}"
        resolved: list[ScientificObservationResult] = []
        blockers: list[str] = []
        warnings: list[str] = []
        observations_by_metric: dict[str, list[ScientificReferenceObservation]] = defaultdict(list)
        measurement_cache: dict[str, tuple[MaskAnnotation, MaskMeasurementResponse] | None] = {}

        for observation in request.observations:
            observations_by_metric[observation.metric].append(observation)
            predicted = observation.predicted_value
            mask: MaskAnnotation | None = None
            measurement: MaskMeasurementResponse | None = None
            if predicted is None and observation.mask_annotation_id:
                cached = measurement_cache.get(observation.mask_annotation_id)
                if observation.mask_annotation_id not in measurement_cache:
                    mask = self._mask(project_id, observation.mask_annotation_id)
                    if mask is None:
                        cached = None
                    else:
                        try:
                            cached = (
                                mask,
                                self.measurements.measure(observation.mask_annotation_id),
                            )
                        except (NotFoundError, ValidationError) as exc:
                            warnings.append(
                                f"{observation.specimen_id}/{observation.metric}: {exc}"
                            )
                            cached = None
                    measurement_cache[observation.mask_annotation_id] = cached
                if cached is not None:
                    mask, measurement = cached
                    predicted = _measurement_value(measurement, observation.metric)
            if predicted is None:
                blockers.append(
                    f"{observation.specimen_id}/{observation.metric} has no predicted value "
                    "and no compatible ReefVision mask measurement."
                )
                continue
            error = float(predicted) - observation.reference_value
            absolute_error = abs(error)
            relative_error = (
                absolute_error / abs(observation.reference_value) * 100.0
                if observation.reference_value != 0
                else 0.0
                if absolute_error == 0
                else None
            )
            resolved.append(
                ScientificObservationResult(
                    specimen_id=observation.specimen_id,
                    metric=observation.metric,
                    unit=observation.unit,
                    observer_id=observation.observer_id,
                    session_id=observation.session_id,
                    mask_annotation_id=observation.mask_annotation_id,
                    measurement_id=mask.id
                    if measurement is not None and mask is not None
                    else None,
                    measurement_revision=(
                        mask.revision if measurement is not None and mask is not None else None
                    ),
                    reference_value=observation.reference_value,
                    predicted_value=float(predicted),
                    error=error,
                    absolute_error=absolute_error,
                    relative_error_percent=relative_error,
                )
            )

        metric_results: list[ScientificMetricResult] = []
        for metric in sorted(observations_by_metric):
            source_rows = observations_by_metric[metric]
            units = sorted({row.unit for row in source_rows})
            metric_warnings: list[str] = []
            failures: list[str] = []
            if len(units) > 1:
                failures.append(
                    "Reference observations use inconsistent units: " + ", ".join(units)
                )
            unit = units[0]
            rows = [item for item in resolved if item.metric == metric]
            threshold = request.thresholds[metric]
            if rows:
                reference = np.asarray([item.reference_value for item in rows], dtype=np.float64)
                predicted = np.asarray([item.predicted_value for item in rows], dtype=np.float64)
            else:
                failures.append("No observations have both reference and predicted values.")
                reference = np.asarray([0.0], dtype=np.float64)
                predicted = np.asarray([0.0], dtype=np.float64)
            errors = predicted - reference
            absolute = np.abs(errors)
            bias = float(np.mean(errors))
            mae = float(np.mean(absolute))
            rmse = float(np.sqrt(np.mean(np.square(errors))))
            nonzero = np.abs(reference) > np.finfo(np.float64).eps
            relative_mae = (
                float(np.mean(absolute[nonzero] / np.abs(reference[nonzero])) * 100.0)
                if np.any(nonzero)
                else None
            )
            pearson = _pearson(reference, predicted) if rows else None
            model_icc = (
                _icc_absolute_agreement(np.column_stack([reference, predicted]))
                if len(rows) >= 2
                else None
            )
            interobserver, intraobserver = _observer_reliability(source_rows)
            if len(rows) < threshold.minimum_sample_count:
                failures.append(
                    f"Sample count {len(rows)} is below the required "
                    f"{threshold.minimum_sample_count}."
                )
            if threshold.maximum_mae is not None and mae > threshold.maximum_mae:
                failures.append(f"MAE {mae:.6g} exceeds {threshold.maximum_mae:.6g}.")
            if threshold.maximum_rmse is not None and rmse > threshold.maximum_rmse:
                failures.append(f"RMSE {rmse:.6g} exceeds {threshold.maximum_rmse:.6g}.")
            if (
                threshold.maximum_absolute_bias is not None
                and abs(bias) > threshold.maximum_absolute_bias
            ):
                failures.append(
                    f"Absolute bias {abs(bias):.6g} exceeds {threshold.maximum_absolute_bias:.6g}."
                )
            if threshold.maximum_relative_mae_percent is not None:
                if relative_mae is None:
                    failures.append(
                        "Relative MAE is undefined because all reference values are zero."
                    )
                elif relative_mae > threshold.maximum_relative_mae_percent:
                    failures.append(
                        f"Relative MAE {relative_mae:.6g}% exceeds "
                        f"{threshold.maximum_relative_mae_percent:.6g}%."
                    )
            if threshold.minimum_pearson_r is not None and (
                pearson is None or pearson < threshold.minimum_pearson_r
            ):
                failures.append(
                    f"Pearson r {pearson if pearson is not None else 'undefined'} "
                    f"is below {threshold.minimum_pearson_r:.6g}."
                )
            if threshold.minimum_icc is not None and (
                model_icc is None or model_icc < threshold.minimum_icc
            ):
                failures.append(
                    "Model-reference ICC "
                    f"{model_icc if model_icc is not None else 'undefined'} "
                    f"is below {threshold.minimum_icc:.6g}."
                )
            if interobserver is None:
                metric_warnings.append(
                    "Interobserver ICC is unavailable; at least two observers with "
                    "complete shared specimens are required."
                )
            if intraobserver is None:
                metric_warnings.append(
                    "Intraobserver ICC is unavailable; repeated sessions for an observer "
                    "are required."
                )
            if metric.startswith(_DEPTH_METRIC_PREFIXES):
                if not request.calibration_metadata.get("depth_source"):
                    failures.append(
                        "Depth-assisted metrics require calibration_metadata.depth_source."
                    )
                if not request.calibration_metadata.get("camera_intrinsics"):
                    failures.append("Metric depth-assisted dimensions require camera_intrinsics.")
            metric_results.append(
                ScientificMetricResult(
                    metric=metric,
                    unit=unit,
                    sample_count=len(rows),
                    mean_reference=float(np.mean(reference)),
                    mean_predicted=float(np.mean(predicted)),
                    bias=bias,
                    mae=mae,
                    rmse=rmse,
                    relative_mae_percent=relative_mae,
                    pearson_r=pearson,
                    icc_absolute_agreement=model_icc,
                    interobserver_icc=interobserver,
                    intraobserver_icc_mean=intraobserver,
                    threshold=threshold,
                    passed=not failures,
                    failures=failures,
                    warnings=metric_warnings,
                )
            )

        frozen_payload = {
            "dataset_name": request.dataset_name,
            "dataset_version": request.dataset_version,
            "observations": [
                item.model_dump(mode="json")
                for item in sorted(
                    request.observations,
                    key=lambda row: (
                        row.metric,
                        row.specimen_id,
                        row.observer_id,
                        row.session_id,
                        row.replicate_id or "",
                    ),
                )
            ],
            "thresholds": {
                key: value.model_dump(mode="json")
                for key, value in sorted(request.thresholds.items())
            },
            "calibration_metadata": request.calibration_metadata,
        }
        frozen_checksum = canonical_json_sha256(frozen_payload)
        passed = not blockers and all(result.passed for result in metric_results)
        report_payload: dict[str, Any] = {
            "format": "reefvision-scientific-validation-report",
            "format_version": "1.0",
            "report_id": report_id,
            "report_version": report_version,
            "project": {"id": project.id, "name": project.name, "slug": project.slug},
            "dataset_name": request.dataset_name,
            "dataset_version": request.dataset_version,
            "frozen_dataset_checksum": frozen_checksum,
            "created_at": created.isoformat(),
            "passed": passed,
            "calibration_metadata": request.calibration_metadata,
            "notes": request.notes,
            "metric_results": [result.model_dump(mode="json") for result in metric_results],
            "observations": [item.model_dump(mode="json") for item in resolved],
            "warnings": warnings,
            "blockers": blockers,
        }
        report_checksum = canonical_json_sha256(report_payload)
        artifact_id: str | None = None
        json_relative: str | None = None
        csv_relative: str | None = None
        html_relative: str | None = None
        if request.persist_report:
            relative_root = f"{project.storage_root}/scientific-reports/{report_id}"
            output_root = resolve_managed_project_path(self.settings, relative_root)
            temporary = output_root.with_name(f".{output_root.name}.{uuid4().hex[:8]}.tmp")
            temporary.mkdir(parents=True, exist_ok=False)
            try:
                json_path = temporary / "scientific-validation.json"
                csv_path = temporary / "scientific-observations.csv"
                html_path = temporary / "scientific-validation.html"
                json_path.write_bytes(
                    canonical_json_bytes({**report_payload, "report_checksum": report_checksum})
                )
                with csv_path.open("w", encoding="utf-8", newline="") as handle:
                    fieldnames = list(ScientificObservationResult.model_fields)
                    writer = csv.DictWriter(handle, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(item.model_dump(mode="json") for item in resolved)
                metric_rows = "".join(_metric_html(result) for result in metric_results)
                html_path.write_text(
                    "<!doctype html><html><head><meta charset='utf-8'>"
                    "<title>ReefVision Scientific Validation</title>"
                    "<style>body{font-family:system-ui,sans-serif;margin:2rem;line-height:1.45}"
                    "table{border-collapse:collapse;width:100%;font-size:.9rem}"
                    "th,td{border:1px solid #999;padding:.45rem;vertical-align:top}"
                    ".pass{color:#176b36}.fail{color:#a12626}code{overflow-wrap:anywhere}</style>"
                    "</head><body>"
                    f"<h1>{html.escape(request.dataset_name)}</h1>"
                    f"<p>Dataset version: {html.escape(request.dataset_version)}</p>"
                    f"<p>Report version: {html.escape(report_version)}</p>"
                    f"<p>Status: <strong class='{'pass' if passed else 'fail'}'>"
                    f"{'PASS' if passed else 'FAIL'}</strong></p>"
                    f"<p>Frozen dataset checksum: <code>{frozen_checksum}</code></p>"
                    "<h2>Metric acceptance</h2><table><thead><tr>"
                    "<th>Metric</th><th>Unit</th><th>n</th><th>MAE</th><th>RMSE</th>"
                    "<th>Bias</th><th>Relative MAE %</th><th>Pearson r</th><th>ICC</th>"
                    "<th>Status</th><th>Failures</th><th>Warnings</th>"
                    f"</tr></thead><tbody>{metric_rows}</tbody></table>"
                    f"<h2>Blockers</h2><ul>{''.join(f'<li>{html.escape(item)}</li>' for item in blockers) or '<li>None</li>'}</ul>"
                    f"<h2>Notes</h2><p>{html.escape(request.notes or 'None')}</p>"
                    "</body></html>",
                    encoding="utf-8",
                )
                output_root.parent.mkdir(parents=True, exist_ok=True)
                if output_root.exists():
                    shutil.rmtree(output_root)
                temporary.replace(output_root)
            except Exception:
                shutil.rmtree(temporary, ignore_errors=True)
                raise
            json_relative = f"{relative_root}/scientific-validation.json"
            csv_relative = f"{relative_root}/scientific-observations.csv"
            html_relative = f"{relative_root}/scientific-validation.html"
            final_html = output_root / "scientific-validation.html"
            artifact = ArtifactRecord(
                project_id=project_id,
                artifact_type="scientific_validation_report",
                created_by="scientific_validation",
                reefvision_version=__version__,
                source_kind="frozen_reference_dataset",
                source_id=report_id,
                source_checksum=frozen_checksum,
                parameters_json={
                    "dataset_name": request.dataset_name,
                    "dataset_version": request.dataset_version,
                    "thresholds": {
                        key: value.model_dump(mode="json")
                        for key, value in request.thresholds.items()
                    },
                },
                postprocessing_json={"report_checksum": report_checksum},
                review_status="unreviewed",
                managed_path=html_relative,
                checksum=_sha256(final_html),
                size_bytes=final_html.stat().st_size,
                metadata_json={
                    "json_path": json_relative,
                    "csv_path": csv_relative,
                    "report_id": report_id,
                    "report_version": report_version,
                    "passed": passed,
                    "payload": report_payload,
                },
            )
            self.session.add(artifact)
            self.session.commit()
            artifact_id = artifact.id

        return ScientificValidationResponse(
            project_id=project_id,
            report_id=report_id,
            report_version=report_version,
            dataset_name=request.dataset_name,
            dataset_version=request.dataset_version,
            frozen_dataset_checksum=frozen_checksum,
            report_checksum=report_checksum,
            created_at=created.isoformat(),
            passed=passed,
            metric_results=metric_results,
            observations=resolved,
            warnings=warnings,
            blockers=blockers,
            artifact_id=artifact_id,
            json_path=json_relative,
            csv_path=csv_relative,
            html_path=html_relative,
        )
