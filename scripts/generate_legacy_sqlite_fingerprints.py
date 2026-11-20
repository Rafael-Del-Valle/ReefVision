"""Rebuild the numeric lineage fingerprints using the preserved Alembic migrations."""

import argparse
from pathlib import Path

from alembic.config import Config
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine

from reefvision.db.legacy_sqlite_schema import digest, sqlite_table_signatures

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "apps" / "api"
TARGET = API / "reefvision" / "db" / "legacy_sqlite_fingerprints.py"
FAMILIES = {
    "": (38, 42),
    "reefpose_": (38, 44),
    "spatial_": (38, 39),
    "reviewq_": (38, 41),
    "b12_identity_": (1, 5),
}


def fingerprint_line(indent: str, name: str, value: str) -> str:
    line = f'{indent}"{name}": "{value}",'
    if len(line) <= 100:
        return line
    return f'{indent}"{name}": (\n{indent}    "{value}"\n{indent}),'


def generate() -> str:
    config = Config(str(API / "alembic.ini"))
    config.set_main_option("script_location", str(API / "migrations"))
    scripts = ScriptDirectory.from_config(config)
    changes = {}
    baseline = {}
    for prefix, (first, last) in FAMILIES.items():
        engine = create_engine("sqlite://")
        try:
            with (
                engine.begin() as connection,
                Operations.context(MigrationContext.configure(connection)),
            ):
                for step in reversed(list(scripts.iterate_revisions("0037", "base"))):
                    step.module.upgrade()
                baseline = sqlite_table_signatures(connection)
                previous = baseline
                for index in range(first, last + 1):
                    revision = f"{prefix}{index:04}"
                    step = scripts.get_revision(revision)
                    assert step is not None
                    step.module.upgrade()
                    current = sqlite_table_signatures(connection)
                    assert not previous.keys() - current.keys()
                    changes[revision] = {k: v for k, v in current.items() if previous.get(k) != v}
                    previous = current
        finally:
            engine.dispose()
    varied = set().union(*(set(fields) for fields in changes.values()))
    stable = {k: v for k, v in baseline.items() if k not in varied}
    base_variable = {k: v for k, v in baseline.items() if k in varied}
    lines = [
        '"""SQLite contracts derived by scripts/generate_legacy_sqlite_fingerprints.py."""',
        "",
        f'COMMON_SHA256 = "{digest(stable)}"',
        "BASE_VARIABLE_TABLES = {",
        *(fingerprint_line("    ", k, v) for k, v in sorted(base_variable.items())),
        "}",
        "REVISION_CHANGES = {",
    ]
    for revision, fields in changes.items():
        lines.append(f'    "{revision}": {{')
        lines.extend(fingerprint_line("        ", k, v) for k, v in sorted(fields.items()))
        lines.append("    },")
    return "\n".join([*lines, "}", ""])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    source = generate()
    if args.check:
        if source != TARGET.read_text(encoding="utf-8"):
            raise SystemExit("Historical SQLite fingerprints differ from the preserved migrations")
    else:
        TARGET.write_text(source, encoding="utf-8", newline="\n")
