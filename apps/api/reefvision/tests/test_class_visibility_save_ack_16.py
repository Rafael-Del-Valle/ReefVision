"""Visibility save acknowledgements must identify our write, not a racing editor's."""

from __future__ import annotations

from datetime import timedelta
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from reefvision.db.models.class_visibility_preference import ClassVisibilityPreference
from reefvision.db.models.project_class_visibility_default import ProjectClassVisibilityDefault
from reefvision.tests.test_class_visibility import create_label_class, create_project


@pytest.mark.parametrize("scope", ["preferences", "defaults"])
@pytest.mark.parametrize("conditional", [False, True])
def test_visibility_save_ack_is_pinned_to_own_write(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    scope: str,
    conditional: bool,
) -> None:
    """A second local editor may commit after ours but before HTTP serialization.

    Both legacy PUT and revision-checked PUT must acknowledge the revision
    written by the current request, not the newer revision from another editor.
    The newer revision must remain visible on a subsequent GET and reject a
    stale compare-and-save. No annotation or scientific data is modified.
    """
    project = create_project(client, name="Visibility concurrent acknowledgement")
    first = create_label_class(
        client,
        project["id"],
        class_index=0,
        name="Swiftia Open",
        display_color="#C74343",
    )
    second = create_label_class(
        client,
        project["id"],
        class_index=1,
        name="Swiftia Closed",
        display_color="#326EA8",
    )
    path = f"/api/v1/projects/{project['id']}/class-visibility/{scope}/annotations"
    original = client.put(path, json={"hidden_class_ids": [first["id"]]})
    assert original.status_code == 200, original.text
    before = original.json()
    payload: dict[str, Any] = {"hidden_class_ids": [second["id"]]}
    if conditional:
        payload.update(
            expected_updated_at=before["updated_at"],
            expected_record_id=before["record_id"],
        )

    app = cast(FastAPI, client.app)
    model = ClassVisibilityPreference if scope == "preferences" else ProjectClassVisibilityDefault
    real_commit = Session.commit
    competing_revisions: list[str] = []

    def competing_commit(session: Session) -> None:
        real_commit(session)
        if competing_revisions:
            return
        # The first editor has actually committed and released its writer lock.
        # Commit another editor's update *before* its HTTP response is assembled.
        with Session(app.state.engine) as other:
            row = other.scalar(
                select(model).where(
                    model.project_id == project["id"],
                    model.layer_type == "annotations",
                )
            )
            assert row is not None
            newer_time = row.updated_at + timedelta(seconds=1)
            values: dict[str, Any] = {
                "hidden_class_ids_json": [first["id"]],
                "updated_at": newer_time,
            }
            if scope == "defaults":
                values["updated_by_identity"] = "local-user:second-editor"
            other.execute(update(model).where(model.id == row.id).values(**values))
            real_commit(other)
            competing_revisions.append(newer_time.isoformat())

    with monkeypatch.context() as patch:
        patch.setattr(Session, "commit", competing_commit)
        saved = client.put(path, json=payload)
    assert saved.status_code == 200, saved.text
    assert len(competing_revisions) == 1
    acknowledged = saved.json()
    assert acknowledged["record_id"] == before["record_id"]
    assert acknowledged["hidden_class_ids"] == [second["id"]]
    assert acknowledged["updated_at"] != before["updated_at"]

    bundle = client.get(f"/api/v1/projects/{project['id']}/class-visibility")
    assert bundle.status_code == 200, bundle.text
    key = "user_preferences" if scope == "preferences" else "project_defaults"
    current = bundle.json()[key]["annotations"]
    assert current["record_id"] == acknowledged["record_id"]
    assert current["hidden_class_ids"] == [first["id"]]
    assert current["updated_at"] != acknowledged["updated_at"]
    if scope == "defaults":
        assert current["updated_by_identity"] == "local-user:second-editor"

    # The saved response's revision is the correct CAS token to reject now.
    stale = client.put(
        path,
        json={
            "hidden_class_ids": [],
            "expected_updated_at": acknowledged["updated_at"],
            "expected_record_id": acknowledged["record_id"],
        },
    )
    assert stale.status_code == 409, stale.text
    assert client.get(f"/api/v1/projects/{project['id']}/class-visibility").json()[key][
        "annotations"
    ]["hidden_class_ids"] == [first["id"]]
