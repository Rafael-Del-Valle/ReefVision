"""Authenticate live band bindings and reproduce portable index values from original media."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError as SchemaError

from reefvision.domain.errors import ConflictError, ValidationError
from reefvision.domain.multispectral import Planes, normalized_difference
from reefvision.schemas.multispectral import (
    AcquisitionInput,
    AcquisitionSnapshot,
    IndexSnapshot,
    SpectralRecord,
)
from reefvision.services.workflow_multispectral import NODE, IndexPin
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.storage.multispectral import decode_band

ACQUISITIONS = "multispectral_acquisitions"
BINDINGS = "multispectral_band_bindings"
INDICES = "multispectral_indices"
SECTIONS = (ACQUISITIONS, BINDINGS, INDICES)
Rows = dict[str, list[dict[str, Any]]]


def _check_index_outputs(project_id: str, sections: Rows, origins: dict[str, str]) -> None:
    """Authenticate the result a researcher sees when reopening a historical workflow."""
    nodes = {row["id"]: row for row in sections.get("workflow_node_runs", [])}
    reports = {row["id"]: row for row in sections.get(INDICES, [])}
    for artifact in sections.get("workflow_artifacts", []):
        if artifact["data_type"] != NODE:
            continue
        producer = nodes[artifact["producer_node_run_id"]]
        pin = IndexPin.model_validate(producer["parameters_json"])
        row = reports[str(pin.index_id)]
        result = SpectralRecord[IndexSnapshot].model_validate(artifact["payload_json"])
        source_id, owner = str(result.id), str(result.project_id)
        timestamp = datetime.fromisoformat(row["created_at"])
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)
        if (
            producer["node_type"] != NODE
            or artifact["producer_port_id"] != "index"
            or origins.get(source_id, source_id) != row["id"]
            or origins.get(owner, owner) != project_id
            or result.content_sha256 != row["content_sha256"]
            or pin.content_sha256 != result.content_sha256
            or result.created_at != timestamp
            or result.snapshot.model_dump(mode="json") != row["snapshot_json"]
        ):
            raise ValidationError("The spectral workflow output differs from its saved index")


def validate_spectral_archive(
    project_id: str,
    sections: Rows,
    origins: dict[str, str],
    original: Callable[[str], bytes | None],
) -> None:
    if not any(sections.get(s) for s in SECTIONS):
        if any(a.get("data_type") == NODE for a in sections.get("workflow_artifacts", [])):
            raise ValidationError("The spectral workflow output has lost its original index")
        return
    if not all(s in sections for s in SECTIONS):
        raise ValidationError("The multispectral archive is missing band or analysis records")
    images = {row["id"]: row for row in sections.get("images", [])}
    acqs = {row["id"]: row for row in sections[ACQUISITIONS]}
    bindings: dict[str, dict[int, str]] = {k: {} for k in acqs}
    results: dict[str, list[dict[str, Any]]] = {k: [] for k in acqs}

    def same(old: str, current: str) -> bool:
        return old == current or origins.get(old) == current

    try:
        for row in sections[BINDINGS]:
            bound = bindings[row["acquisition_id"]]
            if (
                row["project_id"] != project_id
                or type(row["position"]) is not int
                or row["position"] in bound
            ):
                raise ValidationError("The archive has an invalid spectral band position or owner")
            bound[row["position"]] = row["image_id"]
        for row in sections[INDICES]:
            results[row["acquisition_id"]].append(row)
        for acq_id, row in acqs.items():
            saved = AcquisitionSnapshot.model_validate(row["snapshot_json"])
            digest = canonical_json_sha256(saved.model_dump(mode="json"))
            if (
                row["project_id"] != project_id
                or not same(str(saved.source_project_id), project_id)
                or row["content_sha256"] != digest
                or row["snapshot_json"] != saved.model_dump(mode="json")
                or set(bindings[acq_id]) != set(range(len(saved.bands)))
            ):
                raise ValidationError(
                    "A spectral acquisition has inconsistent ownership, checksum or band bindings"
                )
            AcquisitionInput.model_validate(
                {
                    "label": saved.label,
                    "sensor": saved.sensor,
                    "alignment": saved.alignment,
                    "bands": [
                        b.model_dump(exclude={"width", "height", "bits"}) for b in saved.bands
                    ],
                }
            )
            planes: Planes = {}
            for position, band in enumerate(saved.bands):
                image = images[bindings[acq_id][position]]
                if (
                    image["project_id"] != project_id
                    or not same(str(band.image_id), image["id"])
                    or image["sha256"] != band.original_sha256
                    or (image["width_px"], image["height_px"]) != (band.width, band.height)
                ):
                    raise ValidationError(
                        "A spectral band has lost its project image, grid or original checksum"
                    )
                data = original(image["id"])
                if data is None:
                    raise ValidationError(
                        "Include original spectral band media to reproduce the acquisition"
                    )
                pixels, bits = decode_band(data, band.width, band.height)
                limit = 2**bits - 1
                if (
                    bits != band.bits
                    or (band.nodata is not None and band.nodata > limit)
                    or (band.calibration and band.calibration.white_dn > limit)
                ):
                    raise ValidationError(
                        "The archived band depth or calibration differs from the original"
                    )
                planes[position] = pixels
            for result in results[acq_id]:
                report = IndexSnapshot.model_validate(result["snapshot_json"])
                if (
                    result["project_id"] != project_id
                    or report.acquisition != saved
                    or report.selection.acquisition_sha256 != digest
                    or result["content_sha256"]
                    != canonical_json_sha256(report.model_dump(mode="json"))
                ):
                    raise ValidationError(
                        "A saved spectral index has lost its acquisition or result checksum"
                    )
                actual, _ = normalized_difference(saved, report.selection, planes)
                if actual != report.result:
                    raise ValidationError(
                        "The spectral index cannot be reproduced from the archived band pixels"
                    )
        _check_index_outputs(project_id, sections, origins)
    except (SchemaError, KeyError, IndexError, ValueError, TypeError, ConflictError) as exc:
        raise ValidationError(
            "The spectral archive contains invalid source data, references or calibration"
        ) from exc
