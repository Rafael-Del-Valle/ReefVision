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


    def test_hardlinked_camera_files_are_flagged_as_one_scientific_source(self) -> None:
        """Two JPEG paths pointing to one inode must not count as independent captures."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "capture_one.JPG"
            alias = root / "capture_two.jpeg"
            original = bytes.fromhex("ffd8") + b"same-source" + bytes.fromhex("ffd9")
            first.write_bytes(original)
            try:
                import os
                os.link(first, alias)
            except (OSError, NotImplementedError):
                self.skipTest("Hard links unavailable on this filesystem")
            records, errors = MODULE.inventory(root)
            self.assertEqual({record["path"] for record in records}, {first.name, alias.name})
            self.assertEqual(len({record["sha256"] for record in records}), 1)
            self.assertEqual(errors, [
                "JPEG hard-link alias (same source image): capture_one.JPG / capture_two.jpeg"
            ])
            self.assertEqual(first.read_bytes(), original)
            self.assertEqual(alias.read_bytes(), original)

    def test_copied_camera_captures_are_not_counted_as_independent(self) -> None:
        """Different filenames cannot make byte-identical camera files independent."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first_dir = root / "a_captures"
            copy_dir = root / "z_archive"
            first_dir.mkdir()
            copy_dir.mkdir()
            original = bytes.fromhex("ffd8") + b"same-immutable-capture" + bytes.fromhex("ffd9")
            first = first_dir / "IMG_0001.JPG"
            copied = copy_dir / "reexport.jpeg"
            first.write_bytes(original)
            copied.write_bytes(original)

            records, errors = MODULE.inventory(root)
            self.assertEqual(len(records), 2)
            self.assertEqual({record["sha256"] for record in records}, {records[0]["sha256"]})
            self.assertEqual(errors, [
                "JPEG duplicate source bytes (SHA-256): a_captures/IMG_0001.JPG / z_archive/reexport.jpeg"
            ])
            self.assertEqual(first.read_bytes(), original)
            self.assertEqual(copied.read_bytes(), original)

    def test_distinct_camera_bytes_do_not_trigger_duplicate_source_warning(self) -> None:
        """Inventory must not conflate distinct exposures by name, size or alias."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "DSC_0001.JPG"
            second = root / "DSC_0002.jpeg"
            first.write_bytes(bytes.fromhex("ffd8") + b"exposure-1" + bytes.fromhex("ffd9"))
            second.write_bytes(bytes.fromhex("ffd8") + b"exposure-2" + bytes.fromhex("ffd9"))
            records, errors = MODULE.inventory(root)
            self.assertEqual(errors, [])
            self.assertEqual(len({record["sha256"] for record in records}), 2)

    def test_windows_case_insensitive_camera_name_collision(self) -> None:
        """Distinct Linux filenames must not silently alias on Windows."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "capture.JPG"
            second = root / "CAPTURE.jpg"
            first.write_bytes(bytes.fromhex("ffd8") + b"first" + bytes.fromhex("ffd9"))
            second.write_bytes(bytes.fromhex("ffd8") + b"second" + bytes.fromhex("ffd9"))
            if len(list(root.iterdir())) != 2:
                self.skipTest("Filesystem is case-insensitive")
            originals = {p.name: p.read_bytes() for p in (first, second)}
            records, errors = MODULE.inventory(root)
            self.assertEqual(len(records), 2)
            self.assertEqual(len(errors), 1)
            self.assertIn("Windows case-insensitive filename collision:", errors[0])
            self.assertIn("capture.JPG", errors[0])
            self.assertIn("CAPTURE.jpg", errors[0])
            self.assertEqual({p.name: p.read_bytes() for p in (first, second)}, originals)

    def test_windows_case_insensitive_parent_directory_collision(self) -> None:
        """Case-only directory aliases must be reported even for different JPEG names."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            upper = root / "Camera"
            lower = root / "camera"
            upper.mkdir()
            try:
                lower.mkdir()
            except FileExistsError:
                self.skipTest("Filesystem is case-insensitive")
            first = upper / "first.JPG"
            second = lower / "second.jpeg"
            first.write_bytes(bytes.fromhex("ffd8") + b"first" + bytes.fromhex("ffd9"))
            second.write_bytes(bytes.fromhex("ffd8") + b"second" + bytes.fromhex("ffd9"))
            originals = (first.read_bytes(), second.read_bytes())
            records, errors = MODULE.inventory(root)
            self.assertEqual(len(records), 2)
            self.assertIn(
                "Windows case-insensitive directory collision: Camera / camera",
                errors,
            )
            self.assertEqual((first.read_bytes(), second.read_bytes()), originals)

    def test_windows_invalid_path_character_is_reported_read_only(self) -> None:
        """Linux camera paths containing Win32-forbidden characters must be flagged."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            invalid = root / "camera:one"
            try:
                invalid.mkdir()
                fixture = invalid / "photo?.JPG"
                original = bytes.fromhex("ffd8") + b"camera" + bytes.fromhex("ffd9")
                fixture.write_bytes(original)
            except OSError:
                self.skipTest("Host filesystem rejects Win32-invalid path characters")
            records, errors = MODULE.inventory(root)
            self.assertEqual([record["path"] for record in records], ["camera:one/photo?.JPG"])
            self.assertIn("Windows invalid path character: camera:one/photo?.JPG", errors)
            self.assertEqual(fixture.read_bytes(), original)

    def test_windows_reserved_device_parent_directory_is_rejected(self) -> None:
        """A valid JPEG below a Windows device-named directory is not portable."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reserved = root / "CON"
            try:
                reserved.mkdir()
            except OSError:
                self.skipTest("Filesystem prohibits Windows device directory names")
            photo = reserved / "photo.JPG"
            original = bytes.fromhex("ffd8") + b"camera" + bytes.fromhex("ffd9")
            photo.write_bytes(original)
            records, errors = MODULE.inventory(root)
            self.assertEqual([record["path"] for record in records], ["CON/photo.JPG"])
            self.assertIn("Windows reserved device directory: CON/photo.JPG", errors)
            self.assertEqual(photo.read_bytes(), original)

    def test_windows_reserved_device_camera_filenames(self) -> None:
        """Windows cannot open device basenames even with JPEG suffixes."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            names = ("CON.JPG", "com1.jpeg", "LPT9.JFIF", "safe.jpg")
            # Distinct bytes isolate Win32 device-name checks from the separate
            # SHA-256 duplicate-capture safeguard tested above.
            originals = {
                name: bytes.fromhex("ffd8") + name.encode("ascii") + bytes.fromhex("ffd9")
                for name in names
            }
            try:
                for name in names:
                    (root / name).write_bytes(originals[name])
            except OSError:
                self.skipTest("Host filesystem rejects Windows device filenames")
            records, errors = MODULE.inventory(root)
            self.assertEqual({record["path"] for record in records}, set(names))
            self.assertEqual(
                set(errors),
                {f"Windows reserved device filename: {name}" for name in names[:3]},
            )
            self.assertEqual(
                [p.read_bytes() for p in (root / name for name in names)],
                [originals[name] for name in names],
            )

    def test_windows_superscript_device_aliases_are_rejected_read_only(self) -> None:
        """Win32 treats COM¹/²/³ and LPT¹/²/³ as reserved device names."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = bytes.fromhex("ffd8") + b"unchanged" + bytes.fromhex("ffd9")
            paths = [root / "COM¹.JPG", root / "LPT².jpeg"]
            try:
                for path in paths:
                    path.write_bytes(original)
            except OSError:
                self.skipTest("Host filesystem rejects superscript device filenames")
            records, errors = MODULE.inventory(root)
            self.assertEqual({record["path"] for record in records},
                             {path.name for path in paths})
            for path in paths:
                self.assertIn(f"Windows reserved device filename: {path.name}", errors)
                self.assertEqual(path.read_bytes(), original)

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

    def test_opt_in_pixel_decode_accepts_rgb_cmyk_and_exif_without_mutation(self) -> None:
        """Actual camera codecs must decode originals without rewriting EXIF or color mode."""
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow unavailable; full camera JPEG decoding is unverified")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            originals = {}
            for mode, suffix in (("RGB", ".JPG"), ("CMYK", ".JFIF")):
                fixture = root / f"camera_{mode}{suffix}"
                values = (30, 80, 120) if mode == "RGB" else (30, 80, 120, 150)
                image = Image.new(mode, (12, 8), values)
                exif = Image.Exif()
                exif[274] = 6
                image.save(fixture, format="JPEG", exif=exif)
                originals[fixture.name] = fixture.read_bytes()
            records, errors = MODULE.inventory(root, verify_decode=True)
            self.assertEqual(errors, [])
            self.assertEqual(len(records), 2)
            self.assertTrue(all(record["jpeg_boundary_markers"] for record in records))
            self.assertTrue(all(record["jpeg_decodable"] for record in records))
            self.assertEqual(
                {record["jpeg_color_mode"] for record in records}, {"RGB", "CMYK"}
            )
            for record in records:
                self.assertEqual(record["jpeg_pixel_width"], 12)
                self.assertEqual(record["jpeg_pixel_height"], 8)
                self.assertEqual(record["jpeg_exif_orientation"], 6)
            for name, content in originals.items():
                self.assertEqual((root / name).read_bytes(), content)

    def test_opt_in_pixel_decode_reports_exif_display_geometry_for_all_orientations(self) -> None:
        """EXIF 5-8 transpose displayed axes; native pixels remain unchanged."""
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow unavailable; EXIF display geometry unverified")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            originals = {}
            for orientation in range(1, 9):
                path = root / f"orientation_{orientation}.JPG"
                exif = Image.Exif()
                exif[274] = orientation
                Image.new("RGB", (12, 8), (orientation * 15, 40, 100)).save(
                    path, format="JPEG", exif=exif
                )
                originals[path.name] = path.read_bytes()
            # No EXIF orientation means normal, untransposed display axes.
            plain = root / "no_exif.jpeg"
            Image.new("RGB", (12, 8), (4, 20, 70)).save(plain, format="JPEG")
            originals[plain.name] = plain.read_bytes()

            records, errors = MODULE.inventory(root, verify_decode=True)
            self.assertEqual(errors, [])
            self.assertEqual(len(records), 9)
            by_path = {record["path"]: record for record in records}
            for orientation in range(1, 9):
                record = by_path[f"orientation_{orientation}.JPG"]
                self.assertTrue(record["jpeg_decodable"])
                self.assertEqual(record["jpeg_exif_orientation"], orientation)
                self.assertEqual((record["jpeg_pixel_width"], record["jpeg_pixel_height"]), (12, 8))
                expected = (8, 12) if orientation >= 5 else (12, 8)
                self.assertEqual((record["jpeg_display_width"], record["jpeg_display_height"]), expected)
            plain_record = by_path["no_exif.jpeg"]
            self.assertIsNone(plain_record["jpeg_exif_orientation"])
            self.assertEqual(
                (plain_record["jpeg_display_width"], plain_record["jpeg_display_height"]),
                (12, 8),
            )
            for name, original in originals.items():
                self.assertEqual((root / name).read_bytes(), original)

    def test_invalid_exif_orientation_fails_geometry_qc_read_only(self) -> None:
        """Do not invent display dimensions for malformed camera EXIF."""
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow unavailable; invalid EXIF orientation unverified")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            originals = {}
            for orientation in (0, 9):
                path = root / f"invalid_{orientation}.JPG"
                exif = Image.Exif()
                exif[274] = orientation
                Image.new("RGB", (12, 8), (orientation * 15, 40, 100)).save(
                    path, format="JPEG", exif=exif
                )
                originals[path.name] = path.read_bytes()
            records, errors = MODULE.inventory(root, verify_decode=True)
            self.assertEqual(len(records), 2)
            self.assertEqual(
                errors,
                [
                    "JPEG decode failed: invalid_0.JPG: ValueError",
                    "JPEG decode failed: invalid_9.JPG: ValueError",
                ],
            )
            for record in records:
                self.assertFalse(record["jpeg_decodable"])
                self.assertNotIn("jpeg_display_width", record)
                self.assertNotIn("jpeg_display_height", record)
                self.assertNotIn("jpeg_pixel_width", record)
            for name, original in originals.items():
                self.assertEqual((root / name).read_bytes(), original)

    def test_opt_in_pixel_decode_rejects_corruption_with_valid_jpeg_markers(self) -> None:
        """SOI/EOI and SHA-256 alone cannot prove that an image is usable."""
        try:
            from PIL import Image  # noqa: F401
        except ImportError:
            self.skipTest("Pillow unavailable; full camera JPEG decoding is unverified")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = root / "undecodable.JpEg"
            original = bytes.fromhex("ffd8") + b"not a real JPEG image" + bytes.fromhex("ffd9")
            fixture.write_bytes(original)
            records, errors = MODULE.inventory(root, verify_decode=True)
            self.assertEqual([record["path"] for record in records], [fixture.name])
            self.assertTrue(records[0]["jpeg_boundary_markers"])
            self.assertFalse(records[0]["jpeg_decodable"])
            self.assertNotIn("jpeg_pixel_width", records[0])
            self.assertNotIn("jpeg_exif_orientation", records[0])
            self.assertEqual(len(errors), 1)
            self.assertTrue(errors[0].startswith(f"JPEG decode failed: {fixture.name}:"))
            self.assertEqual(fixture.read_bytes(), original)

    def test_opt_in_pixel_decode_rejects_pillow_pixel_budget_warning(self) -> None:
        """An oversized yet decodable JPEG must not silently pass camera QC."""
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow unavailable; decompression warning unverified")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = root / "pixel_budget.JPEG"
            Image.new("RGB", (12, 8), (20, 45, 120)).save(fixture, format="JPEG")
            original = fixture.read_bytes()

            # Header/integrity inventory must remain available read-only;
            # only explicitly requested decoding enforces the pixel budget.
            records, errors = MODULE.inventory(root)
            self.assertEqual(errors, [])
            self.assertEqual(len(records), 1)
            self.assertTrue(records[0]["jpeg_boundary_markers"])

            # 96 pixels exceeds the warning threshold (60) but not Pillow's
            # hard error threshold (120); exercise the otherwise silent path.
            with mock.patch.object(Image, "MAX_IMAGE_PIXELS", 60):
                records, errors = MODULE.inventory(root, verify_decode=True)
            self.assertEqual(len(records), 1)
            self.assertTrue(records[0]["jpeg_boundary_markers"])
            self.assertFalse(records[0]["jpeg_decodable"])
            self.assertEqual(
                errors,
                ["JPEG decode failed: pixel_budget.JPEG: DecompressionBombWarning"],
            )
            self.assertEqual(fixture.read_bytes(), original)

    def test_opt_in_pixel_decode_reports_pillow_decompression_bomb_guard(self) -> None:
        """Large camera images must fail QC explicitly, not abort the manifest."""
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow unavailable; decompression-bomb guard unverified")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = root / "overlarge_camera.JPG"
            original = bytes.fromhex("ffd8") + b"camera-payload" + bytes.fromhex("ffd9")
            fixture.write_bytes(original)
            with mock.patch.object(
                Image, "open", side_effect=Image.DecompressionBombError("too many pixels")
            ):
                records, errors = MODULE.inventory(root, verify_decode=True)
            self.assertEqual(len(records), 1)
            self.assertTrue(records[0]["jpeg_boundary_markers"])
            self.assertFalse(records[0]["jpeg_decodable"])
            self.assertEqual(
                errors,
                ["JPEG decode failed: overlarge_camera.JPG: DecompressionBombError"],
            )
            self.assertEqual(fixture.read_bytes(), original)

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
            original_open = Path.open
            reading_complete = False

            def observed_open(path: Path, *args: object, **kwargs: object):
                stream = original_open(path, *args, **kwargs)
                if path != fixture:
                    return stream

                class ObservedStream:
                    def __enter__(self):
                        return self

                    def __exit__(self, exc_type, exc, tb):
                        nonlocal reading_complete
                        try:
                            return stream.__exit__(exc_type, exc, tb)
                        finally:
                            reading_complete = True

                    def read(self, *read_args, **read_kwargs):
                        return stream.read(*read_args, **read_kwargs)

                    def fileno(self):
                        return stream.fileno()

                return ObservedStream()

            def changed_stat(path: Path, *args: object, **kwargs: object):
                result = original_stat(path, *args, **kwargs)
                if path == fixture and reading_complete:
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

            with mock.patch.object(Path, "stat", changed_stat), mock.patch.object(Path, "open", observed_open):
                records, errors = MODULE.inventory(root)
            self.assertEqual(records, [])
            self.assertIn("JPEG fixture changed during inventory: changing.jpg", errors)
            self.assertEqual(fixture.read_bytes(), original)
            self.assertEqual(len(original), 11)

    def test_swapped_open_handle_cannot_hash_unrelated_camera_image(self) -> None:
        """A substituted fd must fail even if the approved path stays unchanged."""
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            root = Path(directory)
            photo = root / "approved.JPG"
            private = Path(outside) / "other_study.JPEG"
            approved_bytes = b"\xff\xd8approved-camera\xff\xd9"
            private_bytes = b"\xff\xd8different-camera\xff\xd9"
            photo.write_bytes(approved_bytes)
            private.write_bytes(private_bytes)
            original_open = Path.open

            def substituted_open(path: Path, *args: object, **kwargs: object):
                if path == photo:
                    return original_open(private, *args, **kwargs)
                return original_open(path, *args, **kwargs)

            with mock.patch.object(Path, "open", substituted_open):
                records, errors = MODULE.inventory(root)
            self.assertEqual(records, [])
            self.assertEqual(errors, ["JPEG fixture changed during inventory: approved.JPG"])
            self.assertEqual(photo.read_bytes(), approved_bytes)
            self.assertEqual(private.read_bytes(), private_bytes)

    def test_pixel_decode_rejects_swapped_handle_after_hash(self) -> None:
        """EXIF and pixel geometry must correspond to the hashed camera source."""
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow unavailable; file-identity decode guard unverified")
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            root = Path(directory)
            photo = root / "approved.JPG"
            private = Path(outside) / "other_study.jpeg"
            Image.new("RGB", (12, 8), (15, 20, 45)).save(photo, format="JPEG")
            Image.new("RGB", (8, 12), (90, 30, 10)).save(private, format="JPEG")
            approved_bytes = photo.read_bytes()
            private_bytes = private.read_bytes()
            original_open = Path.open
            opened = 0

            def substituted_decode_open(path: Path, *args: object, **kwargs: object):
                nonlocal opened
                if path == photo:
                    opened += 1
                    if opened == 2:
                        return original_open(private, *args, **kwargs)
                return original_open(path, *args, **kwargs)

            with mock.patch.object(Path, "open", substituted_decode_open):
                records, errors = MODULE.inventory(root, verify_decode=True)
            self.assertEqual(opened, 2)
            self.assertEqual(len(records), 1)
            self.assertTrue(records[0]["jpeg_boundary_markers"])
            self.assertFalse(records[0]["jpeg_decodable"])
            self.assertNotIn("jpeg_display_width", records[0])
            self.assertEqual(errors, ["JPEG decode failed: approved.JPG: ValueError"])
            self.assertEqual(photo.read_bytes(), approved_bytes)
            self.assertEqual(private.read_bytes(), private_bytes)

    def test_direct_inventory_rejects_linked_root_and_parent_read_only(self) -> None:
        """Library callers must not bypass the CLI's approved fixture boundary."""
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            actual = parent / "approved"
            fixtures = actual / "fixtures"
            fixtures.mkdir(parents=True)
            original = bytes.fromhex("ffd8") + b"original" + bytes.fromhex("ffd9")
            camera = fixtures / "camera.JPG"
            camera.write_bytes(original)
            linked = parent / "linked"
            try:
                linked.symlink_to(actual, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("Directory symlinks unavailable on this platform")
            for root in (linked, linked / "fixtures"):
                with self.subTest(root=root):
                    records, errors = MODULE.inventory(root)
                    self.assertEqual(records, [])
                    self.assertEqual(errors, [
                        "camera fixture directory must not be a symbolic link (including parent components)"
                    ])
            self.assertEqual(camera.read_bytes(), original)

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

    def test_non_jpeg_file_is_not_statted_during_inventory(self) -> None:
        """Unrelated scientific files must not trigger JPEG file metadata reads."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            unrelated = root / "original-scientific-data.csv"
            unrelated.write_text("sample,value\\n1,2\\n", encoding="utf-8")
            fixture = root / "camera.JPG"
            original = bytes.fromhex("ffd8") + b"payload" + bytes.fromhex("ffd9")
            fixture.write_bytes(original)
            original_stat = Path.stat

            def guarded_stat(path: Path, *args: object, **kwargs: object):
                if path == unrelated:
                    raise AssertionError("unrelated file was statted")
                return original_stat(path, *args, **kwargs)

            with mock.patch.object(Path, "stat", guarded_stat):
                records, errors = MODULE.inventory(root)
            self.assertEqual(errors, [])
            self.assertEqual([record["path"] for record in records], ["camera.JPG"])
            self.assertEqual(fixture.read_bytes(), original)

    def test_windows_trailing_dot_directory_is_rejected_read_only(self) -> None:
        """A Linux-valid directory ending in a dot is not portable to Win32."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            camera_dir = root / "camera."
            try:
                camera_dir.mkdir()
            except OSError:
                self.skipTest("Trailing-dot directories unavailable on this filesystem")
            # Win32 may silently normalize camera. to camera even when mkdir succeeds.
            # Only assert the Linux-specific path diagnostic if the filesystem
            # actually preserved the trailing dot on disk.
            if not any(entry.name == "camera." for entry in root.iterdir()):
                self.skipTest("Filesystem normalized the trailing-dot directory name")
            fixture = camera_dir / "frame.JPG"
            original = bytes.fromhex("ffd8") + b"payload" + bytes.fromhex("ffd9")
            fixture.write_bytes(original)
            records, errors = MODULE.inventory(root)
            self.assertEqual(len(records), 1)
            self.assertIn(
                "Windows trailing dot/space path component: camera./frame.JPG",
                errors,
            )
            self.assertEqual(fixture.read_bytes(), original)

    def test_empty_fixture_directory_is_not_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            records, errors = MODULE.inventory(Path(directory))
            self.assertEqual(records, [])
            self.assertEqual(errors, ["no JPEG-family fixtures found"])

    def test_symlinked_camera_directory_cannot_hide_uninspected_captures(self) -> None:
        """A linked subdirectory must not silently pass the fixture inventory."""
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "approved"
            root.mkdir()
            outside = base / "outside"
            outside.mkdir()
            original = bytes.fromhex("ffd8") + b"outside" + bytes.fromhex("ffd9")
            (outside / "unapproved.JPG").write_bytes(original)
            (root / "approved.jpeg").write_bytes(bytes.fromhex("ffd8") + b"approved" + bytes.fromhex("ffd9"))
            link = root / "linked_camera"
            try:
                link.symlink_to(outside, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("Directory symlinks unavailable on this filesystem")
            records, errors = MODULE.inventory(root)
            self.assertEqual([record["path"] for record in records], ["approved.jpeg"])
            self.assertIn("symlinked directory not inspected: linked_camera", errors)
            self.assertEqual((outside / "unapproved.JPG").read_bytes(), original)

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


    def test_unreadable_camera_directory_is_reported_not_silently_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "approved.JPG"
            original = b"\xff\xd8original\xff\xd9"
            image.write_bytes(original)

            def failing_walk(_root, *, followlinks, onerror):
                self.assertFalse(followlinks)
                onerror(PermissionError(13, "access denied", str(root / "unreadable")))
                yield str(root), [], ["approved.JPG"]

            with mock.patch.object(MODULE.os, "walk", side_effect=failing_walk):
                records, errors = MODULE.inventory(root)
            self.assertEqual([record["path"] for record in records], ["approved.JPG"])
            self.assertTrue(any("camera directory traversal failed:" in error
                                and "PermissionError" in error for error in errors))
            self.assertEqual(image.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
