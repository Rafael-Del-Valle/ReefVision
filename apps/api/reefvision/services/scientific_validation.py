"""Frozen coral measurement acceptance, reliability, and report generation."""

from __future__ import annotations

import csv
import hashlib
import html
import json
import math
import shutil
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any
from uuid import uuid4

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision import __version__
from reefvision.config import Settings
from reefvision.db.models import ArtifactRecord, MaskAnnotation, MaskMeasurement, Project
from reefvision.domain.errors import NotFoundError
from reefvision.schemas.scientific_validation import (
    ScientificMetricResult,
    ScientificObservationResult,
    ScientificReferenceObservation,
    ScientificValidationRequest,
    ScientificValidationResponse,
)
from reefvision.services.measurement_agreement import (
    intraclass_correlation_absolute_agreement,
)
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


def _measurement_value(measurement: MaskMeasurement, metric: str) -> float | None:
    aliases = {
        "area": "area_pixels",
        "area_px": "area_pixels",
        "perimeter": "perimeter_pixels",
        "perimeter_px": "perimeter_pixels",
        "tle": "tle_pixels",
        "tle_px": "tle_pixels",
        "width_m": "projected_width_m",
        "height_m": "projected_height_m",
        "area_m2": "projected_area_m2",
    }
    field_name = aliases.get(metric, metric)
    if hasattr(measurement, field_name):
        value = _finite(getattr(measurement, field_name))
        if value is not None:
            return value
    return _finite((measurement.metrics_json or {}).get(metric))


def _pearson(reference: np.ndarray, predicted: np.ndarray) -> float | None:
    if reference.size < 2 or np.std(reference) == 0 or np.std(predicted) == 0:
        return None
    value = float(np.corrcoef(reference, predicted)[0, 1])
    return value if math.isfinite(value) else None


def _icc_matrix(rows: dict[str, dict[str, float]]) -> float | None:
    if not rows:
        return None
    raters = sorted({rater for values in rows.values() for rater in values})
    complete = [
        [values[rater] for rater in raters]
        for _specimen, values in sorted(rows.items())
        if all(rater in values for rater in raters)
    ]
    if len(raters) < 2 or len(complete) < 2:
        return None
    value = intraclass_correlation_absolute_agreement(np.asarray(complete, dtype=np.float64))
    return value if value is not None and math.isfinite(value) else None


def _observer_reliability(
    observations: list[ScientificReferenceObservation],
) -> tuple[float | None, float | None]:
    interobserver_rows: dict[str, dict[str, float]] = defaultdict(dict)
    by_observer: dict[str, list[ScientificReferenceObservation]] = defaultdict(list)
    for observation in observations:
        interobserver_rows[observation.specimen_id][observation.observer_id] = (
            observation.reference_value
        )
        by_observer[observation.observer_id].append(observation)
    interobserver = _icc_matrix(interobserver_rows)
    intraobserver_values: list[float] = []
    for observer_rows in by_observer.values():
        sessions = {row.session_id for row in observer_rows}
        if len(sessions) < 2:
            continue
        matrix: dict[str, dict[str, float]] = defaultdict(dict)
        for row in observer_rows:
            matrix[row.specimen_id][row.session_id] = row.reference_value
        value = _icc_matrix(matrix)
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

    def _project(self, project_id: str) -> Project:
        project = self.session.get(Project, project_id)
        if project is None:
            raise NotFoundError("Project not found")
        return project

    def run(
        self,
        project_id: str,
        request: ScientificValidationRequest,
    ) -> ScientificValidationResponse:
        project = self._project(project_id)
        report_id = str(uuid4())
        created = datetime.now(UTC)
        report_version = f"1.0-{created.strftime('%Y%m%dT%H%M%SZ')}"
        mask_ids = {
            observation.mask_annotation_id
            for observation in request.observations
            if observation.mask_annotation_id
        }
        measurement_by_mask: dict[str, MaskMeasurement] = {}
        if mask_ids:
            rows = self.session.execute(
                select(MaskMeasurement, MaskAnnotation)
                .join(MaskAnnotation, MaskAnnotation.id == MaskMeasurement.mask_annotation_id)
                .where(
                    MaskMeasurement.mask_annotation_id.in_(mask_ids),
                    MaskMeasurement.is_latest.is_(True),
                    MaskMeasurement.deleted_at.is_(None),
                    MaskAnnotation.project_id == project_id,
                    MaskAnnotation.deleted_at.is_(None),
                )
            )
            measurement_by_mask = {
                measurement.mask_annotation_id: measurement
                for measurement, _mask in rows
            }

        resolved: list[ScientificObservationResult] = []
        blockers: list[str] = []
        warnings: list[str] = []
        observations_by_metric: dict[str, list[ScientificReferenceObservation]] = defaultdict(list)
        for observation in request.observations:
            observations_by_metric[observation.metric].append(observation)
            predicted = observation.predicted_value
            measurement: MaskMeasurement | None = None
            if predicted is None and observation.mask_annotation_id:
                measurement = measurement_by_mask.get(observation.mask_annotation_id)
                if measurement is not None:
                    predicted = _measurement_value(measurement, observation.metric)
            if predicted is None:
                blockers.append(
                    f"{observation.specimen_id}/{observation.metric} has no predicted value and no compatible latest mask measurement."
                )
                continue
            error = float(predicted) - observation.reference_value
            absolute_error = abs(error)
            relative_error = (
                absolute_error / abs(observation.reference_value) * 100.0
                if observation.reference_value != 0
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
                    measurement_id=measurement.id if measurement else None,
                    measurement_revision=measurement.revision if measurement else None,
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
                failures.append("Reference observations use inconsistent units: " + ", ".join(units))
            unit = units[0]
            rows = [item for item in resolved if item.metric == metric]
            threshold = request.thresholds[metric]
            if not rows:
                failures.append("No observations have both reference and predicted values.")
                reference = np.asarray([0.0])
                predicted = np.asarray([0.0])
            else:
                reference = np.asarray([item.reference_value for item in rows], dtype=np.float64)
                predicted = np.asarray([item.predicted_value for item in rows], dtype=np.float64)
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
                intraclass_correlation_absolute_agreement(
                    np.column_stack([reference, predicted])
                )
                if len(rows) >= 2
                else None
            )
            interobserver, intraobserver = _observer_reliability(source_rows)
            if len(rows) < threshold.minimum_sample_count:
                failures.append(
                    f"Sample count {len(rows)} is below the required {threshold.minimum_sample_count}."
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
                    failures.append("Relative MAE is undefined because all reference values are zero.")
                elif relative_mae > threshold.maximum_relative_mae_percent:
                    failures.append(
                        f"Relative MAE {relative_mae:.6g}% exceeds {threshold.maximum_relative_mae_percent:.6g}%."
                    )
            if threshold.minimum_pearson_r is not None:
                if pearson is None or pearson < threshold.minimum_pearson_r:
                    failures.append(
                        f"Pearson r {pearson if pearson is not None else 'undefined'} is below {threshold.minimum_pearson_r:.6g}."
                    )
            if threshold.minimum_icc is not None:
                if model_icc is None or model_icc < threshold.minimum_icc:
                    failures.append(
                        f"Model-reference ICC {model_icc if model_icc is not None else 'undefined'} is below {threshold.minimum_icc:.6g}."
                    )
            if interobserver is None:
                metric_warnings.append(
                    "Interobserver ICC is unavailable; at least two observers with complete shared specimens are required."
                )
            if intraobserver is None:
                metric_warnings.append(
                    "Intraobserver ICC is unavailable; repeated sessions for an observer are required."
                )
            if metric.startswith(_DEPTH_METRIC_PREFIXES):
                if not request.calibration_metadata.get("depth_source"):
                    failures.append("Depth-assisted metrics require calibration_metadata.depth_source.")
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
                    icc_absolute_agreement=(
                        float(model_icc) if model_icc is not None and math.isfinite(model_icc) else None
                    ),
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
                json_path.write_bytes(canonical_json_bytes({**report_payload, "report_checksum": report_checksum}))
                with csv_path.open("w", encoding="utf-8", newline="") as handle:
                    writer = csv.writer(handle)
                    writer.writerow(
                        [
                            "specimen_id",
                            "metric",
                            "unit",
                            "observer_id",
                            "session_id",
                            "mask_annotation_id",
                            "measurement_id",
                            "measurement_revision",
                            "reference_value",
                            "predicted_value",
                            "error",
                            "absolute_error",
                            "relative_error_percent",
                        ]
                    )
                    for item in resolved:
                        writer.writerow(list(item.model_dump(mode="json").values()))
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
                    f"<p>Status: <strong class='{'pass' if passed else 'fail'}'>{'PASS' if passed else 'FAIL'}</strong></p>"
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
