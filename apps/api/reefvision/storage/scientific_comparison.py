"""CSV export for saved scientific comparison results."""

import csv
from io import StringIO

from reefvision.schemas.scientific_comparison import ComparisonRecord
from reefvision.schemas.static_comparison import StaticComparisonRecord


def _text_cell(value: str) -> str:
    if value.startswith(("\t", "\r", "\n")) or value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def comparison_csv(report: ComparisonRecord) -> str:
    buffer = StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(
        [
            "source_report",
            "checkpoint_sha256",
            "reference_manifest_sha256",
            "agreement_sha256",
            "method",
            "evidence",
            "metric",
            "name",
            "unit",
            "recording",
            "recording_group",
            "individual",
            "frame",
            "start_s",
            "end_s",
            "reference",
            "estimate",
            "signed_difference",
            "absolute_difference",
            "signed_percentage_error",
            "exclusion",
        ]
    )
    snapshot = report.snapshot
    for model in snapshot.models:
        base = [
            model.source_job_id,
            model.checkpoint_sha256,
            snapshot.reference_sha256,
            report.content_sha256,
            snapshot.method,
            snapshot.data_kind,
            snapshot.options.metric,
            _text_cell(snapshot.options.name),
            _text_cell(snapshot.options.unit or "events"),
        ]
        for row in model.pairs:
            difference = row.estimate - row.reference
            writer.writerow(
                [
                    *base,
                    row.video_id,
                    _text_cell(row.group_id),
                    _text_cell(row.individual_id),
                    row.frame,
                    row.start_s,
                    row.end_s,
                    row.reference,
                    row.estimate,
                    difference,
                    abs(difference),
                    difference / abs(row.reference) * 100 if row.reference else None,
                    None,
                ]
            )
        for excluded in snapshot.exclusions:
            if excluded.source_job_id == model.source_job_id:
                writer.writerow(
                    [
                        *base,
                        excluded.video_id,
                        None,
                        _text_cell(excluded.individual_id),
                        excluded.frame,
                        excluded.start_s,
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        _text_cell(excluded.reason),
                    ]
                )
    return buffer.getvalue()


def static_comparison_csv(report: StaticComparisonRecord) -> str:
    buffer = StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(
        [
            "comparison_sha256",
            "reference_sha256",
            "checkpoint_sha256",
            "lineage",
            "model_id",
            "model",
            "image_id",
            "image",
            "group_key",
            "class_id",
            "class",
            "reference",
            "predicted",
            "signed_error",
            "absolute_error",
            "signed_percentage_error",
            "status",
            "message",
        ]
    )
    snapshot = report.snapshot
    evidence = snapshot.evidence
    images = {row.id: row for row in evidence.images}
    classes = {row.id: row.name for row in evidence.classes}
    for model, result in zip(evidence.models, snapshot.results, strict=True):
        for row in result.images:
            image = images[row.image_id]
            for count in row.counts:
                error = count.prediction - count.reference if count.prediction is not None else None
                writer.writerow(
                    [
                        report.content_sha256,
                        evidence.reference_sha256,
                        model.checkpoint_sha256,
                        model.lineage.status,
                        model.id,
                        _text_cell(model.name),
                        image.id,
                        _text_cell(image.name),
                        _text_cell(image.group_key or ""),
                        count.class_id,
                        _text_cell(classes[count.class_id]),
                        count.reference,
                        count.prediction,
                        error,
                        abs(error) if error is not None else None,
                        error / count.reference * 100
                        if error is not None and count.reference
                        else None,
                        count.status,
                        _text_cell(row.message or ""),
                    ]
                )
    return buffer.getvalue()
