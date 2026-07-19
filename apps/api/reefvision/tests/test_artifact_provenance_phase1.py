from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from reefvision.db.models import Project
from reefvision.schemas.artifacts import ArtifactCreateRequest
from reefvision.services.artifacts import ArtifactService


def test_artifact_provenance_records_content_and_lineage(client: TestClient) -> None:
    settings = client.app.state.settings
    with client.app.state.session_factory() as session:
        project = Project(
            name="Artifact project",
            slug="artifact-project",
            storage_root="projects/artifact-project",
        )
        session.add(project)
        session.commit()
        session.refresh(project)
        managed_path = f"{project.storage_root}/exports/result.csv"
        content_path = Path(settings.resolved_data_dir) / managed_path
        content_path.parent.mkdir(parents=True, exist_ok=True)
        content_path.write_text("class,count\nopen,12\n", encoding="utf-8")

        service = ArtifactService(session, settings)
        parent = service.create(
            project.id,
            ArtifactCreateRequest(
                artifact_type="measurement_csv",
                source_kind="image",
                source_id="image-1",
                source_annotation_revision=4,
                provider_id="reefvision.measurements",
                provider_version="1",
                parameters={"unit": "mm"},
                managed_path=managed_path,
                metadata={"scientific_unit": "millimetres"},
            ),
        )
        child = service.create(
            project.id,
            ArtifactCreateRequest(
                artifact_type="measurement_summary",
                parent_artifact_id=parent.id,
                supersedes_artifact_id=parent.id,
                payload={"mean": 12.5, "n": 3},
                postprocessing={"aggregation": "mean"},
                review_status="accepted",
            ),
        )

        assert parent.size_bytes == content_path.stat().st_size
        assert len(parent.checksum) == 64
        assert child.metadata_json["payload"] == {"mean": 12.5, "n": 3}
        lineage = service.lineage(child.id)
        assert [item.id for item in lineage.ancestors] == [parent.id]
        assert service.lineage(parent.id).descendants[0].id == child.id
