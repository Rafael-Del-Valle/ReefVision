"""Create disposable predecessor profiles using each pinned original API."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import tarfile
from io import BytesIO
from pathlib import Path
from time import sleep
from typing import Any
from uuid import uuid4
from zipfile import ZipFile

HISTORIES = {
    "science38": ("0038", "e1cd11d389b70631cf13dc829a47494d35305112"),
    "qc38": ("0038", "d4dc3a3aa2a65d8824af45cc026250bc146fb55e"),
    "qc39": ("0039", "56e9bf67efe8caccfe46c4eb6e31e77a054e6100"),
    "qc40": ("0040", "237c9db5858001a393ca38ba48fb53a185196389"),
    "qc41": ("0041", "0dfd7619c3d50dacb42620906a8e1f0286ce0f61"),
}
MARKER = ".reefvision-qc-history-disposable"
DATABASE = "reefvision.db"


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def receipt(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def checked(response: Any, status: int = 200) -> Any:
    if response.status_code != status:
        raise RuntimeError(f"Expected HTTP {status}, got {response.status_code}: {response.text}")
    return response.json()


def isolated_environment(profile: Path) -> dict[str, str]:
    excluded = {"PYTHONHOME", "PYTHONPATH", "TRANSFORMERS_CACHE", "GH_TOKEN", "GITHUB_TOKEN"}
    return {
        **{
            key: value
            for key, value in os.environ.items()
            if not key.upper().startswith("REEFVISION_") and key.upper() not in excluded
        },
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "YOLO_AUTOINSTALL": "false",
        "HF_HOME": str(profile / "cache" / "hf"),
        "TORCH_HOME": str(profile / "cache" / "torch"),
        "YOLO_CONFIG_DIR": str(profile / "cache" / "ultralytics"),
    }


def historical_environment(source: Path, profile: Path) -> dict[str, str]:
    return {
        **isolated_environment(profile),
        "PYTHONPATH": str(source / "apps" / "api"),
        "PYTHONDONTWRITEBYTECODE": "1",
        "REEFVISION_DATA_DIR": str(profile),
        "REEFVISION_CONFIG_DIR": str(profile / "config"),
        "REEFVISION_ENV": "test",
        "REEFVISION_BACKGROUND_WORKER_ENABLED": "false",
    }


def register_weight_bundle(client: Any, project_id: str) -> dict[str, Any]:
    # One safe tensor in a synthetic bundle. Exercise historic registration and
    # byte preservation. This fixture has no trained model or inference claim.
    head = b'{"fixture.weight":{"dtype":"F32","shape":[1],"data_offsets":[0,4]}}'
    while len(head) % 8:
        head += b" "
    file = BytesIO()
    with ZipFile(file, "w") as bundle:
        bundle.writestr("config.json", '{"model_type":"sam2"}')
        bundle.writestr("preprocessor_config.json", "{}")
        bundle.writestr("model.safetensors", struct.pack("<Q", len(head)) + head + b"\0" * 4)
    payload = file.getvalue()
    model = checked(
        client.post(
            f"/api/v1/projects/{project_id}/models/register",
            data={
                "purpose": "assist",
                "provider_name": "sam2",
                "display_name": "Synthetic weight bundle",
            },
            files={"file": ("synthetic-preservation.zip", payload, "application/zip")},
        )
    )
    assert model["sha256"] == hashlib.sha256(payload).hexdigest()
    assert model["file_size_bytes"] == len(payload)
    return {key: model[key] for key in ("id", "managed_path", "file_size_bytes", "sha256")}


def source_image(client: Any, project_id: str, filename: str, width: int) -> dict[str, Any]:
    from PIL import Image

    from reefvision.jobs.worker import process_thumbnail_job

    image = BytesIO()
    Image.new("RGB", (width, 60), (20, 90, 120)).save(image, format="PNG")
    raw = image.getvalue()
    imported = checked(
        client.post(
            f"/api/v1/projects/{project_id}/imports/images",
            files={"files": (filename, raw, "image/png")},
            data={"relative_paths": f"transect/{filename}"},
        )
    )["successful"][0]
    job = imported["thumbnail_job_id"]
    assert process_thumbnail_job(client.app.state.settings, client.app.state.session_factory, job)
    assert checked(client.get(f"/api/v1/jobs/{job}"))["status"] == "succeeded"
    return {
        "id": imported["image_id"],
        "sha256": hashlib.sha256(raw).hexdigest(),
        "thumbnail_job_id": job,
    }


def add_event(client: Any, queue: str, item: str, kind: str, **details: str) -> dict[str, Any]:
    url = f"/api/v1/review-queues/{queue}/items/{item}/events"
    request = {
        "client_request_id": str(uuid4()),
        "event_type": kind,
        "actor": "Generated local observer",
        **details,
    }
    original = checked(client.post(url, json=request), 201)
    assert checked(client.post(url, json=request), 201) == original
    # The oldest readers order simultaneous saved events by UUID. Give these
    # sequential human actions separate ticks on the Windows test clock.
    sleep(0.03)
    return original


def items(client: Any, queue: str) -> list[dict[str, Any]]:
    return checked(client.get(f"/api/v1/review-queues/{queue}/items"))["items"]


def events(client: Any, queue: str, item: str) -> list[dict[str, Any]]:
    return checked(client.get(f"/api/v1/review-queues/{queue}/items/{item}/events"))["items"]


def bulk(
    client: Any, queue: str, action: str, ids: list[str], *, status: int = 200, **extra: Any
) -> Any:
    result = client.post(
        f"/api/v1/review-queues/{queue}/items/bulk",
        json={"item_ids": ids, "action": action, "actor": "Generated local observer", **extra},
    )
    payload = checked(result, status)
    if status == 200:
        assert payload["requires_researcher_review"] is True
        if payload["changed_count"]:
            sleep(0.03)
    return payload


def seed_initial(client: Any, history: str) -> dict[str, Any]:
    project = checked(
        client.post("/api/v1/projects", json={"name": f"Generated predecessor {history}"}), 201
    )
    project_id = project["id"]
    root = f"/api/v1/projects/{project_id}"
    label = checked(
        client.post(
            f"{root}/classes",
            json={"name": "Synthetic outline", "display_color": "#B79870", "class_index": 0},
        ),
        201,
    )
    registration = register_weight_bundle(client, project_id) if history == "qc38" else None
    image = source_image(client, project_id, "calibrated-original.png", 80)
    annotation = {
        "id": str(uuid4()),
        "label_class_id": label["id"],
        "x_min": 5,
        "x_max": 25,
        "y_min": 5,
        "y_max": 25,
    }
    reviewed = checked(
        client.put(
            f"/api/v1/images/{image['id']}/annotations",
            json={"base_revision": 0, "annotation_status": "reviewed", "annotations": [annotation]},
        )
    )
    assert reviewed["image"]["annotation_status"] == "reviewed"
    result: dict[str, Any] = {
        "project_id": project_id,
        "source_image": image,
        "label_id": label["id"],
        "annotation_id": annotation["id"],
        "registration": registration,
    }
    if history == "science38":
        checked(
            client.put(
                f"/api/v1/images/{image['id']}/measurement-calibration",
                json={"distance_per_pixel": 0.25, "unit": "mm", "source": "manual_scale_bar"},
            )
        )
        supplied = {
            "variable": "water_temperature",
            "value": 68.0,
            "unit": "degF",
            "observed_at": "2026-04-03T08:00:00-05:00",
            "source_kind": "observed",
            "location": {"latitude": 32.75, "longitude": -79.93},
            "provenance": {
                "source": "Synthetic laboratory sensor",
                "dataset_id": "historical-fixture",
                "acquired_at": "2026-04-03T13:01:00Z",
            },
            "subject": {"image_id": image["id"]},
            "pixel": {"x": 40, "y": 30, "frame": "image_pixels"},
            "uncertainty": {
                "value": 1.8,
                "kind": "standard_deviation",
                "method": "Generated observation thermometer",
            },
        }
        record = checked(
            client.post(f"{root}/scientific-records", json={"records": [supplied]}), 201
        )["items"][0]
        assert [
            record[key]
            for key in (
                "value",
                "unit",
                "normalized_value",
                "normalized_unit",
                "normalized_uncertainty",
            )
        ] == [68, "degF", 20, "degC", 1]
        result["scientific_id"] = record["id"]
        result["scientific_sha256"] = record["content_sha256"]
    else:
        queue = checked(client.post(f"{root}/review-queues", json={}), 201)["id"]
        [item] = items(client, queue)
        for kind, details in [
            ("comment", {"comment": "Inspect the outline on the original"}),
            ("assign", {"assignee": "Generated second reviewer"}),
            ("unassign", {}),
        ]:
            add_event(client, queue, item["id"], kind, **details)
        result.update(queue_id=queue, item_id=item["id"])
    return result


def seed_qc_successor(client: Any, history: str, ref: dict[str, Any]) -> None:
    project_id = ref["project_id"]
    if history == "qc39":
        ref["additional_sources"] = [
            source_image(client, project_id, f"qc-{width}.png", width) for width in (81, 82, 83)
        ]
        graph = {
            "graph_id": "historical-qc",
            "name": "Generated historical QC graph",
            "nodes": [
                {"node_id": "project", "node_type": "project_source"},
                {"node_id": "qc", "node_type": "qc_review_queue"},
            ],
            "edges": [
                {
                    "edge_id": "project-qc",
                    "source_node_id": "project",
                    "source_port_id": "project",
                    "target_node_id": "qc",
                    "target_port_id": "project",
                }
            ],
        }
        from reefvision.jobs.workflow import process_workflow_run_job

        root = f"/api/v1/projects/{project_id}"
        saved = checked(client.post(f"{root}/workflow-graphs", json={"graph": graph}), 201)
        run = checked(
            client.post(f"{root}/workflow-runs", json={"graph_record_id": saved["id"]}), 202
        )
        assert process_workflow_run_job(
            client.app.state.settings, client.app.state.session_factory, run["job_id"]
        )
        detail = checked(client.get(f"/api/v1/workflow-runs/{run['id']}"))
        assert detail["run"]["status"] == "succeeded"
        [artifact] = [
            row for row in detail["artifacts"] if row["data_type"] == "review_queue_reference"
        ]
        assert artifact["payload_json"]["review_status"] == "requires_researcher_review"
        queue = artifact["payload_json"]["queue_id"]
        rows = items(client, queue)
        [primary] = [row["id"] for row in rows if row["image_id"] == ref["source_image"]["id"]]
        remaining = [row["id"] for row in rows if row["id"] != primary]
        assert len(remaining) == 3
        add_event(client, queue, primary, "comment", comment="Check the reviewed boundary")
        add_event(client, queue, primary, "assign", assignee="Generated second reviewer")
        assert bulk(client, queue, "start", [primary])["changed_count"] == 1
        assert (
            bulk(client, queue, "skip", [primary], reason="Inspect original scale")["changed_count"]
            == 1
        )
        assert bulk(client, queue, "return", [primary])["changed_count"] == 1
        ref.update(
            workflow_queue=queue,
            workflow_item=primary,
            workflow_items=remaining,
            graph_id=saved["id"],
            workflow_run_id=run["id"],
            workflow_job_id=run["job_id"],
            workflow_payload_sha256=artifact["payload_sha256"],
        )
    elif history == "qc40":
        item = ref["workflow_item"]
        checked(client.post(f"/api/v1/review-queue-items/{item}/start"))
        sleep(0.03)
        assert (
            checked(client.post(f"/api/v1/review-queue-items/{item}/complete"))["review_state"]
            == "completed"
        )
    else:
        queue = ref["workflow_queue"]
        first, second, excluded = ref["workflow_items"]
        key, complete = str(uuid4()), str(uuid4())
        assert (
            bulk(client, queue, "start", [first, second], client_request_id=key)["changed_count"]
            == 2
        )
        assert (
            checked(client.post(f"/api/v1/review-queue-items/{first}/complete"))["review_state"]
            == "completed"
        )
        assert (
            bulk(client, queue, "start", [second, first], client_request_id=key)["changed_count"]
            == 0
        )
        assert (
            bulk(
                client,
                queue,
                "complete",
                [second],
                client_request_id=complete,
                review_confirmed=True,
            )["changed_count"]
            == 1
        )
        assert (
            bulk(
                client,
                queue,
                "complete",
                [second],
                client_request_id=complete,
                review_confirmed=True,
            )["changed_count"]
            == 0
        )
        rejected = str(uuid4())
        bulk(
            client,
            queue,
            "start",
            [ref["workflow_item"], excluded],
            client_request_id=rejected,
            status=409,
        )
        bulk(
            client,
            queue,
            "start",
            [ref["item_id"], excluded],
            client_request_id=str(uuid4()),
            status=409,
        )
        bulk(client, ref["queue_id"], "start", [ref["item_id"]], client_request_id=key, status=409)
        assert {row["id"]: row["review_state"] for row in items(client, queue)}[
            excluded
        ] == "pending"
        ref.update(
            bulk_start=key,
            bulk_complete=complete,
            bulk_selected=[first, second],
            rejected_bulk=rejected,
        )


def verify_original_api(client: Any, history: str, ref: dict[str, Any]) -> None:
    project = checked(client.get(f"/api/v1/projects/{ref['project_id']}"))
    assert any(
        row["id"] == ref["label_id"] and row["class_index"] == 0 for row in project["label_classes"]
    )
    image_id = ref["source_image"]["id"]
    image_response = client.get(f"/api/v1/images/{image_id}/content")
    assert image_response.is_success
    assert hashlib.sha256(image_response.content).hexdigest() == ref["source_image"]["sha256"]
    annotation = checked(client.get(f"/api/v1/images/{image_id}/annotations"))
    assert annotation["image"]["annotation_status"] == "reviewed"
    assert annotation["annotations"][0]["id"] == ref["annotation_id"]
    if history == "science38":
        [row] = checked(client.get(f"/api/v1/projects/{ref['project_id']}/scientific-records"))[
            "items"
        ]
        assert (
            row["id"] == ref["scientific_id"] and row["content_sha256"] == ref["scientific_sha256"]
        )
    else:
        [row] = items(client, ref["queue_id"])
        assert row["id"] == ref["item_id"] and row["image_id"] == image_id
        assert [row["event_type"] for row in events(client, ref["queue_id"], ref["item_id"])] == [
            "comment",
            "assign",
            "unassign",
        ]
        registration = checked(client.get(f"/api/v1/models/{ref['registration']['id']}"))
        assert registration["sha256"] == ref["registration"]["sha256"]
        if history != "qc38":
            vocabulary = ["comment", "assign", "triage_start", "triage_skip", "triage_return"]
            if history in {"qc40", "qc41"}:
                vocabulary.extend(("triage_start", "triage_complete"))
            assert [
                row["event_type"]
                for row in events(client, ref["workflow_queue"], ref["workflow_item"])
            ] == vocabulary


def historical_api(
    history: str, source: Path, profile: Path, metadata: Path, *, reopen: bool
) -> None:
    from alembic import command
    from alembic.config import Config
    from fastapi.testclient import TestClient

    import reefvision
    from reefvision.main import create_app

    assert (source / "apps" / "api").resolve() in Path(reefvision.__file__).resolve().parents
    assert Path(os.environ["REEFVISION_DATA_DIR"]).resolve() == profile
    revision, commit = HISTORIES[history]
    if not reopen:
        config = Config(str(source / "apps" / "api" / "alembic.ini"))
        config.attributes.update(
            configure_logger=False,
            desktop_database_url=f"sqlite:///{profile.as_posix()}/{DATABASE}",
        )
        command.upgrade(config, revision)
    ref = json.loads(metadata.read_text(encoding="utf-8")) if metadata.is_file() else None
    with TestClient(create_app()) as client:
        if not reopen:
            if history in {"science38", "qc38"}:
                ref = seed_initial(client, history)
            else:
                seed_qc_successor(client, history, ref)
        verify_original_api(client, history, ref)
    if not reopen:
        ref.update(
            source_commit=commit, revision=revision, database_sha256=sha256(profile / DATABASE)
        )
        receipt(metadata, ref)


def call_historical(
    history: str, source: Path, profile: Path, metadata: Path, *, reopen: bool = False
) -> None:
    subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "reopen" if reopen else "seed",
            history,
            str(source),
            str(profile),
            str(metadata),
        ],
        cwd=source,
        env=historical_environment(source, profile),
        check=True,
        timeout=120,
    )


def prepare(repository: Path, root: Path) -> None:
    root.mkdir(exist_ok=False)
    (root / MARKER).write_text("Generated disposable QC lineage profiles\n", encoding="utf-8")
    for history, (_, commit) in HISTORIES.items():
        has_commit = subprocess.run(
            ["git", "cat-file", "-e", commit + "^{commit}"], cwd=repository, check=False
        )
        if has_commit.returncode:
            subprocess.run(
                ["git", "fetch", "--no-tags", "origin", commit],
                cwd=repository,
                check=True,
                timeout=180,
            )
        payload = subprocess.check_output(
            ["git", "archive", commit, "apps/api"], cwd=repository, timeout=60
        )
        source, profile = root / "src" / history, root / "donors" / history
        source.mkdir(parents=True)
        profile.parent.mkdir(exist_ok=True)
        with tarfile.open(fileobj=BytesIO(payload)) as archive:
            archive.extractall(source, filter="data")
        metadata = root / f"{history}.json"
        if history in {"science38", "qc38"}:
            profile.mkdir()
        else:
            preceding = f"qc{int(history.removeprefix('qc')) - 1}"
            donor = root / "donors" / preceding
            previous_db = sha256(donor / DATABASE)
            shutil.copytree(donor, profile)
            shutil.copyfile(root / f"{preceding}.json", metadata)
        (profile / MARKER).write_text(commit + "\n", encoding="utf-8")
        call_historical(history, source, profile, metadata)
        if history not in {"science38", "qc38"}:
            assert sha256(donor / DATABASE) == previous_db
        assert not list(profile.glob(DATABASE + "-*"))
        print(f"Generated {history} from {commit}", flush=True)


if __name__ == "__main__":
    if sys.argv[1:2] in (["seed"], ["reopen"]):
        mode, selection, source_dir, data_dir, notes = sys.argv[1:]
        historical_api(
            selection, Path(source_dir), Path(data_dir), Path(notes), reopen=mode == "reopen"
        )
    else:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("root", type=Path)
        args = parser.parse_args()
        prepare(Path(__file__).resolve().parents[1], args.root.resolve())
