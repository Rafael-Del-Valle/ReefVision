"""Metadata-only Workflow Builder parity for local provider manifests."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import WorkflowArtifact
from reefvision.domain.errors import ValidationError
from reefvision.schemas.workflow_graphs import (
    WorkflowNodeDefinitionResponse,
    WorkflowPortDefinition,
)
from reefvision.services import workflow_runtime_adapters as runtime_adapters
from reefvision.services.advanced_providers import discover_advanced_local_provider_manifests

NODE_TYPE = "provider_manifest_snapshot"
ARTIFACT_SCHEMA_VERSION = "provider-manifest-snapshot-0001"


def extend_provider_manifest_registry(
    base: Callable[[], dict[str, WorkflowNodeDefinitionResponse]],
) -> Callable[[], dict[str, WorkflowNodeDefinitionResponse]]:
    def registry() -> dict[str, WorkflowNodeDefinitionResponse]:
        nodes = dict(base())
        nodes[NODE_TYPE] = WorkflowNodeDefinitionResponse(
            node_type=NODE_TYPE,
            display_name="Local Provider Manifest Snapshot",
            category="sources",
            description=(
                "Snapshot one inspect-only local provider declaration and its discovery status."
            ),
            input_ports=[
                WorkflowPortDefinition(
                    port_id="project",
                    display_name="Project",
                    accepted_types=["project_reference"],
                )
            ],
            output_ports=[
                WorkflowPortDefinition(
                    port_id="manifest",
                    display_name="Provider manifest snapshot",
                    accepted_types=["provider_manifest_snapshot"],
                    required=False,
                    multiple=True,
                )
            ],
            required_parameters=["record_id"],
            optional_parameters={"expected_source_sha256": None},
            execution_state="executable_source",
            executable=True,
            implementation_notes=[
                "Snapshots declarative metadata and never executes provider code.",
                "Does not import modules, install packages, load checkpoints, or enable adapters.",
                "An expected SHA-256 makes saved graphs fail closed when the source changes.",
            ],
        )
        return nodes

    return registry


def _canonical_sha256(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def execute_provider_manifest_snapshot(
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: dict[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    del session
    project_inputs = inputs.get("project", [])
    if (
        len(project_inputs) != 1
        or project_inputs[0].data_type != "project_reference"
        or (project_inputs[0].payload_json or {}).get("project_id") != project_id
    ):
        raise ValidationError("Provider manifest snapshot requires the current project reference")

    allowed_parameters = {
        "record_id",
        "expected_source_sha256",
        "__workflow_run_id",
        "__workflow_node_run_id",
    }
    unexpected = sorted(set(parameters) - allowed_parameters)
    if unexpected:
        raise ValidationError(
            "Provider manifest snapshot received unsupported parameters: " + ", ".join(unexpected)
        )
    record_id = parameters.get("record_id")
    if not isinstance(record_id, str) or not record_id:
        raise ValidationError("Provider manifest snapshot requires a record_id")
    records = discover_advanced_local_provider_manifests(settings)
    record = next((item for item in records if item.record_id == record_id), None)
    if record is None:
        raise ValidationError("Local provider manifest record is missing")

    expected = parameters.get("expected_source_sha256")
    if expected is not None and (
        not isinstance(expected, str)
        or len(expected) != 64
        or any(character not in "0123456789abcdef" for character in expected)
    ):
        raise ValidationError("expected_source_sha256 must be a lowercase SHA-256 digest")
    if expected is not None and record.source_sha256 != expected:
        raise ValidationError("Local provider manifest changed after the workflow was saved")

    snapshot: dict[str, Any] = {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "project_id": project_id,
        "record_id": record.record_id,
        "source_filename": record.source_filename,
        "source_sha256": record.source_sha256,
        "discovery_status": record.discovery_status,
        "discovery_errors": list(record.errors),
        "manifest": record.manifest.model_dump(mode="json") if record.manifest else None,
        "execution_allowed": False,
    }
    snapshot["snapshot_sha256"] = _canonical_sha256(snapshot)
    return [
        {
            "port_id": "manifest",
            "data_type": "provider_manifest_snapshot",
            "payload": snapshot,
        }
    ]


def register_provider_manifest_adapter() -> None:
    runtime_adapters.RUNTIME_ADAPTER_NODE_TYPES.add(NODE_TYPE)
    runtime_adapters._ADAPTERS[NODE_TYPE] = execute_provider_manifest_snapshot
