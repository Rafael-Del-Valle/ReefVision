from reefvision.storage.datasets import (
    dataset_export_relative_paths,
    safe_export_filename,
)


def test_export_paths_use_distinct_compact_identifiers() -> None:
    first_id = "12345678-0000-4000-8000-000000000001"
    second_id = "12345678-0000-4000-8000-000000000002"

    first = dataset_export_relative_paths(
        project_storage_root="projects/project-1",
        version_number=7,
        export_id=first_id,
    )
    second = dataset_export_relative_paths(
        project_storage_root="projects/project-1",
        version_number=7,
        export_id=second_id,
    )

    assert first != second
    assert first_id not in first[0]
    assert second_id not in second[0]
    assert first[0].startswith("projects/project-1/exports/v0007-")
    assert second[0].startswith("projects/project-1/exports/v0007-")
    assert len(first[0].rsplit("-", 1)[-1]) == 16
    assert len(second[0].rsplit("-", 1)[-1]) == 16


def test_exported_image_names_use_distinct_compact_identifiers() -> None:
    first_id = "abcdef12-0000-4000-8000-000000000001"
    second_id = "abcdef12-0000-4000-8000-000000000002"

    first = safe_export_filename(first_id, "coral image.png")
    second = safe_export_filename(second_id, "coral image.png")

    assert first != second
    assert first_id not in first
    assert second_id not in second
    assert first.startswith("i-")
    assert second.startswith("i-")
    assert first.endswith(".png")
    assert second.endswith(".png")
    assert len(first) == len("i-") + 16 + len(".png")
    assert len(second) == len("i-") + 16 + len(".png")
