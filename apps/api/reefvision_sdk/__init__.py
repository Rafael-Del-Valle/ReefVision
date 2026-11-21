"""Offline Python SDK for the running ReefVision 2.0 local API. Requires only Python."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import UUID

__version__ = "2.0.0"
Transport = Callable[[str, str, Any], tuple[int, bytes]]


class AutomationError(Exception):
    def __init__(self, message: str, *, status: int = 400, details: Any = None) -> None:
        super().__init__(message)
        self.status = status
        self.details = details


class _LocalOnly(HTTPRedirectHandler):
    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> None:
        return None


def _uuid(value: str) -> str:
    try:
        return str(UUID(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise AutomationError("A valid ReefVision UUID is required.") from exc


def _digest(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
        raise AutomationError("A lowercase SHA-256 checksum is required.")
    return value


class ReefVision:
    """Use the same project, job and review services as the desktop application."""

    def __init__(
        self, api_url: str, *, timeout: float = 120, transport: Transport | None = None
    ) -> None:
        url = urlsplit(api_url.rstrip("/"))
        if (
            url.scheme != "http"
            or url.hostname not in {"127.0.0.1", "::1", "localhost"}
            or url.username is not None
            or url.password is not None
            or url.query
            or url.fragment
            or url.path != "/api/v1"
        ):
            raise AutomationError(
                "Supply the local HTTP URL ending in /api/v1 from Help → Automation API."
            )
        self.api_url = url.geturl()
        self.timeout = timeout
        self._opener = build_opener(ProxyHandler({}), _LocalOnly())
        self._transport = transport

    def _open(self, method: str, path: str, data: Any = None) -> Any:
        request = Request(
            self.api_url + path,
            method=method,
            data=None if data is None else json.dumps(data, allow_nan=False).encode(),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, application/zip",
            },
        )
        try:
            return self._opener.open(request, timeout=self.timeout)
        except HTTPError as exc:
            with exc:
                self._error(exc.code, exc.read(128 * 1024))
            raise
        except (OSError, URLError) as exc:
            raise AutomationError(
                "The selected local ReefVision service is unavailable.", status=503
            ) from exc

    @staticmethod
    def _error(status: int, raw: bytes) -> None:
        try:
            payload = json.loads(raw)
        except (ValueError, UnicodeError):
            payload = {}
        detail = payload.get("detail", payload) if isinstance(payload, dict) else payload
        message = detail.get("message") if isinstance(detail, dict) else detail
        raise AutomationError(
            str(message or f"Local service returned HTTP {status}."), status=status, details=detail
        )

    def _json(self, method: str, path: str, data: Any = None) -> dict[str, Any]:
        if self._transport:
            status, raw = self._transport(method, path, data)
            if status >= 400:
                self._error(status, raw)
        else:
            with self._open(method, path, data) as response:
                raw = response.read()
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise AutomationError("The local service returned an unexpected response.", status=502)
        return payload

    def system(self) -> dict[str, Any]:
        return self._json("GET", "/system/version")

    def create_project(self, name: str) -> dict[str, Any]:
        return self._json("POST", "/projects", {"name": name, "template": "blank"})

    def open_project(self, project: str) -> dict[str, Any]:
        return self._json("GET", f"/projects/{_uuid(project)}")

    def _graph(self, project: str, graph_id: str, sha256: str) -> dict[str, Any]:
        graph = self._json("GET", f"/projects/{_uuid(project)}/workflow-graphs/{_uuid(graph_id)}")
        if graph["graph_sha256"] != _digest(sha256):
            raise AutomationError(
                "The saved graph checksum differs from the selected revision.", status=409
            )
        return graph

    def plan_workflow(self, project: str, graph_id: str, sha256: str) -> dict[str, Any]:
        graph = self._graph(project, graph_id, sha256)
        return self._json(
            "POST", f"/projects/{_uuid(project)}/workflow-graphs/plan", graph["graph_json"]
        )

    def run_workflow(
        self, project: str, graph_id: str, sha256: str, *, inputs: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return self._json(
            "POST",
            f"/projects/{_uuid(project)}/workflow-runs",
            {
                "graph_record_id": _uuid(graph_id),
                "expected_graph_sha256": _digest(sha256),
                "inputs": inputs or {},
            },
        )

    def workflow(self, project: str, run_id: str) -> dict[str, Any]:
        detail = self._json("GET", f"/workflow-runs/{_uuid(run_id)}")
        if detail["run"]["project_id"] != _uuid(project):
            raise AutomationError("The workflow run belongs to a different project.", status=409)
        return detail

    def resume_workflow(
        self, project: str, run_id: str, node_id: str, reviewer: str, note: str
    ) -> dict[str, Any]:
        detail = self.workflow(project, run_id)
        node_id = _uuid(node_id)
        if not any(
            n["id"] == node_id and n["status"] == "waiting_for_review" for n in detail["nodes"]
        ):
            raise AutomationError(
                "Select the current review gate from this workflow run.", status=409
            )
        if not reviewer.strip() or not note.strip():
            raise AutomationError("Supply the reviewer and a review note.")
        return self._json(
            "POST",
            f"/workflow-node-runs/{node_id}/resume-review",
            {"reviewed_by": reviewer, "note": note},
        )

    def infer(
        self,
        project: str,
        model: str,
        checkpoint_sha256: str,
        images: dict[str, str],
        *,
        device: str = "auto",
    ) -> dict[str, Any]:
        pins = {_uuid(i): _digest(s) for i, s in images.items()}
        if not pins:
            raise AutomationError("Choose at least one image and its source checksum.")
        return self._json(
            "POST",
            f"/projects/{_uuid(project)}/inference-jobs",
            {
                "model_id": _uuid(model),
                "image_ids": list(pins),
                "device": device,
                "source_pins": {"checkpoint_sha256": _digest(checkpoint_sha256), "images": pins},
            },
        )

    def benchmark(self, project: str, comparison: dict[str, Any]) -> dict[str, Any]:
        return self._json(
            "POST", f"/projects/{_uuid(project)}/paired-model-comparisons", comparison
        )

    def benchmark_result(self, project: str, job_id: str) -> dict[str, Any]:
        return self._json(
            "GET", f"/projects/{_uuid(project)}/paired-model-comparisons/{_uuid(job_id)}/export"
        )

    def export(
        self, project: str, version_id: str, manifest_sha256: str, *, format: str = "yolo_detection"
    ) -> dict[str, Any]:
        version = self._json("GET", f"/dataset-versions/{_uuid(version_id)}")
        if version["project_id"] != _uuid(project) or version["manifest_sha256"] != _digest(
            manifest_sha256
        ):
            raise AutomationError(
                "The dataset belongs to another project or has a different manifest checksum.",
                status=409,
            )
        return self._json(
            "POST", f"/dataset-versions/{_uuid(version_id)}/exports", {"format": format}
        )

    def download_export(self, project: str, export_id: str, destination: Path) -> dict[str, Any]:
        export_id = _uuid(export_id)
        saved = self._json("GET", f"/exports/{export_id}")
        if saved["project_id"] != _uuid(project) or saved["status"] != "succeeded":
            raise AutomationError("The selected export is unavailable in this project.", status=409)
        destination = Path(destination).resolve()
        if destination.exists():
            raise AutomationError("Choose a new filename for the export.", status=409)
        digest = hashlib.sha256()
        size = 0
        route = f"/exports/{export_id}/download"
        temp: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=destination.parent, prefix=".reefvision-export-", delete=False
            ) as output:
                temp = Path(output.name)
                with self._open("GET", route) as response:
                    while block := response.read(1024 * 1024):
                        output.write(block)
                        digest.update(block)
                        size += len(block)
                    if response.headers.get("Content-Length") and size != int(
                        response.headers["Content-Length"]
                    ):
                        raise AutomationError("The export download ended early.", status=502)
            # Publish without replacing an existing file, including a concurrent download.
            if os.name == "nt":
                temp.rename(destination)
            else:
                os.link(temp, destination)
        except OSError as exc:
            raise AutomationError(f"Could not write the export: {exc}", status=409) from exc
        finally:
            if temp:
                temp.unlink(missing_ok=True)
        return {
            "export_id": export_id,
            "file": str(destination),
            "sha256": digest.hexdigest(),
            "size_bytes": size,
        }

    def job(self, project: str, job_id: str) -> dict[str, Any]:
        job = self._json("GET", f"/jobs/{_uuid(job_id)}")
        if job["project_id"] != _uuid(project):
            raise AutomationError("The job belongs to a different project.", status=409)
        return job

    def resume_job(self, project: str, job_id: str) -> dict[str, Any]:
        self.job(project, job_id)
        return self._json("POST", f"/jobs/{_uuid(job_id)}/resume")

    def wait(
        self, project: str, identifier: str, *, workflow: bool = False, seconds: float = 3600
    ) -> dict[str, Any]:
        deadline = time.monotonic() + seconds
        while True:
            value = (
                self.workflow(project, identifier) if workflow else self.job(project, identifier)
            )
            state = value["run"] if workflow else value
            if state["status"] in {"succeeded", "completed", "waiting_for_review"}:
                return value
            if state["status"] in {"failed", "cancelled"}:
                raise AutomationError(
                    state.get("error_message") or f"Local job {state['status']}.",
                    status=409,
                    details=state,
                )
            if time.monotonic() >= deadline:
                raise AutomationError(
                    "Timed out waiting for the local operation.", status=408, details=state
                )
            time.sleep(0.25)
