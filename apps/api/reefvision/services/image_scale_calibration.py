"""Automatic and reusable image-scale calibration helpers."""

from __future__ import annotations

import math
from statistics import median, pstdev
from typing import Any, Literal

from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import ImageAsset
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.schemas.image_calibration import (
    ApplyCalibrationProfileRequest,
    CalibrationProfileResponse,
    CalibrationRoi,
    MarkerCalibrationCandidate,
    MarkerCalibrationDetectRequest,
    RulerCalibrationCandidate,
    RulerCalibrationDetectRequest,
)
from reefvision.schemas.measurements import (
    CalibrationCameraSignature,
    MeasurementCalibrationResponse,
    MeasurementCalibrationUpdate,
)
from reefvision.storage.projects import resolve_managed_project_path

MEASUREMENT_CALIBRATION_KEY = "measurement_calibration"
MAX_ANALYSIS_DIMENSION = 1400


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
    return ordered[index]


def _interval_stats(positions: list[float]) -> tuple[float, float, list[float]] | None:
    spacings = [second - first for first, second in zip(positions, positions[1:], strict=False)]
    spacings = [value for value in spacings if value > 1.5]
    if len(spacings) < 2:
        return None
    initial = median(spacings)
    filtered = [value for value in spacings if initial * 0.55 <= value <= initial * 1.6]
    if len(filtered) < 2:
        return None
    interval = median(filtered)
    mean = sum(filtered) / len(filtered)
    cv = pstdev(filtered) / mean if len(filtered) > 1 and mean > 0 else 0.0
    return interval, cv, filtered


def _projection_profile(image: Image.Image, orientation: Literal["horizontal", "vertical"]) -> list[float]:
    width, height = image.size
    pixels = image.load()
    if orientation == "horizontal":
        if width < 5:
            return []
        step = max(1, height // 320)
        return [
            sum(
                abs(2 * int(pixels[x, y]) - int(pixels[x - 1, y]) - int(pixels[x + 1, y]))
                for y in range(0, height, step)
            )
            for x in range(1, width - 1)
        ]
    if height < 5:
        return []
    step = max(1, width // 320)
    return [
        sum(
            abs(2 * int(pixels[x, y]) - int(pixels[x, y - 1]) - int(pixels[x, y + 1]))
            for x in range(0, width, step)
        )
        for y in range(1, height - 1)
    ]


def _peak_positions(profile: list[float]) -> tuple[list[int], list[float], float]:
    if len(profile) < 8:
        return [], [], 0.0
    baseline = median(profile)
    deviations = [abs(value - baseline) for value in profile]
    mad = median(deviations) or max(1.0, baseline * 0.02)
    threshold = baseline + 3.0 * mad
    raw: list[tuple[int, float]] = []
    for index in range(1, len(profile) - 1):
        value = profile[index]
        if value >= threshold and value >= profile[index - 1] and value >= profile[index + 1]:
            raw.append((index + 1, value))
    if not raw:
        return [], [], 0.0

    minimum_gap = max(2, len(profile) // 600)
    merged: list[tuple[int, float]] = []
    for position, score in raw:
        if merged and position - merged[-1][0] <= minimum_gap:
            if score > merged[-1][1]:
                merged[-1] = (position, score)
        else:
            merged.append((position, score))
    prominence = max(0.0, (sum(score for _, score in merged) / len(merged) - baseline) / (6 * mad))
    return [position for position, _ in merged], [score for _, score in merged], prominence


def _analyze_ruler_crop(
    crop: Image.Image,
    *,
    orientation: Literal["horizontal", "vertical"],
    roi: CalibrationRoi,
    roi_supplied: bool,
) -> dict[str, Any] | None:
    original_width, original_height = crop.size
    analysis = crop.convert("L")
    if max(analysis.size) > MAX_ANALYSIS_DIMENSION:
        ratio = MAX_ANALYSIS_DIMENSION / max(analysis.size)
        analysis = analysis.resize(
            (
                max(5, round(analysis.width * ratio)),
                max(5, round(analysis.height * ratio)),
            )
        )
    scale_x = original_width / analysis.width
    scale_y = original_height / analysis.height
    profile = _projection_profile(analysis, orientation)
    positions, strengths, prominence = _peak_positions(profile)
    if len(positions) < 4:
        return None
    axis_scale = scale_x if orientation == "horizontal" else scale_y
    scaled_positions = [float(position) * axis_scale for position in positions]
    stats = _interval_stats(scaled_positions)
    if stats is None:
        return None
    interval, cv, filtered = stats

    strong_cutoff = _percentile(strengths, 0.7)
    strong_positions = [
        position
        for position, strength in zip(scaled_positions, strengths, strict=True)
        if strength >= strong_cutoff
    ]
    major_interval: float | None = None
    major_stats = _interval_stats(strong_positions)
    if major_stats is not None and major_stats[0] >= interval * 1.5 and major_stats[1] <= 0.35:
        major_interval = major_stats[0]

    regularity = max(0.0, 1.0 - min(1.0, cv / 0.35))
    count_score = min(1.0, len(filtered) / 8.0)
    prominence_score = min(1.0, prominence)
    confidence = 0.55 * regularity + 0.3 * count_score + 0.15 * prominence_score
    if not roi_supplied:
        confidence *= 0.88
    confidence = min(0.98, max(0.0, confidence))

    axis_origin = roi.x_min if orientation == "horizontal" else roi.y_min
    absolute_positions = [axis_origin + value for value in scaled_positions]
    warnings = [
        "The detector estimates repeating ruler ticks only; it does not infer mm, cm, or another physical interval."
    ]
    if confidence < 0.7:
        warnings.append("Low-confidence ruler candidate; review the detected interval before applying calibration.")
    if not roi_supplied:
        warnings.append("No ruler ROI was supplied; the detector selected the strongest periodic image band.")
    return {
        "orientation": orientation,
        "roi": roi,
        "base_interval_pixels": interval,
        "major_interval_pixels": major_interval,
        "tick_positions_pixels": absolute_positions,
        "interval_count": len(filtered),
        "interval_coefficient_of_variation": cv,
        "confidence": confidence,
        "warnings": warnings,
    }


def _candidate_bands(width: int, height: int, orientation: str) -> list[CalibrationRoi]:
    bands: list[CalibrationRoi] = []
    if orientation in {"auto", "horizontal"}:
        band_height = max(24.0, height * 0.24)
        for fraction in (0.0, 0.19, 0.38, 0.57, 0.76):
            y_min = min(height - band_height, height * fraction)
            bands.append(CalibrationRoi(x_min=0, y_min=y_min, x_max=width, y_max=y_min + band_height))
    if orientation in {"auto", "vertical"}:
        band_width = max(24.0, width * 0.24)
        for fraction in (0.0, 0.19, 0.38, 0.57, 0.76):
            x_min = min(width - band_width, width * fraction)
            bands.append(CalibrationRoi(x_min=x_min, y_min=0, x_max=x_min + band_width, y_max=height))
    return bands


def _homography_list(matrix: Any) -> list[list[float]]:
    return [[float(matrix[row, column]) for column in range(3)] for row in range(3)]


class ImageScaleCalibrationService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def _image(self, image_id: str) -> ImageAsset:
        image = self.session.get(ImageAsset, image_id)
        if image is None:
            raise NotFoundError("Image not found")
        return image

    def _image_path(self, image: ImageAsset) -> str:
        path = resolve_managed_project_path(self.settings, image.managed_path)
        if not path.is_file():
            raise ValidationError("Managed image content is missing")
        return str(path)

    def _open_image(self, image: ImageAsset) -> Image.Image:
        try:
            with Image.open(self._image_path(image)) as source:
                source.load()
                return source.convert("RGB")
        except (OSError, UnidentifiedImageError) as exc:
            raise ValidationError("Managed image could not be read for calibration") from exc

    def detect_ruler(
        self,
        image_id: str,
        payload: RulerCalibrationDetectRequest,
    ) -> RulerCalibrationCandidate:
        image_asset = self._image(image_id)
        source = self._open_image(image_asset)
        width, height = source.size
        candidates: list[dict[str, Any]] = []
        if payload.roi is not None:
            roi = payload.roi
            if roi.x_max > width or roi.y_max > height:
                raise ValidationError("Calibration ROI cannot extend outside the image")
            crop = source.crop((roi.x_min, roi.y_min, roi.x_max, roi.y_max))
            orientations = (
                ("horizontal", "vertical")
                if payload.orientation == "auto"
                else (payload.orientation,)
            )
            for orientation in orientations:
                candidate = _analyze_ruler_crop(
                    crop,
                    orientation=orientation,
                    roi=roi,
                    roi_supplied=True,
                )
                if candidate is not None:
                    candidates.append(candidate)
        else:
            for roi in _candidate_bands(width, height, payload.orientation):
                crop = source.crop((roi.x_min, roi.y_min, roi.x_max, roi.y_max))
                orientation: Literal["horizontal", "vertical"] = (
                    "horizontal" if roi.x_min == 0 and roi.x_max == width else "vertical"
                )
                candidate = _analyze_ruler_crop(
                    crop,
                    orientation=orientation,
                    roi=roi,
                    roi_supplied=False,
                )
                if candidate is not None:
                    candidates.append(candidate)
        if not candidates:
            raise ValidationError(
                "No sufficiently periodic ruler tick candidate was detected; select a ruler ROI or use manual calibration"
            )
        best = max(candidates, key=lambda item: float(item["confidence"]))
        return RulerCalibrationCandidate(image_id=image_asset.id, **best)

    @staticmethod
    def _aruco_module() -> tuple[Any, Any]:
        try:
            import cv2  # type: ignore[import-not-found]
            import numpy as np  # type: ignore[import-not-found]
        except ImportError as exc:
            raise ValidationError(
                "ArUco/ChArUco calibration requires an OpenCV build with the aruco module"
            ) from exc
        if not hasattr(cv2, "aruco"):
            raise ValidationError(
                "This OpenCV runtime does not include cv2.aruco; install/use an opencv-contrib runtime to enable marker calibration"
            )
        return cv2, np

    @staticmethod
    def _aruco_dictionary(cv2: Any, name: str) -> Any:
        constant = getattr(cv2.aruco, name, None)
        if constant is None:
            raise ValidationError(f"Unsupported ArUco dictionary: {name}")
        return cv2.aruco.getPredefinedDictionary(constant)

    @staticmethod
    def _detect_markers(cv2: Any, frame: Any, dictionary: Any) -> tuple[Any, Any]:
        if hasattr(cv2.aruco, "ArucoDetector"):
            detector = cv2.aruco.ArucoDetector(dictionary)
            corners, ids, _rejected = detector.detectMarkers(frame)
        else:
            corners, ids, _rejected = cv2.aruco.detectMarkers(frame, dictionary)
        return corners, ids

    def detect_marker(
        self,
        image_id: str,
        payload: MarkerCalibrationDetectRequest,
    ) -> MarkerCalibrationCandidate:
        image_asset = self._image(image_id)
        cv2, np = self._aruco_module()
        encoded = np.fromfile(self._image_path(image_asset), dtype=np.uint8)
        frame = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
        if frame is None:
            raise ValidationError("Managed image could not be decoded by OpenCV")
        dictionary = self._aruco_dictionary(cv2, payload.dictionary)
        corners, ids = self._detect_markers(cv2, frame, dictionary)
        if ids is None or len(ids) == 0:
            raise ValidationError("No ArUco/ChArUco markers were detected")

        if payload.kind == "aruco":
            id_values = [int(value) for value in ids.flatten()]
            if payload.marker_id is not None:
                if payload.marker_id not in id_values:
                    raise ValidationError(f"Requested ArUco marker id {payload.marker_id} was not detected")
                index = id_values.index(payload.marker_id)
            else:
                index = max(
                    range(len(corners)),
                    key=lambda item: float(cv2.contourArea(corners[item].reshape(4, 2))),
                )
            marker_id = id_values[index]
            points = corners[index].reshape(4, 2).astype("float32")
            side_pixels = [
                math.hypot(
                    float(points[(edge + 1) % 4][0] - points[edge][0]),
                    float(points[(edge + 1) % 4][1] - points[edge][1]),
                )
                for edge in range(4)
            ]
            mean_side = sum(side_pixels) / 4.0
            if mean_side <= 1:
                raise ValidationError("Detected ArUco marker is too small for calibration")
            side_cv = pstdev(side_pixels) / mean_side
            target = np.array(
                [
                    [0.0, 0.0],
                    [payload.marker_length, 0.0],
                    [payload.marker_length, payload.marker_length],
                    [0.0, payload.marker_length],
                ],
                dtype=np.float32,
            )
            homography = cv2.getPerspectiveTransform(points, target)
            confidence = max(0.0, min(0.99, 1.0 - min(1.0, side_cv / 0.35)))
            calibration = MeasurementCalibrationUpdate(
                distance_per_pixel=payload.marker_length / mean_side,
                unit=payload.unit,
                source="aruco",
                reference_length=payload.marker_length,
                reference_pixel_length=mean_side,
                confidence=confidence,
                detector=f"opencv-aruco:{payload.dictionary}",
                perspective_homography=_homography_list(homography),
                reference_plane_only=True,
                notes=(
                    "ArUco homography maps image pixels to physical coordinates on the marker plane only."
                ),
            )
            return MarkerCalibrationCandidate(
                image_id=image_asset.id,
                method="aruco",
                marker_id=marker_id,
                detected_corner_count=4,
                confidence=confidence,
                calibration=calibration,
                corners_pixels=[[float(value) for value in point] for point in points],
                warnings=[
                    "Perspective correction is valid only for objects lying on the marker reference plane."
                ],
            )

        squares_x = int(payload.charuco_squares_x or 0)
        squares_y = int(payload.charuco_squares_y or 0)
        square_length = float(payload.charuco_square_length or 0)
        try:
            board = cv2.aruco.CharucoBoard(
                (squares_x, squares_y), square_length, payload.marker_length, dictionary
            )
        except TypeError:
            board = cv2.aruco.CharucoBoard_create(
                squares_x, squares_y, square_length, payload.marker_length, dictionary
            )
        _count, charuco_corners, charuco_ids = cv2.aruco.interpolateCornersCharuco(
            corners, ids, frame, board
        )
        if charuco_ids is None or charuco_corners is None or len(charuco_ids) < 4:
            raise ValidationError("ChArUco calibration requires at least four detected chessboard corners")
        if hasattr(board, "getChessboardCorners"):
            board_corners = board.getChessboardCorners()
        else:
            board_corners = board.chessboardCorners
        ids_flat = [int(value) for value in charuco_ids.flatten()]
        image_points = charuco_corners.reshape(-1, 2).astype("float32")
        physical_points = np.array(
            [[float(board_corners[index][0]), float(board_corners[index][1])] for index in ids_flat],
            dtype=np.float32,
        )
        homography, inliers = cv2.findHomography(image_points, physical_points, 0)
        if homography is None:
            raise ValidationError("Could not estimate a ChArUco plane homography")
        interval_scales: list[float] = []
        for first in range(len(ids_flat)):
            for second in range(first + 1, len(ids_flat)):
                physical_distance = math.hypot(
                    float(physical_points[second][0] - physical_points[first][0]),
                    float(physical_points[second][1] - physical_points[first][1]),
                )
                if not math.isclose(physical_distance, square_length, rel_tol=0.08):
                    continue
                pixel_distance = math.hypot(
                    float(image_points[second][0] - image_points[first][0]),
                    float(image_points[second][1] - image_points[first][1]),
                )
                if pixel_distance > 1:
                    interval_scales.append(physical_distance / pixel_distance)
        if not interval_scales:
            raise ValidationError("Detected ChArUco corners do not contain an adjacent square interval")
        distance_per_pixel = median(interval_scales)
        projected = cv2.perspectiveTransform(image_points.reshape(-1, 1, 2), homography).reshape(-1, 2)
        errors = [
            math.hypot(
                float(projected[index][0] - physical_points[index][0]),
                float(projected[index][1] - physical_points[index][1]),
            )
            for index in range(len(projected))
        ]
        reprojection_ratio = (sum(errors) / len(errors)) / max(square_length, 1e-12)
        inlier_ratio = (
            float(inliers.sum()) / len(inliers) if inliers is not None and len(inliers) else 1.0
        )
        confidence = max(
            0.0,
            min(0.99, min(1.0, len(ids_flat) / 12.0) * inlier_ratio * (1.0 - min(1.0, reprojection_ratio))),
        )
        calibration = MeasurementCalibrationUpdate(
            distance_per_pixel=distance_per_pixel,
            unit=payload.unit,
            source="charuco",
            reference_length=square_length,
            reference_pixel_length=square_length / distance_per_pixel,
            confidence=confidence,
            detector=f"opencv-charuco:{payload.dictionary}",
            perspective_homography=_homography_list(homography),
            reference_plane_only=True,
            notes=(
                "ChArUco homography maps image pixels to physical coordinates on the board plane only."
            ),
        )
        return MarkerCalibrationCandidate(
            image_id=image_asset.id,
            method="charuco",
            marker_id=None,
            detected_corner_count=len(ids_flat),
            confidence=confidence,
            calibration=calibration,
            corners_pixels=[[float(value) for value in point] for point in image_points],
            warnings=[
                "Perspective correction is valid only for objects lying on the ChArUco board plane."
            ],
        )

    def profiles(self, project_id: str) -> list[CalibrationProfileResponse]:
        statement = (
            select(ImageAsset)
            .where(ImageAsset.project_id == project_id)
            .order_by(ImageAsset.updated_at.desc(), ImageAsset.id)
        )
        profiles: list[CalibrationProfileResponse] = []
        seen: set[str] = set()
        for image in self.session.scalars(statement):
            raw = dict(image.metadata_json or {}).get(MEASUREMENT_CALIBRATION_KEY)
            if not isinstance(raw, dict) or not raw.get("profile_name"):
                continue
            try:
                calibration = MeasurementCalibrationUpdate.model_validate(raw)
            except ValueError:
                continue
            profile_name = str(calibration.profile_name)
            normalized = profile_name.casefold()
            if normalized in seen:
                continue
            seen.add(normalized)
            profiles.append(
                CalibrationProfileResponse(
                    project_id=project_id,
                    source_image_id=image.id,
                    profile_name=profile_name,
                    unit=calibration.unit,
                    distance_per_pixel=calibration.distance_per_pixel,
                    width_px=image.width_px,
                    height_px=image.height_px,
                    source=calibration.source,
                    confidence=calibration.confidence,
                    camera_signature=calibration.camera_signature,
                    notes=calibration.notes,
                )
            )
        return profiles

    def prepare_saved_calibration(
        self,
        image_id: str,
        payload: MeasurementCalibrationUpdate,
    ) -> MeasurementCalibrationUpdate:
        image = self._image(image_id)
        data = payload.model_dump(mode="json")
        if payload.profile_name:
            signature = payload.camera_signature or CalibrationCameraSignature()
            signature_data = signature.model_dump()
            signature_data["width_px"] = image.width_px
            signature_data["height_px"] = image.height_px
            data["camera_signature"] = CalibrationCameraSignature(**signature_data).model_dump()
        return MeasurementCalibrationUpdate.model_validate(data)

    def apply_profile(
        self,
        image_id: str,
        payload: ApplyCalibrationProfileRequest,
    ) -> MeasurementCalibrationResponse:
        if not payload.confirm_same_setup:
            raise ValidationError(
                "Applying a calibration profile requires explicit confirmation that camera, lens, focus, and subject-plane distance are unchanged"
            )
        target = self._image(image_id)
        source = self._image(payload.source_image_id)
        if source.project_id != target.project_id:
            raise ValidationError("Calibration profiles cannot be reused across projects")
        if source.id == target.id:
            raise ValidationError("Target image already owns the selected calibration profile")
        raw = dict(source.metadata_json or {}).get(MEASUREMENT_CALIBRATION_KEY)
        if not isinstance(raw, dict):
            raise ValidationError("Selected profile source image does not have a calibration")
        try:
            calibration = MeasurementCalibrationUpdate.model_validate(raw)
        except ValueError as exc:
            raise ValidationError("Selected calibration profile is invalid") from exc
        if not calibration.profile_name:
            raise ValidationError("Selected calibration is not saved as a reusable profile")
        signature = calibration.camera_signature
        expected_width = signature.width_px if signature and signature.width_px else source.width_px
        expected_height = signature.height_px if signature and signature.height_px else source.height_px
        if target.width_px != expected_width or target.height_px != expected_height:
            raise ValidationError(
                "Calibration profile resolution does not match the target image; recalibrate instead of rescaling the profile"
            )
        copied = calibration.model_dump(mode="json")
        copied.update(
            {
                "source": "camera_profile",
                "profile_source_image_id": source.id,
                "default_depth": (
                    payload.default_depth
                    if payload.default_depth is not None
                    else calibration.default_depth
                ),
                "notes": payload.notes or calibration.notes,
                # A projective warp is view-specific even when scalar setup scale is reused.
                "perspective_homography": None,
                "reference_plane_only": True,
            }
        )
        saved = MeasurementCalibrationUpdate.model_validate(copied)
        metadata = dict(target.metadata_json or {})
        metadata[MEASUREMENT_CALIBRATION_KEY] = saved.model_dump(mode="json")
        target.metadata_json = metadata
        self.session.commit()
        self.session.refresh(target)
        return MeasurementCalibrationResponse(image_id=target.id, **saved.model_dump())
