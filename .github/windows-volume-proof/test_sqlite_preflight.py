"""Exercise the two stock SQLite modes used by the disposable pressure harness."""

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from sqlite_preflight import prepare_for_capacity_pressure


class SQLitePreflightTests(unittest.TestCase):
    def prepare_database(self, path: Path, mode: str) -> sqlite3.Connection:
        connection = sqlite3.connect(path)
        self.assertEqual(connection.execute(f"PRAGMA journal_mode={mode}").fetchone(), (mode,))
        connection.execute("CREATE TABLE witness (value INTEGER NOT NULL)")
        connection.execute("INSERT INTO witness VALUES (1)")
        connection.commit()
        return connection

    def test_keeps_healthy_rollback_journal_mode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "fixture.db"
            with closing(self.prepare_database(database, "delete")) as connection:
                self.assertEqual(
                    connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone(), (0, -1, -1)
                )
                before = database.read_bytes()

                prepared = prepare_for_capacity_pressure(database)

                self.assertEqual(prepared["journal_mode"], "delete")
                self.assertIs(prepared["rollback_writer_idle"], True)
                self.assertIsNone(prepared["sqlite_wal_checkpoint_truncated"])
                self.assertEqual(connection.execute("PRAGMA journal_mode").fetchone(), ("delete",))
                self.assertEqual(database.read_bytes(), before)

    def test_truncates_healthy_wal_without_changing_the_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "fixture.db"
            with closing(self.prepare_database(database, "wal")) as connection:
                self.assertGreater(database.with_suffix(".db-wal").stat().st_size, 0)

                prepared = prepare_for_capacity_pressure(database)

                self.assertEqual(prepared["journal_mode"], "wal")
                self.assertIs(prepared["sqlite_wal_checkpoint_truncated"], True)
                self.assertIsNone(prepared["rollback_writer_idle"])
                self.assertEqual(connection.execute("PRAGMA journal_mode").fetchone(), ("wal",))
                self.assertEqual(connection.execute("SELECT value FROM witness").fetchall(), [(1,)])
                self.assertEqual(database.with_suffix(".db-wal").stat().st_size, 0)

    def test_refuses_a_busy_rollback_writer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "fixture.db"
            with closing(self.prepare_database(database, "delete")) as connection:
                connection.execute("BEGIN IMMEDIATE")
                with self.assertRaisesRegex(sqlite3.OperationalError, "database is locked"):
                    prepare_for_capacity_pressure(database)
                connection.rollback()
                self.assertEqual(connection.execute("SELECT value FROM witness").fetchall(), [(1,)])


if __name__ == "__main__":
    unittest.main()
