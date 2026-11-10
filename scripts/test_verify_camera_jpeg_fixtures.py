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


    def test_real_pillow_encoded_rgb_and_cmyk_camera_jpegs(self) -> None:
        """Inventory actual decodable JPEG streams, not just SOI/EOI markers."""
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow is not installed on this runner; JPEG codec acceptance remains unverified")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for mode, suffix in (("RGB", ".JPG"), ("CMYK", ".JfIf")):
                path = root / f"camera_{mode}{suffix}"
                image = Image.new(mode, (8, 6), (35, 90, 140, 180) if mode == "CMYK" else (35, 90, 140))
                image.save(path, format="JPEG")
                with Image.open(path) as decoded:
                    decoded.load()
                    self.assertEqual(decoded.format, "JPEG")
                    self.assertEqual(decoded.mode, mode)
                    self.assertEqual(decoded.size, (8, 6))
            records, errors = MODULE.inventory(root)
            self.assertEqual(errors, [])
            self.assertEqual(len(records), 2)
            self.assertTrue(all(record["jpeg_boundary_markers"] for record in records))
            self.assertEqual({record["extension"] for record in records}, {".jpg", ".jfif"})

    def test_exif_oriented_camera_jpeg_is_inventoried_without_rewriting_metadata(self) -> None:
        """Camera EXIF orientation must survive read-only JPEG inventory."""
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow unavailable; camera EXIF acceptance unverified")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = root / "portrait_camera.JPEG"
            image = Image.new("RGB", (12, 8), (40, 100, 180))
            exif = Image.Exif()
            exif[274] = 6  # Rotate 90 degrees clockwise for display.
            image.save(fixture, format="JPEG", exif=exif)
            original = fixture.read_bytes()

            with Image.open(fixture) as decoded:
                decoded.load()
                self.assertEqual(decoded.getexif().get(274), 6)
                self.assertEqual(decoded.size, (12, 8))

            records, errors = MODULE.inventory(root)
            self.assertEqual(errors, [])
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["path"], fixture.name)
            self.assertTrue(records[0]["jpeg_boundary_markers"])
            self.assertEqual(fixture.read_bytes(), original)

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

    def test_only_unreadable_jpeg_reports_read_error_not_empty_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            blocked = root / "locked.JPG"
            blocked.write_bytes(bytes.fromhex("ffd8") + b"payload" + bytes.fromhex("ffd9"))
            original_open = Path.open

            def deny_fixture(path: Path, *args: object, **kwargs: object):
                if path == blocked:
                    raise PermissionError("camera file locked")
                return original_open(path, *args, **kwargs)

            with mock.patch.object(Path, "open", deny_fixture):
                records, errors = MODULE.inventory(root)
            self.assertEqual(records, [])
            self.assertEqual(errors, ["cannot read JPEG fixture: locked.JPG: PermissionError"])
            self.assertEqual(blocked.read_bytes(), bytes.fromhex("ffd8") + b"payload" + bytes.fromhex("ffd9"))

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
            original = bytes.fromhex("ffd8") + b"payload" + bytes.fromhex("ffd9")
            fixture.write_bytes(original)
            original_stat = Path.stat
            calls = 0

            def changed_stat(path: Path, *args: object, **kwargs: object):
                nonlocal calls
                result = original_stat(path, *args, **kwargs)
                if path == fixture:
                    calls += 1
                    if calls >= 2:
                        from types import SimpleNamespace
                        return SimpleNamespace(
                            st_mode=result.st_mode,
                            st_size=result.st_size,
                            st_mtime_ns=result.st_mtime_ns + 1,
                            st_ctime_ns=result.st_ctime_ns,
                            st_ino=result.st_ino,
                            st_dev=result.st_dev,
                        )
                return result

            with mock.patch.object(Path, "stat", changed_stat):
                records, errors = MODULE.inventory(root)
            self.assertEqual(records, [])
            self.assertIn("JPEG fixture changed during inventory: changing.jpg", errors)
            self.assertEqual(fixture.read_bytes(), original)
            self.assertEqual(len(original), 11)

    def test_cli_rejects_symlink_root_without_inspecting_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            actual = parent / "actual"
            actual.mkdir()
            (actual / "camera.jpg").write_bytes(b"\xff\xd8payload\xff\xd9")
            linked = parent / "linked"
            try:
                linked.symlink_to(actual, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("Directory symlinks unavailable on this platform")
            output = io.StringIO()
            with mock.patch("sys.argv", [str(SCRIPT), str(linked)]):
                with contextlib.redirect_stderr(output):
                    with self.assertRaises(SystemExit) as caught:
                        MODULE.main()
            self.assertEqual(caught.exception.code, 2)
            self.assertIn("must not be a symbolic link", output.getvalue())
            self.assertEqual((actual / "camera.jpg").read_bytes(),
                             b"\xff\xd8payload\xff\xd9")

    def test_cli_rejects_symlinked_parent_directory(self) -> None:
        """A linked parent must not bypass the approved camera fixture root."""
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            actual = parent / "actual"
            fixtures = actual / "fixtures"
            fixtures.mkdir(parents=True)
            camera = fixtures / "camera.JPG"
            original = bytes.fromhex("ffd8") + b"unchanged" + bytes.fromhex("ffd9")
            camera.write_bytes(original)
            linked_parent = parent / "linked-parent"
            try:
                linked_parent.symlink_to(actual, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("Directory symlinks unavailable on this platform")
            output = io.StringIO()
            with mock.patch("sys.argv", [str(SCRIPT), str(linked_parent / "fixtures")]):
                with contextlib.redirect_stderr(output):
                    with self.assertRaises(SystemExit) as caught:
                        MODULE.main()
            self.assertEqual(caught.exception.code, 2)
            self.assertIn("including parent components", output.getvalue())
            self.assertEqual(camera.read_bytes(), original)

    def test_cli_missing_directory_reports_usage_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing-camera-fixtures"
            output = io.StringIO()
            with mock.patch("sys.argv", [str(SCRIPT), str(missing)]):
                with contextlib.redirect_stderr(output):
                    with self.assertRaises(SystemExit) as caught:
                        MODULE.main()
            self.assertEqual(caught.exception.code, 2)
            self.assertIn("cannot resolve camera fixture directory: FileNotFoundError", output.getvalue())
            self.assertFalse(missing.exists())

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
