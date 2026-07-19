"""Schema-aware complete-project archive, import, duplication, and storage migration."""

from __future__ import annotations

import base64
import hashlib
import json
import shutil
import zipfile
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import uuid4

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Table, func, select
from sqlalchemy.orm import Session, sessionmaker

from reefvision import __version__
from reefvision.config import Settings
from reefvision.db.base import Base
from reefvision.desktop import resolve_alembic_paths
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.schemas.project_archives import ProjectArchiveVerificationResponse
from reefvision.storage.datasets import canonical_json_bytes, canonical_json_sha256
from reefvision.storage.projects import resolve_managed_project_path

PROJECT_ARCHIVE_FORMAT_VERSION = "1.0"
_COMPLETION_MARKER = "REEFVISION_PROJECT_ARCHIVE_COMPLETE"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _encode(value: Any) -> Any:
    if isinstance(value, datetime):
        return {"__reefvision_type__": "datetime", "value": value.isoformat()}
    if isinstance(value, bytes):
        return {
            "__reefvision_type__": "bytes",
            "value": base64.b64encode(value).decode("ascii"),
        }
    if isinstance(value, dict):
        return {str(key): _encode(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_encode(item) for item in value]
    return value


def _decode(value: Any) -> Any:
    if isinstance(value, dict):
        marker = value.get("__reefvision_type__")
        if marker == "datetime":
            return datetime.fromisoformat(str(value["value"]))
        if marker == "bytes":
            return base64.b64decode(str(value["value"]))
        return {key: _decode(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_decode(item) for item in value]
    return value


def _safe_member(name: str) -> bool:
    path = PurePosixPath(name)
    return not path.is_absolute() and ".." not in path.parts and name not in {"", "."}


def _schema_revision(session: Session) -> str | None:
    context = MigrationContext.configure(session.connection())
    return context.get_current_revision()


def _expected_revision() -> str | None:
    alembic_ini, migrations_dir = resolve_alembic_paths()
    config = Config(str(alembic_ini))
    config.attributes["configure_logger"] = False
    config.set_main_option("script_location", str(migrations_dir))
    return ScriptDirectory.from_config(config).get_current_head()


def _schema_signature() -> dict[str, Any]:
    return {
        table.name: {
            "columns": {
                column.name: {
                    "type": str(column.type),
                    "nullable": column.nullable,
                    "primary_key": column.primary_key,
                    "has_default": bool(column.default or column.server_default),
                }
                for column in table.columns
            },
            "primary_key": [column.name for column in table.primary_key.columns],
        }
        for table in Base.metadata.sorted_tables
    }


def _pk_tuple(table: Table, row: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(row[column.name] for column in table.primary_key.columns)


def _row_dict(row: Any) -> dict[str, Any]:
    return dict(row._mapping)


def collect_project_graph(
    session: Session,
    project_id: str,
    *,
    include_archived_records: bool = True,
) -> dict[str, list[dict[str, Any]]]:
    project_table = Base.metadata.tables["projects"]
    project_row = session.execute(
        select(project_table).where(project_table.c.id == project_id)
    ).first()
    if project_row is None:
        raise NotFoundError("Project not found")
    rows: dict[str, list[dict[str, Any]]] = {"projects": [_row_dict(project_row)]}
    keys: dict[str, set[tuple[Any, ...]]] = {
        "projects": {_pk_tuple(project_table, rows["projects"][0])}
    }

    changed = True
    while changed:
        changed = False
        # Pull parent rows referenced by already selected child rows.
        for table_name, table_rows in list(rows.items()):
            table = Base.metadata.tables[table_name]
            for foreign_key in table.foreign_keys:
                parent_table = foreign_key.column.table
                local_column = foreign_key.parent.name
                parent_column = foreign_key.column.name
                values = {
                    item.get(local_column)
                    for item in table_rows
                    if item.get(local_column) is not None
                }
                if not values:
                    continue
                fetched = session.execute(
                    select(parent_table).where(parent_table.c[parent_column].in_(values))
                )
                for raw in fetched:
                    item = _row_dict(raw)
                    if (
                        not include_archived_records
                        and "archived_at" in item
                        and item["archived_at"] is not None
                    ):
                        continue
                    key = _pk_tuple(parent_table, item)
                    if key in keys.setdefault(parent_table.name, set()):
                        continue
                    rows.setdefault(parent_table.name, []).append(item)
                    keys[parent_table.name].add(key)
                    changed = True

        # Pull all descendants that reference a selected row.
        for table in Base.metadata.sorted_tables:
            for foreign_key in table.foreign_keys:
                parent_name = foreign_key.column.table.name
                if parent_name not in rows:
                    continue
                parent_column = foreign_key.column.name
                local_column = foreign_key.parent.name
                parent_values = {
                    item.get(parent_column)
                    for item in rows[parent_name]
                    if item.get(parent_column) is not None
                }
                if not parent_values:
                    continue
                fetched = session.execute(
                    select(table).where(table.c[local_column].in_(parent_values))
                )
                for raw in fetched:
                    item = _row_dict(raw)
                    if (
                        not include_archived_records
                        and "archived_at" in item
                        and item["archived_at"] is not None
                    ):
                        continue
                    key = _pk_tuple(table, item)
                    if key in keys.setdefault(table.name, set()):
                        continue
                    rows.setdefault(table.name, []).append(item)
                    keys[table.name].add(key)
                    changed = True

    for table_name, table_rows in rows.items():
        table = Base.metadata.tables[table_name]
        table_rows.sort(key=lambda item: tuple(str(value) for value in _pk_tuple(table, item)))
    return rows


def _project_storage_root(rows: dict[str, list[dict[str, Any]]]) -> str:
    projects = rows.get("projects", [])
    if len(projects) != 1:
        raise ValidationError("A project archive must contain exactly one project row")
    return str(projects[0]["storage_root"])


def write_project_archive(
    settings: Settings,
    session: Session,
    *,
    project_id: str,
    archive_id: str,
    include_archived_records: bool,
    notes: str | None,
) -> tuple[str, dict[str, Any]]:
    rows = collect_project_graph(
        session,
        project_id,
        include_archived_records=include_archived_records,
    )
    project_row = rows["projects"][0]
    storage_root = _project_storage_root(rows)
    project_root = resolve_managed_project_path(settings, storage_root)
    if not project_root.is_dir():
        raise ValidationError("The managed project directory is missing")

    relative_archive = f"archives/projects/{project_id}/{archive_id}.reefvision-project.zip"
    destination = resolve_managed_project_path(settings, relative_archive)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex[:8]}.tmp")

    records_payload = {
        "source_project_id": project_id,
        "source_storage_root": storage_root,
        "tables": {
            table_name: [_encode(row) for row in table_rows]
            for table_name, table_rows in sorted(rows.items())
        },
    }
    records_bytes = canonical_json_bytes(records_payload)
    files: list[dict[str, Any]] = []
    for path in sorted(project_root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(project_root).as_posix()
        files.append(
            {
                "path": relative,
                "sha256": _sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
        )
    manifest = {
        "format": "reefvision-project-archive",
        "format_version": PROJECT_ARCHIVE_FORMAT_VERSION,
        "application_version": __version__,
        "source_schema_revision": _schema_revision(session),
        "expected_schema_revision": _expected_revision(),
        "created_at": datetime.now(UTC).isoformat(),
        "source_project": {
            "id": project_id,
            "name": project_row["name"],
            "slug": project_row["slug"],
            "storage_root": storage_root,
            "archived_at": (
                project_row["archived_at"].isoformat()
                if project_row.get("archived_at")
                else None
            ),
        },
        "notes": notes,
        "include_archived_records": include_archived_records,
        "schema": _schema_signature(),
        "records": {
            "path": "records.json",
            "sha256": hashlib.sha256(records_bytes).hexdigest(),
            "table_count": len(rows),
            "record_count": sum(len(items) for items in rows.values()),
        },
        "files": files,
        "completion_marker": _COMPLETION_MARKER,
    }
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", canonical_json_bytes(manifest))
            archive.writestr("records.json", records_bytes)
            archive.writestr("COMPLETED", _COMPLETION_MARKER)
            for item in files:
                archive.write(
                    project_root / item["path"],
                    f"files/{item['path']}",
                )
        temporary.replace(destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    result = {
        "archive_path": relative_archive,
        "archive_sha256": _sha256_file(destination),
        "archive_size_bytes": destination.stat().st_size,
        "table_count": manifest["records"]["table_count"],
        "record_count": manifest["records"]["record_count"],
        "file_count": len(files),
        "total_file_bytes": sum(int(item["size_bytes"]) for item in files),
    }
    return relative_archive, result


def resolve_archive_path(settings: Settings, archive_path: str) -> Path:
    candidate = Path(archive_path).expanduser()
    if not candidate.is_absolute():
        candidate = resolve_managed_project_path(settings, archive_path)
    else:
        candidate = candidate.resolve()
    if not candidate.is_file():
        raise NotFoundError("Project archive not found")
    return candidate


def inspect_project_archive(
    settings: Settings,
    archive_path: str,
) -> ProjectArchiveVerificationResponse:
    path = resolve_archive_path(settings, archive_path)
    warnings: list[str] = []
    blockers: list[str] = []
    checksum_failures: list[str] = []
    missing_tables: list[str] = []
    incompatible_columns: list[str] = []
    manifest: dict[str, Any] = {}
    record_count = 0
    table_count = 0
    file_count = 0
    total_file_bytes = 0
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            unsafe = [name for name in names if not _safe_member(name)]
            if unsafe:
                blockers.append("The archive contains unsafe or parent-relative paths")
            for required in ("manifest.json", "records.json", "COMPLETED"):
                if required not in names:
                    blockers.append(f"The archive is missing {required}")
            if blockers:
                raise ValidationError("Archive structure is incomplete")
            manifest = json.loads(archive.read("manifest.json"))
            records_bytes = archive.read("records.json")
            records = json.loads(records_bytes)
            if manifest.get("format") != "reefvision-project-archive":
                blockers.append("The archive format identifier is not recognized")
            if archive.read("COMPLETED").decode("utf-8", errors="replace").strip() != _COMPLETION_MARKER:
                blockers.append("The archive completion marker is invalid")
            expected_records_sha = str(manifest.get("records", {}).get("sha256", ""))
            if hashlib.sha256(records_bytes).hexdigest() != expected_records_sha:
                checksum_failures.append("records.json")
            table_payload = records.get("tables", {})
            if not isinstance(table_payload, dict):
                blockers.append("records.json does not contain a table map")
                table_payload = {}
            table_count = len(table_payload)
            record_count = sum(
                len(items) for items in table_payload.values() if isinstance(items, list)
            )
            current_schema = _schema_signature()
            archived_schema = manifest.get("schema", {})
            if not isinstance(archived_schema, dict):
                archived_schema = {}
            for table_name, table_rows in table_payload.items():
                if table_name not in current_schema:
                    missing_tables.append(str(table_name))
                    continue
                archived_columns = set(
                    (archived_schema.get(table_name) or {}).get("columns", {}).keys()
                )
                if not archived_columns and isinstance(table_rows, list) and table_rows:
                    archived_columns = set(table_rows[0].keys())
                current_columns = set(current_schema[table_name]["columns"])
                for column in sorted(archived_columns - current_columns):
                    incompatible_columns.append(f"{table_name}.{column}")
                for column, metadata in current_schema[table_name]["columns"].items():
                    if (
                        column not in archived_columns
                        and not metadata["nullable"]
                        and not metadata["primary_key"]
                        and not metadata["has_default"]
                    ):
                        incompatible_columns.append(
                            f"{table_name}.{column} (required by current schema)"
                        )
            for item in manifest.get("files", []):
                if not isinstance(item, dict):
                    continue
                relative = str(item.get("path", ""))
                member = f"files/{relative}"
                file_count += 1
                total_file_bytes += int(item.get("size_bytes", 0))
                if member not in names:
                    checksum_failures.append(relative)
                    continue
                digest = hashlib.sha256(archive.read(member)).hexdigest()
                if digest != str(item.get("sha256", "")):
                    checksum_failures.append(relative)
    except (zipfile.BadZipFile, json.JSONDecodeError, KeyError, ValidationError) as exc:
        if not blockers:
            blockers.append(f"The archive could not be read: {exc}")

    if missing_tables:
        blockers.append("The current ReefVision schema does not contain every archived table")
    if incompatible_columns:
        blockers.append("The archive schema is incompatible with the current database schema")
    if checksum_failures:
        blockers.append("One or more archive checksums failed")
    source_revision = manifest.get("source_schema_revision")
    current_revision = _expected_revision()
    if source_revision and current_revision and source_revision != current_revision:
        warnings.append(
            f"Archive schema revision {source_revision} differs from current head {current_revision}; compatibility was checked column by column."
        )
    source_project = manifest.get("source_project") or {}
    return ProjectArchiveVerificationResponse(
        archive_path=str(path),
        valid=not blockers,
        format_version=(str(manifest.get("format_version")) if manifest else None),
        application_version=(str(manifest.get("application_version")) if manifest else None),
        source_schema_revision=(str(source_revision) if source_revision else None),
        source_project_id=(
            str(source_project.get("id")) if source_project.get("id") else None
        ),
        source_project_name=(
            str(source_project.get("name")) if source_project.get("name") else None
        ),
        table_count=table_count,
        record_count=record_count,
        file_count=file_count,
        total_file_bytes=total_file_bytes,
        missing_tables=missing_tables,
        incompatible_columns=incompatible_columns,
        checksum_failures=checksum_failures,
        warnings=warnings,
        blockers=blockers,
    )


def _unique_slug(session: Session, requested: str) -> str:
    from reefvision.services.projects import slugify

    base = slugify(requested)
    candidate = base
    suffix = 2
    projects = Base.metadata.tables["projects"]
    while session.scalar(select(projects.c.id).where(projects.c.slug == candidate)):
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


def _recursive_remap(value: Any, value_map: dict[str, str], old_root: str, new_root: str) -> Any:
    if isinstance(value, str):
        if value in value_map:
            return value_map[value]
        if value == old_root or value.startswith(f"{old_root}/"):
            return f"{new_root}{value[len(old_root):]}"
        return value
    if isinstance(value, list):
        return [_recursive_remap(item, value_map, old_root, new_root) for item in value]
    if isinstance(value, dict):
        return {
            str(_recursive_remap(key, value_map, old_root, new_root)): _recursive_remap(
                item, value_map, old_root, new_root
            )
            for key, item in value.items()
        }
    return value


def _single_pk(table: Table) -> Any | None:
    columns = list(table.primary_key.columns)
    return columns[0] if len(columns) == 1 else None


def _build_id_maps(
    session: Session,
    rows: dict[str, list[dict[str, Any]]],
) -> tuple[dict[tuple[str, str, Any], Any], dict[str, str]]:
    field_map: dict[tuple[str, str, Any], Any] = {}
    string_map: dict[str, str] = {}
    integer_next: dict[str, int] = {}
    for table_name, table_rows in rows.items():
        table = Base.metadata.tables[table_name]
        pk = _single_pk(table)
        if pk is None:
            continue
        for row in table_rows:
            old = row.get(pk.name)
            if old is None:
                continue
            try:
                python_type = pk.type.python_type
            except NotImplementedError:
                python_type = type(old)
            if python_type is str:
                new: Any = str(uuid4())
                string_map[str(old)] = str(new)
            elif python_type is int:
                if table_name not in integer_next:
                    maximum = session.scalar(select(func.max(pk))) or 0
                    integer_next[table_name] = int(maximum) + 1
                new = integer_next[table_name]
                integer_next[table_name] += 1
            else:
                new = old
            field_map[(table_name, pk.name, old)] = new
    return field_map, string_map


def _remap_rows(
    session: Session,
    rows: dict[str, list[dict[str, Any]]],
    *,
    old_root: str,
    new_root: str,
    new_project_id: str,
    new_name: str,
    new_slug: str,
    restore_as_active: bool,
) -> dict[str, list[dict[str, Any]]]:
    field_map, string_map = _build_id_maps(session, rows)
    old_project_id = str(rows["projects"][0]["id"])
    string_map[old_project_id] = new_project_id
    field_map[("projects", "id", old_project_id)] = new_project_id
    transformed: dict[str, list[dict[str, Any]]] = {}
    for table_name, table_rows in rows.items():
        table = Base.metadata.tables[table_name]
        output: list[dict[str, Any]] = []
        for source_row in table_rows:
            row = {
                column.name: _recursive_remap(
                    source_row.get(column.name),
                    string_map,
                    old_root,
                    new_root,
                )
                for column in table.columns
                if column.name in source_row
            }
            for pk in table.primary_key.columns:
                old_value = source_row.get(pk.name)
                key = (table_name, pk.name, old_value)
                if key in field_map:
                    row[pk.name] = field_map[key]
            for foreign_key in table.foreign_keys:
                old_value = source_row.get(foreign_key.parent.name)
                key = (
                    foreign_key.column.table.name,
                    foreign_key.column.name,
                    old_value,
                )
                if key in field_map:
                    row[foreign_key.parent.name] = field_map[key]
            if table_name == "projects":
                row.update(
                    {
                        "id": new_project_id,
                        "name": new_name,
                        "slug": new_slug,
                        "storage_root": new_root,
                        "archived_at": None if restore_as_active else row.get("archived_at"),
                        "updated_at": datetime.now(UTC),
                    }
                )
            output.append(row)
        transformed[table_name] = output
    _repair_known_checksums(transformed, new_project_id, new_name, new_slug)
    return transformed


def _dataset_item_payload(row: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "image_id": row.get("image_id"),
        "image_sha256": row.get("image_sha256"),
        "original_filename": row.get("original_filename"),
        "width_px": row.get("width_px"),
        "height_px": row.get("height_px"),
        "annotation_status": row.get("image_annotation_status"),
        "split": row.get("split"),
        "group_key": row.get("group_key"),
        "annotation_count": row.get("annotation_count", 0),
        "per_class_counts": row.get("per_class_counts_json", {}),
        "annotations": row.get("annotation_snapshot_json", []),
    }
    if "mask_annotation_count" in row:
        payload["mask_annotation_count"] = row.get("mask_annotation_count", 0)
        payload["per_mask_class_counts"] = row.get("per_mask_class_counts_json", {})
        payload["mask_annotations"] = row.get("mask_annotation_snapshot_json", [])
    return payload


def _repair_known_checksums(
    rows: dict[str, list[dict[str, Any]]],
    project_id: str,
    project_name: str,
    project_slug: str,
) -> None:
    item_sha_by_image: dict[tuple[str, str], str] = {}
    for item in rows.get("dataset_version_items", []):
        item["snapshot_sha256"] = canonical_json_sha256(_dataset_item_payload(item))
        item_sha_by_image[(str(item.get("dataset_version_id")), str(item.get("image_id")))] = str(
            item["snapshot_sha256"]
        )
    for version in rows.get("dataset_versions", []):
        manifest = version.get("manifest_json")
        if not isinstance(manifest, dict):
            continue
        project = manifest.get("project")
        if isinstance(project, dict):
            project.update({"id": project_id, "name": project_name, "slug": project_slug})
        version_payload = manifest.get("dataset_version")
        if isinstance(version_payload, dict):
            version_payload["id"] = version.get("id")
            version_payload["parent_version_id"] = version.get("parent_version_id")
        for item in manifest.get("items", []) if isinstance(manifest.get("items"), list) else []:
            if not isinstance(item, dict):
                continue
            key = (str(version.get("id")), str(item.get("image_id")))
            if key in item_sha_by_image:
                item["snapshot_sha256"] = item_sha_by_image[key]
        version["manifest_sha256"] = canonical_json_sha256(manifest)
    for revision in rows.get("workflow_revisions", []):
        workflow = revision.get("workflow_json")
        if isinstance(workflow, dict):
            revision["workflow_checksum"] = canonical_json_sha256(workflow)


def _self_reference_order(table: Table, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    self_foreign_keys = [
        foreign_key
        for foreign_key in table.foreign_keys
        if foreign_key.column.table.name == table.name
    ]
    if not self_foreign_keys:
        return rows
    pending = list(rows)
    output: list[dict[str, Any]] = []
    emitted: set[tuple[Any, ...]] = set()
    while pending:
        progress = False
        for row in list(pending):
            ready = True
            for foreign_key in self_foreign_keys:
                value = row.get(foreign_key.parent.name)
                if value is None:
                    continue
                parent_key = tuple(
                    value if column.name == foreign_key.column.name else row.get(column.name)
                    for column in table.primary_key.columns
                )
                if parent_key not in emitted and any(
                    candidate.get(foreign_key.column.name) == value for candidate in pending
                ):
                    ready = False
                    break
            if ready:
                output.append(row)
                emitted.add(_pk_tuple(table, row))
                pending.remove(row)
                progress = True
        if not progress:
            output.extend(pending)
            break
    return output


def import_project_archive(
    settings: Settings,
    factory: sessionmaker[Session],
    *,
    archive_path: str,
    name: str | None,
    slug: str | None,
    restore_as_active: bool,
) -> dict[str, Any]:
    verification = inspect_project_archive(settings, archive_path)
    if not verification.valid:
        raise ValidationError("Project archive verification failed: " + "; ".join(verification.blockers))
    path = resolve_archive_path(settings, archive_path)
    with zipfile.ZipFile(path) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        records_payload = _decode(json.loads(archive.read("records.json")))
        rows = {
            str(table_name): [dict(item) for item in table_rows]
            for table_name, table_rows in records_payload["tables"].items()
        }
        source_project = rows["projects"][0]
        old_root = str(source_project["storage_root"])
        new_project_id = str(uuid4())
        with factory() as session:
            new_name = name or f"{source_project['name']} (Imported)"
            new_slug = _unique_slug(session, slug or new_name)
            new_root = f"projects/{new_project_id}"
            transformed = _remap_rows(
                session,
                rows,
                old_root=old_root,
                new_root=new_root,
                new_project_id=new_project_id,
                new_name=new_name,
                new_slug=new_slug,
                restore_as_active=restore_as_active,
            )

            destination = resolve_managed_project_path(settings, new_root)
            temporary = destination.with_name(f".{destination.name}.{uuid4().hex[:8]}.tmp")
            if destination.exists() or temporary.exists():
                raise ConflictError("The destination project directory already exists")
            temporary.mkdir(parents=True, exist_ok=False)
            try:
                for file_item in manifest.get("files", []):
                    relative = str(file_item["path"])
                    if not _safe_member(relative):
                        raise ValidationError("The archive contains an unsafe project file path")
                    target = temporary / PurePosixPath(relative)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(f"files/{relative}") as source, target.open("wb") as output:
                        shutil.copyfileobj(source, output)
                    if _sha256_file(target) != str(file_item["sha256"]):
                        raise ValidationError(f"Checksum verification failed while extracting {relative}")
                temporary.replace(destination)
                for table in Base.metadata.sorted_tables:
                    table_rows = transformed.get(table.name, [])
                    if not table_rows:
                        continue
                    ordered = _self_reference_order(table, table_rows)
                    session.execute(table.insert(), ordered)
                session.commit()
            except Exception:
                session.rollback()
                shutil.rmtree(temporary, ignore_errors=True)
                shutil.rmtree(destination, ignore_errors=True)
                raise
    return {
        "project_id": new_project_id,
        "project_name": new_name,
        "project_slug": new_slug,
        "storage_root": new_root,
        "source_project_id": verification.source_project_id,
        "record_count": verification.record_count,
        "file_count": verification.file_count,
        "warnings": verification.warnings,
    }


def migrate_project_storage(
    settings: Settings,
    session: Session,
    *,
    project_id: str,
    destination_relative_path: str,
    mode: str,
) -> dict[str, Any]:
    rows = collect_project_graph(session, project_id)
    project = rows["projects"][0]
    old_root = str(project["storage_root"])
    new_root = destination_relative_path.strip().replace("\\", "/").strip("/")
    if not new_root:
        raise ValidationError("A destination relative path is required")
    source = resolve_managed_project_path(settings, old_root)
    destination = resolve_managed_project_path(settings, new_root)
    if destination.exists():
        raise ConflictError("The destination project directory already exists")
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex[:8]}.tmp")
    temporary.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, temporary)
    temporary.replace(destination)
    try:
        for table_name, table_rows in rows.items():
            table = Base.metadata.tables[table_name]
            for source_row in table_rows:
                changes: dict[str, Any] = {}
                for column in table.columns:
                    if column.name not in source_row:
                        continue
                    replaced = _recursive_remap(source_row[column.name], {}, old_root, new_root)
                    if replaced != source_row[column.name]:
                        changes[column.name] = replaced
                if not changes:
                    continue
                condition = [
                    table.c[column.name] == source_row[column.name]
                    for column in table.primary_key.columns
                ]
                session.execute(table.update().where(*condition).values(**changes))
        session.commit()
    except Exception:
        session.rollback()
        shutil.rmtree(destination, ignore_errors=True)
        raise
    if mode == "move":
        shutil.rmtree(source, ignore_errors=True)
    return {
        "project_id": project_id,
        "old_storage_root": old_root,
        "new_storage_root": new_root,
        "mode": mode,
    }
