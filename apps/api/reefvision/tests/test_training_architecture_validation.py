from reefvision.services.training import _ultralytics_architecture_available


def test_scaled_yolo_catalog_architectures_match_base_ultralytics_yaml() -> None:
    available = {"yolo11.yaml", "yolov8.yaml"}

    for family in ("yolo11", "yolov8"):
        for scale in "nslmx":
            assert _ultralytics_architecture_available(
                f"{family}{scale}.yaml",
                available,
            )


def test_exact_ultralytics_architecture_name_still_matches() -> None:
    assert _ultralytics_architecture_available(
        "yolo11.yaml",
        {"yolo11.yaml"},
    )


def test_unknown_ultralytics_architecture_remains_unavailable() -> None:
    assert not _ultralytics_architecture_available(
        "yolo99n.yaml",
        {"yolo11.yaml", "yolov8.yaml"},
    )
