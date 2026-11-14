"""CSV export for saved scientific comparison results."""

import csv
from io import StringIO

from reefvision.schemas.scientific_comparison import ComparisonRecord


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
            snapshot.options.name,
            snapshot.options.unit or "events",
        ]
        for row in model.pairs:
            difference = row.estimate - row.reference
            writer.writerow(
                [
                    *base,
                    row.video_id,
                    row.group_id,
                    row.individual_id,
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
                        excluded.individual_id,
                        excluded.frame,
                        excluded.start_s,
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        excluded.reason,
                    ]
                )
    return buffer.getvalue()
