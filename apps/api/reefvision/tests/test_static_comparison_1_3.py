from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import func, select

from reefvision.db.models import Annotation, Job, ModelRegistration, PredictionProposal, TrainingRun
from reefvision.domain.static_count_agreement import CountPair, paired_difference, statistics
from reefvision.jobs.worker import process_next_thumbnail_job
from reefvision.ml.providers import DetectionPrediction, PixelBox
from reefvision.schemas.static_comparison import StaticComparisonRequest, StaticReferenceImage
from reefvision.services.static_comparison_lineage import detector_lineage
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.storage.models import hash_model_file
from reefvision.tests.test_dataset_versions import (
    import_image,
    save_annotations,
    update_image,
)
from reefvision.tests.test_scientific_project_exchange import (
    export_archive,
    import_archive,
    rewrite,
)
from reefvision.tests.test_workflow_connected_branch_preview_1_2 import _run


class FixtureDetector:
    provider_version = "fixture"

    def load_model(self, model_path: Path, device: str) -> None:
        pass

    def predict(self, image_path: Path, settings: Any) -> list[DetectionPrediction]:
        with Image.open(image_path) as image:
            pixel = image.convert("RGB").getpixel((0, 0))
        if pixel == (80, 60, 3):
            raise RuntimeError("Synthetic detector failure")
        if pixel == (80, 60, 4):
            return [DetectionPrediction("new-model-class", 0, 0.9, PixelBox(4, 5, 20, 24))]
        return [
            DetectionPrediction("coral", 0, 0.9, PixelBox(4, 5, 20, 24)),
            DetectionPrediction("unmapped", 1, 0.9, PixelBox(6, 9, 30, 34)),
        ]

    def unload_model(self) -> None:
        pass


def test_saved_static_comparison_reuses_reviewed_counts_and_preserves_raw_output(
    client: TestClient, monkeypatch: Any
) -> None:
    project = client.post("/api/v1/projects", json={"name": "Static counts", "template": "blank"})
    assert project.status_code == 201, project.text
    project_id = project.json()["id"]
    base = f"/api/v1/projects/{project_id}"
    response = client.post(
        f"{base}/classes", json={"name": "Coral", "class_index": 0, "display_color": "#ffffff"}
    )
    assert response.status_code == 201, response.text
    class_id = response.json()["id"]
    for index in range(5):
        image = import_image(
            client,
            project_id,
            filename=f"image{index}.png",
            relative_path=f"image{index}.png",
            color=(80, 60, index),
        )["successful"][0]["image_id"]
        if index == 1:
            save_annotations(
                client,
                image,
                base_revision=0,
                annotation_status="reviewed",
                annotations=[
                    {
                        "id": str(uuid4()),
                        "label_class_id": class_id,
                        "x_min": x,
                        "x_max": x + 4,
                        "y_min": 0,
                        "y_max": 5,
                    }
                    for x in (5, 20, 30)
                ],
            )
        update_image(
            client,
            image,
            group_key=f"tank-{index}",
            annotation_status="excluded" if index == 2 else "reviewed",
        )
    dataset = client.post(
        f"{base}/dataset-versions",
        json={
            "name": "Reviewed set",
            "eligible_annotation_statuses": ["reviewed", "excluded"],
            "split_method": "group_random",
            "requested_ratios": {"train": 0, "validation": 0, "test": 1},
        },
    )
    assert dataset.status_code == 201, dataset.text
    settings = client.app.state.settings
    checkpoint = settings.resolved_data_dir / "fixture.pt"
    checkpoint.write_bytes(b"local fixture")
    digest, size = hash_model_file(checkpoint)
    with client.app.state.session_factory() as session:
        registered = ModelRegistration(
            project_id=project_id,
            purpose="detector",
            display_name="Coral detector",
            source_filename=checkpoint.name,
            managed_path=checkpoint.name,
            sha256=digest,
            file_size_bytes=size,
            framework="fixture",
            task="detect",
            provider_name="fixture",
            provider_version="fixture",
            class_map_json={"labels": ["coral", "unmapped"], "mapping": {"coral": class_id}},
        )
        session.add(registered)
        session.commit()
        model_id = registered.id

    response = client.get(f"{base}/static-comparisons/options")
    assert response.status_code == 200, response.text
    assert response.json()["datasets"][0]["test_reviewed_count"] == 4
    submitted = client.post(
        f"{base}/static-comparisons",
        json={
            "dataset_version_id": dataset.json()["id"],
            "model_ids": [model_id],
        },
    )
    assert submitted.status_code == 202, submitted.text
    job_id = submitted.json()["id"]
    from reefvision.jobs import static_comparison

    monkeypatch.setattr(
        static_comparison, "detection_provider_for_name", lambda _: FixtureDetector()
    )
    for _ in range(6):
        process_next_thumbnail_job(settings, client.app.state.session_factory)
    saved = client.get(f"{base}/static-comparisons/{job_id}")
    assert saved.status_code == 200, saved.text
    result = saved.json()["snapshot"]
    assert result["evaluation_status"] == "exploratory"
    stats = result["results"][0]["total_statistics"]
    assert stats["observation_count"] == 2
    assert stats["frozen_group_count"] == 2
    assert stats["independent_group_count"] is None
    assert stats["zero_reference_count"] == 1
    assert stats["percentage_denominator"] == 1
    assert stats["bias"] == -0.5
    assert stats["mean_absolute_error"] == 1.5
    assert stats["root_mean_squared_error"] == (2.5**0.5)
    assert stats["mean_signed_percentage_error"] == pytest.approx(-200 / 3)
    rows = {
        result["evidence"]["images"][index]["name"]: row
        for index, row in enumerate(result["results"][0]["images"])
    }
    assert rows["image0.png"]["raw_predictions"][0]["class_id"] == class_id
    assert rows["image0.png"]["counts"][0]["status"] == "scored"
    assert "unmapped" in rows["image0.png"]["message"]
    assert rows["image2.png"]["status"] == "excluded_image"
    assert rows["image3.png"]["status"] == "inference_failed"
    assert rows["image4.png"]["counts"][0]["status"] == "output_class_mismatch"
    assert rows["image4.png"]["raw_predictions"][0]["class_id"] is None
    with client.app.state.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Annotation)) == 3
        assert session.scalar(select(func.count()).select_from(PredictionProposal)) == 0
    csv = client.get(f"{base}/static-comparisons/{job_id}/export?format=csv")
    assert csv.status_code == 200, csv.text
    assert class_id in csv.text
    figure = client.post(
        f"{base}/research-reports",
        json={
            "source_kind": "static_comparison",
            "source_id": job_id,
            "figure": "identity_scatter",
            "title": "Coral count agreement",
        },
    )
    assert figure.status_code == 201, figure.text
    assert figure.json()["snapshot"]["source_sha256"] == saved.json()["content_sha256"]
    svg = client.get(f"{base}/research-reports/{figure.json()['id']}/figure.svg")
    assert "Coral count agreement" in svg.text
    graph = {
        "graph_id": "static-comparison-fixture",
        "name": "Static comparison",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "comparison",
                "node_type": "scientific_comparison",
                "parameters": {
                    "static_configuration": submitted.json()["request_json"]["evidence"]["options"]
                },
            },
        ],
        "edges": [
            {
                "edge_id": "counts",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "comparison",
                "target_port_id": "project",
            },
        ],
    }
    workflow = _run(client, project_id, graph)
    assert workflow["run"]["status"] == "succeeded", workflow
    published = next(
        row for row in workflow["artifacts"] if row["data_type"] == "scientific_comparison_report"
    )
    assert published["payload_json"]["content_sha256"] == saved.json()["content_sha256"]
    graph["nodes"][1]["parameters"] = {"static_comparison_id": job_id}
    replayed = _run(client, project_id, graph)
    assert replayed["run"]["status"] == "succeeded", replayed

    raw = export_archive(client, settings, project_id)

    def forge(_manifest: dict[str, Any], sections: dict[str, Any]) -> None:
        record = next(row for row in sections["jobs"] if row["job_type"] == "static_comparison")
        result = record["result_json"]
        result["snapshot"]["results"][0]["total_statistics"]["bias"] = 10.0
        result["content_sha256"] = canonical_json_sha256(result["snapshot"])

    forged = import_archive(client, rewrite(raw, forge))
    assert forged.status_code == 400 and "statistics do not replay" in forged.text

    def forge_lineage(_manifest: dict[str, Any], sections: dict[str, Any]) -> None:
        record = next(row for row in sections["jobs"] if row["job_type"] == "static_comparison")
        request = record["request_json"]
        evidence = request["evidence"]
        evidence["models"][0]["lineage"].update(status="held_out", reasons=[])
        request["evidence_sha256"] = canonical_json_sha256(evidence)
        result = record["result_json"]
        result["snapshot"].update(evidence=evidence, evaluation_status="held_out")
        result["content_sha256"] = canonical_json_sha256(result["snapshot"])

    forged_lineage = import_archive(client, rewrite(raw, forge_lineage))
    assert forged_lineage.status_code == 400 and "lineage does not replay" in forged_lineage.text
    imported = import_archive(client, raw)
    assert imported.status_code == 201, imported.text
    project = imported.json()["project_id"]
    target = f"/api/v1/projects/{project}"
    summaries = client.get(f"{target}/static-comparisons").json()
    assert len(summaries) == 2
    restored = client.get(f"{target}/static-comparisons/{summaries[0]['id']}")
    assert restored.status_code == 200, restored.text
    assert restored.json()["content_sha256"] == saved.json()["content_sha256"]
    assert restored.json()["source_id_map"]
    assert not restored.json()["stale"]
    figures = client.get(f"{target}/research-reports").json()
    assert len(figures) == 1
    assert figures[0]["content_sha256"] == figure.json()["content_sha256"]
    assert client.get(f"{target}/static-comparisons/{job_id}").status_code == 404
    imported_again = import_archive(client, export_archive(client, settings, project))
    assert imported_again.status_code == 201, imported_again.text

    checkpoint.write_bytes(b"changed fixture content")
    changed = client.get(f"{base}/static-comparisons/{job_id}").json()
    assert changed["stale"]
    assert changed["content_sha256"] == saved.json()["content_sha256"]
    assert (
        client.post(
            f"{base}/research-reports",
            json={
                "source_kind": "static_comparison",
                "source_id": job_id,
                "figure": "identity_scatter",
                "title": "Changed checkpoint",
            },
        ).status_code
        == 409
    )


def test_agreement_counts_images_and_independent_units_separately() -> None:
    options = StaticComparisonRequest(
        dataset_version_id=uuid4(),
        model_ids=[uuid4(), uuid4()],
        independent_groups=True,
        icc="A,1",
        homoscedastic_normal_differences=True,
    )
    points = [CountPair(f"tank-{index}", index + 1, index + 2) for index in range(5)]
    stats = statistics(points, options)
    assert stats.limits_of_agreement == (1, 1)
    assert stats.icc == pytest.approx(5 / 6)
    consistent = statistics(points, options.model_copy(update={"icc": "C,1"}))
    assert consistent.icc == 1
    ids = [uuid4() for _ in points]
    left = dict(zip(ids, points, strict=True))
    right = {
        identifier: CountPair(row.group, row.reference, row.reference)
        for identifier, row in left.items()
    }
    paired = paired_difference(left, right, options)
    assert paired.absolute_error_change == -1
    assert paired.absolute_error_change_ci95 == (-1, -1)
    right.pop(ids[0])
    incomplete = paired_difference(left, right, options)
    assert incomplete.observation_count == 4
    assert incomplete.absolute_error_change_ci95 is None

    repeated = statistics(points + [points[0]] * 7, options)
    assert repeated.independent_group_count == 5
    assert repeated.observation_count == 12
    assert repeated.bias_ci95 == (1, 1)
    assert repeated.limits_of_agreement is None
    assert repeated.icc is None


def test_group_overlap_with_model_selection_revokes_held_out_status(client: TestClient) -> None:
    project_id = client.post("/api/v1/projects", json={"name": "Lineage study"}).json()["id"]
    manual = []
    for index, split in enumerate(("train", "validation", "test")):
        name = f"{split}.png"
        image_id = import_image(
            client, project_id, filename=name, relative_path=name, color=(30, 60, index)
        )["successful"][0]["image_id"]
        update_image(client, image_id, group_key=f"tank-{split}", annotation_status="reviewed")
        manual.append({"image_id": image_id, "split": split})
    version = client.post(
        f"/api/v1/projects/{project_id}/dataset-versions",
        json={
            "name": "Training version",
            "split_method": "manual",
            "manual_assignments": manual,
        },
    )
    assert version.status_code == 201, version.text
    dataset = version.json()
    with client.app.state.session_factory() as session:
        training = TrainingRun(
            project_id=project_id,
            dataset_version_id=dataset["id"],
            dataset_manifest_sha256=dataset["manifest_sha256"],
            split_manifest_sha256="a" * 64,
            task="detect",
            provider_id="fixture",
            architecture="fixture",
            status="completed",
            initial_checkpoint_source="scratch",
            device="cpu",
            precision="fp32",
            run_name="fixture",
        )
        session.add(training)
        session.flush()
        model = ModelRegistration(
            project_id=project_id,
            purpose="detector",
            display_name="Trained detector",
            source_filename="local.pt",
            managed_path="local.pt",
            sha256="b" * 64,
            file_size_bytes=0,
            framework="fixture",
            task="detect",
            provider_name="fixture",
            provider_version="fixture",
            metadata_json={
                "source_training_run_id": training.id,
                "source_dataset_version_id": dataset["id"],
                "source_dataset_manifest_sha256": dataset["manifest_sha256"],
                "source_split_manifest_sha256": training.split_manifest_sha256,
            },
        )
        session.add(model)
        session.flush()
        image = StaticReferenceImage(
            id=uuid4(),
            name="Follow-up from test tank",
            image_sha256="c" * 64,
            item_sha256="d" * 64,
            group_key="tank-test",
            split="test",
            exclusion=None,
            annotations=[],
        )
        assert detector_lineage(session, model, [image], []).status == "held_out"
        training_replica = image.model_copy(update={"group_key": "tank-validation"})
        assert detector_lineage(session, model, [training_replica], []).status == "overlap"
        selection = Job(
            project_id=project_id,
            job_type="learning_evaluation",
            status="succeeded",
            request_json={
                "candidate_model_id": model.id,
                "dataset_version_id": dataset["id"],
                "split": "test",
            },
        )
        session.add(selection)
        session.flush()
        result = detector_lineage(session, model, [image], [selection])
        assert result.status == "overlap"
        assert result.overlapping_image_ids == [image.id]
        assert str(result.model_selection_job_ids[0]) == selection.id
