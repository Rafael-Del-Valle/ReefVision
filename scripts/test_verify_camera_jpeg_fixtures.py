"""Regression tests for the read-only camera JPEG fixture inventory.

Run: python -m unittest discover -s scripts -p 'test_verify_camera_jpeg_fixtures.py'
"""
from __future__ import annotations

import importlib.util
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).with_name("verify_camera_jpeg_fixtures.py")
SPEC = importlib.util.spec_from_file_location("verify_camera_jpeg_fixtures", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class CameraFixtureInventoryTests(unittest.TestCase):
    def test_mixed_case_extensions_and_nested_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nested = root / "camera"
            nested.mkdir()
            (root / "capture.JPG").write_bytes(b"\xff\xd8payload\xff\xd9")
            (nested / "second.JpEg").write_bytes(b"\xff\xd8other\xff\xd9")
            (root / "third.JPE").write_bytes(b"\xff\xd8third\xff\xd9")
            (root / "fourth.JFIF").write_bytes(b"\xff\xd8fourth\xff\xd9")
            (root / "fifth.JFI").write_bytes(b"\xff\xd8fifth\xff\xd9")
            (root / "sixth.JiF").write_bytes(b"\xff\xd8sixth\xff\xd9")
            (root / "ignore.png").write_bytes(b"\xff\xd8payload\xff\xd9")
            records, errors = MODULE.inventory(root)
            self.assertEqual(errors, [])
            self.assertEqual({record["path"] for record in records},
                             {"capture.JPG", "camera/second.JpEg", "third.JPE", "fourth.JFIF", "fifth.JFI", "sixth.JiF"})
            self.assertTrue(all(record["jpeg_boundary_markers"] for record in records))
            self.assertEqual({record["extension"] for record in records}, {".jpg", ".jpeg", ".jpe", ".jfif", ".jfi", ".jif"})
            self.assertEqual(len({record["sha256"] for record in records}), 6)

    def test_corrupt_markers_are_reported_without_changing_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = root / "broken.jpeg"
            original = b"not a jpeg"
            fixture.write_bytes(original)
            records, errors = MODULE.inventory(root)
            self.assertEqual(len(records), 1)
            self.assertFalse(records[0]["jpeg_boundary_markers"])
            self.assertEqual(errors, ["invalid JPEG boundary markers: broken.jpeg"])
            self.assertEqual(fixture.read_bytes(), original)

    def test_unreadable_file_is_reported_and_other_files_are_inventoried(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            blocked = root / "blocked.jpg"
            good = root / "good.jpeg"
            blocked.write_bytes(b"\xff\xd8blocked\xff\xd9")
            good.write_bytes(b"\xff\xd8good\xff\xd9")
            original_open = Path.open

            def selective_open(path: Path, *args: object, **kwargs: object):
                if path == blocked:
                    raise PermissionError("fixture is locked")
                return original_open(path, *args, **kwargs)

            with mock.patch.object(Path, "open", selective_open):
                records, errors = MODULE.inventory(root)
            self.assertEqual([record["path"] for record in records], ["good.jpeg"])
            self.assertEqual(errors, ["cannot read JPEG fixture: blocked.jpg: PermissionError"])
            self.assertEqual(blocked.read_bytes(), b"\xff\xd8blocked\xff\xd9")

    def test_cli_emits_machine_readable_manifest_and_success_exit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = root / "camera.JPG"
            original = bytes.fromhex("ffd8") + b"payload" + bytes.fromhex("ffd9")
            fixture.write_bytes(original)
            output = io.StringIO()
            with mock.patch("sys.argv", [str(SCRIPT), str(root)]):
                with contextlib.redirect_stdout(output):
                    exit_code = MODULE.main()
            manifest = json.loads(output.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(manifest["errors"], [])
            self.assertEqual(len(manifest["files"]), 1)
            self.assertEqual(manifest["files"][0]["path"], "camera.JPG")
            self.assertEqual(manifest["files"][0]["bytes"], len(original))
            self.assertEqual(fixture.read_bytes(), original)

    def test_cli_reports_corrupt_fixture_with_nonzero_exit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = root / "bad.jfif"
            fixture.write_bytes(b"not a jpeg")
            output = io.StringIO()
            with mock.patch("sys.argv", [str(SCRIPT), str(root)]):
                with contextlib.redirect_stdout(output):
                    exit_code = MODULE.main()
            manifest = json.loads(output.getvalue())
            self.assertEqual(exit_code, 1)
            self.assertEqual(manifest["files"][0]["jpeg_boundary_markers"], False)
            self.assertEqual(manifest["errors"], ["invalid JPEG boundary markers: bad.jfif"])

    def test_changed_fixture_during_hash_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = root / "changing.jpg"
            original = b"\\xff\\xd8payload\\xff\\xd9"
            fixture.write_bytes(original)
            original_stat = Path.stat
            calls = 0

            def changed_stat(path: Path, *args: object, **kwargs: object):
                nonlocal calls
                result = original_stat(path, *args, **kwargs)
                if path == fixture:
                    calls += 1
                    if calls >= 2:
                        from unittest.mock import Mock
                        modified = Mock(wraps=result)
                        modified.st_mtime_ns = result.st_mtime_ns + 1
                        return modified
                return result

            with mock.patch.object(Path, "stat", changed_stat):
                records, errors = MODULE.inventory(root)
            self.assertEqual(records, [])
            self.assertIn("JPEG fixture changed during inventory: changing.jpg", errors)
            self.assertEqual(fixture.read_bytes(), original)

    def test_empty_fixture_directory_is_not_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            records, errors = MODULE.inventory(Path(directory))
            self.assertEqual(records, [])
            self.assertEqual(errors, ["no JPEG-family fixtures found"])

    def test_symlink_is_rejected_without_reading_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "real.jpg"
            target.write_bytes(b"\xff\xd8real\xff\xd9")
            link = root / "linked.jpg"
            try:
                link.symlink_to(target)
            except (OSError, NotImplementedError):
                self.skipTest("Symlink creation unavailable on this platform")
            records, errors = MODULE.inventory(root)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["path"], "real.jpg")
            self.assertIn("symlink not inspected: linked.jpg", errors)


if __name__ == "__main__":
    unittest.main()
