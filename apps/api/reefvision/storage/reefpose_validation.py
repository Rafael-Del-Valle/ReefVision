"""Tabular export of scientific validation results."""

import csv
import io
import json
from typing import Any


def validation_csv(report: dict[str, Any]) -> str:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["result_sha256", "section", "path", "value_json"])

    def write(section: str, path: str, value: Any) -> None:
        if isinstance(value, dict):
            for key, item in sorted(value.items()):
                write(section, f"{path}/{key}", item)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                write(section, f"{path}/{index}", item)
        else:
            writer.writerow([report["result_sha256"], section, path, json.dumps(value)])

    for name, value in sorted(report.items()):
        write(name, "", value)
    return output.getvalue()


def validation_summary_csv(report: dict[str, Any]) -> str:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(
        ["report_sha256", "video_id", "individual", "measure", "unit", "metric", "value"]
    )

    def write(
        video: str,
        individual: str,
        measure: str,
        unit: str,
        row: dict[str, Any],
        fields: tuple[str, ...],
    ) -> None:
        for field in fields:
            writer.writerow(
                [
                    report["result_sha256"],
                    video,
                    individual,
                    measure,
                    unit,
                    field,
                    row.get(field),
                ]
            )

    write(
        "",
        "",
        "identity",
        "",
        report["identity"],
        ("id_f1", "id_precision", "id_recall", "conditional_id_f1"),
    )
    complete = report["sensitivity"][report["selected_configuration_index"]]["complete"]
    write("", "", "complete events", "", complete, ("tp", "fp", "fn", "precision", "recall", "f1"))
    for recording in report["recordings"]:
        video = recording["video_id"]
        for row in recording["measurements"]:
            write(
                video,
                row["individual_id"],
                row["definition_id"],
                row["unit"],
                row,
                ("reference_n", "n", "bias", "mae", "rmse"),
            )
        for row in recording["events"]:
            if "complete" in row:
                write(
                    video,
                    row["individual_id"],
                    row["label"],
                    "",
                    row["complete"],
                    ("tp", "fp", "fn", "precision", "recall", "f1", "count_error"),
                )
    return output.getvalue()
