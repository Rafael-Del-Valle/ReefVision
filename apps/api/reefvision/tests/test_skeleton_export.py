from __future__ import annotations

import json
import zipfile
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.domain.errors import ValidationError
from reefvision.schemas.skeletonization import (
    SkeletonAnalysisCreateRequest,
    SkeletonAnalysisReviewRequest,
)
from reefvision.services.skeletonization import SkeletonizationService
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.storage.skeleton_exports import verify_skeleton_export
from reefvision.tests.test_annotations import create_project, import_one


def _seed(client: TestClient) -> tuple[dict[str, object], str]:
    project = create_project(client, "Skeleton export")
    report = import_one(client, str(project["id"]), size=(80, 60))
    image_id = report["successful"][0]["image_id"]
    class_id = project["label_classes"][0]["id"]
    mask_id = "ca90bf55-f033-486a-82ca-b3f254687879"
    saved = client.put(
        f"/api/v1/images/{image_id}/annotations",
        json={
            "base_revision": 0,
            "annotation_status": "reviewed",
            "annotations": [],
            "mask_annotations": [
                {
                    "id": mask_id,
                    "label_class_id": class_id,
                    "geometry_kind": "polygon",
                    "points": [
                        {"x": 10, "y": 20},
                        {"x": 60, "y": 20},
                        {"x": 60, "y": 30},
                        {"x": 10, "y": 30},
                    ],
                }
            ],
        },
    )
    assert saved.status_code == 200, saved.text
    return project, mask_id


def test_unreviewed_skeleton_analysis_cannot_export(
    client: TestClient,
) -> None:
    _project, mask_id = _seed(client)
    app = cast(FastAPI, client.app)

    with app.state.session_factory() as session:
        service = SkeletonizationService(session, app.state.settings)
        record = service.persist_analysis(
            mask_id,
            SkeletonAnalysisCreateRequest(),
        )
        with pytest.raises(
            ValidationError,
            match="Only approved skeleton analyses",
        ):
            service.export_persisted_analysis(record.id)


def test_approved_skeleton_export_contains_verified_raw_pruned_and_final_data(
    client: TestClient,
) -> None:
    project, mask_id = _seed(client)
    app = cast(FastAPI, client.app)

    with app.state.session_factory() as session:
        service = SkeletonizationService(session, app.state.settings)
        record = service.persist_analysis(
            mask_id,
            SkeletonAnalysisCreateRequest(),
        )
        approved = service.review_persisted_analysis(
            record.id,
            SkeletonAnalysisReviewRequest(
                review_status="approved",
                note="Approved for scientific export.",
            ),
        )
        exported = service.export_persisted_analysis(approved.id)

    project_root = str(project["storage_root"])
    export_root = resolve_managed_project_path(
        app.state.settings,
        f"{project_root}/skeletonization/exports",
    )
    package = export_root / exported.package_name
    archive = export_root / exported.archive_name

    assert package.is_dir()
    assert archive.is_file()
    assert exported.verification_status == "verified"
    assert len(exported.archive_sha256) == 64
    assert len(exported.manifest_sha256) == 64

    expected = {
        "data/analysis.json",
        "data/provenance.json",
        "data/summary.csv",
        "data/raw_skeleton_pixels.csv",
        "data/pruned_skeleton_pixels.csv",
        "data/final_skeleton_pixels.csv",
        "data/raw_branches.csv",
        "data/pruned_branches.csv",
        "data/final_branches.csv",
        "data/raw_branch_angles.csv",
        "data/pruned_branch_angles.csv",
        "data/final_branch_angles.csv",
        "manifest.json",
        "checksums.sha256",
    }
    actual = {
        path.relative_to(package).as_posix()
        for path in package.rglob("*")
        if path.is_file()
    }
    assert expected == actual

    manifest = json.loads(
        (package / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["schema_version"] == "skeleton-export-0001"
    assert manifest["analysis_id"] == approved.id
    assert manifest["result_sha256"] == approved.result_sha256
    assert len(manifest["files"]) == 12

    with zipfile.ZipFile(archive) as bundle:
        names = set(bundle.namelist())
        assert f"{exported.package_name}/data/final_skeleton_pixels.csv" in names
        assert f"{exported.package_name}/manifest.json" in names



def test_skeleton_export_verification_detects_tampering(
    client: TestClient,
) -> None:
    project, mask_id = _seed(client)
    app = cast(FastAPI, client.app)

    with app.state.session_factory() as session:
        service = SkeletonizationService(session, app.state.settings)
        record = service.persist_analysis(
            mask_id,
            SkeletonAnalysisCreateRequest(),
        )
        approved = service.review_persisted_analysis(
            record.id,
            SkeletonAnalysisReviewRequest(
                review_status="approved",
            ),
        )
        exported = service.export_persisted_analysis(approved.id)

    export_root = resolve_managed_project_path(
        app.state.settings,
        f"{project['storage_root']}/skeletonization/exports",
    )
    package = export_root / exported.package_name
    target = package / "data" / "summary.csv"
    target.write_text("tampered\n", encoding="utf-8")

    verification = verify_skeleton_export(package)

    assert verification["valid"] is False
    assert any(
        "mismatch" in error.casefold()
        for error in verification["errors"]
    )
