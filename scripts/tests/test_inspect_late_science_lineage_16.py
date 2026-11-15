"""Read-only 1.1 environmental science migration lineage CLI regressions."""

import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "inspect-alembic-lineage.py"
SCIENCE_EXTENSIONS = (
    "environmental_event_definitions",
    "environmental_analysis_definitions",
    "environmental_analysis_results",
)


class LateScienceLineageInventoryTests(unittest.TestCase):
    def test_interrupted_0040_0042_science_never_authorizes_upgrade(self) -> None:
        for table in SCIENCE_EXTENSIONS:
            for revision in ("0037", "0040"):
                with self.subTest(table=table, revision=revision):
                    with tempfile.TemporaryDirectory() as directory:
                        database = Path(directory) / "research.sqlite"
                        with sqlite3.connect(database) as connection:
                            connection.execute(
                                "CREATE TABLE alembic_version "
                                "(version_num TEXT NOT NULL PRIMARY KEY)"
                            )
                            connection.execute(
                                "INSERT INTO alembic_version VALUES (?)", (revision,)
                            )
                            connection.execute(
                                "CREATE TABLE biological_observation (note TEXT)"
                            )
                            connection.execute(
                                "INSERT INTO biological_observation VALUES "
                                "('private coral observation')"
                            )
                            connection.execute(
                                f"CREATE TABLE {table} (id TEXT PRIMARY KEY)"
                            )
                            connection.execute(
                                f"INSERT INTO {table} VALUES ('preserve')"
                            )
                        original = database.read_bytes()
                        result = subprocess.run(
                            [
                                sys.executable,
                                str(SCRIPT),
                                "--fail-on-warning",
                                str(database),
                            ],
                            capture_output=True,
                            text=True,
                            check=False,
                        )
                        self.assertEqual(result.returncode, 2, result.stderr)
                        report = json.loads(result.stdout)
                        self.assertFalse(report["upgrade_authorized"])
                        self.assertEqual(report["lineage_hint"], "scientific")
                        self.assertIn(
                            "scientific_extension_without_base_lineage",
                            report["warnings"],
                        )
                        self.assertEqual(report["inventory"][table]["rows"], 1)
                        if table != "environmental_event_definitions":
                            self.assertIn(
                                "incomplete_environmental_analysis_schema_family",
                                report["warnings"],
                            )
                        self.assertNotIn("private coral observation", result.stdout)
                        self.assertEqual(database.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
