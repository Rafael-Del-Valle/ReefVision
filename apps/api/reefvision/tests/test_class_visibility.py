from pathlib import Path
from typing import Any, cast

from fastapi.testclient import TestClient

from reefvision.config import Settings
from reefvision.db.base import Base
from reefvision.main import create_app


def create_project(client: TestClient, **overrides: object) -> dict[str, Any]:
    payload: dict[str, object] = {"name": "Visibility Study", "template": "blank"}
    payload.update(overrides)
    response = client.post("/api/v1/projects", json=payload)
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


def create_label_class(
    client: TestClient,
    project_id: str,
    *,
    class_index: int,
    name: str,
    display_color: str,
) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/projects/{project_id}/classes",
        json={
            "class_index": class_index,
            "name": name,
            "display_color": display_color,
        },
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


def test_class_visibility_preferences_persist_across_restart(tmp_path: Path) -> None:
    settings = Settings(
        env="test",
        data_dir=tmp_path / "persistent-data",
        database_url=f"sqlite:///{(tmp_path / 'persistent.db').as_posix()}",
        web_origin="http://testserver",
        background_worker_enabled=False,
    )

    first_app = create_app(settings)
    Base.metadata.create_all(first_app.state.engine)
    with TestClient(first_app) as first_client:
        project = create_project(first_client)
        label_class = create_label_class(
            first_client,
            project["id"],
            class_index=0,
            name="Muricea Closed",
            display_color="#E76F51",
        )
        saved = first_client.put(
            f"/api/v1/projects/{project['id']}/class-visibility/preferences/annotations",
            json={"hidden_class_ids": [label_class["id"]]},
        )
        assert saved.status_code == 200, saved.text
        bundle = first_client.get(f"/api/v1/projects/{project['id']}/class-visibility")
        assert bundle.status_code == 200, bundle.text
        first_identity = bundle.json()["user_identity"]
        assert first_identity.startswith("local-user:")

    second_app = create_app(settings)
    with TestClient(second_app) as second_client:
        bundle = second_client.get(f"/api/v1/projects/{project['id']}/class-visibility")
        assert bundle.status_code == 200, bundle.text
        payload = bundle.json()
        assert payload["user_identity"] == first_identity
        assert payload["user_preferences"]["annotations"]["saved"] is True
        assert payload["user_preferences"]["annotations"]["hidden_class_ids"] == [
            label_class["id"]
        ]
        assert (settings.resolved_data_dir / "local-user-id.txt").is_file()
        Base.metadata.drop_all(second_app.state.engine)


def test_project_defaults_and_resets_round_trip(client: TestClient) -> None:
    project = create_project(client)
    first_class = create_label_class(
        client,
        project["id"],
        class_index=0,
        name="Muricea Closed",
        display_color="#E76F51",
    )
    second_class = create_label_class(
        client,
        project["id"],
        class_index=1,
        name="Muricea Open",
        display_color="#2A9D8F",
    )

    default_response = client.put(
        f"/api/v1/projects/{project['id']}/class-visibility/defaults/predictions",
        json={"hidden_class_ids": [first_class["id"]]},
    )
    assert default_response.status_code == 200, default_response.text
    assert default_response.json()["saved"] is True

    preference_response = client.put(
        f"/api/v1/projects/{project['id']}/class-visibility/preferences/predictions",
        json={"hidden_class_ids": [second_class["id"]]},
    )
    assert preference_response.status_code == 200, preference_response.text

    bundle = client.get(f"/api/v1/projects/{project['id']}/class-visibility")
    assert bundle.status_code == 200, bundle.text
    payload = bundle.json()
    assert payload["project_defaults"]["predictions"]["hidden_class_ids"] == [first_class["id"]]
    assert payload["user_preferences"]["predictions"]["hidden_class_ids"] == [second_class["id"]]

    reset_preference = client.delete(
        f"/api/v1/projects/{project['id']}/class-visibility/preferences/predictions"
    )
    assert reset_preference.status_code == 204, reset_preference.text
    reset_default = client.delete(
        f"/api/v1/projects/{project['id']}/class-visibility/defaults/predictions"
    )
    assert reset_default.status_code == 204, reset_default.text

    refreshed = client.get(f"/api/v1/projects/{project['id']}/class-visibility")
    assert refreshed.status_code == 200, refreshed.text
    refreshed_payload = refreshed.json()
    assert refreshed_payload["user_preferences"]["predictions"]["saved"] is False
    assert refreshed_payload["project_defaults"]["predictions"]["saved"] is False


def test_class_visibility_rejects_other_project_class_ids(client: TestClient) -> None:
    first_project = create_project(client, name="Project One")
    second_project = create_project(client, name="Project Two")
    own_class = create_label_class(
        client,
        first_project["id"],
        class_index=0,
        name="Muricea Closed",
        display_color="#E76F51",
    )
    foreign_class = create_label_class(
        client,
        second_project["id"],
        class_index=0,
        name="Swiftia",
        display_color="#4D96FF",
    )

    invalid = client.put(
        f"/api/v1/projects/{first_project['id']}/class-visibility/preferences/annotations",
        json={"hidden_class_ids": [own_class["id"], foreign_class["id"]]},
    )
    assert invalid.status_code == 400
    assert "project" in invalid.json()["detail"].lower()
