"""Regression tests for the read-only camera JPEG fixture inventory.

Run: python -m unittest discover -s scripts -p 'test_verify_camera_jpeg_fixtures.py'
"""
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


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
