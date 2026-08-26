from __future__ import annotations

from pathlib import Path

from reefvision.ml.task_registry import TASKS

ROOT = Path(__file__).resolve().parents[4]


def _task(task_id: str):
    return next(item for item in TASKS if item.task_id == task_id)


def test_release_capability_registry_promotes_completed_11_to_13_workflows() -> None:
    classify = _task("classify")
    track = _task("track")
    video_annotate = _task("video_annotate")

    assert classify.state == "ready"
    assert classify.supports_training is True
    assert classify.supports_inference is True

    assert track.state == "ready"
    assert track.supports_inference is True

    assert video_annotate.state == "ready"
    assert video_annotate.supports_inference is True


def test_classification_release_surface_includes_dataset_training_inference_and_review() -> None:
    source = (
        ROOT / "apps" / "api" / "reefvision" / "api" / "routes" / "classification.py"
    ).read_text(encoding="utf-8")

    for required in (
        "/classification-datasets",
        "/classification-training-jobs",
        "/classification-inference-jobs",
        "/classification-predictions",
        "/classification-predictions/{prediction_id}/review",
    ):
        assert required in source


def test_active_learning_release_surface_freezes_reviewed_feedback() -> None:
    service = (
        ROOT / "apps" / "api" / "reefvision" / "services" / "active_learning_rounds.py"
    ).read_text(encoding="utf-8")
    frontend = (
        ROOT
        / "apps"
        / "web"
        / "src"
        / "features"
        / "active-learning"
        / "ActiveLearningWorkspace.tsx"
    ).read_text(encoding="utf-8")

    assert "uncertainty" in service
    assert "selection_manifest_json" in service
    assert "feedback_dataset_version_id" in service
    assert "Complete round + snapshot feedback" in frontend


def test_video_release_surface_includes_tracking_benchmark_and_science_workflow() -> None:
    routes = (ROOT / "apps" / "api" / "reefvision" / "api" / "routes" / "videos.py").read_text(
        encoding="utf-8"
    )
    workspace = (
        ROOT / "apps" / "web" / "src" / "features" / "video" / "VideoTrackingWorkspace.tsx"
    ).read_text(encoding="utf-8")

    assert "/tracking-benchmark" in routes
    assert "/tracking-jobs" in routes
    assert "getVideoTrackInterpolation" in workspace
    assert "getVideoTrackAnalytics" in workspace


def test_workflow_builder_release_surface_has_typed_reviewable_production_nodes() -> None:
    registry = (
        ROOT / "apps" / "api" / "reefvision" / "services" / "workflow_node_registry.py"
    ).read_text(encoding="utf-8")
    graph_service = (
        ROOT / "apps" / "api" / "reefvision" / "services" / "workflow_graphs.py"
    ).read_text(encoding="utf-8")

    for node_type in (
        'node_type="classification_inference"',
        'node_type="classification_training"',
        'node_type="detection_review_gate"',
        'node_type="mask_review_gate"',
        'node_type="classification_review_gate"',
        'node_type="mask_measurements"',
        'node_type="video_tracking"',
        'node_type="project_exchange_export"',
    ):
        assert node_type in registry

    assert "classification_inference" in graph_service
    assert "video_tracking" in graph_service


def test_release_facing_workspaces_do_not_expose_internal_phase_numbers() -> None:
    targets = (
        ROOT
        / "apps"
        / "web"
        / "src"
        / "features"
        / "classification"
        / "ClassificationWorkspace.tsx",
        ROOT
        / "apps"
        / "web"
        / "src"
        / "features"
        / "active-learning"
        / "ActiveLearningWorkspace.tsx",
        ROOT / "apps" / "web" / "src" / "features" / "video" / "VideoTrackingWorkspace.tsx",
    )
    joined = "\n".join(path.read_text(encoding="utf-8") for path in targets)
    assert ">Phase 5<" not in joined
    assert ">Phase 6<" not in joined
    assert ">Phase 7<" not in joined


def test_release_candidate_assets_exist_and_keep_final_manual_signoff_explicit() -> None:
    script = ROOT / "scripts" / "release-candidate.ps1"
    checklist = ROOT / "docs" / "RELEASE_CANDIDATE_CHECKLIST.md"

    assert script.is_file()
    assert checklist.is_file()

    script_text = script.read_text(encoding="utf-8")
    checklist_text = checklist.read_text(encoding="utf-8")

    for gate in (
        "ruff check",
        "-m mypy",
        "-m pytest",
        "run typecheck",
        "run test",
        "run build",
        "desktop:build",
    ):
        assert gate in script_text

    assert "Manual acceptance" in checklist_text
    assert "not a release authorization" in checklist_text
