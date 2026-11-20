"""Verify authentic historical controls with administratively extracted MSI sidecars."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
from contextlib import closing, contextmanager
from pathlib import Path, PurePosixPath
from time import monotonic, sleep
from typing import Any

import httpx
import psutil
from create_windows_qc_history_controls import (
    DATABASE,
    HISTORIES,
    MARKER,
    call_historical,
    checked,
    isolated_environment,
    receipt,
    sha256,
    verify_original_api,
)

CURRENT_VERSION = "1.7.0"
CURRENT = "b17_monitor_0003"
PREVIOUS = "b15_integrated_0002"


def digest(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def sorted_rows(rows: list[tuple[Any, ...]]) -> list[str]:
    return sorted(json.dumps(row, default=lambda value: {"blob": value.hex()}) for row in rows)


def identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def database(path: Path) -> sqlite3.Connection:
    if not path.is_file() or any(path.parent.glob(path.name + "-*")):
        raise RuntimeError(f"Expected a closed SQLite snapshot at {path}")
    return sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)


def inspect_database(
    path: Path,
    previous: dict[str, Any] | None = None,
    *,
    new_job_id: str | None = None,
    new_backup_id: str | None = None,
) -> tuple[str, dict[str, Any]]:
    with closing(database(path)) as db:
        assert db.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        assert not db.execute("PRAGMA foreign_key_check").fetchall()
        [(head,)] = db.execute("SELECT version_num FROM alembic_version")
        tables = (
            previous
            if previous is not None
            else [
                name
                for (name,) in db.execute(
                    "SELECT name FROM sqlite_schema WHERE type='table' "
                    "AND name NOT GLOB 'sqlite_*' AND name != 'alembic_version' ORDER BY name"
                )
            ]
        )
        result = {}
        for table in tables:
            name = identifier(table)
            recorded = [row[1] for row in db.execute(f"PRAGMA table_info({name})")]
            fields = previous[table]["columns"] if previous is not None else recorded
            assert set(fields) <= set(recorded), table
            query = ",".join(map(identifier, fields))
            new_record = {"jobs": new_job_id, "backup_records": new_backup_id}.get(table)
            if new_record is None:
                rows = db.execute(f"SELECT {query} FROM {name}").fetchall()
            else:
                rows = db.execute(
                    f"SELECT {query} FROM {name} WHERE id != ?", (new_record,)
                ).fetchall()
            result[table] = {
                "columns": fields,
                "rows": len(rows),
                "sha256": digest(sorted_rows(rows)),
            }
            if table == "review_queue_item_events":
                order = db.execute(f"SELECT id FROM {name} ORDER BY rowid").fetchall()
                result[table]["event_order_sha256"] = digest(order)
        return head, result


def media(profile: Path) -> dict[str, tuple[int, str]]:
    assets = {}
    for path in sorted((profile / "projects").rglob("*")):
        if path.is_symlink() or path.is_junction():
            raise RuntimeError(f"Unexpected link in generated data: {path}")
        if path.is_file():
            assets[path.relative_to(profile).as_posix()] = (path.stat().st_size, sha256(path))
    return assets


def protected(profile: Path) -> tuple[str, str, dict[str, tuple[int, str]]]:
    return sha256(profile / DATABASE), sha256(profile / MARKER), media(profile)


def new_copy(source: Path, target: Path) -> None:
    assert (source / MARKER).is_file()
    expected = protected(source)
    shutil.copytree(source, target)
    assert protected(target) == expected


def managed(root: Path, relative: str) -> Path:
    parts = PurePosixPath(relative)
    path = (root / parts).resolve(strict=True)
    if parts.is_absolute() or not path.is_relative_to(root.resolve(strict=True)):
        raise RuntimeError("The reported managed path escapes the disposable profile")
    return path


def packaged_environment(profile: Path) -> dict[str, str]:
    env = isolated_environment(profile)
    system = Path(os.environ["SYSTEMROOT"])
    return {
        **env,
        "PATH": os.pathsep.join(str(system / part) for part in ("System32", "", "System32/Wbem")),
        "REEFVISION_CONFIG_DIR": str(profile / "config"),
    }


@contextmanager
def sidecar(executable: Path, profile: Path, logs: Path, label: str, *, safe: bool = True):
    if not (profile / MARKER).is_file():
        raise RuntimeError(f"Refusing unmarked profile {profile}")
    note = logs / f"{label}.log"
    endpoint = logs / f"{label}.port"
    arguments = [
        str(executable),
        "--host",
        "127.0.0.1",
        "--port",
        "0",
        "--data-dir",
        str(profile),
        "--context-file",
        str(endpoint),
        "--log-file",
        str(note),
    ]
    if safe:
        arguments.append("--safe-mode")
    with (
        (logs / f"{label}-output.log").open("wb") as output,
        subprocess.Popen(
            arguments,
            cwd=executable.parent,
            env=packaged_environment(profile),
            stdin=subprocess.PIPE,
            stdout=output,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW,
        ) as process,
    ):
        try:
            yield process, endpoint, note, profile
        finally:
            if process.poll() is None:
                try:
                    assert process.stdin is not None
                    process.stdin.write(b"shutdown\n")
                    process.stdin.flush()
                    process.wait(timeout=25)
                except (BrokenPipeError, subprocess.TimeoutExpired):
                    process.terminate()
                    process.wait(timeout=10)
                    raise


def validate_listener_owner(port: int, process: subprocess.Popen) -> None:
    listeners = [
        row.pid
        for row in psutil.net_connections(kind="tcp4")
        if row.status == psutil.CONN_LISTEN and row.laddr == ("127.0.0.1", port)
    ]
    if len(listeners) != 1 or (owner := listeners[0]) is None:
        raise RuntimeError(f"Expected one loopback listener with a known owner on 127.0.0.1:{port}")
    try:
        parent = psutil.Process(owner).ppid() if owner != process.pid else process.pid
    except (psutil.NoSuchProcess, psutil.AccessDenied) as error:
        raise RuntimeError(f"Could not verify PID {owner} owning 127.0.0.1:{port}") from error
    if process.poll() is not None or parent != process.pid:
        raise RuntimeError(
            f"127.0.0.1:{port} does not belong to the launched sidecar PID {process.pid}"
        )


@contextmanager
def ready(
    process: subprocess.Popen, endpoint: Path, log: Path, profile: Path, *, version: str, head: str
):
    deadline = monotonic() + 65
    while not endpoint.is_file() and process.poll() is None and monotonic() < deadline:
        sleep(0.2)
    if not endpoint.is_file():
        raise RuntimeError(f"Expected loopback API startup; process={process.poll()}, log={log}")
    port = int(endpoint.read_text().strip())
    assert 0 < port < 65536
    validate_listener_owner(port, process)
    with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=8, trust_env=False) as api:
        while True:
            try:
                assert checked(api.get("/api/v1/health"))["version"] == version
                break
            except httpx.TransportError:
                if process.poll() is not None or monotonic() >= deadline:
                    raise
                sleep(0.2)
        system = checked(api.get("/api/v1/system/version"))
        assert system["application_version"] == version
        assert system["current_schema_revision"] == head
        assert Path(system["data_dir"]).resolve() == profile.resolve()
        assert Path(system["database_path"]).resolve() == (profile / DATABASE).resolve()
        yield api


def assert_refusal(
    executable: Path, profile: Path, logs: Path, name: str, revision: str
) -> dict[str, str]:
    before = protected(profile)
    with sidecar(executable, profile, logs, name) as (process, endpoint, log, _):
        assert process.wait(timeout=65) == 1 and not endpoint.exists(), log
    text = log.read_text(encoding="utf-8")
    if revision == CURRENT:
        expected = "can't locate revision identified by"
    elif name == "ambiguous-0038":
        expected = "preserve the original"
    else:
        expected = "cannot determine migration lineage"
    assert revision in text and expected in text.lower(), log
    assert before == protected(profile), name
    assert not list(profile.glob(DATABASE + "-*"))
    return {"database_before_and_after_sha256": before[0], "log_sha256": sha256(log)}


def wait_job(api: httpx.Client, job_id: str) -> dict[str, Any]:
    deadline = monotonic() + 120
    while monotonic() < deadline:
        job = checked(api.get(f"/api/v1/jobs/{job_id}"))
        if job["status"] == "succeeded":
            return job["result_json"]
        if job["status"] not in {"queued", "running"}:
            raise RuntimeError(f"Job {job_id} ended as {job['status']}: {job['error_message']}")
        sleep(0.25)
    raise RuntimeError(f"Job {job_id} did not finish within 120 seconds")


def backup_and_restore(api: httpx.Client, profile: Path) -> tuple[Path, dict[str, Any]]:
    created = checked(
        api.post("/api/v1/backups", json={"notes": "Generated historical QC acceptance"}), 201
    )
    backup = created["backup"]
    wait_job(api, created["job"]["id"])
    route = f"/api/v1/backups/{backup['id']}"
    verified = checked(api.post(route + "/verify"))
    assert verified["status"] == "valid" and verified["completion_marker_present"]
    assert verified["current_schema_revision"] == CURRENT and not verified["errors"]
    restore = checked(api.post(route + "/restore", json={"destination_name": "history-copy"}))
    assert restore["verification_status"] == "valid"
    result = wait_job(api, restore["job"]["id"])
    assert result["restored_file_count"] == verified["file_count"]
    assert result["restored_total_size_bytes"] == verified["total_size_bytes"]
    target = managed(profile, restore["destination_path"])
    snapshot = managed(profile, backup["destination_path"])
    manifest_path = managed(profile, backup["manifest_path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert len(manifest["file_inventory"]) == verified["file_count"]
    for entry in manifest["file_inventory"]:
        member = managed(snapshot, entry["path"])
        copied = managed(target, entry["path"].split("/", 1)[1])
        assert member.stat().st_size == copied.stat().st_size == entry["size_bytes"]
        assert sha256(member) == sha256(copied) == entry["sha256"]
    return target, {
        "backup_id": backup["id"],
        "backup_job_id": created["job"]["id"],
        "restore_job_id": restore["job"]["id"],
        "manifest_sha256": sha256(manifest_path),
        "files": verified["file_count"],
        "bytes": verified["total_size_bytes"],
        "restored_database_sha256": sha256(target / DATABASE),
    }


def backfill_ambiguity(root: Path, candidate: Path, logs: Path) -> dict[str, str]:
    # The colliding numeric 0038 contains both original table signatures.
    # Neither history may be guessed even though SQLite can read the file.
    ambiguous = root / "ambiguous"
    new_copy(root / "donors" / "qc38", ambiguous)
    with closing(database(root / "donors" / "science38" / DATABASE)) as science:
        ddl = science.execute(
            "SELECT sql FROM sqlite_schema WHERE tbl_name IN "
            "('scientific_records', 'environmental_cache_entries') "
            "AND sql IS NOT NULL ORDER BY type DESC"
        ).fetchall()
    assert len(ddl) >= 2
    with closing(sqlite3.connect(ambiguous / DATABASE)) as connection, connection:
        for (sql,) in ddl:
            connection.execute(sql)
    return assert_refusal(candidate, ambiguous, logs, "ambiguous-0038", "0038")


def exercise(
    root: Path, logs: Path, history: str, candidate: Path, previous: Path
) -> dict[str, Any]:
    donor = root / "donors" / history
    metadata = root / f"{history}.json"
    ref = json.loads(metadata.read_text(encoding="utf-8"))
    expected, commit = HISTORIES[history]
    baseline = protected(donor)
    assert ref["source_commit"] == commit and ref["database_sha256"] == baseline[0]
    registration = ref["registration"]
    if registration:
        assert baseline[2][registration["managed_path"]] == (
            registration["file_size_bytes"],
            registration["sha256"],
        )
    stamp, fingerprints = inspect_database(donor / DATABASE)
    assert stamp == expected
    before_upgrade = root / "pre" / history
    updated = root / "trial" / history
    new_copy(donor, before_upgrade)
    new_copy(before_upgrade, updated)
    prior = root / "older" / history
    new_copy(before_upgrade, prior)
    if history == "science38":
        with (
            sidecar(previous, prior, logs, f"{history}-previous-positive") as launched,
            ready(*launched, version="1.5.0", head=PREVIOUS) as api,
        ):
            verify_original_api(api, history, ref)
        assert inspect_database(prior / DATABASE, fingerprints) == (PREVIOUS, fingerprints)
        previous_control: dict[str, Any] = {"opened_scientific_0038": True}
    else:
        previous_control = assert_refusal(
            previous, prior, logs, f"{history}-previous-historical-refusal", stamp
        )
    with (
        sidecar(candidate, updated, logs, f"{history}-upgrade") as launched,
        ready(*launched, version=CURRENT_VERSION, head=CURRENT) as api,
    ):
        verify_original_api(api, history, ref)
    assert inspect_database(updated / DATABASE, fingerprints) == (CURRENT, fingerprints)
    assert media(updated) == baseline[2]
    upgraded_sha = sha256(updated / DATABASE)
    with (
        sidecar(candidate, updated, logs, f"{history}-reopen") as launched,
        ready(*launched, version=CURRENT_VERSION, head=CURRENT) as api,
    ):
        verify_original_api(api, history, ref)
    assert sha256(updated / DATABASE) == upgraded_sha

    with (
        sidecar(candidate, updated, logs, f"{history}-backup-restore", safe=False) as launched,
        ready(*launched, version=CURRENT_VERSION, head=CURRENT) as api,
    ):
        restored, backup = backup_and_restore(api, updated)
    assert media(restored) == baseline[2]
    assert inspect_database(
        restored / DATABASE,
        fingerprints,
        new_job_id=backup["backup_job_id"],
        new_backup_id=backup["backup_id"],
    ) == (CURRENT, fingerprints)
    # The runtime reads an independently marked recovery copy. The exact
    # verification snapshot above remains unchanged in its managed location.
    if not (restored / MARKER).is_file():
        shutil.copyfile(donor / MARKER, restored / MARKER)
    rejected_copy = root / "reject" / history
    new_copy(restored, rejected_copy)
    refusal = assert_refusal(
        previous, rejected_copy, logs, f"{history}-older-reader-newer-refusal", CURRENT
    )
    with (
        sidecar(candidate, restored, logs, f"{history}-open-recovery") as launched,
        ready(*launched, version=CURRENT_VERSION, head=CURRENT) as api,
    ):
        verify_original_api(api, history, ref)
    assert sha256(restored / DATABASE) == backup["restored_database_sha256"]

    rollback = root / "rollback" / history
    new_copy(before_upgrade, rollback)
    call_historical(history, root / "src" / history, rollback, metadata, reopen=True)
    assert protected(rollback) == protected(before_upgrade) == protected(donor) == baseline
    assert inspect_database(rollback / DATABASE) == (expected, fingerprints)
    bindings = {
        key: ref[key]
        for key in (
            "project_id",
            "label_id",
            "annotation_id",
            "source_image",
            "scientific_id",
            "scientific_sha256",
            "queue_id",
            "item_id",
            "graph_id",
            "workflow_run_id",
            "workflow_job_id",
            "workflow_payload_sha256",
            "bulk_start",
            "bulk_complete",
            "bulk_selected",
            "rejected_bulk",
        )
        if key in ref
    }
    return {
        "historical_source_commit": commit,
        "before_schema": expected,
        "current_schema": CURRENT,
        "original_db_sha256": baseline[0],
        "upgraded_db_sha256": upgraded_sha,
        "protected_files": len(baseline[2]),
        "protected_media_inventory_sha256": digest(baseline[2]),
        "protected_prior_table_count": len(fingerprints),
        "all_prior_tables_sha256": digest(fingerprints),
        "generated_identity_bindings": bindings,
        "nonempty_prior_tables": {
            key: {field: data for field, data in value.items() if field != "columns"}
            for key, value in fingerprints.items()
            if value["rows"]
        },
        "registration": (
            {
                "sha256": ref["registration"]["sha256"],
                "bytes": ref["registration"]["file_size_bytes"],
            }
            if ref["registration"]
            else None
        ),
        "prior_media_and_rows_preserved": True,
        "second_open_byte_identical": True,
        "previous_reader_control": previous_control,
        "previous_reader_newer_refusal": refusal,
        "verified_new_location_backup_restore": backup,
        "original_reader_rollback_reopened": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("previous", type=Path)
    parser.add_argument("evidence", type=Path)
    args = parser.parse_args()
    root, candidate, previous, evidence = (
        arg.resolve(strict=True)
        for arg in (args.fixture, args.candidate, args.previous, args.evidence)
    )
    assert (root / MARKER).is_file() and candidate.name == previous.name == "reefvision-api.exe"
    summary: dict[str, Any] = {
        "surface": "administratively_extracted_windows_msi_sidecars",
        "candidate_sidecar_sha256": sha256(candidate),
        "previous_sidecar_sha256": sha256(previous),
        "controls": {},
    }
    for history in HISTORIES:
        summary["controls"][history] = exercise(root, evidence, history, candidate, previous)
        receipt(evidence / "qc-history-report.json", summary)
        print(f"Preserved and recovered {history}; verified original reader rollback", flush=True)
    summary["ambiguous_refusal"] = backfill_ambiguity(root, candidate, evidence)
    receipt(evidence / "qc-history-report.json", summary)


if __name__ == "__main__":
    main()
