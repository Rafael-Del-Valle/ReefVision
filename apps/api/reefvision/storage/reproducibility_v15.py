"""Write and verify managed research ZIPs and their native Project Exchange contents."""

import json
from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from tempfile import SpooledTemporaryFile
from typing import IO, Any, BinaryIO, cast
from zipfile import ZIP_DEFLATED, ZIP_STORED, BadZipFile, ZipFile

from reefvision.config import Settings
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.domain.reproducibility_v15 import (
    EVIDENCE_SECTIONS,
    ReproducibilityEvidence,
    derive_evidence,
    verify_proof,
)
from reefvision.schemas.project_exchange import ProjectExchangeInspectionResponse
from reefvision.schemas.reproducibility_v15 import (
    ManifestEntry,
    ReproducibilityManifest,
    ReproducibilitySelection,
    SourceOmission,
)
from reefvision.storage.datasets import canonical_json_bytes, canonical_json_sha256
from reefvision.storage.projects import resolve_managed_project_path

MANIFEST = "manifest.json"
NATIVE_PACKAGE = "project.reefvision.zip"
_NATIVE_MANIFEST = "reefvision-exchange-manifest.json"
_CHUNK_SIZE = 1024 * 1024
_MAX_NATIVE_BYTES = 100 * 1024**3
_MAX_JSON_BYTES = 256 * 1024**2
_RELINK_STEPS = {
    "image": ["visual review", "detector or mask inference", "image measurements"],
    "video": ["playback", "pose, tracking, or event inference", "video measurements"],
    "model": ["model inference", "recomputing paired model scores"],
    "spatial_source": ["spatial preview", "geometry measurements"],
    "field_capture": ["field original playback", "source reanalysis"],
}


@dataclass(frozen=True)
class NativeResearchArchive:
    manifest: dict[str, Any]
    sections: dict[str, list[dict[str, Any]]]
    inspection: ProjectExchangeInspectionResponse
    omitted: list[SourceOmission]
    verified_paired_comparison_ids: frozenset[str]


@dataclass(frozen=True)
class VerifiedBundle:
    manifest: ReproducibilityManifest
    native: BinaryIO
    project_name: str | None


def _section_path(key: str) -> str:
    return f"evidence/{key}.json"


def _transfer(source: IO[bytes], target: IO[bytes] | None = None) -> tuple[str, int]:
    digest = sha256()
    size = 0
    while chunk := source.read(_CHUNK_SIZE):
        digest.update(chunk)
        size += len(chunk)
        if target is not None:
            target.write(chunk)
    return digest.hexdigest(), size


def _read_json(archive: ZipFile, path: str) -> Any:
    if archive.getinfo(path).file_size > _MAX_JSON_BYTES:
        raise ValueError(f"Research metadata exceeds the inspection limit: {path}")
    return json.loads(archive.read(path))


def _omissions(
    inspection: ProjectExchangeInspectionResponse,
    manifest: dict[str, Any],
    sections: dict[str, list[dict[str, Any]]],
) -> list[SourceOmission]:
    missing = [
        SourceOmission(
            kind=item.kind,
            record_id=item.record_id,
            name=item.name,
            sha256=item.sha256,
            requires_relink_for=_RELINK_STEPS[item.kind],
        )
        for item in inspection.unavailable_assets
    ]
    included = {item["sha256"] for item in manifest["media"] if item["kind"] == "field_source"}
    missing.extend(
        SourceOmission(
            kind="field_capture",
            record_id=item["id"],
            name=item["filename"],
            sha256=item["sha256"],
            requires_relink_for=_RELINK_STEPS["field_capture"],
        )
        for item in sections.get("field_capture_observations", [])
        if item["sha256"] not in included
    )
    return sorted(missing, key=lambda item: (item.kind, item.name, item.record_id))


def _validate_native_inventory(archive: ZipFile, manifest: dict[str, Any]) -> None:
    # The native inspector has already checked ownership and byte integrity. A
    # reconciled field observation may reference the canonical image/video member.
    media: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for descriptor in manifest.get("media", []):
        media[descriptor["path"]].append(descriptor)
    for references in media.values():
        if len(references) == 1:
            continue
        kinds = {entry["kind"] for entry in references}
        checksum = {(entry["sha256"], entry["size_bytes"]) for entry in references}
        if (
            len(references) != 2
            or kinds not in ({"field_source", "image"}, {"field_source", "video"})
            or len(checksum) != 1
        ):
            raise ValueError("Nested Project Exchange has inconsistent shared media members")

    descriptors = (
        *manifest["sections"].values(),
        *manifest.get("telemetry_sidecars", []),
        *manifest.get("generated_artifacts", []),
    )
    paths = [item["path"] for item in descriptors]
    required = {_NATIVE_MANIFEST, *paths, *media}
    names = archive.namelist()
    if (
        len(required) != 1 + len(paths) + len(media)
        or len(names) != len(required)
        or set(names) != required
        or any(name.startswith("reviewer_lab_credentials") for name in manifest["sections"])
    ):
        raise ValueError(
            "Nested Project Exchange contains undeclared, duplicate, or credential entries"
        )


def read_native_research_archive(source: BinaryIO) -> NativeResearchArchive:
    # This path is shared by the exporter and verifier. Run the native scientific and
    # filesystem inventory checks before providing any underlying package bytes for import.
    from reefvision.services.project_exchange_inspection import inspect_project_exchange

    verified_ids: set[str] = set()
    inspected = inspect_project_exchange(source, verified_paired_comparison_ids=verified_ids)
    if not inspected.compatible or inspected.format_version != "1.5":
        raise ValidationError(
            "Nested Project Exchange could not be verified: "
            + ("; ".join(inspected.errors) or "research evidence requires Exchange 1.5")
        )
    source.seek(0)
    with ZipFile(source) as archive:
        manifest = _read_json(archive, _NATIVE_MANIFEST)
        _validate_native_inventory(archive, manifest)
        sections = {}
        for name in (
            "study_design_revisions",
            "reviewer_lab_reports",
            "jobs",
            "field_capture_observations",
        ):
            if descriptor := manifest["sections"].get(name):
                path = descriptor["path"]
                if archive.getinfo(path).file_size > _MAX_JSON_BYTES:
                    raise ValueError(
                        f"Research record inventory exceeds the inspection limit: {name}"
                    )
                with archive.open(path) as rows:
                    sections[name] = [json.loads(line) for line in rows if line.strip()]
    return NativeResearchArchive(
        manifest,
        sections,
        inspected,
        _omissions(inspected, manifest, sections),
        frozenset(verified_ids),
    )


def _repro_manifest(
    native: NativeResearchArchive,
    evidence: ReproducibilityEvidence,
    entries: list[ManifestEntry],
) -> ReproducibilityManifest:
    return ReproducibilityManifest(
        proof=evidence.proof,
        exchange_manifest_sha256=canonical_json_sha256(native.manifest),
        entries=entries,
        omitted_sources=native.omitted,
        included_media_count=len({entry["path"] for entry in native.manifest["media"]}),
    )


def _write_bundle(
    source: BinaryIO,
    destination: Path,
    selection: ReproducibilitySelection,
) -> ReproducibilityManifest:
    native = read_native_research_archive(source)
    evidence = derive_evidence(
        native.sections,
        selection=selection,
        project_id=native.manifest["project"]["id"],
        origin_ids=(native.manifest.get("origin") or {}).get("id_map", {}),
        verified_paired_comparison_ids=native.verified_paired_comparison_ids,
    )
    entries = []
    temporary = destination.with_suffix(".partial")
    try:
        with ZipFile(temporary, "w", compression=ZIP_STORED) as archive:
            source.seek(0)
            with archive.open(NATIVE_PACKAGE, "w", force_zip64=True) as target:
                digest, size = _transfer(source, target)
            entries.append(ManifestEntry(path=NATIVE_PACKAGE, size_bytes=size, sha256=digest))
            for name in EVIDENCE_SECTIONS:
                path = _section_path(name)
                body = canonical_json_bytes(evidence.sections[name])
                archive.writestr(path, body, compress_type=ZIP_DEFLATED)
                entries.append(
                    ManifestEntry(path=path, size_bytes=len(body), sha256=sha256(body).hexdigest())
                )
            manifest = _repro_manifest(native, evidence, entries)
            archive.writestr(MANIFEST, canonical_json_bytes(manifest.model_dump(mode="json")))
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return manifest


def _read_bundle(
    source: BinaryIO,
    native: BinaryIO,
) -> tuple[ReproducibilityManifest, str | None]:
    source.seek(0)
    with ZipFile(source) as archive:
        expected = {MANIFEST, NATIVE_PACKAGE, *(_section_path(key) for key in EVIDENCE_SECTIONS)}
        names = archive.namelist()
        if len(names) != len(expected) or set(names) != expected:
            raise ValueError("Package contains missing, duplicate, or undeclared entries")
        raw = _read_json(archive, MANIFEST)
        manifest = ReproducibilityManifest.model_validate(raw)
        if archive.read(MANIFEST) != canonical_json_bytes(manifest.model_dump(mode="json")):
            raise ValueError("Package manifest is not canonical")
        paths = [entry.path for entry in manifest.entries]
        if len(paths) != len(expected) - 1 or set(paths) != expected - {MANIFEST}:
            raise ValueError("Package manifest does not enumerate each entry once")
        for entry in manifest.entries:
            size_limit = _MAX_NATIVE_BYTES if entry.path == NATIVE_PACKAGE else _MAX_JSON_BYTES
            if (
                entry.size_bytes > size_limit
                or archive.getinfo(entry.path).file_size != entry.size_bytes
            ):
                raise ValueError(f"Package entry size differs: {entry.path}")
            with archive.open(entry.path) as stream:
                digest, size = _transfer(stream, native if entry.path == NATIVE_PACKAGE else None)
            if (digest, size) != (entry.sha256, entry.size_bytes):
                raise ValueError(f"Package entry checksum differs: {entry.path}")
        verified = read_native_research_archive(native)
        evidence = verify_proof(
            manifest.proof,
            verified.sections,
            verified.manifest,
            verified_paired_comparison_ids=verified.verified_paired_comparison_ids,
        )
        for key in EVIDENCE_SECTIONS:
            path = _section_path(key)
            if archive.read(path) != canonical_json_bytes(evidence.sections[key]):
                raise ValueError(f"Package proof section differs from Project Exchange: {path}")
        if manifest != _repro_manifest(verified, evidence, manifest.entries):
            raise ValueError("Manifest and nested Exchange inventory or omissions differ")
        return manifest, verified.inspection.project_name


@contextmanager
def open_verified_bundle(source: BinaryIO) -> Iterator[VerifiedBundle]:
    with SpooledTemporaryFile(max_size=8 * _CHUNK_SIZE, mode="w+b") as spool:
        native = cast(BinaryIO, spool)
        try:
            manifest, project_name = _read_bundle(source, native)
        except (
            BadZipFile,
            OSError,
            RuntimeError,
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
        ) as exc:
            raise ValidationError(f"Research package could not be verified: {exc}") from exc
        native.seek(0)
        yield VerifiedBundle(manifest=manifest, native=native, project_name=project_name)


def copy_uploaded_bundle(source: BinaryIO, destination: Path) -> None:
    """Keep the exact verified outer archive beside the corresponding Exchange import."""
    source.seek(0)
    with destination.open("xb") as target:
        _transfer(source, target)


def archive_location(settings: Settings, exchange_path: str, package_id: str) -> Path:
    return resolve_managed_project_path(settings, exchange_path).with_name(
        f"{package_id}.reproducibility.zip"
    )


def existing_bundle(settings: Settings, exchange_path: str, package_id: str) -> Path:
    path = archive_location(settings, exchange_path, package_id)
    if not path.is_file():
        raise NotFoundError("Reproducibility archive is unavailable")
    return path


def build_bundle(
    settings: Settings,
    exchange_path: str,
    package_id: str,
    selection: ReproducibilitySelection,
) -> ReproducibilityManifest:
    destination = archive_location(settings, exchange_path, package_id)
    with resolve_managed_project_path(settings, exchange_path).open("rb") as source:
        return _write_bundle(source, destination, selection)
