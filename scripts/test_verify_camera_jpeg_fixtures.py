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
    def test_owner_camera_manifest_recipes_use_pinned_read_only_scanner(self) -> None:
        """Both owner-hardware recipes must decode and pin the pre-import evidence."""
        guide = (
            Path(__file__).resolve().parents[1]
            / "docs"
            / "acceptance"
            / "REEFVISION_103_WINDOWS_RELEASE_EVIDENCE.md"
        ).read_text(encoding="utf-8")
        commands = [
            line.split()
            for line in guide.splitlines()
            if line.startswith("python scripts/verify_camera_jpeg_fixtures.py ")
        ]
        common = ["python", "scripts/verify_camera_jpeg_fixtures.py",
                  "$cameraRoot", "--verify-decode"]
        self.assertEqual(commands, [
            common + [">", "$before"],
            common + ["--compare-manifest", "$before",
                      "--expected-manifest-sha256", "$beforeSha256", ">", "$after"],
        ])
        digest_command = '$beforeSha256 = (Get-FileHash -LiteralPath $before -Algorithm SHA256).Hash'
        self.assertLess(guide.index(" ".join(commands[0])), guide.index(digest_command))
        self.assertLess(guide.index(digest_command), guide.index(" ".join(commands[1])))
        routing_row = next(line for line in guide.splitlines()
                           if line.startswith("| Extension routing |"))
        for suffix in ("JPG", "JPEG", "JPE", "JFIF", "JFI", "JIF"):
            with self.subTest(suffix=suffix):
                self.assertIn(suffix, routing_row.replace("/", " ").replace(",", " ").split())

    def test_owner_camera_scanner_decodes_and_replays_every_jpeg_suffix(self) -> None:
        """Exercise the shared scanner, not a second documentation-only suffix filter."""
        import hashlib

        expected = {".jpg", ".jpeg", ".jpe", ".jfif", ".jfi", ".jif"}
        self.assertEqual(MODULE.JPEG_SUFFIXES, expected)
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow unavailable; camera decode replay unverified")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "camera"
            root.mkdir()
            originals = {}
            for index, suffix in enumerate(sorted(expected)):
                for case_index, extension in enumerate((suffix, suffix.upper())):
                    photo = root / f"capture_{index}_{case_index}{extension}"
                    Image.new("RGB", (8 + index, 8 + case_index)).save(photo, format="JPEG")
                    originals[photo.name] = photo.read_bytes()
            for suffix in (".png", ".tif", ".arw", ".heic"):
                (root / f"ignored{suffix}").write_bytes(b"not a JPEG")
            before_output = io.StringIO()
            common = [str(SCRIPT), str(root), "--verify-decode"]
            with mock.patch("sys.argv", common), contextlib.redirect_stdout(before_output):
                self.assertEqual(MODULE.main(), 0)
            before = json.loads(before_output.getvalue())
            self.assertEqual({record["path"] for record in before["files"]}, set(originals))
            self.assertTrue(all(record["jpeg_decodable"] is True for record in before["files"]))
            self.assertEqual(len({record["sha256"] for record in before["files"]}), 12)
            baseline = Path(directory) / "before.json"
            baseline.write_bytes(before_output.getvalue().encode("utf-8"))
            digest = hashlib.sha256(baseline.read_bytes()).hexdigest()
            after_output = io.StringIO()
            replay = common + [
                "--compare-manifest", str(baseline), "--expected-manifest-sha256", digest,
            ]
            with mock.patch("sys.argv", replay), contextlib.redirect_stdout(after_output):
                self.assertEqual(MODULE.main(), 0)
            self.assertEqual(json.loads(after_output.getvalue()), before)
            for name, original in originals.items():
                self.assertEqual((root / name).read_bytes(), original)

    def test_windows_file_identity_ignores_inconsistent_ctime_only(self) -> None:
        """Windows path stat and handle fstat can disagree on creation/change time."""
        from types import SimpleNamespace

        baseline = dict(st_dev=4, st_ino=25, st_size=32,
                        st_mtime_ns=123456789, st_ctime_ns=987654321)
        first = SimpleNamespace(**baseline)
        differing_ctime = SimpleNamespace(**{**baseline, "st_ctime_ns": 987654322})
        differing_size = SimpleNamespace(**{**baseline, "st_size": 33})
        differing_mtime = SimpleNamespace(**{**baseline, "st_mtime_ns": 123456790})
        substituted_handle = SimpleNamespace(**{**baseline, "st_ino": 26})

        with mock.patch.object(MODULE.os, "name", "nt"):
            self.assertEqual(MODULE._file_fingerprint(first),
                             MODULE._file_fingerprint(differing_ctime))
            for changed in (differing_size, differing_mtime, substituted_handle):
                self.assertNotEqual(MODULE._file_fingerprint(first),
                                    MODULE._file_fingerprint(changed))
        with mock.patch.object(MODULE.os, "name", "posix"):
            self.assertNotEqual(MODULE._file_fingerprint(first),
                                MODULE._file_fingerprint(differing_ctime))

    def test_decoded_baseline_requires_matching_geometry_exif_icc_and_qc(self) -> None:
        """Matching JPEG bytes must not conceal changed EXIF QC/uncertainty verdicts."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline_record = {
                "path": "portrait.JPEG",
                "bytes": 42,
                "sha256": "a" * 64,
                "jpeg_boundary_markers": True,
                "jpeg_decodable": True,
                "jpeg_pixel_width": 12,
                "jpeg_pixel_height": 8,
                "jpeg_display_width": 8,
                "jpeg_display_height": 12,
                "jpeg_exif_orientation": 6,
                "jpeg_exif_datetime_original_local": "2026:04:03 14:00:00",
                "jpeg_exif_offset_time_original": "-04:00",
                "jpeg_exif_capture_timezone_unknown": False,
                "jpeg_exif_exposure_ifd_conflict": False,
                "jpeg_exif_ifd0_dimension_conflict": False,
                "jpeg_exif_camera_model_malformed": False,
                "jpeg_exif_pixel_width": 12,
                "jpeg_icc_profile_sha256": "b" * 64,
            }
            baseline = {"root": str(root), "errors": [], "files": [baseline_record]}
            self.assertEqual(MODULE.compare_source_manifest(root, [baseline_record], baseline), [])

            for field, replacement in (
                ("jpeg_decodable", False),
                ("jpeg_decodable", None),
                ("jpeg_display_width", 12),
                ("jpeg_exif_orientation", 1),
                ("jpeg_exif_offset_time_original", None),
                # A decoder changing only its QC determination must not pass
                # even when file SHA, orientation and timestamps stay identical.
                ("jpeg_exif_capture_timezone_unknown", True),
                ("jpeg_exif_exposure_ifd_conflict", True),
                ("jpeg_exif_ifd0_dimension_conflict", True),
                ("jpeg_exif_camera_model_malformed", True),
                ("jpeg_exif_pixel_width", 11),
                ("jpeg_icc_profile_sha256", "c" * 64),
            ):
                with self.subTest(field=field, replacement=replacement):
                    current = {**baseline_record, field: replacement}
                    errors = MODULE.compare_source_manifest(root, [current], baseline)
                    self.assertTrue(errors, "Decoder drift or missing verification passed")
                    self.assertIn("source JPEG", errors[0])

            header_only = {
                key: value for key, value in baseline_record.items()
                if not key.startswith("jpeg_") or key == "jpeg_boundary_markers"
            }
            self.assertIn(
                "pixel decoding not reverified",
                MODULE.compare_source_manifest(root, [header_only], baseline)[0],
            )
            invalid_baseline = {
                "root": str(root), "errors": [],
                "files": [{**baseline_record, "jpeg_decodable": False}],
            }
            self.assertEqual(
                MODULE.compare_source_manifest(root, [baseline_record], invalid_baseline),
                ["baseline JPEG manifest contains unverified pixel-decode evidence"],
            )
            # Legacy checksum-only baselines retain their original comparison
            # contract; do not claim they ever carried pixel/EXIF evidence.
            self.assertEqual(
                MODULE.compare_source_manifest(
                    root, [header_only],
                    {"root": str(root), "errors": [], "files": [header_only]},
                ),
                [],
            )

    def test_manifest_replay_rejects_inconsistent_alias_and_decode_labels(self) -> None:
        """Saved JPEG evidence cannot silently change alias or decode coverage."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = {
                "path": "camera.JfIf",
                "extension": ".jfif",
                "bytes": 42,
                "sha256": "a" * 64,
                "jpeg_boundary_markers": True,
            }
            baseline = {"root": str(root), "errors": [], "files": [record]}
            self.assertEqual(MODULE.compare_source_manifest(root, [record], baseline), [])
            for patch in (
                {"extension": ".jpeg"},
                {"extension": ".JFIF"},
                {"extension": None},
                {"jpeg_pixel_width": 12},
                {"jpeg_exif_orientation": 1},
                {"jpeg_icc_profile_present": True},
            ):
                with self.subTest(patch=patch):
                    invalid = {**record, **patch}
                    self.assertEqual(
                        MODULE.compare_source_manifest(
                            root, [invalid], {**baseline, "files": [invalid]}
                        ),
                        ["baseline JPEG manifest contains inconsistent evidence labels"],
                    )
                    self.assertEqual(
                        MODULE.compare_source_manifest(root, [invalid], baseline),
                        ["current JPEG inventory contains inconsistent evidence labels"],
                    )
            legacy = {key: value for key, value in record.items() if key != "extension"}
            self.assertEqual(
                MODULE.compare_source_manifest(root, [legacy], baseline),
                ["source JPEG extension evidence missing since baseline: 'camera.JfIf'"],
            )
            self.assertEqual(
                MODULE.compare_source_manifest(
                    root, [record], {**baseline, "files": [legacy]}
                ),
                [],
            )

    def test_decoded_manifest_requires_valid_source_and_display_geometry(self) -> None:
        """Matching malformed inventories cannot certify camera pixel geometry."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            good = {
                "path": "portrait.JPEG",
                "bytes": 42,
                "sha256": "a" * 64,
                "jpeg_boundary_markers": True,
                "jpeg_decodable": True,
                "jpeg_pixel_width": 12,
                "jpeg_pixel_height": 8,
                "jpeg_display_width": 8,
                "jpeg_display_height": 12,
                "jpeg_exif_orientation": 6,
            }
            baseline = {"root": str(root), "errors": [], "files": [good]}
            self.assertEqual(MODULE.compare_source_manifest(root, [good], baseline), [])
            cases = (
                {key: value for key, value in good.items() if key != "jpeg_pixel_width"},
                {key: value for key, value in good.items() if key != "jpeg_exif_orientation"},
                {**good, "jpeg_pixel_width": True},
                {**good, "jpeg_pixel_height": 0},
                {**good, "jpeg_display_height": -1},
                {**good, "jpeg_display_width": 12},
                {**good, "jpeg_exif_orientation": True},
                {**good, "jpeg_exif_orientation": 9},
                {**good, "jpeg_exif_orientation": None},
            )
            for malformed in cases:
                with self.subTest(malformed=malformed):
                    self.assertEqual(
                        MODULE.compare_source_manifest(
                            root, [malformed], {**baseline, "files": [malformed]}
                        ),
                        ["baseline JPEG manifest contains invalid decoded geometry evidence"],
                    )
            neutral = {
                **good,
                "jpeg_exif_orientation": None,
                "jpeg_display_width": 12,
                "jpeg_display_height": 8,
            }
            self.assertEqual(
                MODULE.compare_source_manifest(
                    root, [neutral], {**baseline, "files": [neutral]}
                ),
                [],
            )

    def test_header_only_baseline_rejects_invalid_decode_upgrade(self) -> None:
        """Optional stronger verification must not certify invalid pixel evidence."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            header = {
                "path": "CAMERA.JPG",
                "bytes": 42,
                "sha256": "a" * 64,
                "jpeg_boundary_markers": True,
            }
            baseline = {"root": str(root), "errors": [], "files": [header]}
            decoded = {
                **header,
                "jpeg_decodable": True,
                "jpeg_pixel_width": 12,
                "jpeg_pixel_height": 8,
                "jpeg_display_width": 8,
                "jpeg_display_height": 12,
                "jpeg_exif_orientation": 6,
            }
            for valid in (header, decoded):
                self.assertEqual(
                    MODULE.compare_source_manifest(root, [valid], baseline), []
                )
            for invalid in (
                {**header, "jpeg_decodable": False},
                {**header, "jpeg_decodable": True},
                {**decoded, "jpeg_decodable": 1},
                {**decoded, "jpeg_display_width": 12},
            ):
                with self.subTest(invalid=invalid):
                    self.assertEqual(
                        MODULE.compare_source_manifest(root, [invalid], baseline),
                        ["source JPEG pixel-decode upgrade invalid: 'CAMERA.JPG'"],
                    )

    def test_comparator_rejects_untrusted_current_integrity_records(self) -> None:
        """A malformed replay cannot be accepted or crash the camera comparator."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            good = {
                "path": "SONY.JPG",
                "bytes": 16,
                "sha256": "a" * 64,
                "jpeg_boundary_markers": True,
            }
            baseline = {"root": str(root), "errors": [], "files": [good]}
            self.assertEqual(MODULE.compare_source_manifest(root, [good], baseline), [])
            cases = (
                ("non-object", None),
                ("no size", {key: value for key, value in good.items() if key != "bytes"}),
                ("boolean size", {**good, "bytes": True}),
                ("negative size", {**good, "bytes": -1}),
                ("missing checksum", {**good, "sha256": None}),
                ("noncanonical checksum", {**good, "sha256": "A" * 64}),
                ("missing signature", {key: value for key, value in good.items()
                                       if key != "jpeg_boundary_markers"}),
                ("failed signature", {**good, "jpeg_boundary_markers": False}),
                ("nonboolean signature", {**good, "jpeg_boundary_markers": 1}),
                ("traversal path", {**good, "path": "../SONY.JPG"}),
                ("Windows path", {**good, "path": "folder\\\\SONY.JPG"}),
            )
            for label, current in cases:
                with self.subTest(case=label):
                    self.assertEqual(
                        MODULE.compare_source_manifest(root, [current], baseline),
                        ["current JPEG inventory contains malformed source-file evidence"],
                    )

    def test_comparator_rejects_windows_incompatible_replayed_paths(self) -> None:
        """Matching fabricated manifests cannot certify unaddressable Windows paths."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            good = {
                "path": "Sony/DSC_0001.JPEG",
                "bytes": 42,
                "sha256": "a" * 64,
                "jpeg_boundary_markers": True,
            }
            baseline = {"root": str(root), "errors": [], "files": [good]}
            self.assertEqual(MODULE.compare_source_manifest(root, [good], baseline), [])
            for path in (
                "CON.JPG", "COM¹.JPEG", "AUX/DSC.JPG", "folder./DSC.JPG",
                "folder /DSC.JPG", "C:/DSC.JPG", "camera/DSC:1.JPG",
                "camera/DSC?.JPG", "camera/DSC\x1f.JPG",
            ):
                with self.subTest(path=path):
                    invalid = {**good, "path": path}
                    self.assertEqual(
                        MODULE.compare_source_manifest(
                            root, [invalid], {**baseline, "files": [invalid]}
                        ),
                        ["baseline JPEG manifest contains malformed source-file evidence"],
                    )
                    self.assertEqual(
                        MODULE.compare_source_manifest(root, [invalid], baseline),
                        ["current JPEG inventory contains malformed source-file evidence"],
                    )

    def test_comparator_rejects_windows_path_collisions_in_replayed_manifests(self) -> None:
        """A matching manifest must still describe distinct addressable Windows paths."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = {
                "path": "Sony/DSC_0001.JPG",
                "bytes": 42,
                "sha256": "a" * 64,
                "jpeg_boundary_markers": True,
            }
            second = {**first, "path": "Sony/DSC_0002.JPG", "sha256": "b" * 64}
            baseline = {"root": str(root), "errors": [], "files": [first, second]}
            self.assertEqual(
                MODULE.compare_source_manifest(root, [first, second], baseline), []
            )
            for path in (
                "Sony/dsc_0001.jpg",
                "sony/DSC_0002.JPG",
                "Sony/DSC_0001.JPG/other.jpg",
                "sony/dsc_0001.jpg/other.jpg",
            ):
                for reverse in (False, True):
                    with self.subTest(path=path, reverse=reverse):
                        records = [first, {**second, "path": path}]
                        if reverse:
                            records.reverse()
                        self.assertEqual(
                            MODULE.compare_source_manifest(
                                root, records, {**baseline, "files": records}
                            ),
                            ["baseline JPEG manifest contains Windows path collisions"],
                        )
                        self.assertEqual(
                            MODULE.compare_source_manifest(root, records, baseline),
                            ["current JPEG inventory contains Windows path collisions"],
                        )

    def test_comparator_rejects_duplicate_source_bytes_and_impossible_sizes(self) -> None:
        """Replayed camera evidence cannot certify aliases as independent captures."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = {
                "path": "SONY.JPG",
                "bytes": 16,
                "sha256": "a" * 64,
                "jpeg_boundary_markers": True,
            }
            second = {**first, "path": "CANON.JPEG", "sha256": "b" * 64}
            baseline = {"root": str(root), "errors": [], "files": [first, second]}
            self.assertEqual(
                MODULE.compare_source_manifest(root, [first, second], baseline), []
            )
            duplicate = {**second, "sha256": first["sha256"]}
            self.assertEqual(
                MODULE.compare_source_manifest(
                    root, [first, duplicate], {**baseline, "files": [first, duplicate]}
                ),
                ["baseline JPEG manifest contains duplicate source bytes"],
            )
            errors = MODULE.compare_source_manifest(root, [first, duplicate], baseline)
            self.assertTrue(any("duplicate source bytes" in error for error in errors))
            self.assertTrue(any("bytes changed" in error for error in errors))
            for size in range(4):
                with self.subTest(size=size):
                    invalid = {**first, "bytes": size}
                    self.assertEqual(
                        MODULE.compare_source_manifest(
                            root, [invalid], {**baseline, "files": [invalid]}
                        ),
                        ["baseline JPEG manifest contains malformed source-file evidence"],
                    )
                    self.assertEqual(
                        MODULE.compare_source_manifest(root, [invalid, second], baseline),
                        ["current JPEG inventory contains malformed source-file evidence"],
                    )

    def test_cli_verified_decode_baseline_cannot_be_downgraded(self) -> None:
        """A post-import run must explicitly repeat the original pixel check."""
        import hashlib

        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow unavailable; camera decode replay unverified")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "camera"
            root.mkdir()
            photo = root / "DSC_0001.JPEG"
            exif = Image.Exif()
            exif[274] = 6
            Image.new("RGB", (12, 8), (30, 60, 90)).save(
                photo, format="JPEG", exif=exif
            )
            original = photo.read_bytes()
            before_output = io.StringIO()
            with mock.patch("sys.argv", [str(SCRIPT), str(root), "--verify-decode"]):
                with contextlib.redirect_stdout(before_output):
                    self.assertEqual(MODULE.main(), 0)
            before_bytes = before_output.getvalue().encode("utf-8")
            before_path = Path(directory) / "before.json"
            before_path.write_bytes(before_bytes)
            arguments = [
                str(SCRIPT), str(root), "--compare-manifest", str(before_path),
                "--expected-manifest-sha256", hashlib.sha256(before_bytes).hexdigest(),
            ]
            unchecked_output = io.StringIO()
            with mock.patch("sys.argv", arguments):
                with contextlib.redirect_stdout(unchecked_output):
                    self.assertEqual(MODULE.main(), 1)
            self.assertIn(
                "source JPEG pixel decoding not reverified since baseline",
                json.loads(unchecked_output.getvalue())["errors"][0],
            )
            replay_output = io.StringIO()
            with mock.patch("sys.argv", arguments + ["--verify-decode"]):
                with contextlib.redirect_stdout(replay_output):
                    self.assertEqual(MODULE.main(), 0)
            self.assertEqual(json.loads(replay_output.getvalue())["errors"], [])
            self.assertEqual(photo.read_bytes(), original)

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


    def test_non_regular_jpeg_entry_is_not_silently_ignored(self) -> None:
        """A JPEG-named non-file must fail acceptance without being opened."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            jpeg = root / "camera.JPG"
            original = bytes.fromhex("ffd8") + b"camera" + bytes.fromhex("ffd9")
            jpeg.write_bytes(original)
            original_is_file = Path.is_file

            def pretend_non_regular(path: Path) -> bool:
                if path == jpeg:
                    return False
                return original_is_file(path)

            with mock.patch.object(Path, "is_file", pretend_non_regular):
                records, errors = MODULE.inventory(root)

            self.assertEqual(records, [])
            self.assertEqual(
                errors, ["non-regular JPEG fixture not inspected: camera.JPG"]
            )
            self.assertEqual(jpeg.read_bytes(), original)

    def test_jpeg_named_directory_is_not_silently_omitted(self) -> None:
        """A folder masquerading as a JPEG must fail read-only acceptance."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            apparent_capture = root / "missing_capture.JPEG"
            apparent_capture.mkdir()
            nested = apparent_capture / "real_capture.jpg"
            valid = bytes.fromhex("ffd8") + b"raw-camera-source" + bytes.fromhex("ffd9")
            nested.write_bytes(valid)
            records, errors = MODULE.inventory(root)

            # Continue inspecting actual files; only the apparent JPEG directory
            # is rejected, and its contained camera capture stays unchanged.
            self.assertEqual([record["path"] for record in records],
                             ["missing_capture.JPEG/real_capture.jpg"])
            self.assertEqual(errors, [
                "non-regular JPEG fixture directory not inspected: missing_capture.JPEG"
            ])
            self.assertEqual(nested.read_bytes(), valid)

    def test_fifo_named_as_jpeg_is_rejected_without_opening(self) -> None:
        """A Unix FIFO must not block inspection or be accepted as a camera."""
        import os

        if not hasattr(os, "mkfifo"):
            self.skipTest("FIFO creation is unavailable on this platform")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fifo = root / "camera.JPG"
            try:
                os.mkfifo(fifo)
            except OSError:
                self.skipTest("Filesystem does not support FIFOs")
            records, errors = MODULE.inventory(root)
            self.assertEqual(records, [])
            self.assertEqual(
                errors, ["non-regular JPEG fixture not inspected: camera.JPG"]
            )

    def test_fifo_substituted_at_camera_open_is_rejected_without_blocking(self) -> None:
        """A file changed after stat must not hang the read-only inventory."""
        import os

        if not hasattr(os, "mkfifo") or not hasattr(os, "O_NONBLOCK"):
            self.skipTest("Nonblocking FIFO access is unavailable")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            photo = root / "approved.JPG"
            original = b"\xff\xd8camera\xff\xd9"
            photo.write_bytes(original)
            fifo = root / "substitute.pipe"
            try:
                os.mkfifo(fifo)
            except OSError:
                self.skipTest("Filesystem does not support FIFOs")
            real_open = os.open

            def substitute_at_open(path, flags):
                self.assertEqual(path, photo)
                self.assertTrue(flags & os.O_NONBLOCK)
                if hasattr(os, "O_NOFOLLOW"):
                    self.assertTrue(flags & os.O_NOFOLLOW)
                return real_open(fifo, flags)

            with mock.patch.object(MODULE.os, "open", side_effect=substitute_at_open):
                records, errors = MODULE.inventory(root)
            self.assertEqual(records, [])
            self.assertEqual(
                errors, ["JPEG fixture changed during inventory: approved.JPG"]
            )
            self.assertEqual(photo.read_bytes(), original)

    def test_external_hardlink_cannot_masquerade_as_approved_camera_capture(self) -> None:
        """One approved path to another study's inode is not provenance evidence."""
        import os

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "approved-camera-fixtures"
            root.mkdir()
            outside = Path(directory) / "other-study.JPG"
            original = b"\xff\xd8other-study-private-capture\xff\xd9"
            outside.write_bytes(original)
            photo = root / "capture.JPG"
            try:
                os.link(outside, photo)
            except (OSError, NotImplementedError) as error:
                self.skipTest(f"Hard links unavailable on this filesystem: {error}")
            if photo.stat().st_ino == 0 or photo.stat().st_nlink < 2:
                self.skipTest("Filesystem does not expose hard-link identity")

            records, errors = MODULE.inventory(root)
            self.assertEqual([record["path"] for record in records], ["capture.JPG"])
            self.assertEqual(
                errors,
                [
                    "JPEG hard-link alias outside approved fixture inventory: "
                    "capture.JPG (1 inventoried of 2 filesystem links)"
                ],
            )
            self.assertEqual(photo.read_bytes(), original)
            self.assertEqual(outside.read_bytes(), original)

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

    def test_camera_declared_exif_make_model_is_optional_and_not_origin_proof(self) -> None:
        """Keep bounded Sony/Canon labels but do not invent absent camera provenance."""
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow unavailable; EXIF camera Make/Model unverified")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            expected = {
                "sony.JPG": ("Sony", "ILCE-7RM3"),
                "canon.JPEG": ("Canon", "EOS R5"),
                "untagged.jfif": (None, None),
            }
            originals = {}
            for index, (name, labels) in enumerate(expected.items()):
                image = Image.new("RGB", (12, 8), (20 + index * 40, 60, 100))
                exif = Image.Exif()
                if labels[0] is not None:
                    exif[271], exif[272] = labels
                path = root / name
                image.save(path, format="JPEG", exif=exif)
                originals[name] = path.read_bytes()

            records, errors = MODULE.inventory(root, verify_decode=True)
            self.assertEqual(errors, [])
            self.assertEqual(len(records), 3)
            by_path = {record["path"]: record for record in records}
            for name, (make, model) in expected.items():
                record = by_path[name]
                self.assertTrue(record["jpeg_decodable"])
                self.assertEqual(record["jpeg_exif_camera_make"], make)
                self.assertEqual(record["jpeg_exif_camera_model"], model)
                self.assertFalse(record["jpeg_exif_camera_make_malformed"])
                self.assertFalse(record["jpeg_exif_camera_model_malformed"])
                self.assertEqual((root / name).read_bytes(), originals[name])
            # Only non-identifying camera labels are surfaced, not owner,
            # camera serial number, GPS coordinates or arbitrary EXIF fields.
            self.assertNotIn("camera_serial", json.dumps(records).lower())
            json.dumps(records, allow_nan=False)


    def test_camera_exif_exposure_time_is_local_unless_offset_is_explicit(self) -> None:
        """Preserve EXIF clock evidence and uncertainty without inventing UTC."""
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow unavailable; EXIF exposure provenance unverified")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            captures = {
                "sony.JPG": ("2026:04:03 14:25:30", "-04:00"),
                "canon.JPEG": ("2026:04:04 09:10:11", None),
                "without_clock.jfif": (None, None),
            }
            original_bytes = {}
            for name, (captured, offset) in captures.items():
                exif = Image.Exif()
                if captured is not None:
                    exif[34665] = {
                        36867: captured,
                        **({36881: offset} if offset is not None else {}),
                    }
                path = root / name
                Image.new("RGB", (12, 8), (30, 80, 120)).save(
                    path, format="JPEG", exif=exif
                )
                original_bytes[name] = path.read_bytes()
            records, errors = MODULE.inventory(root, verify_decode=True)
            self.assertEqual(errors, [])
            self.assertEqual(len(records), 3)
            by_path = {record["path"]: record for record in records}
            for name, (captured, offset) in captures.items():
                record = by_path[name]
                self.assertTrue(record["jpeg_decodable"])
                self.assertEqual(record["jpeg_exif_datetime_original_local"], captured)
                self.assertEqual(record["jpeg_exif_offset_time_original"], offset)
                self.assertEqual(
                    record["jpeg_exif_capture_timezone_unknown"],
                    captured is not None and offset is None,
                )
                self.assertFalse(record["jpeg_exif_datetime_original_malformed"])
                self.assertFalse(record["jpeg_exif_offset_time_original_malformed"])
                self.assertEqual((root / name).read_bytes(), original_bytes[name])
            json.dumps(records, allow_nan=False)

    def test_padded_ascii_exif_fields_agree_across_ifd0_and_nested(self) -> None:
        """NUL-padded vendor bytes must not create false camera-clock conflicts."""
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow unavailable; JPEG EXIF equivalence unverified")

        exposure = "2026:04:03 14:25:30"
        offset = "-04:00"
        original_getexif = Image.Image.getexif
        original_get_ifd = Image.Exif.get_ifd
        cases = (
            (
                "equivalent padded bytes",
                {36867: exposure, 36881: offset},
                {36867: exposure.encode("ascii") + b"\x00", 36881: b"-04:00\x00"},
                False,
            ),
            (
                "nested ASCII bytes only",
                {},
                {36867: exposure.encode("ascii"), 36881: offset.encode("ascii")},
                False,
            ),
            (
                "genuinely conflicting padded offset",
                {36867: exposure, 36881: offset},
                {36867: exposure.encode("ascii") + b"\x00", 36881: b"+01:00\x00"},
                True,
            ),
            (
                "equivalent padded fractional seconds",
                {36867: exposure, 36881: offset, 37521: "123456"},
                {
                    36867: exposure.encode("ascii") + b"\x00",
                    36881: b"-04:00\x00",
                    37521: b"123456\x00",
                },
                False,
            ),
            (
                "conflicting fractional seconds with matching UTC offset",
                {36867: exposure, 36881: offset, 37521: "120000"},
                {36867: exposure, 36881: offset, 37521: "340000"},
                True,
            ),
        )
        for label, top_tags, nested_tags, conflict in cases:
            with self.subTest(label=label):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    path = root / "DSC_EQUIVALENT.JPEG"
                    Image.new("RGB", (19, 11), (20, 65, 130)).save(path, format="JPEG")
                    original = path.read_bytes()

                    def forged_exif(image):
                        exif = original_getexif(image)
                        exif.update(top_tags)
                        return exif

                    def forged_ifd(exif, tag):
                        if tag == 34665:
                            return nested_tags
                        return original_get_ifd(exif, tag)

                    with (
                        mock.patch.object(Image.Image, "getexif", forged_exif),
                        mock.patch.object(Image.Exif, "get_ifd", forged_ifd),
                    ):
                        records, errors = MODULE.inventory(root, verify_decode=True)
                    expected = (
                        ["conflicting EXIF camera exposure metadata between IFD0 and Exif IFD: DSC_EQUIVALENT.JPEG"]
                        if conflict else []
                    )
                    self.assertEqual(errors, expected)
                    self.assertEqual(len(records), 1)
                    record = records[0]
                    self.assertTrue(record["jpeg_decodable"])
                    self.assertEqual(record["jpeg_exif_exposure_ifd_conflict"], conflict)
                    self.assertEqual(
                        record["jpeg_exif_datetime_original_local"],
                        None if conflict else exposure,
                    )
                    self.assertEqual(
                        record["jpeg_exif_offset_time_original"],
                        None if conflict else offset,
                    )
                    self.assertFalse(record["jpeg_exif_datetime_original_malformed"])
                    self.assertFalse(record["jpeg_exif_offset_time_original_malformed"])
                    json.dumps(records, allow_nan=False)
                    self.assertEqual(path.read_bytes(), original)

    def test_conflicting_exif_exposure_or_orphan_offset_is_qc_rejected(self) -> None:
        """Camera clocks need unambiguous IFD provenance, not invented timestamps."""
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow unavailable; camera exposure conflict QC unverified")
        original_getexif = Image.Image.getexif
        original_get_ifd = Image.Exif.get_ifd
        cases = (
            (
                "conflict",
                {36867: "2026:04:03 14:00:00", 36881: "+00:00"},
                {36867: "2026:04:04 14:00:00", 36881: "+01:00"},
                "conflicting EXIF camera exposure metadata between IFD0 and Exif IFD: DSC_0001.JPG",
                True,
                False,
            ),
            (
                "orphan",
                {36881: "+00:00"},
                {},
                "EXIF camera offset without original exposure time: DSC_0001.JPG",
                False,
                True,
            ),
        )
        for label, top_tags, nested_tags, expected_error, conflict, orphan in cases:
            with self.subTest(label=label):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    path = root / "DSC_0001.JPG"
                    Image.new("RGB", (12, 8), (30, 70, 90)).save(
                        path, format="JPEG"
                    )
                    original = path.read_bytes()

                    def forged_exif(image):
                        exif = original_getexif(image)
                        for tag, value in top_tags.items():
                            exif[tag] = value
                        return exif

                    def forged_ifd(exif, tag):
                        if tag == 34665:
                            return nested_tags
                        return original_get_ifd(exif, tag)

                    with (
                        mock.patch.object(Image.Image, "getexif", forged_exif),
                        mock.patch.object(Image.Exif, "get_ifd", forged_ifd),
                    ):
                        records, errors = MODULE.inventory(root, verify_decode=True)
                    self.assertEqual(errors, [expected_error])
                    self.assertEqual(len(records), 1)
                    record = records[0]
                    self.assertTrue(record["jpeg_decodable"])
                    self.assertEqual(record["jpeg_exif_exposure_ifd_conflict"], conflict)
                    self.assertEqual(
                        record["jpeg_exif_offset_without_datetime_original"], orphan
                    )
                    self.assertIsNone(record["jpeg_exif_datetime_original_local"])
                    if conflict:
                        self.assertIsNone(record["jpeg_exif_offset_time_original"])
                    json.dumps(records, allow_nan=False)
                    self.assertEqual(path.read_bytes(), original)

    def test_malformed_exif_sub_ifd_fails_decode_without_crashing_inventory(self) -> None:
        """A malformed camera IFD must not abort other camera fixtures."""
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow unavailable; malformed EXIF IFD QC unverified")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "DSC_0001.JPG"
            Image.new("RGB", (12, 8), (30, 70, 90)).save(
                path, format="JPEG"
            )
            original = path.read_bytes()
            with mock.patch.object(Image.Exif, "get_ifd", return_value=[]):
                records, errors = MODULE.inventory(root, verify_decode=True)
            self.assertEqual(errors, ["JPEG decode failed: DSC_0001.JPG: ValueError"])
            self.assertEqual(len(records), 1)
            self.assertFalse(records[0]["jpeg_decodable"])
            self.assertNotIn("jpeg_exif_datetime_original_local", records[0])
            self.assertEqual(path.read_bytes(), original)

    def test_malformed_camera_exposure_tags_fail_qc_without_mutating_capture(self) -> None:
        """Invalid timestamps and offsets cannot become trusted acquisition times."""
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow unavailable; invalid EXIF exposure QC unverified")
        original_get_ifd = Image.Exif.get_ifd
        invalid_cases = (
            ("2026:02:30 14:00:00", "+00:00"),
            ("2026:04:03 14:00:00", "+14:30"),
            ("2026:04:03 14:00:00", "-99:00"),
            (b"\xff", "+00:00"),
            (b"2026:04:03 14:\x000:00", "+00:00"),
            ("2026:04:03 14:00:00", "not UTC"),
        )
        for captured, offset in invalid_cases:
            with self.subTest(captured=repr(captured), offset=repr(offset)):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    path = root / "DSC_0001.JPG"
                    Image.new("RGB", (12, 8), (20, 60, 100)).save(
                        path, format="JPEG"
                    )
                    original = path.read_bytes()

                    def forged_ifd(exif, tag):
                        # Simulate a malformed nested EXIF IFD without
                        # forging a numeric offset in the live Exif object.
                        # Pillow interprets a direct dict assignment to tag
                        # 34665 as a file offset and fails before our parser.
                        if tag == 34665:
                            return {36867: captured, 36881: offset}
                        return original_get_ifd(exif, tag)

                    with mock.patch.object(Image.Exif, "get_ifd", forged_ifd):
                        records, errors = MODULE.inventory(root, verify_decode=True)
                    self.assertEqual(
                        errors, ["invalid EXIF camera exposure time metadata: DSC_0001.JPG"]
                    )
                    self.assertEqual(len(records), 1)
                    self.assertTrue(records[0]["jpeg_decodable"])
                    self.assertTrue(
                        records[0]["jpeg_exif_datetime_original_malformed"]
                        or records[0]["jpeg_exif_offset_time_original_malformed"]
                    )
                    json.dumps(records, allow_nan=False)
                    self.assertEqual(path.read_bytes(), original)


    def test_malformed_camera_make_model_tags_fail_qc_without_rewriting_images(self) -> None:
        """Malformed EXIF identifiers are flagged without mislabeling JPEG pixels."""
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow unavailable; malformed camera Make/Model unverified")
        original_getexif = Image.Image.getexif
        invalid_labels = (
            (b"Canon", "EOS R5"),
            ("Sony", "line\nbreak"),
            ("X" * 129, "model"),
            ("", "model"),
            ("Canon", b"EOS"),
        )
        for make, model in invalid_labels:
            with self.subTest(make=repr(make)[:20], model=repr(model)[:20]):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    path = root / "camera.JPG"
                    Image.new("RGB", (12, 8), (30, 70, 90)).save(
                        path, format="JPEG"
                    )
                    original = path.read_bytes()

                    def forged_exif(image):
                        exif = original_getexif(image)
                        exif[271], exif[272] = make, model
                        return exif

                    with mock.patch.object(Image.Image, "getexif", forged_exif):
                        records, errors = MODULE.inventory(root, verify_decode=True)
                    self.assertEqual(
                        errors, ["invalid EXIF camera Make/Model metadata: camera.JPG"]
                    )
                    self.assertEqual(len(records), 1)
                    record = records[0]
                    self.assertTrue(record["jpeg_decodable"])
                    self.assertTrue(
                        record["jpeg_exif_camera_make_malformed"]
                        or record["jpeg_exif_camera_model_malformed"]
                    )
                    json.dumps(record, allow_nan=False)
                    self.assertEqual(path.read_bytes(), original)

    def test_opt_in_decode_records_multisegment_icc_payload_provenance(self) -> None:
        """Fingerprint assembled ICC payloads without claiming calibrated camera color."""
        import hashlib

        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow unavailable; ICC payload provenance unverified")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            # More than 64 KiB requires multiple JPEG APP2 ICC chunks. These
            # synthetic bytes test preservation, NOT valid color calibration.
            profiles = {
                "profile_a.JPG": b"synthetic-profile-A:" + b"A" * 70_000,
                "profile_b.JPEG": b"synthetic-profile-B:" + b"B" * 70_000,
                "untagged.jpg": None,
            }
            originals = {}
            for name, profile in profiles.items():
                path = root / name
                options = {"icc_profile": profile} if profile is not None else {}
                Image.new("RGB", (12, 8), (30, 80, 140)).save(
                    path, format="JPEG", **options
                )
                originals[name] = path.read_bytes()

            records, errors = MODULE.inventory(root, verify_decode=True)
            self.assertEqual(errors, [])
            self.assertEqual(len(records), len(profiles))
            by_path = {record["path"]: record for record in records}
            for name, profile in profiles.items():
                record = by_path[name]
                self.assertTrue(record["jpeg_decodable"])
                self.assertEqual(record["jpeg_icc_profile_present"], profile is not None)
                self.assertEqual(
                    record["jpeg_icc_profile_bytes"], len(profile) if profile else 0
                )
                self.assertEqual(
                    record["jpeg_icc_profile_sha256"],
                    hashlib.sha256(profile).hexdigest() if profile else None,
                )
                self.assertEqual((root / name).read_bytes(), originals[name])
            self.assertNotEqual(
                by_path["profile_a.JPG"]["jpeg_icc_profile_sha256"],
                by_path["profile_b.JPEG"]["jpeg_icc_profile_sha256"],
            )

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

    def test_malformed_exif_parser_fails_only_affected_camera_fixture(self) -> None:
        """Malformed EXIF parsing must not abort QC for unrelated captures."""
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow unavailable; malformed camera EXIF not verified")
        for failure in (SyntaxError, EOFError, IndexError, KeyError, TypeError):
            with self.subTest(failure=failure.__name__):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    bad = root / "broken_exif.JPG"
                    good = root / "healthy.JPEG"
                    Image.new("RGB", (12, 8), (10, 40, 80)).save(bad, format="JPEG")
                    Image.new("RGB", (12, 8), (210, 50, 90)).save(good, format="JPEG")
                    originals = {p.name: p.read_bytes() for p in (bad, good)}
                    original_getexif = Image.Image.getexif

                    def selective_getexif(image):
                        # Pillow clears filename when decoding an open stream.
                        # Synthetic pixel values distinguish this bad fixture.
                        if image.getpixel((0, 0))[0] < 100:
                            raise failure("malformed camera EXIF")
                        return original_getexif(image)

                    with mock.patch.object(Image.Image, "getexif", selective_getexif):
                        records, errors = MODULE.inventory(root, verify_decode=True)
                    self.assertEqual(
                        errors,
                        [f"JPEG decode failed: {bad.name}: {failure.__name__}"],
                    )
                    self.assertEqual(len(records), 2)
                    by_path = {record["path"]: record for record in records}
                    self.assertFalse(by_path[bad.name]["jpeg_decodable"])
                    self.assertNotIn("jpeg_display_width", by_path[bad.name])
                    self.assertTrue(by_path[good.name]["jpeg_decodable"])
                    self.assertEqual(
                        (
                            by_path[good.name]["jpeg_display_width"],
                            by_path[good.name]["jpeg_display_height"],
                        ),
                        (12, 8),
                    )
                    self.assertEqual(
                        {p.name: p.read_bytes() for p in (bad, good)}, originals
                    )

    def test_opt_in_decode_checks_exif_pixel_dimensions_against_native_raster(
        self,
    ) -> None:
        """Camera EXIF dimensions must not silently disagree with JPEG pixels."""
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow unavailable; EXIF raster dimensions unverified")

        cases = (
            ("matching", 12, 8, True, False),
            ("stale_crop", 13, 8, False, False),
            ("missing_axis", 12, None, False, False),
            ("zero_axis", 0, 8, False, False),
            ("no_dimensions", None, None, True, False),
            ("ifd0_export", 12, 8, True, True),
        )
        for label, width, height, expected_ok, use_ifd0 in cases:
            with self.subTest(case=label):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    photo = root / f"{label}.JpEg"
                    exif = Image.Exif()
                    exif[274] = 6  # Native 12x8 raster displays as 8x12.
                    dimensions = exif if use_ifd0 else exif.get_ifd(34665)
                    if width is not None:
                        dimensions[40962] = width
                    if height is not None:
                        dimensions[40963] = height
                    Image.new("RGB", (12, 8), (15, 40, 90)).save(
                        photo, format="JPEG", exif=exif
                    )
                    original = photo.read_bytes()

                    records, errors = MODULE.inventory(root, verify_decode=True)
                    self.assertEqual(len(records), 1)
                    record = records[0]
                    # Decodable pixels and scientifically consistent EXIF
                    # metadata are independent acceptance dimensions.
                    self.assertTrue(record["jpeg_decodable"])
                    self.assertEqual(record["jpeg_exif_pixel_width"], width)
                    self.assertEqual(record["jpeg_exif_pixel_height"], height)
                    self.assertEqual(
                        record["jpeg_exif_dimensions_match_raster"],
                        None if width is None and height is None else expected_ok,
                    )
                    self.assertEqual(
                        (record["jpeg_pixel_width"], record["jpeg_pixel_height"]),
                        (12, 8),
                    )
                    self.assertEqual(
                        (
                            record["jpeg_display_width"],
                            record["jpeg_display_height"],
                        ),
                        (8, 12),
                    )
                    self.assertEqual(
                        errors,
                        []
                        if expected_ok
                        else [
                            "EXIF pixel dimensions inconsistent with JPEG raster: "
                            f"{photo.name}"
                        ],
                    )
                    self.assertEqual(photo.read_bytes(), original)

    def test_conflicting_ifd0_and_exif_ifd_dimensions_fail_qc_read_only(self) -> None:
        """A corrected Exif IFD must not hide contradictory IFD0 camera geometry."""
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow unavailable; duplicate EXIF dimensions unverified")

        cases = (
            ("consistent_dual_tags", (12, 8), False),
            ("stale_ifd0_width", (13, 8), True),
            ("stale_ifd0_height", (12, 9), True),
            ("stale_ifd0_both", (13, 9), True),
        )
        for label, ifd0_dimensions, expected_conflict in cases:
            with self.subTest(case=label):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    photo = root / f"{label}.JPG"
                    exif = Image.Exif()
                    exif[40962], exif[40963] = ifd0_dimensions
                    exif.get_ifd(34665).update({40962: 12, 40963: 8})
                    Image.new("RGB", (12, 8), (35, 60, 85)).save(
                        photo, format="JPEG", exif=exif
                    )
                    original = photo.read_bytes()

                    records, errors = MODULE.inventory(root, verify_decode=True)
                    self.assertEqual(len(records), 1)
                    record = records[0]
                    self.assertTrue(record["jpeg_decodable"])
                    # The preferred Exif IFD is individually correct, but an
                    # additional contradictory metadata source fails QC.
                    self.assertEqual(record["jpeg_exif_pixel_width"], 12)
                    self.assertEqual(record["jpeg_exif_pixel_height"], 8)
                    self.assertEqual(
                        record["jpeg_exif_ifd0_dimension_conflict"],
                        expected_conflict,
                    )
                    self.assertEqual(
                        record["jpeg_exif_dimensions_match_raster"],
                        not expected_conflict,
                    )
                    self.assertEqual(
                        errors,
                        [
                            "conflicting EXIF pixel dimensions between IFD0 and Exif IFD: "
                            f"{photo.name}"
                        ]
                        if expected_conflict
                        else [],
                    )
                    self.assertEqual(
                        json.loads(json.dumps(records))[0]["jpeg_decodable"], True
                    )
                    self.assertEqual(photo.read_bytes(), original)

    def test_malformed_exif_pixel_dimensions_have_json_safe_qc_evidence(self) -> None:
        """Noninteger camera EXIF dimensions cannot crash the inventory manifest."""
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow unavailable; malformed EXIF types unverified")

        samples = (
            ("bytes_width", b"\x04\xff", 8),
            ("tuple_width", (12, 13), 8),
            ("string_width", "12", 8),
            ("float_width", 12.5, 8),
            ("bytes_height", 12, b"\xfe"),
        )
        for label, width, height in samples:
            with self.subTest(case=label):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    photo = root / f"{label}.JPEG"
                    exif = Image.Exif()
                    dimensions = exif.get_ifd(34665)
                    dimensions[40962] = width
                    dimensions[40963] = height
                    Image.new("RGB", (12, 8), (25, 80, 120)).save(
                        photo, format="JPEG", exif=exif
                    )
                    original = photo.read_bytes()

                    records, errors = MODULE.inventory(root, verify_decode=True)
                    self.assertEqual(len(records), 1)
                    record = records[0]
                    self.assertTrue(record["jpeg_decodable"])
                    self.assertEqual(record["jpeg_exif_dimensions_match_raster"], False)
                    self.assertEqual(
                        record["jpeg_exif_pixel_width"],
                        width if type(width) is int else None,
                    )
                    self.assertEqual(
                        record["jpeg_exif_pixel_height"],
                        height if type(height) is int else None,
                    )
                    self.assertEqual(
                        record["jpeg_exif_pixel_width_invalid_type"],
                        type(width).__name__ if type(width) is not int else None,
                    )
                    self.assertEqual(
                        record["jpeg_exif_pixel_height_invalid_type"],
                        type(height).__name__ if type(height) is not int else None,
                    )
                    self.assertEqual(
                        errors,
                        [f"EXIF pixel dimensions inconsistent with JPEG raster: {photo.name}"],
                    )
                    self.assertTrue(json.loads(json.dumps(records))[0]["jpeg_decodable"])
                    self.assertEqual(photo.read_bytes(), original)

    def test_boolean_exif_orientation_is_not_raster_geometry(self) -> None:
        """True is numerically 1, but a boolean EXIF tag cannot certify orientation."""
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow unavailable; boolean EXIF orientation QC unverified")

        original_getexif = Image.Image.getexif
        for orientation in (True, False):
            with self.subTest(orientation=orientation), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                photo = root / "camera.JPG"
                Image.new("RGB", (12, 8), (20, 60, 100)).save(photo, format="JPEG")
                original = photo.read_bytes()

                def forged_exif(image):
                    exif = original_getexif(image)
                    exif[274] = orientation
                    return exif

                with mock.patch.object(Image.Image, "getexif", forged_exif):
                    records, errors = MODULE.inventory(root, verify_decode=True)

                self.assertEqual(
                    errors, ["JPEG decode failed: camera.JPG: ValueError"]
                )
                self.assertEqual(len(records), 1)
                self.assertTrue(records[0]["jpeg_boundary_markers"])
                self.assertFalse(records[0]["jpeg_decodable"])
                self.assertNotIn("jpeg_exif_orientation", records[0])
                self.assertNotIn("jpeg_display_width", records[0])
                self.assertEqual(photo.read_bytes(), original)

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
            original_open = MODULE._open_camera_file

            def selective_open(path: Path, *args: object, **kwargs: object):
                if path == blocked:
                    raise PermissionError("fixture is locked")
                return original_open(path, *args, **kwargs)

            with mock.patch.object(MODULE, "_open_camera_file", selective_open):
                records, errors = MODULE.inventory(root)
            self.assertEqual([record["path"] for record in records], ["good.jpeg"])
            self.assertEqual(errors, ["cannot read JPEG fixture: blocked.jpg: PermissionError"])
            self.assertEqual(blocked.read_bytes(), b"\xff\xd8blocked\xff\xd9")

    def test_only_unreadable_jpeg_reports_read_error_not_empty_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            blocked = root / "locked.JPG"
            blocked.write_bytes(bytes.fromhex("ffd8") + b"payload" + bytes.fromhex("ffd9"))
            original_open = MODULE._open_camera_file

            def deny_fixture(path: Path, *args: object, **kwargs: object):
                if path == blocked:
                    raise PermissionError("camera file locked")
                return original_open(path, *args, **kwargs)

            with mock.patch.object(MODULE, "_open_camera_file", deny_fixture):
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
            original_open = MODULE._open_camera_file
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

            with mock.patch.object(Path, "stat", changed_stat), mock.patch.object(MODULE, "_open_camera_file", observed_open):
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
            original_open = MODULE._open_camera_file

            def substituted_open(path: Path, *args: object, **kwargs: object):
                if path == photo:
                    return original_open(private, *args, **kwargs)
                return original_open(path, *args, **kwargs)

            with mock.patch.object(MODULE, "_open_camera_file", substituted_open):
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
            original_open = MODULE._open_camera_file
            opened = 0

            def substituted_decode_open(path: Path, *args: object, **kwargs: object):
                nonlocal opened
                if path == photo:
                    opened += 1
                    if opened == 2:
                        return original_open(private, *args, **kwargs)
                return original_open(path, *args, **kwargs)

            with mock.patch.object(MODULE, "_open_camera_file", substituted_decode_open):
                records, errors = MODULE.inventory(root, verify_decode=True)
            self.assertEqual(opened, 2)
            self.assertEqual(len(records), 1)
            self.assertTrue(records[0]["jpeg_boundary_markers"])
            self.assertFalse(records[0]["jpeg_decodable"])
            self.assertNotIn("jpeg_display_width", records[0])
            self.assertEqual(errors, ["JPEG decode failed: approved.JPG: ValueError"])
            self.assertEqual(photo.read_bytes(), approved_bytes)
            self.assertEqual(private.read_bytes(), private_bytes)

    def test_pixel_decode_rejects_same_size_rewrite_with_unchanged_windows_fingerprint(self) -> None:
        """Pixel metadata must not be attached to bytes replaced after manifest hashing."""
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow unavailable; byte-identity decode guard unverified")
        import os

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            photo = root / "approved.JPG"
            replacement = root / "replacement.png"
            Image.new("RGB", (12, 8), (0, 0, 0)).save(photo, format="JPEG")
            Image.new("RGB", (12, 8), (255, 255, 255)).save(replacement, format="JPEG")
            original_bytes = photo.read_bytes()
            replacement_bytes = replacement.read_bytes()
            self.assertNotEqual(original_bytes, replacement_bytes)
            self.assertEqual(len(original_bytes), len(replacement_bytes))
            original_stat = photo.stat()
            real_image_open = Image.open
            modified = False

            def rewrite_before_decode(stream, *args, **kwargs):
                nonlocal modified
                if not modified:
                    modified = True
                    # Synthetic temporary fixture only: emulate a same-size
                    # in-place rewrite with an unchanged Windows stat tuple.
                    with photo.open("r+b") as writer:
                        writer.write(replacement_bytes)
                    os.utime(
                        photo,
                        ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns),
                    )
                return real_image_open(stream, *args, **kwargs)

            def windows_fingerprint(stat):
                return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns

            with (
                mock.patch.object(MODULE, "_file_fingerprint", windows_fingerprint),
                mock.patch.object(Image, "open", rewrite_before_decode),
            ):
                records, errors = MODULE.inventory(root, verify_decode=True)
            self.assertTrue(modified)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["path"], "approved.JPG")
            self.assertFalse(records[0]["jpeg_decodable"])
            self.assertNotIn("jpeg_display_width", records[0])
            self.assertEqual(
                errors, ["JPEG decode failed: approved.JPG: ValueError"]
            )
            self.assertEqual(photo.read_bytes(), replacement_bytes)

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

    def test_simulated_windows_junction_root_and_parent_are_rejected(self) -> None:
        """Refuse junctions even when pathlib does not classify them as symlinks."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            junction = root / "junction"
            fixtures = junction / "fixtures"
            fixtures.mkdir(parents=True)
            original = bytes.fromhex("ffd8") + b"unchanged" + bytes.fromhex("ffd9")
            camera = fixtures / "camera.JPG"
            camera.write_bytes(original)

            def simulate_junction(path: Path) -> bool:
                return path == junction

            with mock.patch.object(Path, "is_junction", simulate_junction, create=True):
                for candidate in (junction, fixtures):
                    with self.subTest(candidate=candidate):
                        records, errors = MODULE.inventory(candidate)
                        self.assertEqual(records, [])
                        self.assertEqual(errors, [
                            "camera fixture directory must not be a symbolic link (including parent components)"
                        ])
                stderr = io.StringIO()
                with mock.patch("sys.argv", [str(SCRIPT), str(fixtures)]):
                    with contextlib.redirect_stderr(stderr):
                        with self.assertRaises(SystemExit) as caught:
                            MODULE.main()
                self.assertEqual(caught.exception.code, 2)
                self.assertIn("including parent components", stderr.getvalue())
            self.assertEqual(camera.read_bytes(), original)

    def test_simulated_windows_junction_subdirectory_is_not_traversed(self) -> None:
        """Never count linked external camera files as approved scientific fixtures."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            junction = root / "linked-camera-library"
            junction.mkdir()
            protected = junction / "outside.JPG"
            original = bytes.fromhex("ffd8") + b"external" + bytes.fromhex("ffd9")
            protected.write_bytes(original)
            accepted = root / "approved.JPG"
            accepted.write_bytes(bytes.fromhex("ffd8") + b"approved" + bytes.fromhex("ffd9"))

            def simulate_junction(path: Path) -> bool:
                return path == junction

            with mock.patch.object(Path, "is_junction", simulate_junction, create=True):
                records, errors = MODULE.inventory(root)
            self.assertEqual([record["path"] for record in records], ["approved.JPG"])
            self.assertEqual(errors, [
                "junction directory not inspected: linked-camera-library"
            ])
            self.assertEqual(protected.read_bytes(), original)

    def test_ntfs_junction_fallback_on_python_without_is_junction(self) -> None:
        """Python 3.11 acceptance must reject mount-point reparse tags too."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            junction = root / "junction"
            junction.mkdir()
            original = bytes.fromhex("ffd8") + b"protected" + bytes.fromhex("ffd9")
            camera = junction / "camera.JPG"
            camera.write_bytes(original)
            original_lstat = Path.lstat

            def simulate_ntfs_mountpoint(path: Path, *args: object, **kwargs: object):
                if path == junction:
                    return mock.Mock(st_mode=0o040755, st_reparse_tag=0xA0000003)
                return original_lstat(path, *args, **kwargs)

            with mock.patch.object(Path, "is_junction", None, create=True):
                with mock.patch.object(Path, "lstat", simulate_ntfs_mountpoint):
                    self.assertTrue(MODULE._is_windows_junction(junction))
                    self.assertFalse(MODULE._is_windows_junction(root))
                    records, errors = MODULE.inventory(junction)
            self.assertEqual(records, [])
            self.assertEqual(errors, [
                "camera fixture directory must not be a symbolic link (including parent components)"
            ])
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

    def test_windows_trailing_dot_or_space_jpegs_are_not_silently_skipped(self) -> None:
        """A POSIX camera export with Win32-normalized JPEG names must fail QC."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            names = ("camera.JPG.", "other.jpeg ")
            for name in names:
                try:
                    (root / name).write_bytes(b"\xff\xd8" + name.encode("utf-8") + b"\xff\xd9")
                except OSError:
                    self.skipTest("Trailing-dot/space filenames unavailable on this filesystem")
            if {path.name for path in root.iterdir()} != set(names):
                self.skipTest("Filesystem normalized trailing-dot/space filenames")
            records, errors = MODULE.inventory(root)
            self.assertEqual({record["path"] for record in records}, set(names))
            self.assertEqual({record["extension"] for record in records}, {".jpg", ".jpeg"})
            for name in names:
                self.assertIn(f"Windows trailing dot/space path component: {name}", errors)
                self.assertEqual((root / name).read_bytes(),
                                 b"\xff\xd8" + name.encode("utf-8") + b"\xff\xd9")
            self.assertNotIn("no JPEG-family fixtures found", errors)

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

    def test_fractional_exif_exposure_qc_read_only(self) -> None:
        """Preserve fractional precision; reject malformed and orphaned EXIF tags."""
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow unavailable; EXIF fractional exposure QC unverified")

        original_get_ifd = Image.Exif.get_ifd
        cases = (
            (
                "valid padded fraction",
                {36867: "2026:04:03 14:25:30", 37521: b"000123\x00"},
                "000123",
                False,
                False,
                [],
            ),
            (
                "malformed fraction",
                {36867: "2026:04:03 14:25:30", 37521: b"1\x002"},
                None,
                True,
                False,
                ["invalid EXIF camera exposure time metadata: CAMERA.JPG"],
            ),
            (
                "orphan fraction",
                {37521: "123"},
                "123",
                False,
                True,
                [
                    "EXIF camera fractional seconds without original exposure time: "
                    "CAMERA.JPG"
                ],
            ),
        )
        for label, exif_tags, fraction, malformed, orphan, expected_errors in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                path = root / "CAMERA.JPG"
                Image.new("RGB", (12, 8), (30, 70, 90)).save(path, format="JPEG")
                original = path.read_bytes()

                def forged_ifd(exif, tag):
                    if tag == 34665:
                        return exif_tags
                    return original_get_ifd(exif, tag)

                with mock.patch.object(Image.Exif, "get_ifd", forged_ifd):
                    records, errors = MODULE.inventory(root, verify_decode=True)

                self.assertEqual(errors, expected_errors)
                self.assertEqual(len(records), 1)
                record = records[0]
                self.assertTrue(record["jpeg_decodable"])
                self.assertEqual(record["jpeg_exif_subsec_time_original"], fraction)
                self.assertEqual(
                    record["jpeg_exif_subsec_time_original_malformed"], malformed
                )
                self.assertEqual(
                    record["jpeg_exif_subsec_without_datetime_original"], orphan
                )
                self.assertEqual(
                    record["jpeg_exif_capture_timezone_unknown"], not orphan
                )
                self.assertEqual(path.read_bytes(), original)
                json.dumps(records, allow_nan=False)


    def test_saved_camera_manifest_detects_mutated_added_and_missing_originals(self) -> None:
        """Actual CLI pre/post checks must fail closed without rewriting sources."""
        import subprocess
        import sys

        with tempfile.TemporaryDirectory() as directory:
            staging = Path(directory)
            camera = staging / "approved originals"
            camera.mkdir()
            first = camera / "Sony DSC_0001.JPG"
            second = camera / "Canon IMG_0002.jpeg"
            first_bytes = bytes.fromhex("ffd8") + b"source-one" + bytes.fromhex("ffd9")
            second_bytes = bytes.fromhex("ffd8") + b"source-two" + bytes.fromhex("ffd9")
            first.write_bytes(first_bytes)
            second.write_bytes(second_bytes)
            manifest = staging / "baseline-camera.json"

            command = [sys.executable, str(SCRIPT), str(camera)]
            baseline_run = subprocess.run(command, capture_output=True, text=True, check=False)
            self.assertEqual(baseline_run.returncode, 0, baseline_run.stderr)
            manifest.write_text(baseline_run.stdout, encoding="utf-8")

            def compare() -> tuple[int, list[str]]:
                result = subprocess.run(
                    [*command, "--compare-manifest", str(manifest)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                return result.returncode, json.loads(result.stdout)["errors"]

            code, errors = compare()
            self.assertEqual((code, errors), (0, []))
            # Changing data while preserving file length must invalidate the
            # original SHA-256 rather than passing a size-only acceptance.
            first.write_bytes(first_bytes.replace(b"one", b"two"))
            code, errors = compare()
            self.assertEqual(code, 1)
            self.assertIn(
                "source JPEG bytes changed since baseline: 'Sony DSC_0001.JPG'", errors
            )
            first.write_bytes(first_bytes)
            extra = camera / "unexpected.JPEG"
            extra.write_bytes(bytes.fromhex("ffd8") + b"new" + bytes.fromhex("ffd9"))
            code, errors = compare()
            self.assertEqual(code, 1)
            self.assertIn(
                "source JPEG added since baseline: 'unexpected.JPEG'", errors
            )
            extra.unlink()
            second.unlink()
            code, errors = compare()
            self.assertEqual(code, 1)
            self.assertIn(
                "source JPEG missing since baseline: 'Canon IMG_0002.jpeg'", errors
            )
            self.assertEqual(first.read_bytes(), first_bytes)

    def test_pinned_baseline_detects_coedited_camera_source_and_manifest(self) -> None:
        """An independently recorded digest must detect edits hidden in baseline JSON."""
        import hashlib
        import subprocess
        import sys

        with tempfile.TemporaryDirectory() as directory:
            staging = Path(directory)
            camera = staging / "camera originals"
            camera.mkdir()
            photo = camera / "DSC_0001.JPG"
            original = b"\xff\xd8capture-original\xff\xd9"
            altered = b"\xff\xd8capture-modified\xff\xd9"
            self.assertEqual(len(original), len(altered))
            photo.write_bytes(original)
            command = [sys.executable, str(SCRIPT), str(camera)]
            baseline_run = subprocess.run(
                command, capture_output=True, text=True, check=False
            )
            self.assertEqual(baseline_run.returncode, 0, baseline_run.stderr)
            baseline_path = staging / "baseline.json"
            baseline_path.write_bytes(baseline_run.stdout.encode("utf-8"))
            independent_digest = hashlib.sha256(baseline_path.read_bytes()).hexdigest()

            def compare(*extra: str) -> subprocess.CompletedProcess[str]:
                return subprocess.run(
                    [*command, "--compare-manifest", str(baseline_path), *extra],
                    capture_output=True,
                    text=True,
                    check=False,
                )

            verified = compare("--expected-manifest-sha256", independent_digest.upper())
            self.assertEqual(verified.returncode, 0, verified.stderr)
            self.assertEqual(json.loads(verified.stdout)["errors"], [])

            # Rewriting the saved baseline to match a changed camera capture
            # defeats an unpinned source comparison, but not the independent hash.
            photo.write_bytes(altered)
            rewritten = json.loads(baseline_path.read_text(encoding="utf-8"))
            rewritten["files"][0]["sha256"] = hashlib.sha256(altered).hexdigest()
            baseline_path.write_text(json.dumps(rewritten), encoding="utf-8")
            self.assertEqual(compare().returncode, 0)
            rejected = compare("--expected-manifest-sha256", independent_digest)
            self.assertEqual(rejected.returncode, 1, rejected.stderr)
            self.assertIn(
                "baseline JPEG manifest SHA-256 mismatch",
                json.loads(rejected.stdout)["errors"][0],
            )
            for invalid in ("0" * 63, "z" * 64):
                with self.subTest(invalid=invalid):
                    failure = compare("--expected-manifest-sha256", invalid)
                    self.assertEqual(failure.returncode, 2)
                    self.assertIn("64 hexadecimal digits", failure.stderr)
            missing_baseline = subprocess.run(
                [*command, "--expected-manifest-sha256", independent_digest],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(missing_baseline.returncode, 2)
            self.assertIn("requires --compare-manifest", missing_baseline.stderr)
            self.assertEqual(photo.read_bytes(), altered)

    def test_cli_camera_baseline_stays_outside_source_tree_and_unlinked(self) -> None:
        """A camera inventory must not trust redirected or in-tree evidence."""
        import subprocess
        import sys

        with tempfile.TemporaryDirectory() as directory:
            staging = Path(directory)
            camera = staging / "approved-camera-originals"
            camera.mkdir()
            original = b"\xff\xd8original-camera-capture\xff\xd9"
            photo = camera / "DSC_0001.JPG"
            photo.write_bytes(original)
            records, errors = MODULE.inventory(camera.resolve())
            self.assertEqual(errors, [])

            evidence = staging / "evidence"
            evidence.mkdir()
            baseline = evidence / "baseline.json"
            baseline.write_text(
                json.dumps(
                    {"root": str(camera.resolve()), "files": records, "errors": []}
                ),
                encoding="utf-8",
            )
            command = [
                sys.executable,
                str(SCRIPT),
                str(camera),
                "--compare-manifest",
            ]

            def compare(path: Path) -> subprocess.CompletedProcess[str]:
                return subprocess.run(
                    [*command, str(path)],
                    capture_output=True,
                    text=True,
                    check=False,
                )

            verified = compare(baseline)
            self.assertEqual(verified.returncode, 0, verified.stderr)
            self.assertEqual(json.loads(verified.stdout)["errors"], [])

            # Even a valid inventory must never live among immutable images.
            embedded = camera / "baseline.json"
            embedded.write_bytes(baseline.read_bytes())
            denied = compare(embedded)
            self.assertEqual(denied.returncode, 2)
            self.assertIn("outside the camera fixture", denied.stderr)

            linked_file = staging / "linked-baseline.json"
            try:
                linked_file.symlink_to(baseline)
            except (OSError, NotImplementedError):
                pass  # Windows without symlink privilege still tests in-tree safety.
            else:
                denied = compare(linked_file)
                self.assertEqual(denied.returncode, 2)
                self.assertIn("symbolic link or junction", denied.stderr)

            linked_parent = staging / "linked-evidence"
            try:
                linked_parent.symlink_to(evidence, target_is_directory=True)
            except (OSError, NotImplementedError):
                pass
            else:
                denied = compare(linked_parent / "baseline.json")
                self.assertEqual(denied.returncode, 2)
                self.assertIn("symbolic link or junction", denied.stderr)

            self.assertEqual(photo.read_bytes(), original)
            self.assertTrue(baseline.read_text(encoding="utf-8").startswith("{"))

    def test_baseline_reader_rejects_nonregular_and_changed_files(self) -> None:
        """A named pipe or substituted baseline must not hang or certify acceptance."""
        import os

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline = root / "baseline.json"
            payload = b'{"files": []}'
            baseline.write_bytes(payload)
            self.assertEqual(MODULE._read_baseline_manifest(baseline), payload)
            with self.assertRaisesRegex(ValueError, "not a regular file"):
                MODULE._read_baseline_manifest(root)

            # Simulate replacement between path.stat() and opening the handle.
            substitute = root / "substitute.json"
            substitute.write_bytes(b'{"files": [1]}')
            original_open = os.open

            def substituted_open(path, flags):
                self.assertEqual(path, baseline)
                return original_open(substitute, flags)

            with mock.patch.object(MODULE.os, "open", side_effect=substituted_open):
                with self.assertRaisesRegex(ValueError, "changed before reading"):
                    MODULE._read_baseline_manifest(baseline)
            self.assertEqual(baseline.read_bytes(), payload)

    def test_cli_rejects_fifo_baseline_without_blocking(self) -> None:
        import os
        import subprocess
        import sys

        if not hasattr(os, "mkfifo"):
            self.skipTest("FIFO creation unavailable on this platform")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            camera = root / "camera"
            camera.mkdir()
            image = camera / "approved.JPG"
            original = bytes.fromhex("ffd8") + b"capture" + bytes.fromhex("ffd9")
            image.write_bytes(original)
            baseline = root / "baseline.json"
            try:
                os.mkfifo(baseline)
            except OSError:
                self.skipTest("Filesystem does not support FIFOs")
            result = subprocess.run(
                [sys.executable, str(SCRIPT), str(camera),
                 "--compare-manifest", str(baseline)],
                capture_output=True, text=True, check=False, timeout=10,
            )
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn(
                "cannot read baseline JPEG manifest: ValueError",
                json.loads(result.stdout)["errors"],
            )
            self.assertEqual(image.read_bytes(), original)

    def test_cli_rejects_ambiguous_baseline_json_even_when_digest_matches(self) -> None:
        """Duplicate JSON members must not conceal a contradictory source record."""
        import hashlib
        import subprocess
        import sys

        with tempfile.TemporaryDirectory() as directory:
            staging = Path(directory)
            camera = staging / "camera"
            camera.mkdir()
            photo = camera / "CAMERA.JPG"
            original = bytes.fromhex("ffd8") + b"capture" + bytes.fromhex("ffd9")
            photo.write_bytes(original)
            records, errors = MODULE.inventory(camera.resolve())
            self.assertEqual(errors, [])
            baseline = staging / "baseline.json"
            valid = json.dumps(
                {"root": str(camera.resolve()), "files": records, "errors": []}
            )
            command = [
                sys.executable, str(SCRIPT), str(camera),
                "--compare-manifest", str(baseline),
            ]

            def compare(payload: str) -> tuple[int, list[str]]:
                baseline.write_bytes(payload.encode("utf-8"))
                digest = hashlib.sha256(baseline.read_bytes()).hexdigest()
                result = subprocess.run(
                    [*command, "--expected-manifest-sha256", digest],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                return result.returncode, json.loads(result.stdout)["errors"]

            self.assertEqual(compare(valid), (0, []))
            cases = (
                '{"errors": ["source unreadable"], ' + valid[1:],
                valid.replace('"sha256":', '"sha256": "invalid", "sha256":', 1),
                valid[:-1] + ', "qc": NaN}',
                valid[:-1] + ', "qc": Infinity}',
                valid[:-1] + ', "qc": -Infinity}',
            )
            for payload in cases:
                with self.subTest(payload=payload):
                    self.assertNotEqual(payload, valid)
                    code, errors = compare(payload)
                    self.assertEqual(code, 1)
                    self.assertIn("cannot read baseline JPEG manifest: ValueError", errors)
            self.assertEqual(photo.read_bytes(), original)

    def test_duplicate_current_records_cannot_mask_altered_camera_source(self) -> None:
        """Reject a duplicated scanner path instead of silently taking its last row."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            original = b"\xff\xd8camera-original\xff\xd9"
            photo = root / "CAMERA.JPG"
            photo.write_bytes(original)
            records, errors = MODULE.inventory(root)
            self.assertEqual(errors, [])
            baseline = {"root": str(root), "files": records, "errors": []}
            self.assertEqual(
                MODULE.compare_source_manifest(root, records, baseline), []
            )

            changed = {**records[0], "sha256": "0" * 64}
            for current in ([records[0], records[0]], [changed, records[0]]):
                with self.subTest(current=current):
                    self.assertEqual(
                        MODULE.compare_source_manifest(root, current, baseline),
                        ["current JPEG inventory contains duplicate source-file paths"],
                    )

            self.assertEqual(
                MODULE.compare_source_manifest(
                    root, [{**records[0], "path": None}], baseline
                ),
                ["current JPEG inventory contains malformed source-file evidence"],
            )
            self.assertEqual(photo.read_bytes(), original)

    def test_untrusted_camera_manifest_is_not_accepted_as_immutable_evidence(self) -> None:
        """Malformed, duplicated or wrong-root baselines cannot certify source QC."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            original = root / "CAMERA.JPG"
            original.write_bytes(bytes.fromhex("ffd8") + b"unaltered" + bytes.fromhex("ffd9"))
            records, errors = MODULE.inventory(root)
            self.assertEqual(errors, [])
            baseline = {"root": str(root), "files": records, "errors": []}
            self.assertEqual(MODULE.compare_source_manifest(root, records, baseline), [])

            def check(changes: dict[str, object]) -> None:
                tampered = {**baseline, **changes}
                self.assertNotEqual(
                    MODULE.compare_source_manifest(root, records, tampered), []
                )

            check({"root": str(root.parent)})
            check({"errors": ["source unreadable"]})
            check({"files": [records[0], records[0]]})
            check({"files": [{**records[0], "path": "../CAMERA.JPG"}]})
            check({"files": [{**records[0], "path": "folder\\CAMERA.JPG"}]})
            check({"files": [{**records[0], "bytes": True}]})
            check({"files": [{**records[0], "sha256": "0" * 63}]})
            check({"files": [{**records[0], "jpeg_boundary_markers": False}]})
            check({"files": []})
            check({"files": "not an inventory"})
            check({"files": [None]})
            self.assertEqual(original.read_bytes(), bytes.fromhex("ffd8") + b"unaltered" + bytes.fromhex("ffd9"))


if __name__ == "__main__":
    unittest.main()
