from reefvision.storage.datasets import (
    dataset_export_relative_paths,
    safe_export_filename,
)


def test_export_paths_use_the_complete_export_identifier() -> None:
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
    assert first_id in first[0]
    assert second_id in second[0]


def test_exported_image_names_are_compact_unique_and_extension_preserving() -> None:
    first_id = "abcdef12-0000-4000-8000-000000000001"
    second_id = "abcdef12-0000-4000-8000-000000000002"

    first = safe_export_filename(first_id, "coral image.png")
    second = safe_export_filename(second_id, "coral image.png")

    assert first != second
    assert first.endswith("_coral_image.png")
    assert second.endswith("_coral_image.png")
    assert len(first) <= 63
    assert len(second) <= 63


def test_exported_image_names_bound_long_source_filenames() -> None:
    image_id = "abcdef12-0000-4000-8000-000000000003"
    exported = safe_export_filename(
        image_id,
        "very-long-coral-source-name-" + ("x" * 180) + ".tiff",
    )

    assert exported.endswith(".tiff")
    assert len(exported) <= 63
