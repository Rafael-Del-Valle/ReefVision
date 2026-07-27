from __future__ import annotations

from reefvision.storage.datasets import (
    dataset_export_relative_paths,
    safe_export_filename,
)


def test_dataset_export_paths_are_compact_and_deterministic() -> None:
    output_path, manifest_path, archive_path = dataset_export_relative_paths(
        project_storage_root="projects/645b6818-8876-431c-ab3f-cee8f14d8a55",
        version_number=1,
        export_id="34758aa2-dcb0-4c60-9e81-e4dcce1df48d",
    )
    repeated = dataset_export_relative_paths(
        project_storage_root="projects/645b6818-8876-431c-ab3f-cee8f14d8a55",
        version_number=1,
        export_id="34758aa2-dcb0-4c60-9e81-e4dcce1df48d",
    )

    assert repeated == (output_path, manifest_path, archive_path)
    assert output_path.startswith(
        "projects/645b6818-8876-431c-ab3f-cee8f14d8a55/exports/v0001-"
    )
    assert len(output_path.rsplit("/", 1)[-1]) == len("v0001-") + 16
    assert manifest_path == f"{output_path}/export-manifest.json"
    assert archive_path == f"{output_path}.zip"


def test_safe_export_filename_is_compact_unique_and_preserves_suffix() -> None:
    first = safe_export_filename(
        "8417fcc4-99cd-4c17-a274-585369adcbbb",
        "swiftia-a.png",
    )
    repeated = safe_export_filename(
        "8417fcc4-99cd-4c17-a274-585369adcbbb",
        "renamed-source.png",
    )
    second = safe_export_filename(
        "1dcf1f0f-67ab-49b6-a5a7-59de49631713",
        "swiftia-a.png",
    )

    assert first == repeated
    assert first != second
    assert first.startswith("i-")
    assert first.endswith(".png")
    assert len(first) == len("i-") + 16 + len(".png")
