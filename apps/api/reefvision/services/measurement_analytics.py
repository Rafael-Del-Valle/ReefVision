"""Project-level aggregation for calibrated coral measurements."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from reefvision.config import Settings
from reefvision.db.models import ImageAsset, MaskAnnotation
from reefvision.schemas.measurements import (
    MaskMeasurementResponse,
    MeasurementAggregateGroupResponse,
    ProjectMeasurementSummaryResponse,
)
from reefvision.services.mask_measurements import MaskMeasurementService


def _empty_unit_totals() -> dict[str, float]:
    return {}


@dataclass(slots=True)
class _MeasurementAccumulator:
    mask_count: int = 0
    calibrated_mask_count: int = 0
    area_pixels: int = 0
    perimeter_pixels: float = 0.0
    contained_box_count: int = 0
    total_linear_extension_pixels: float = 0.0
    calibrated_area_by_unit: dict[str, float] = field(default_factory=_empty_unit_totals)
    calibrated_tle_by_unit: dict[str, float] = field(default_factory=_empty_unit_totals)
    surface_area_by_unit: dict[str, float] = field(default_factory=_empty_unit_totals)

    @staticmethod
    def _add_unit(target: dict[str, float], unit: str, value: float) -> None:
        target[unit] = target.get(unit, 0.0) + value

    def add(self, item: MaskMeasurementResponse) -> None:
        self.mask_count += 1
        self.area_pixels += item.area_pixels
        self.perimeter_pixels += item.perimeter_pixels
        self.contained_box_count += item.contained_box_count
        self.total_linear_extension_pixels += item.total_linear_extension_pixels
        if item.calibrated:
            self.calibrated_mask_count += 1
        unit = item.physical_unit
        if unit and item.area_physical is not None:
            self._add_unit(self.calibrated_area_by_unit, unit, item.area_physical)
        if unit and item.total_linear_extension_physical is not None:
            self._add_unit(
                self.calibrated_tle_by_unit,
                unit,
                item.total_linear_extension_physical,
            )
        if unit and item.surface_area_physical is not None:
            self._add_unit(self.surface_area_by_unit, unit, item.surface_area_physical)

    @property
    def density_per_1000_pixels(self) -> float:
        if self.area_pixels <= 0:
            return 0.0
        return self.contained_box_count / self.area_pixels * 1000.0

    def group_response(self, *, key: str, label: str) -> MeasurementAggregateGroupResponse:
        return MeasurementAggregateGroupResponse(
            key=key,
            label=label,
            mask_count=self.mask_count,
            area_pixels=self.area_pixels,
            perimeter_pixels=self.perimeter_pixels,
            contained_box_count=self.contained_box_count,
            density_per_1000_pixels=self.density_per_1000_pixels,
            total_linear_extension_pixels=self.total_linear_extension_pixels,
            calibrated_area_by_unit=dict(sorted(self.calibrated_area_by_unit.items())),
            calibrated_tle_by_unit=dict(sorted(self.calibrated_tle_by_unit.items())),
            surface_area_by_unit=dict(sorted(self.surface_area_by_unit.items())),
        )


class MeasurementAnalyticsService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.measurements = MaskMeasurementService(session, settings)

    def _mask_metadata(self, project_id: str) -> dict[str, MaskAnnotation]:
        statement = (
            select(MaskAnnotation)
            .join(ImageAsset, ImageAsset.id == MaskAnnotation.image_id)
            .options(selectinload(MaskAnnotation.label_class))
            .where(
                ImageAsset.project_id == project_id,
                MaskAnnotation.deleted_at.is_(None),
                MaskAnnotation.status == "verified",
            )
            .order_by(ImageAsset.created_at, MaskAnnotation.created_at, MaskAnnotation.id)
        )
        return {mask.id: mask for mask in self.session.scalars(statement)}

    @staticmethod
    def _group_key(value: str | None, fallback: str) -> tuple[str, str]:
        normalized = (value or "").strip()
        if not normalized:
            return fallback, fallback.replace("_", " ").title()
        return normalized.casefold(), normalized

    @staticmethod
    def _add_group(
        groups: dict[tuple[str, str], _MeasurementAccumulator],
        key: tuple[str, str],
        row: MaskMeasurementResponse,
    ) -> None:
        accumulator = groups.get(key)
        if accumulator is None:
            accumulator = _MeasurementAccumulator()
            groups[key] = accumulator
        accumulator.add(row)

    def summarize(
        self,
        project_id: str,
        *,
        label_class_ids: list[str] | None = None,
        scientific_names: list[str] | None = None,
        state_names: list[str] | None = None,
    ) -> ProjectMeasurementSummaryResponse:
        rows = self.measurements.measure_project(
            project_id,
            label_class_ids=label_class_ids,
            scientific_names=scientific_names,
            state_names=state_names,
        )
        masks = self._mask_metadata(project_id)
        total = _MeasurementAccumulator()
        class_groups: dict[tuple[str, str], _MeasurementAccumulator] = {}
        species_groups: dict[tuple[str, str], _MeasurementAccumulator] = {}
        state_groups: dict[tuple[str, str], _MeasurementAccumulator] = {}

        for row in rows:
            total.add(row)
            mask = masks.get(row.mask_annotation_id)
            label_class = mask.label_class if mask is not None else None
            class_key = self._group_key(
                label_class.name if label_class is not None else None,
                "unassigned_class",
            )
            species_key = self._group_key(
                label_class.scientific_name if label_class is not None else None,
                "unspecified_species",
            )
            state_key = self._group_key(
                label_class.state_name if label_class is not None else None,
                "unspecified_state",
            )
            self._add_group(class_groups, class_key, row)
            self._add_group(species_groups, species_key, row)
            self._add_group(state_groups, state_key, row)

        def responses(
            groups: dict[tuple[str, str], _MeasurementAccumulator],
        ) -> list[MeasurementAggregateGroupResponse]:
            return [
                aggregate.group_response(key=key, label=label)
                for (key, label), aggregate in sorted(
                    groups.items(), key=lambda item: (item[0][1].casefold(), item[0][0])
                )
            ]

        return ProjectMeasurementSummaryResponse(
            project_id=project_id,
            mask_count=total.mask_count,
            calibrated_mask_count=total.calibrated_mask_count,
            area_pixels=total.area_pixels,
            perimeter_pixels=total.perimeter_pixels,
            contained_box_count=total.contained_box_count,
            density_per_1000_pixels=total.density_per_1000_pixels,
            total_linear_extension_pixels=total.total_linear_extension_pixels,
            calibrated_area_by_unit=dict(sorted(total.calibrated_area_by_unit.items())),
            calibrated_tle_by_unit=dict(sorted(total.calibrated_tle_by_unit.items())),
            surface_area_by_unit=dict(sorted(total.surface_area_by_unit.items())),
            by_class=responses(class_groups),
            by_species=responses(species_groups),
            by_state=responses(state_groups),
        )
