from reefvision.storage.datasets import dataset_export_relative_paths


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
