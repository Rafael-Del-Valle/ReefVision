"""Record a pinned plugin's output as an unassessed, derived image measurement."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid5

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import ImageAsset, ScientificRecord
from reefvision.domain.errors import ConflictError, NotFoundError
from reefvision.ml.plugin_worker import run_plugin
from reefvision.schemas.plugins import ABI, PluginMeasurementPin
from reefvision.schemas.scientific_data import (
    ScientificProvenance,
    ScientificRecordCreate,
    ScientificRecordPage,
    ScientificRecordResponse,
    ScientificSubject,
)
from reefvision.services.scientific_data import ScientificDataService
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.storage.plugins import PluginStorage, original_rgb_summary


class PluginMeasurementService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.science = ScientificDataService(session)

    def measure(self, project_id: UUID, pin: PluginMeasurementPin) -> ScientificRecordResponse:
        self.science.require_project(str(project_id))
        image = self.session.get(ImageAsset, str(pin.image_id))
        if image is None or image.project_id != str(project_id):
            raise NotFoundError("Choose a managed image in the current project.")
        if image.sha256 != pin.image_sha256:
            raise ConflictError("The selected image differs from the saved image checksum.")
        manifest, module = PluginStorage(self.settings).enabled_module(
            pin.plugin_record_id, pin.package_sha256
        )
        summary = original_rgb_summary(self.settings, image.managed_path, pin.image_sha256)
        value = run_plugin(
            module, (summary.red_mean, summary.green_mean, summary.blue_mean, summary.pixel_count)
        )
        assert value is not None
        identity = str(
            uuid5(
                project_id,
                f"plugin-measurement:{canonical_json_sha256(pin.model_dump(mode='json'))}",
            )
        )
        existing = self.session.get(ScientificRecord, identity)
        if existing is not None:
            return self.science.response(existing)

        acquired = datetime.now(UTC)
        observation = image.capture_timestamp
        if observation is not None and observation.tzinfo is None:
            observation = observation.replace(tzinfo=UTC)
        measurement = ScientificRecordCreate(
            variable=manifest.quantity,
            value=value,
            unit=manifest.unit,
            observed_at=observation or acquired,
            source_kind="derived",
            qc="unassessed",
            subject=ScientificSubject(image_id=pin.image_id),
            provenance=ScientificProvenance(
                source="ReefVision local plugin",
                method=ABI,
                model_version=manifest.version,
                acquired_at=acquired,
                processing_parameters={
                    "plugin_id": manifest.plugin_id,
                    "plugin_version": manifest.version,
                    "plugin_record_id": str(pin.plugin_record_id),
                    "package_sha256": pin.package_sha256,
                    "module_sha256": manifest.module_sha256,
                    "image_sha256": pin.image_sha256,
                    "rgb_summary": summary.model_dump(mode="json"),
                },
                source_metadata={
                    "display_name": manifest.display_name,
                    "license": manifest.license,
                    "observation_time_basis": "image_capture" if observation else "measurement",
                    "pixel_basis": "8-bit encoded source RGB, alpha ignored",
                },
            ),
        )
        try:
            with self.session.begin_nested():
                row = self.science.add_records(
                    str(project_id), [measurement], record_ids=[UUID(identity)]
                )[0]
        except IntegrityError:
            # A concurrent run of the same pin can finish first. Preserve its original timestamp.
            winner = self.session.get(ScientificRecord, identity)
            if winner is None:
                raise
            row = winner
        return self.science.response(row)

    def history(self, project_id: UUID, limit: int, offset: int) -> ScientificRecordPage:
        self.science.require_project(str(project_id))
        provenance = ScientificRecord.payload_json["provenance"]
        query = select(ScientificRecord).where(
            ScientificRecord.project_id == str(project_id),
            provenance["source"].as_string() == "ReefVision local plugin",
            provenance["method"].as_string() == ABI,
        )
        total = self.session.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = self.session.scalars(
            query.order_by(ScientificRecord.created_at.desc(), ScientificRecord.id)
            .offset(offset)
            .limit(limit)
        )
        return ScientificRecordPage(items=[self.science.response(row) for row in rows], total=total)
