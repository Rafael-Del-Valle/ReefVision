"""Imported class-visibility JSON must not crash or silently rewrite local scopes.

All source modifications below are confined to an isolated disposable test DB.
No scientific annotation, model, or saved workflow is created or changed.
"""

from __future__ import annotations

import json
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from reefvision.tests.test_class_visibility import create_label_class, create_project


@pytest.mark.parametrize("scope", ["preferences", "defaults"])
@pytest.mark.parametrize(
    "malformed_json",
    [
        '{"incomplete"',
        "null",
        '{"hidden_class_ids": []}',
        '"unexpected scalar"',
        "[42]",
        '[["nested"]]',
        '["valid", null]',
    ],
)
def test_restored_bad_json_fails_closed_without_overwriting_reviewer_settings(
    client: TestClient, scope: str, malformed_json: str
) -> None:
    project = create_project(client, name="Restored Coral Visibility")
    control = create_project(client, name="Separate Project")
    label_class = create_label_class(
        client,
        project["id"],
        class_index=0,
        name="Swiftia Open",
        display_color="#E76F51",
    )
    layer_url = (
        f"/api/v1/projects/{project['id']}/class-visibility/{scope}/annotations"
    )
    bundle_url = f"/api/v1/projects/{project['id']}/class-visibility"
    saved = client.put(layer_url, json={"hidden_class_ids": [label_class["id"]]})
    assert saved.status_code == 200, saved.text
    table = {
        "preferences": "class_visibility_preferences",
        "defaults": "project_class_visibility_defaults",
    }[scope]
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        original_json = session.execute(
            text(
                f"SELECT hidden_class_ids_json FROM {table} "
                "WHERE project_id = :project_id AND layer_type = 'annotations'"
            ),
            {"project_id": project["id"]},
        ).scalar_one()
        session.execute(
            text(
                f"UPDATE {table} SET hidden_class_ids_json = :raw "
                "WHERE project_id = :project_id AND layer_type = 'annotations'"
            ),
            {"project_id": project["id"], "raw": malformed_json},
        )
        session.commit()

    # Both startup reading and a legacy unconditional PUT must fail rather
    # than accepting an incomplete subset or replacing imported evidence.
    for response in (
        client.get(bundle_url),
        client.put(layer_url, json={"hidden_class_ids": []}),
    ):
        assert response.status_code == 409, response.text
        assert "malformed" in response.json()["detail"].lower()
        assert label_class["id"] not in response.text

    # Other projects remain usable and the original corrupt bytes survive
    # intact for review/backup restoration. Never auto-repair this test data.
    healthy = client.get(f"/api/v1/projects/{control['id']}/class-visibility")
    assert healthy.status_code == 200, healthy.text
    with app.state.session_factory() as session:
        current = session.execute(
            text(
                f"SELECT hidden_class_ids_json FROM {table} "
                "WHERE project_id = :project_id AND layer_type = 'annotations'"
            ),
            {"project_id": project["id"]},
        ).scalar_one()
        assert current == malformed_json
        # Fixture-only restoration: production has no automatic repair path.
        session.execute(
            text(
                f"UPDATE {table} SET hidden_class_ids_json = :raw "
                "WHERE project_id = :project_id AND layer_type = 'annotations'"
            ),
            {"project_id": project["id"], "raw": original_json},
        )
        session.commit()

    restored = client.get(bundle_url)
    assert restored.status_code == 200, restored.text
    assert restored.json()["user_preferences" if scope == "preferences" else "project_defaults"][
        "annotations"
    ]["hidden_class_ids"] == [label_class["id"]]


@pytest.mark.parametrize("scope", ["preferences", "defaults"])
def test_legacy_unknown_and_duplicate_hidden_class_ids_remain_compatible(
    client: TestClient, scope: str
) -> None:
    project = create_project(client, name="Historical Visibility Compatibility")
    label_class = create_label_class(
        client,
        project["id"],
        class_index=0,
        name="Thesea Closed",
        display_color="#2A9D8F",
    )
    layer_url = f"/api/v1/projects/{project['id']}/class-visibility/{scope}/annotations"
    assert client.put(layer_url, json={"hidden_class_ids": []}).status_code == 200
    table = {
        "preferences": "class_visibility_preferences",
        "defaults": "project_class_visibility_defaults",
    }[scope]
    raw = json.dumps([label_class["id"], "historically-deleted-class", label_class["id"]])
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        session.execute(
            text(
                f"UPDATE {table} SET hidden_class_ids_json = :raw "
                "WHERE project_id = :project_id AND layer_type = 'annotations'"
            ),
            {"project_id": project["id"], "raw": raw},
        )
        session.commit()

    bundle = client.get(f"/api/v1/projects/{project['id']}/class-visibility")
    assert bundle.status_code == 200, bundle.text
    state = bundle.json()["user_preferences" if scope == "preferences" else "project_defaults"][
        "annotations"
    ]
    assert state["saved"] is True
    assert state["hidden_class_ids"] == [label_class["id"]]
    with app.state.session_factory() as session:
        assert session.execute(
            text(
                f"SELECT hidden_class_ids_json FROM {table} "
                "WHERE project_id = :project_id AND layer_type = 'annotations'"
            ),
            {"project_id": project["id"]},
        ).scalar_one() == raw
