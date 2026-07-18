"""Dataset snapshots that preserve revisioned coral measurement metadata."""

from __future__ import annotations

from typing import Any

from reefvision.db.models import MaskAnnotation
from reefvision.services.mask_aware_dataset_versions import MaskAwareDatasetVersionService


class MeasurementAwareDatasetVersionService(MaskAwareDatasetVersionService):
    """Extend mask snapshots with the measurement profile used for analysis."""

    def _mask_snapshot(self, mask: MaskAnnotation) -> dict[str, Any]:
        snapshot = super()._mask_snapshot(mask)
        snapshot["measurement_json"] = dict(mask.measurement_json or {})
        return snapshot
