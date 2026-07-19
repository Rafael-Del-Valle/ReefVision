"""Generate self-contained training and tuning reports with configurable typography."""

from __future__ import annotations

import base64
import html
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import Project, TrainingRun
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.schemas.training_reports import (
    TrainingReportCreateRequest,
    TrainingReportResponse,
)
from reefvision.storage.projects import resolve_managed_project_path


FONT_STACKS = {
    "system": "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
    "sans-serif": "Arial, Helvetica, sans-serif",
    "serif": "Georgia, 'Times New Roman', serif",
    "monospace": "Consolas, 'Courier New', monospace",
    "Arial": "Arial, Helvetica, sans-serif",
    "Aptos": "Aptos, Calibri, Arial, sans-serif",
    "Calibri": "Calibri, Aptos, Arial, sans-serif",
    "Georgia": "Georgia, 'Times New Roman', serif",
    "Helvetica": "Helvetica, Arial, sans-serif",
    "Times New Roman": "'Times New Roman', Georgia, serif",
}


def _number(value: Any, digits: int = 4) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        number = float(value)
        if math.isfinite(number):
            return f"{number:.{digits}f}"
    return "—"


def _managed_json(settings: Settings, managed_path: object) -> dict[str, Any] | None:
    if not isinstance(managed_path, str) or not managed_path.strip():
        return None
    try:
        path = resolve_managed_project_path(settings, managed_path)
    except ValidationError:
        return None
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _svg_line_chart(
    series: list[tuple[str, list[float]]],
    *,
    title: str,
    font_size: float,
    width: int = 940,
    height: int = 300,
) -> str:
    series = [(name, values) for name, values in series if values]
    if not series:
        return ""
    all_values = [value for _, values in series for value in values if math.isfinite(value)]
    if not all_values:
        return ""
    low, high = min(all_values), max(all_values)
    if math.isclose(low, high):
        high = low + 1.0
    left, right, top, bottom = 64, 24, 38, 48
    chart_width = width - left - right
    chart_height = height - top - bottom
    max_points = max(len(values) for _, values in series)

    def point(index: int, value: float) -> tuple[float, float]:
        x = left + (index / max(max_points - 1, 1)) * chart_width
        y = top + (1 - (value - low) / (high - low)) * chart_height
        return x, y

    colors = ("#0f766e", "#2563eb", "#9333ea", "#c2410c", "#be123c", "#4d7c0f")
    paths: list[str] = []
    legend: list[str] = []
    for series_index, (name, values) in enumerate(series):
        coordinates = [point(index, value) for index, value in enumerate(values) if math.isfinite(value)]
        if not coordinates:
            continue
        path_data = " ".join(
            ("M" if index == 0 else "L") + f" {x:.2f} {y:.2f}"
            for index, (x, y) in enumerate(coordinates)
        )
        color = colors[series_index % len(colors)]
        paths.append(
            f'<path d="{path_data}" fill="none" stroke="{color}" stroke-width="2.2" />'
        )
        legend.append(
            f'<g transform="translate({left + series_index * 145},{height - 14})">'
            f'<line x1="0" y1="0" x2="18" y2="0" stroke="{color}" stroke-width="3" />'
            f'<text x="24" y="4" font-size="{font_size}">{html.escape(name)}</text></g>'
        )
    grid = []
    for step in range(5):
        y = top + step / 4 * chart_height
        value = high - step / 4 * (high - low)
        grid.append(
            f'<line x1="{left}" y1="{y:.2f}" x2="{width-right}" y2="{y:.2f}" '
            'stroke="#d1d5db" stroke-width="1" />'
            f'<text x="{left-8}" y="{y+4:.2f}" text-anchor="end" font-size="{font_size}">'
            f'{value:.3f}</text>'
        )
    return (
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(title)}">'
        f'<text x="{left}" y="22" font-size="{font_size + 2}" font-weight="700">'
        f'{html.escape(title)}</text>'
        + "".join(grid)
        + f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top+chart_height}" stroke="#111827" />'
        + f'<line x1="{left}" y1="{top+chart_height}" x2="{width-right}" y2="{top+chart_height}" stroke="#111827" />'
        + "".join(paths)
        + "".join(legend)
        + "</svg>"
    )


def _svg_grouped_bars(
    rows: list[dict[str, Any]],
    *,
    title: str,
    font_size: float,
    width: int = 940,
) -> str:
    if not rows:
        return ""
    metrics = ("precision", "recall", "f1")
    row_height = 34
    top, left, right, bottom = 42, 180, 30, 34
    height = top + bottom + len(rows) * row_height
    chart_width = width - left - right
    colors = {"precision": "#0f766e", "recall": "#2563eb", "f1": "#9333ea"}
    content = [
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(title)}">',
        f'<text x="{left}" y="24" font-size="{font_size + 2}" font-weight="700">{html.escape(title)}</text>',
    ]
    for index, row in enumerate(rows):
        y = top + index * row_height
        label = str(row.get("class_name", row.get("class_id", "Class")))
        content.append(
            f'<text x="{left-10}" y="{y+18}" text-anchor="end" font-size="{font_size}">'
            f'{html.escape(label)}</text>'
        )
        for metric_index, metric in enumerate(metrics):
            value = row.get(metric)
            numeric = float(value) if isinstance(value, (int, float)) else 0.0
            bar_width = max(0.0, min(1.0, numeric)) * chart_width
            bar_y = y + metric_index * 9
            content.append(
                f'<rect x="{left}" y="{bar_y}" width="{bar_width:.2f}" height="7" '
                f'fill="{colors[metric]}" rx="2" />'
            )
    legend_y = height - 12
    for index, metric in enumerate(metrics):
        x = left + index * 130
        content.append(
            f'<rect x="{x}" y="{legend_y-8}" width="14" height="8" fill="{colors[metric]}" />'
            f'<text x="{x+20}" y="{legend_y}" font-size="{font_size}">{metric.title()}</text>'
        )
    content.append("</svg>")
    return "".join(content)


def _svg_tuning_scatter(
    trials: list[dict[str, Any]],
    *,
    parameter: str,
    title: str,
    font_size: float,
    width: int = 460,
    height: int = 300,
) -> str:
    points: list[tuple[float, float]] = []
    for trial in trials:
        parameters = trial.get("parameters", {})
        x = parameters.get(parameter) if isinstance(parameters, dict) else None
        y = trial.get("fitness")
        if isinstance(x, (int, float)) and isinstance(y, (int, float)):
            points.append((float(x), float(y)))
    if not points:
        return ""
    x_min, x_max = min(value[0] for value in points), max(value[0] for value in points)
    y_min, y_max = min(value[1] for value in points), max(value[1] for value in points)
    if math.isclose(x_min, x_max):
        x_max = x_min + 1
    if math.isclose(y_min, y_max):
        y_max = y_min + 1
    left, right, top, bottom = 58, 22, 42, 46
    chart_width, chart_height = width - left - right, height - top - bottom
    circles = []
    for x, y in points:
        px = left + (x - x_min) / (x_max - x_min) * chart_width
        py = top + (1 - (y - y_min) / (y_max - y_min)) * chart_height
        circles.append(f'<circle cx="{px:.2f}" cy="{py:.2f}" r="4" fill="#0f766e" opacity="0.75" />')
    return (
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(title)}">'
        f'<text x="{left}" y="24" font-size="{font_size+1}" font-weight="700">{html.escape(title)}</text>'
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{height-bottom}" stroke="#111827" />'
        f'<line x1="{left}" y1="{height-bottom}" x2="{width-right}" y2="{height-bottom}" stroke="#111827" />'
        + "".join(circles)
        + f'<text x="{width/2}" y="{height-10}" text-anchor="middle" font-size="{font_size}">{html.escape(parameter)}</text>'
        + f'<text x="15" y="{height/2}" transform="rotate(-90 15 {height/2})" text-anchor="middle" font-size="{font_size}">Fitness</text>'
        + "</svg>"
    )


def _embed_png(settings: Settings, managed_path: object) -> str | None:
    if not isinstance(managed_path, str):
        return None
    try:
        path = resolve_managed_project_path(settings, managed_path)
    except ValidationError:
        return None
    if not path.is_file() or path.suffix.casefold() != ".png":
        return None
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


class TrainingReportService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def _run(self, run_id: str) -> TrainingRun:
        run = self.session.get(TrainingRun, run_id)
        if run is None:
            raise NotFoundError("Training run not found")
        return run

    def create(
        self,
        run_id: str,
        request: TrainingReportCreateRequest,
    ) -> TrainingReportResponse:
        run = self._run(run_id)
        project = self.session.get(Project, run.project_id)
        if project is None:
            raise NotFoundError("Project not found")
        report_id = str(uuid4())
        created_at = datetime.now(UTC)
        title = request.title or f"{run.run_name} training report"
        report_relative_root = f"{project.storage_root}/training/{run.id}/reports/{report_id}"
        report_root = resolve_managed_project_path(self.settings, report_relative_root)
        report_root.mkdir(parents=True, exist_ok=False)
        html_path = report_root / "report.html"
        json_path = report_root / "report.json"
        warnings: list[str] = []
        included_sections: list[str] = []
        artifact_manifest = dict(run.artifact_manifest_json or {})

        validation_manifest = artifact_manifest.get("ultralytics_validation", {})
        validation_payload = None
        if isinstance(validation_manifest, dict):
            validation_payload = validation_manifest.get("summary")
            if not isinstance(validation_payload, dict):
                validation_payload = _managed_json(
                    self.settings,
                    validation_manifest.get("json_path"),
                )
        tuning_payload = artifact_manifest.get("tuning")
        if not isinstance(tuning_payload, dict):
            tuning_payload = None

        sections: list[str] = []
        summary_rows = "".join(
            f"<tr><th>{html.escape(str(key))}</th><td>{html.escape(_number(value))}</td></tr>"
            for key, value in sorted(dict(run.metrics_json or {}).items())
        )
        sections.append(
            "<section><h2>Run summary</h2><table><tbody>"
            f"<tr><th>Status</th><td>{html.escape(run.status)}</td></tr>"
            f"<tr><th>Task</th><td>{html.escape(run.task)}</td></tr>"
            f"<tr><th>Architecture</th><td>{html.escape(run.architecture)}</td></tr>"
            f"<tr><th>Dataset manifest</th><td><code>{html.escape(run.dataset_manifest_sha256)}</code></td></tr>"
            f"{summary_rows}</tbody></table></section>"
        )
        included_sections.append("run_summary")

        if request.include_training_history:
            history = dict(run.metrics_history_json or {})
            selected: list[tuple[str, list[float]]] = []
            preferred_tokens = ("precision", "recall", "map50", "mAP50", "loss")
            for key, values in history.items():
                if not isinstance(values, list):
                    continue
                numeric = [float(value) for value in values if isinstance(value, (int, float))]
                if numeric and any(token.casefold() in key.casefold() for token in preferred_tokens):
                    selected.append((key, numeric))
                if len(selected) >= 6:
                    break
            chart = _svg_line_chart(
                selected,
                title="Training and validation history",
                font_size=request.figure_label_font_size_pt,
            )
            if chart:
                sections.append(f"<section><h2>Training history</h2>{chart}</section>")
                included_sections.append("training_history")
            else:
                warnings.append("No numeric training-history series were available for plotting")

        if request.include_per_class_metrics and validation_payload:
            for scope in validation_payload.get("scopes", []):
                rows = scope.get("per_class", []) if isinstance(scope, dict) else []
                if not isinstance(rows, list):
                    continue
                scope_name = str(scope.get("scope", "model"))
                table_rows = "".join(
                    "<tr>"
                    f"<td>{html.escape(str(row.get('class_name', row.get('class_id', 'Class'))))}</td>"
                    f"<td>{_number(row.get('precision'))}</td>"
                    f"<td>{_number(row.get('recall'))}</td>"
                    f"<td>{_number(row.get('f1'))}</td>"
                    f"<td>{_number(row.get('map50'))}</td>"
                    f"<td>{_number(row.get('map50_95'))}</td>"
                    "</tr>"
                    for row in rows
                    if isinstance(row, dict)
                )
                chart = _svg_grouped_bars(
                    [row for row in rows if isinstance(row, dict)],
                    title=f"Per-class precision, recall, and F1 — {scope_name}",
                    font_size=request.figure_label_font_size_pt,
                )
                sections.append(
                    f"<section><h2>Per-class metrics — {html.escape(scope_name)}</h2>{chart}"
                    "<table><thead><tr><th>Class</th><th>Precision</th><th>Recall</th>"
                    "<th>F1</th><th>mAP50</th><th>mAP50–95</th></tr></thead>"
                    f"<tbody>{table_rows}</tbody></table></section>"
                )
            included_sections.append("per_class_metrics")
        elif request.include_per_class_metrics:
            warnings.append("No explicit Ultralytics per-class validation artifact was available")

        if request.include_confusion_matrix and validation_payload:
            confusion = validation_payload.get("confusion_matrix")
            if confusion:
                sections.append(
                    "<section><h2>Confusion matrix data</h2>"
                    f"<pre>{html.escape(json.dumps(confusion, indent=2))}</pre></section>"
                )
                included_sections.append("confusion_matrix")

        if request.include_tuning_analysis and tuning_payload:
            trials = tuning_payload.get("trials", [])
            if isinstance(trials, list) and trials:
                fitness_series = [
                    float(trial["fitness"])
                    for trial in trials
                    if isinstance(trial, dict) and isinstance(trial.get("fitness"), (int, float))
                ]
                charts = [
                    _svg_line_chart(
                        [("fitness", fitness_series)],
                        title="Hyperparameter tuning fitness by trial",
                        font_size=request.figure_label_font_size_pt,
                        height=260,
                    )
                ]
                parameter_names = sorted(
                    {
                        key
                        for trial in trials
                        if isinstance(trial, dict)
                        for key in (
                            trial.get("parameters", {}).keys()
                            if isinstance(trial.get("parameters"), dict)
                            else []
                        )
                    }
                )
                charts.extend(
                    _svg_tuning_scatter(
                        trials,
                        parameter=parameter,
                        title=f"{parameter} versus fitness",
                        font_size=request.figure_label_font_size_pt,
                    )
                    for parameter in parameter_names
                )
                best_parameters = tuning_payload.get("best_parameters", {})
                sections.append(
                    "<section><h2>Hyperparameter tuning</h2>"
                    + "".join(chart for chart in charts if chart)
                    + "<h3>Best parameters</h3>"
                    + f"<pre>{html.escape(json.dumps(best_parameters, indent=2, sort_keys=True))}</pre>"
                    + "</section>"
                )
                included_sections.append("hyperparameter_tuning")
            else:
                warnings.append("Tuning was configured but no trial records were available")

        if request.include_ultralytics_plots and isinstance(validation_manifest, dict):
            plot_paths = validation_manifest.get("plot_paths", [])
            embedded = []
            if isinstance(plot_paths, list):
                for path in plot_paths:
                    source = _embed_png(self.settings, path)
                    if source:
                        embedded.append(
                            f'<figure><img src="{source}" alt="Ultralytics validation plot" />'
                            f'<figcaption>{html.escape(Path(str(path)).name)}</figcaption></figure>'
                        )
            if embedded:
                sections.append(
                    "<section><h2>Ultralytics validation plots</h2>"
                    f"<div class=\"figure-grid\">{''.join(embedded)}</div></section>"
                )
                included_sections.append("ultralytics_plots")

        if request.include_provenance:
            provenance = {
                "training_run_id": run.id,
                "dataset_version_id": run.dataset_version_id,
                "dataset_manifest_sha256": run.dataset_manifest_sha256,
                "split_manifest_sha256": run.split_manifest_sha256,
                "provider_id": run.provider_id,
                "architecture": run.architecture,
                "initial_checkpoint_source": run.initial_checkpoint_source,
                "initial_checkpoint_model_id": run.initial_checkpoint_model_id,
                "resolved_model_checksum": run.resolved_model_checksum,
                "training_config": run.training_config_json,
                "tuning_config": run.tuning_config_json,
                "evaluation_config": run.evaluation_config_json,
                "created_at": created_at.isoformat(),
            }
            sections.append(
                "<section><h2>Reproducibility and provenance</h2>"
                f"<pre>{html.escape(json.dumps(provenance, indent=2, sort_keys=True, default=str))}</pre>"
                "</section>"
            )
            included_sections.append("provenance")

        font_stack = FONT_STACKS[request.font_family]
        document = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{html.escape(title)}</title>
<style>
:root {{ font-family: {font_stack}; font-size: {request.base_font_size_pt}pt; color: #111827; }}
body {{ max-width: 1100px; margin: 0 auto; padding: 2rem; line-height: 1.45; background: white; }}
h1 {{ font-size: {request.heading_font_size_pt}pt; margin-bottom: .25rem; }}
h2 {{ font-size: {request.heading_font_size_pt * .72:.2f}pt; border-bottom: 1px solid #d1d5db; padding-bottom: .25rem; }}
h3 {{ font-size: {request.heading_font_size_pt * .58:.2f}pt; }}
.subtitle {{ color: #4b5563; }}
section {{ margin: 2rem 0; break-inside: avoid; }}
table {{ width: 100%; border-collapse: collapse; font-size: {request.table_font_size_pt}pt; }}
th, td {{ border: 1px solid #d1d5db; padding: .45rem .55rem; text-align: left; }}
th {{ background: #f3f4f6; }}
code, pre {{ font-family: Consolas, 'Courier New', monospace; font-size: .9em; }}
pre {{ white-space: pre-wrap; background: #f8fafc; border: 1px solid #e5e7eb; padding: 1rem; overflow-wrap: anywhere; }}
svg {{ width: 100%; height: auto; margin: .75rem 0; }}
.figure-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(360px, 1fr)); gap: 1rem; }}
figure {{ margin: 0; border: 1px solid #e5e7eb; padding: .75rem; break-inside: avoid; }}
figure img {{ width: 100%; height: auto; }}
figcaption {{ font-size: {request.figure_label_font_size_pt}pt; color: #4b5563; }}
.warning {{ border-left: 4px solid #d97706; background: #fffbeb; padding: .75rem 1rem; }}
@media print {{ body {{ max-width: none; padding: 0; }} .figure-grid {{ grid-template-columns: 1fr 1fr; }} }}
</style>
</head>
<body>
<header><p>ReefVision model-development report</p><h1>{html.escape(title)}</h1>
<p class="subtitle">{html.escape(request.subtitle or project.name)}</p>
<p>Generated {created_at.isoformat()}</p></header>
{''.join(f'<div class="warning">{html.escape(warning)}</div>' for warning in warnings)}
{''.join(sections)}
</body></html>"""
        html_path.write_text(document, encoding="utf-8")
        manifest = {
            "report_id": report_id,
            "training_run_id": run.id,
            "title": title,
            "created_at": created_at.isoformat(),
            "style": request.model_dump(mode="json"),
            "included_sections": included_sections,
            "warnings": warnings,
            "html_path": html_path.relative_to(self.settings.resolved_data_dir).as_posix(),
        }
        json_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
        report_record = {
            **manifest,
            "json_path": json_path.relative_to(self.settings.resolved_data_dir).as_posix(),
        }
        reports = artifact_manifest.get("reports", [])
        if not isinstance(reports, list):
            reports = []
        artifact_manifest["reports"] = [*reports, report_record]
        run.artifact_manifest_json = artifact_manifest
        self.session.commit()
        return TrainingReportResponse(
            report_id=report_id,
            training_run_id=run.id,
            title=title,
            created_at=created_at,
            font_family=request.font_family,
            html_path=manifest["html_path"],
            json_path=report_record["json_path"],
            download_url=f"/training-runs/{run.id}/reports/{report_id}/download",
            included_sections=included_sections,
            warnings=warnings,
        )

    def report_path(self, run_id: str, report_id: str) -> Path:
        run = self._run(run_id)
        reports = dict(run.artifact_manifest_json or {}).get("reports", [])
        if not isinstance(reports, list):
            raise NotFoundError("Training report not found")
        for report in reports:
            if isinstance(report, dict) and report.get("report_id") == report_id:
                managed_path = report.get("html_path")
                if not isinstance(managed_path, str):
                    break
                path = resolve_managed_project_path(self.settings, managed_path)
                if path.is_file():
                    return path
                break
        raise NotFoundError("Training report not found")
