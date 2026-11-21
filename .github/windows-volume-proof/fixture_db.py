"""Check the active SQLite journal or read the final database on the dedicated fixture alone."""

import argparse
import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from sqlite_preflight import prepare_for_capacity_pressure

parser = argparse.ArgumentParser()
parser.add_argument("mode", choices=("checkpoint", "receipt"))
parser.add_argument("profile", type=Path)
parser.add_argument("owned_volume", type=Path)
parser.add_argument("output", type=Path)
args = parser.parse_args()
profile = args.profile.resolve()
root = args.owned_volume.resolve()
assert profile.parent == root and root.anchor != args.output.resolve().anchor
assert (root / ".reefvision-volume-owner").is_file()
assert (profile / ".reefvision-clean-install-acceptance").is_file()
database = profile / "reefvision.db"
assert database.is_file() and database.resolve() == database

if args.mode == "checkpoint":
    result = prepare_for_capacity_pressure(database)
else:
    wal = database.with_suffix(".db-wal")
    wal_bytes = wal.stat().st_size if wal.exists() else 0
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as conn:
        rows = conn.execute(
            "SELECT id, annotation_revision, sha256, managed_path FROM images"
        ).fetchall()
        assert len(rows) == 1
        image_id, revision, source_sha, managed = rows[0]
        media = (profile / managed).resolve()
        assert media.is_relative_to(profile)
        with media.open("rb") as source:
            assert hashlib.file_digest(source, "sha256").hexdigest() == source_sha
        (boxes,) = conn.execute(
            "SELECT COUNT(*) FROM annotations WHERE deleted_at IS NULL"
        ).fetchone()
        events = conn.execute(
            "SELECT event_type, COUNT(*) FROM annotation_events GROUP BY event_type"
        ).fetchall()
        assert revision == 2 and boxes == 192 and events == [("created", 192)]
    result = {"image_id": image_id, "annotation_revision": revision, "annotations": boxes,
              "created_events": events[0][1], "original_sha256": source_sha, "wal_bytes": wal_bytes}
args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
