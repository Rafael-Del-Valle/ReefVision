"""Reproducible acquisition diagnostics using managed scientific images."""

from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC
from typing import Any

from reefvision.config import Settings
from reefvision.db.models import ImageAsset
from reefvision.domain.errors import ValidationError
from reefvision.schemas.quality_control import AcquisitionQualityThresholds
from reefvision.services.mask_measurements import MEASUREMENT_CALIBRATION_KEY
from reefvision.services.skeletonization import skeleton_calibration_payload
from reefvision.storage.acquisition_quality import (
    acquisition_image_path,
    measure_acquisition_pixels,
)
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.storage.images import recover_explicit_exif_capture_time

METHOD = "acquisition-luminance-0001"
RULE_ID = "acquisition_image_review"
EXIF_FIELDS = ("Make", "Model", "LensModel", "FocalLength", "ExposureTime", "FNumber")


@dataclass(frozen=True, slots=True)
class AcquisitionFinding:
    check: str
    title: str
    explanation: str
    values: dict[str, Any]


def _camera_metadata(image: ImageAsset) -> dict[str, str]:
    metadata = image.metadata_json or {}
    value = metadata.get("exif")
    exif = value if isinstance(value, dict) and not metadata.get("exif_warning") else {}
    return {
        key: str(exif[key]).strip()
        for key in EXIF_FIELDS
        if exif.get(key) is not None and str(exif[key]).strip()
    }


def _capture_time(image: ImageAsset) -> str | None:
    stored = image.capture_timestamp
    if stored is None:
        return None
    if stored.utcoffset() is None:
        stored = recover_explicit_exif_capture_time(stored, image.metadata_json or {})
    return stored.astimezone(UTC).isoformat() if stored is not None else None


def metadata_evidence(image: ImageAsset, images: dict[str, ImageAsset]) -> dict[str, Any]:
    raw = (image.metadata_json or {}).get(MEASUREMENT_CALIBRATION_KEY)
    portable_calibration = raw
    if isinstance(raw, dict) and raw.get("profile_source_image_id"):
        profile = images.get(str(raw["profile_source_image_id"]))
        portable_calibration = {
            **raw,
            "profile_source_image_id": None,
            "profile_source_sha256": profile.sha256 if profile else None,
        }
    metadata = {
        "camera_metadata": _camera_metadata(image),
        "capture_time_utc": _capture_time(image),
        "calibration_sha256": canonical_json_sha256(portable_calibration) if raw else None,
        "width_px": image.width_px,
        "height_px": image.height_px,
    }
    return {**metadata, "metadata_sha256": canonical_json_sha256(metadata)}


def _calibration_findings(
    image: ImageAsset,
    camera_metadata: dict[str, str],
    sources: dict[str, ImageAsset],
    thresholds: AcquisitionQualityThresholds,
) -> list[AcquisitionFinding]:
    try:
        calibration = skeleton_calibration_payload(image)
    except ValidationError:
        return [
            AcquisitionFinding(
                "calibration_invalid",
                "Invalid calibration",
                "The recorded calibration cannot be used. Review and save a replacement.",
                {},
            )
        ]
    if calibration is None:
        return (
            [
                AcquisitionFinding(
                    "calibration_missing",
                    "Calibration missing",
                    "The selected acquisition protocol requires a saved calibration.",
                    {},
                )
            ]
            if thresholds.require_calibration
            else []
        )

    differences: dict[str, list[str | int | None]] = {}
    profile_key = calibration.profile_source_image_id
    profile = sources.get(profile_key) if profile_key else None
    if profile_key and profile is None:
        differences["profile_source"] = ["missing", "available"]
    signature = calibration.camera_signature
    expected_width = (
        signature.width_px
        if signature and signature.width_px
        else (profile.width_px if profile else None)
    )
    expected_height = (
        signature.height_px
        if signature and signature.height_px
        else (profile.height_px if profile else None)
    )
    for name, observed, expected in (
        ("width_px", image.width_px, expected_width),
        ("height_px", image.height_px, expected_height),
    ):
        if expected is not None and expected != observed:
            differences[name] = [observed, expected]

    if signature:
        for exif, expected_text in (
            ("Make", signature.camera_make),
            ("Model", signature.camera_model),
            ("LensModel", signature.lens_model),
        ):
            observed_text = camera_metadata.get(exif)
            if (
                expected_text
                and observed_text
                and expected_text.casefold() != observed_text.casefold()
            ):
                differences[exif] = [observed_text, expected_text]
    matrix = calibration.perspective_homography
    if matrix:
        p, q, r = matrix[2]
        corners = [p * x + q * y + r for x in (0, image.width_px) for y in (0, image.height_px)]
        if min(corners) <= 0 <= max(corners):
            differences["reference_plane"] = ["horizon crosses image", "finite reference plane"]
    return (
        [
            AcquisitionFinding(
                "calibration_incompatible",
                "Calibration compatibility needs review",
                "The saved calibration disagrees with available image or camera evidence. "
                "A matching signature alone cannot verify the setup.",
                {"differences_observed_then_expected": differences},
            )
        ]
        if differences
        else []
    )


def evaluate_acquisition(
    settings: Settings,
    images: list[ImageAsset],
    project_images: dict[str, ImageAsset],
    thresholds: AcquisitionQualityThresholds,
    check_cancelled: Callable[[], None],
    *,
    expected_sources: dict[str, tuple[str | None, int, int]],
) -> tuple[dict[str, Any], list[tuple[ImageAsset, AcquisitionFinding]]]:
    rows = []
    findings: list[tuple[ImageAsset, AcquisitionFinding]] = []
    aliases: dict[str, list[ImageAsset]] = {}
    for image in sorted(images, key=lambda row: (row.original_filename.casefold(), row.sha256)):
        check_cancelled()
        expected_sha, width, height = expected_sources[image.id]
        signal = measure_acquisition_pixels(
            acquisition_image_path(settings, image.managed_path),
            expected_sha256=expected_sha,
            dimensions=(width, height),
            dark_luma_max=thresholds.dark_luma_max,
            bright_luma_min=thresholds.bright_luma_min,
            check_cancelled=check_cancelled,
        )
        metadata = metadata_evidence(image, project_images)
        row = {
            "filename": image.original_filename,
            "source_sha256": expected_sha,
            "measurements": asdict(signal),
            **metadata,
        }
        rows.append(row)
        observed: list[AcquisitionFinding] = []
        if signal.status != "measured":
            observed.append(
                AcquisitionFinding(
                    "image_signal_unavailable",
                    "Image signal unavailable",
                    "The managed file could not be evaluated for all pixel checks.",
                    {"signal_status": signal.status, "observed_file_sha256": signal.source_sha256},
                )
            )
        for check, title, fraction, cutoff in (
            (
                "dark_clipping",
                "High dark clipping fraction",
                signal.dark_fraction,
                thresholds.dark_luma_max,
            ),
            (
                "bright_clipping",
                "High bright clipping fraction",
                signal.bright_fraction,
                thresholds.bright_luma_min,
            ),
        ):
            if fraction is not None and fraction > thresholds.max_clipped_fraction:
                observed.append(
                    AcquisitionFinding(
                        check,
                        title,
                        "A large fraction of opaque pixels are within a decoded luma clipping "
                        "band. Check lighting and scene content.",
                        {"opaque_pixel_fraction": fraction, "luma_cutoff": cutoff},
                    )
                )
        if signal.sharpness is not None and signal.sharpness < thresholds.min_sharpness:
            observed.append(
                AcquisitionFinding(
                    "low_detail",
                    "Low image detail",
                    "Inspect focus and motion blur. Low-texture scenes can also "
                    "produce a low score.",
                    {
                        "sharpness": signal.sharpness,
                        "evaluated_width_px": signal.sharpness_width_px,
                        "evaluated_height_px": signal.sharpness_height_px,
                    },
                )
            )
        if width < thresholds.min_width_px or height < thresholds.min_height_px:
            observed.append(
                AcquisitionFinding(
                    "dimensions",
                    "Image below minimum dimensions",
                    "Source dimensions are below the selected acquisition protocol.",
                    {"width_px": width, "height_px": height},
                )
            )
        if thresholds.require_capture_time and not metadata["capture_time_utc"]:
            observed.append(
                AcquisitionFinding(
                    "capture_time",
                    "Capture time unavailable",
                    "The recorded metadata has no verifiable timezone-qualified capture time.",
                    {},
                )
            )
        missing_keys = [key for key in ("Make", "Model") if key not in metadata["camera_metadata"]]
        if thresholds.require_camera_metadata and missing_keys:
            observed.append(
                AcquisitionFinding(
                    "camera_metadata",
                    "Camera metadata incomplete",
                    "Camera make and model are required by the selected acquisition protocol.",
                    {"missing_exif_fields": missing_keys},
                )
            )
        observed.extend(
            _calibration_findings(image, metadata["camera_metadata"], project_images, thresholds)
        )
        findings.extend((image, item) for item in observed)
        if signal.decoded_pixels_sha256:
            aliases.setdefault(signal.decoded_pixels_sha256, []).append(image)

    for decoded_hash, group in sorted(aliases.items()):
        if len(group) > 1:
            for image in group:
                findings.append(
                    (
                        image,
                        AcquisitionFinding(
                            "duplicate_pixels",
                            "Identical decoded pixels",
                            "Different source files contain identical decoded RGBA pixels. Review "
                            "acquisition records before counting separate observations.",
                            {
                                "decoded_pixels_sha256": decoded_hash,
                                "matching_source_sha256": sorted(
                                    other.sha256 for other in group if other.id != image.id
                                ),
                            },
                        ),
                    )
                )
    check_cancelled()
    result = {
        "method": METHOD,
        "review_status": "review_required",
        "evaluated_image_count": len(rows),
        "unavailable_image_count": sum(row["measurements"]["status"] != "measured" for row in rows),
        "finding_counts": dict(Counter(item.check for _, item in findings)),
        "thresholds": thresholds.model_dump(mode="json"),
        "images": rows,
    }
    return {**result, "evidence_sha256": canonical_json_sha256(result)}, findings
