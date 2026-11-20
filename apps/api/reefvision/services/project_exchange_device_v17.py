"""Validate device evidence and rebind only local acquisition identities during Exchange."""

from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
from typing import Any
from uuid import UUID

from reefvision.domain.errors import ValidationError
from reefvision.schemas.acquisition_source import (
    AcquisitionCaptureReceipt,
    AcquisitionMedia,
    AcquisitionReceiptData,
    AcquisitionReceiptPin,
    AcquisitionSourceCreate,
    AcquisitionSourcePin,
    CameraSource,
    RecordedSource,
    SimulatedSource,
    SourceConfiguration,
)
from reefvision.schemas.field_capture import FieldCaptureMetadata
from reefvision.services.acquisition_sources import _source_digest
from reefvision.services.workflow_acquisition_source import (
    ACQUISITION_CAPTURE_NODE,
    ACQUISITION_RECEIPT_TYPE,
    ACQUISITION_REPLAY_NODE,
)
from reefvision.storage.datasets import canonical_json_sha256

SOURCES = "acquisition_sources"
CAPTURES = "acquisition_captures"
SECTIONS = (SOURCES, CAPTURES)
Rows = dict[str, list[dict[str, Any]]]


def _index(rows: Rows, section: str) -> dict[str, dict[str, Any]]:
    records = rows.get(section, [])
    result = {row["id"]: row for row in records}
    if len(result) != len(records):
        raise ValueError("Duplicate device evidence member")
    return result


def _check_source(
    project_id: str,
    row: dict[str, Any],
    batches: dict[str, dict[str, Any]],
) -> SourceConfiguration:
    source_id = str(UUID(row["id"]))
    configuration = AcquisitionSourceCreate.model_validate(
        {"label": row["label"], "configuration": row["configuration_json"]}
    ).configuration
    if (
        row["project_id"] != project_id
        or row["kind"] != configuration.kind
        or type(row["cursor"]) is not int
        or row["cursor"] < 0
        or type(row["revision"]) is not int
        or row["revision"] < 1
        or row["state"] not in ("ready", "paused", "disconnected", "exhausted")
        or _source_digest(project_id, source_id, row["label"], row["configuration_json"])
        != row["source_sha256"]
    ):
        raise ValueError("Source ownership, cursor or configuration checksum differs")
    if isinstance(configuration, RecordedSource):
        batch = batches[str(configuration.batch_id)]
        if (
            batch["project_id"] != project_id
            or batch["manifest_sha256"] != configuration.manifest_sha256
        ):
            raise ValueError("The recorded input is not its sealed field batch")
    return configuration


def _check_media_and_clock(
    project_id: str,
    receipt: AcquisitionReceiptData,
    batch: dict[str, Any],
    original: dict[str, Any],
    configuration: SourceConfiguration,
) -> None:
    expected_media = AcquisitionMedia(
        field_batch_id=UUID(batch["id"]),
        field_batch_sha256=batch["manifest_sha256"],
        field_observation_id=UUID(original["id"]),
        original_observation_id=UUID(original["source_observation_id"]),
        filename=original["filename"],
        kind=original["kind"],
        sha256=original["sha256"],
        size_bytes=original["size_bytes"],
    )
    clock = FieldCaptureMetadata.model_validate(original["metadata_json"]).clock
    time = receipt.time
    if (
        batch["project_id"] != project_id
        or original["project_id"] != project_id
        or original["batch_id"] != batch["id"]
        or receipt.media != expected_media
        or time.clock != clock
        or time.captured_at_utc != clock.utc_timestamp()
    ):
        raise ValueError("The device receipt differs from the sealed field original or clock")

    if isinstance(configuration, RecordedSource):
        if (
            batch["id"] != str(configuration.batch_id)
            or original["ordinal"] != receipt.ordinal
            or time.origin != "field_source"
            or time.uncertainty_seconds is not None
        ):
            raise ValueError("The recorded receipt is not at its original source position")
    elif isinstance(configuration, CameraSource):
        if (
            time.origin != "local_host_read"
            or time.captured_at_utc is not None
            or time.host_received_at_utc is None
            or time.host_read_elapsed_seconds is None
            or time.uncertainty_seconds is not None
        ):
            raise ValueError("The camera receipt overstates its measured clock evidence")
    else:
        expected_time = configuration.start_at_utc + timedelta(
            seconds=configuration.period_seconds * receipt.ordinal
        )
        seed = f"reefvision-synthetic-v1:{configuration.seed}:{receipt.ordinal}"
        expected_value = sha256(seed.encode()).digest()[6] % 101
        if (
            time.origin != "synthetic_clock"
            or time.captured_at_utc != expected_time
            or time.uncertainty_seconds != 0
            or receipt.synthetic_reading is None
            or receipt.synthetic_reading.value != expected_value
        ):
            raise ValueError("The simulated receipt differs from its deterministic configuration")
    if (
        not isinstance(configuration, SimulatedSource) and receipt.synthetic_reading is not None
    ) or (
        not isinstance(configuration, CameraSource)
        and (time.host_received_at_utc is not None or time.host_read_elapsed_seconds is not None)
    ):
        raise ValueError("The receipt claims evidence from a different source type")


def _check_dispatch(
    project_id: str,
    receipt: AcquisitionReceiptData,
    key: str,
    nodes_by_run: dict[tuple[str, str], dict[str, Any]],
    slots: dict[str, dict[str, Any]],
    schedules: dict[str, dict[str, Any]],
) -> None:
    dispatch = receipt.dispatch
    if dispatch.kind == "manual":
        if (
            not key.startswith("manual:")
            or "manual:" + str(UUID(key.removeprefix("manual:"))) != key
        ):
            raise ValueError("Manual capture request identity is invalid")
        return
    slot = slots[str(dispatch.occurrence_id)]
    schedule = schedules[slot["schedule_id"]]
    run_id = str(dispatch.workflow_run_id)
    node = nodes_by_run[(run_id, str(dispatch.node_id))]
    if (
        key != f"schedule:{slot['id']}:{dispatch.node_id}"
        or slot["project_id"] != project_id
        or schedule["project_id"] != project_id
        or schedule["purpose"] != "acquisition"
        or slot["workflow_run_id"] != run_id
        or node["node_type"] != ACQUISITION_CAPTURE_NODE
        or node["parameters_json"]
        != {
            "source_id": str(receipt.source_id),
            "source_sha256": receipt.source_sha256,
        }
        or not any(
            ref.get("node_id") == dispatch.node_id
            and ref.get("kind") == ACQUISITION_CAPTURE_NODE
            and ref.get("id") == str(receipt.source_id)
            and ref.get("sha256") == receipt.source_sha256
            for ref in schedule["inputs_json"].get("references", ())
        )
    ):
        raise ValueError("The device receipt does not name its authorized scheduled node")


def remap_device_receipt(
    payload: dict[str, Any], id_map: dict[str, str], digests: dict[str, str]
) -> dict[str, Any]:
    """Rebind local references while retaining original observation identity and bytes."""
    receipt = deepcopy(payload["receipt"])
    for key in ("id", "project_id", "source_id"):
        receipt[key] = id_map[receipt[key]]
    media = receipt["media"]
    for key in ("field_batch_id", "field_observation_id"):
        media[key] = id_map[media[key]]
    dispatch = receipt["dispatch"]
    if dispatch["kind"] == "schedule":
        for key in ("occurrence_id", "workflow_run_id"):
            dispatch[key] = id_map[dispatch[key]]
    receipt["source_sha256"] = digests[receipt["source_sha256"]]
    return {"receipt": receipt, "content_sha256": canonical_json_sha256(receipt)}


def _check_graph_pins(
    node_type: str,
    pins: dict[str, Any],
    sources: dict[str, dict[str, Any]],
    captures: dict[str, dict[str, Any]],
) -> None:
    if node_type == ACQUISITION_CAPTURE_NODE:
        pin = AcquisitionSourcePin.model_validate(pins)
        if sources[str(pin.source_id)]["source_sha256"] != pin.source_sha256:
            raise ValueError("The saved acquisition source pin differs")
    elif node_type == ACQUISITION_REPLAY_NODE:
        replay = AcquisitionReceiptPin.model_validate(pins)
        if captures[str(replay.capture_id)]["content_sha256"] != replay.content_sha256:
            raise ValueError("The saved acquisition receipt pin differs")


def _check_artifacts(
    rows: Rows,
    project_id: str,
    captures: dict[str, dict[str, Any]],
    sources: dict[str, dict[str, Any]],
    nodes: dict[str, dict[str, Any]],
    origin_ids: dict[str, str],
) -> None:
    for artifact in rows.get("workflow_artifacts", ()):
        if artifact["data_type"] != ACQUISITION_RECEIPT_TYPE:
            continue
        raw = artifact["payload_json"]
        payload = AcquisitionCaptureReceipt.model_validate(raw).receipt
        if (
            canonical_json_sha256(raw["receipt"]) != raw["content_sha256"]
            or artifact["producer_port_id"] != "receipt"
        ):
            raise ValueError("The archived acquisition artifact checksum or port differs")
        if str(payload.project_id) == project_id:
            current = raw
        else:
            source = sources[origin_ids[str(payload.source_id)]]
            config = deepcopy(source["configuration_json"])
            if config["kind"] == "recorded":
                config["batch_id"] = str(payload.media.field_batch_id)
            old_digest = _source_digest(
                str(payload.project_id), str(payload.source_id), source["label"], config
            )
            if old_digest != payload.source_sha256:
                raise ValueError("The historical acquisition source cannot reproduce its pin")
            current = remap_device_receipt(raw, origin_ids, {old_digest: source["source_sha256"]})
        local = captures[current["receipt"]["id"]]
        if current != {"receipt": local["receipt_json"], "content_sha256": local["content_sha256"]}:
            raise ValueError("The workflow artifact differs from its verified acquisition receipt")
        producer = nodes[artifact["producer_node_run_id"]]
        dispatch = current["receipt"]["dispatch"]
        match producer["node_type"]:
            case "acquisition_source_capture":
                if (
                    dispatch["workflow_run_id"] != producer["workflow_run_id"]
                    or dispatch["node_id"] != producer["node_id"]
                ):
                    raise ValueError(
                        "The acquisition artifact did not originate at this scheduled node"
                    )
            case "acquisition_capture_replay":
                if producer["parameters_json"] != {
                    "capture_id": local["id"],
                    "content_sha256": local["content_sha256"],
                }:
                    raise ValueError("The replay artifact did not originate from this receipt pin")
            case _:
                raise ValueError("The artifact has an unsupported acquisition producer")


def validate_device_records(
    project_id: str, rows: Rows, *, origin_ids: dict[str, str] | None = None
) -> None:
    try:
        sources, captures = _index(rows, SOURCES), _index(rows, CAPTURES)
        batches = _index(rows, "field_capture_batches")
        observations = _index(rows, "field_capture_observations")
        nodes = _index(rows, "workflow_node_runs")
        nodes_by_run = {(node["workflow_run_id"], node["node_id"]): node for node in nodes.values()}
        slots = _index(rows, "workflow_schedule_occurrences")
        schedules = _index(rows, "workflow_schedules")
        configurations = {
            source_id: _check_source(project_id, source, batches)
            for source_id, source in sources.items()
        }
        ordinals: dict[str, list[int]] = {source_id: [] for source_id in sources}
        keys: set[tuple[str, str]] = set()
        for row in captures.values():
            source_id = row["source_id"]
            source = sources[source_id]
            receipt = AcquisitionReceiptData.model_validate(row["receipt_json"])
            capture_key = (source_id, row["capture_key"])
            if (
                row["project_id"] != project_id
                or str(receipt.project_id) != project_id
                or str(receipt.id) != row["id"]
                or str(receipt.source_id) != source_id
                or receipt.source_kind != source["kind"]
                or source["source_sha256"] != receipt.source_sha256
                or type(row["ordinal"]) is not int
                or row["ordinal"] != receipt.ordinal
                or capture_key in keys
                or str(receipt.media.field_batch_id) != row["field_batch_id"]
                or str(receipt.media.field_observation_id) != row["field_observation_id"]
                or canonical_json_sha256(row["receipt_json"]) != row["content_sha256"]
            ):
                raise ValueError("The capture identity, position or receipt checksum differs")
            _check_media_and_clock(
                project_id,
                receipt,
                batches[row["field_batch_id"]],
                observations[row["field_observation_id"]],
                configurations[source_id],
            )
            _check_dispatch(project_id, receipt, row["capture_key"], nodes_by_run, slots, schedules)
            keys.add(capture_key)
            ordinals[source_id].append(row["ordinal"])
        for source_id, roster in ordinals.items():
            if len(roster) != sources[source_id]["cursor"] or any(
                index != ordinal for index, ordinal in enumerate(sorted(roster))
            ):
                raise ValueError("The source cursor differs from its saved captures")
        for graph in rows.get("workflow_graphs", ()):
            for node in graph["graph_json"].get("nodes", ()):
                _check_graph_pins(node["node_type"], node.get("parameters", {}), sources, captures)
        for node in nodes.values():
            _check_graph_pins(node["node_type"], node["parameters_json"], sources, captures)
        _check_artifacts(rows, project_id, captures, sources, nodes, origin_ids or {})
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError) as exc:
        raise ValidationError(f"Acquisition Exchange evidence is invalid: {exc}") from exc


def restore_device_row(
    name: str,
    original: dict[str, Any],
    values: dict[str, Any],
    id_map: dict[str, str],
    digests: dict[str, str],
) -> None:
    if name == SOURCES:
        configuration = deepcopy(original["configuration_json"])
        if configuration["kind"] == "recorded":
            configuration["batch_id"] = id_map[configuration["batch_id"]]
        rebound = _source_digest(
            values["project_id"], values["id"], original["label"], configuration
        )
        digests[original["source_sha256"]] = rebound
        values.update(
            label=original["label"],
            configuration_json=configuration,
            source_sha256=rebound,
            last_error=original["last_error"],
            state="paused",
            local_consent_until=None,
            next_retry_at=None,
        )
    elif name == CAPTURES:
        payload = remap_device_receipt(
            {"receipt": original["receipt_json"], "content_sha256": original["content_sha256"]},
            id_map,
            digests,
        )
        dispatch = payload["receipt"]["dispatch"]
        key = original["capture_key"]
        if dispatch["kind"] == "schedule":
            key = f"schedule:{dispatch['occurrence_id']}:{dispatch['node_id']}"
        digests[original["content_sha256"]] = payload["content_sha256"]
        values.update(
            receipt_json=payload["receipt"],
            content_sha256=payload["content_sha256"],
            capture_key=key,
        )
