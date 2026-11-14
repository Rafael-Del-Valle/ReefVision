"""Replicate-aware counts from reviewed canonical annotation evidence."""

from __future__ import annotations

import csv
import io
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from reefvision.db.models import (
    Annotation,
    ImageAsset,
    LabelClass,
    MaskAnnotation,
    PredictionProposal,
    Project,
)
from reefvision.db.models.computed_metric import ComputedMetricDefinition, ComputedMetricResult
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.schemas.computed_aggregate_metrics import (
    AggregateClassCount,
    AggregateGroup,
    ComputedAggregateDefinitionCreate,
    ComputedAggregateDefinitionPage,
    ComputedAggregateDefinitionResponse,
    ComputedAggregatePreview,
    ComputedAggregateResultPage,
    ComputedAggregateResultResponse,
    ComputedAggregateValidationResponse,
)
from reefvision.services.scientific_data import content_hash

FORMULA_VERSION = "reefvision.annotation-aggregate.v1"
SCHEMA_VERSION = "1.1.0"
DEFINITION_KIND = "annotation_aggregate"
RESULT_KIND = "annotation_aggregate"


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _configuration(payload: ComputedAggregateDefinitionCreate) -> dict[str, Any]:
    grouping = payload.grouping_level
    return {
        "schema_version": SCHEMA_VERSION,
        "source_kind": payload.source_kind,
        "grouping_level": grouping,
        "label_class_ids": [str(value) for value in payload.label_class_ids],
        "operation": "count",
        "required_review_state": "reviewed",
        "independence_contract": (
            "one_unit_per_image" if grouping == "image" else "one_unit_per_image_group_key"
        ),
    }


def _definition_payload(row: ComputedMetricDefinition) -> dict[str, Any]:
    return {
        "name": row.name,
        "expression": row.expression,
        "formula_version": row.formula_version,
        "output_unit": row.output_unit,
        "configuration": row.configuration_json,
    }


class ComputedAggregateMetricService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def require_project(self, project_id: str) -> Project:
        project = self.session.get(Project, project_id)
        if project is None:
            raise NotFoundError("Project not found")
        return project

    def create_definition(
        self, project_id: str, payload: ComputedAggregateDefinitionCreate
    ) -> ComputedMetricDefinition:
        self.require_project(project_id)
        label_ids = [str(value) for value in payload.label_class_ids]
        if label_ids:
            labels = self.session.scalars(
                select(LabelClass).where(LabelClass.id.in_(label_ids))
            ).all()
            if len(labels) != len(label_ids) or any(row.project_id != project_id for row in labels):
                raise ValidationError("All label class filters must belong to this project")
        configuration = _configuration(payload)
        row = ComputedMetricDefinition(
            id=str(uuid4()),
            project_id=project_id,
            definition_kind=DEFINITION_KIND,
            name=payload.name,
            expression=f"count({payload.source_kind})",
            formula_version=FORMULA_VERSION,
            input_spec_json=[],
            configuration_json=configuration,
            output_unit="count",
            definition_sha256="",
        )
        row.definition_sha256 = content_hash(_definition_payload(row))
        self.session.add(row)
        self.session.flush()
        return row

    def definition_response(
        self, row: ComputedMetricDefinition
    ) -> ComputedAggregateDefinitionResponse:
        if row.definition_kind != DEFINITION_KIND or row.configuration_json is None:
            raise ValidationError("Metric definition is not an annotation aggregate")
        if content_hash(_definition_payload(row)) != row.definition_sha256:
            raise ConflictError("Computed aggregate definition checksum mismatch")
        config = row.configuration_json
        return ComputedAggregateDefinitionResponse.model_validate(
            {
                "id": row.id,
                "project_id": row.project_id,
                "name": row.name,
                "definition_kind": row.definition_kind,
                "expression": row.expression,
                "formula_version": row.formula_version,
                "output_unit": row.output_unit,
                "definition_sha256": row.definition_sha256,
                "created_at": _utc(row.created_at),
                **config,
            }
        )

    def get_definition(self, project_id: str, definition_id: str) -> ComputedMetricDefinition:
        row = self.session.get(ComputedMetricDefinition, definition_id)
        if row is None or row.project_id != project_id or row.definition_kind != DEFINITION_KIND:
            raise NotFoundError("Computed aggregate definition not found")
        self.definition_response(row)
        return row

    def list_definitions(
        self, project_id: str, *, limit: int, offset: int
    ) -> ComputedAggregateDefinitionPage:
        self.require_project(project_id)
        query = select(ComputedMetricDefinition).where(
            ComputedMetricDefinition.project_id == project_id,
            ComputedMetricDefinition.definition_kind == DEFINITION_KIND,
        )
        total = self.session.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = self.session.scalars(
            query.order_by(ComputedMetricDefinition.created_at, ComputedMetricDefinition.id)
            .limit(limit)
            .offset(offset)
        ).all()
        return ComputedAggregateDefinitionPage(
            items=[self.definition_response(row) for row in rows], total=total
        )

    def _resolve_images(self, project_id: str, image_ids: list[str]) -> list[ImageAsset]:
        rows = self.session.scalars(
            select(ImageAsset).where(ImageAsset.id.in_(image_ids)).order_by(ImageAsset.id)
        ).all()
        if len(rows) != len(image_ids) or any(row.project_id != project_id for row in rows):
            raise ValidationError("All selected images must belong to this project")
        if any(row.annotation_status != "reviewed" for row in rows):
            raise ValidationError("All selected images must have reviewed annotation status")
        return list(rows)

    def _build_preview(
        self,
        definition: ComputedMetricDefinition,
        image_ids: list[str],
    ) -> ComputedAggregatePreview:
        config = definition.configuration_json or {}
        images = self._resolve_images(definition.project_id, image_ids)
        grouping_level = str(config["grouping_level"])
        if grouping_level == "image_group_key" and any(
            not image.group_key or not image.group_key.strip() for image in images
        ):
            raise ValidationError("Image group key is required for group-key aggregation")

        label_filter = set(config.get("label_class_ids", []))
        selected_ids = [image.id for image in images]
        source_kind = str(config["source_kind"])
        observations: list[Annotation | MaskAnnotation]
        if source_kind == "verified_annotations":
            annotation_statement = select(Annotation).where(
                Annotation.image_id.in_(selected_ids), Annotation.deleted_at.is_(None)
            )
            if label_filter:
                annotation_statement = annotation_statement.where(
                    Annotation.label_class_id.in_(label_filter)
                )
            observations = list(
                self.session.scalars(annotation_statement.order_by(Annotation.id)).all()
            )
        elif source_kind == "verified_masks":
            mask_statement = select(MaskAnnotation).where(
                MaskAnnotation.image_id.in_(selected_ids),
                MaskAnnotation.deleted_at.is_(None),
                MaskAnnotation.status == "verified",
            )
            if label_filter:
                mask_statement = mask_statement.where(
                    MaskAnnotation.label_class_id.in_(label_filter)
                )
            observations = list(
                self.session.scalars(mask_statement.order_by(MaskAnnotation.id)).all()
            )
        else:
            raise ValidationError(f"Unsupported aggregate source kind: {source_kind}")

        observed_label_ids = {row.label_class_id for row in observations if row.label_class_id}
        labels = {
            row.id: row.name
            for row in self.session.scalars(
                select(LabelClass).where(LabelClass.id.in_(observed_label_ids))
            ).all()
        }
        by_image: dict[str, list[Any]] = defaultdict(list)
        for row in observations:
            by_image[row.image_id].append(row)

        units: dict[str, list[ImageAsset]] = defaultdict(list)
        for image in images:
            unit_key = image.id if grouping_level == "image" else str(image.group_key)
            units[unit_key].append(image)

        def class_counts(rows: list[Any]) -> list[AggregateClassCount]:
            counts = Counter(row.label_class_id for row in rows)
            return [
                AggregateClassCount(
                    label_class_id=label_id,
                    label_name=labels.get(label_id, "Unclassified"),
                    count=count,
                )
                for label_id, count in sorted(counts.items(), key=lambda item: str(item[0] or ""))
            ]

        groups: list[AggregateGroup] = []
        for unit_key in sorted(units):
            unit_images = sorted(units[unit_key], key=lambda image: image.id)
            unit_rows = [row for image in unit_images for row in by_image[image.id]]
            groups.append(
                AggregateGroup(
                    unit_key=unit_key,
                    image_ids=[image.id for image in unit_images],
                    observation_count=len(unit_rows),
                    counts_by_class=class_counts(unit_rows),
                )
            )

        proposal_statement = select(PredictionProposal).where(
            PredictionProposal.image_id.in_(selected_ids)
        )
        if label_filter:
            proposal_statement = proposal_statement.where(
                PredictionProposal.label_class_id.in_(label_filter)
            )
        proposals = self.session.scalars(proposal_statement.order_by(PredictionProposal.id)).all()
        excluded_proposals = dict(sorted(Counter(row.review_status for row in proposals).items()))
        image_snapshot = [
            {
                "image_id": image.id,
                "sha256": image.sha256,
                "annotation_revision": image.annotation_revision,
                "annotation_status": image.annotation_status,
                "group_key": image.group_key,
            }
            for image in images
        ]
        observation_snapshot = [
            {
                "id": row.id,
                "image_id": row.image_id,
                "label_class_id": row.label_class_id,
                "source_type": row.source_type,
                "revision": row.revision,
            }
            for row in observations
        ]
        evidence_payload = {
            "definition_sha256": definition.definition_sha256,
            "images": image_snapshot,
            "observations": observation_snapshot,
            "excluded_proposals_by_status": excluded_proposals,
        }
        return ComputedAggregatePreview(
            definition_id=definition.id,
            definition_sha256=definition.definition_sha256,
            source_kind=source_kind,
            grouping_level=grouping_level,
            image_count=len(images),
            independent_unit_count=len(groups),
            observation_count=len(observations),
            mean_per_independent_unit=len(observations) / len(groups),
            counts_by_class=class_counts(observations),
            groups=groups,
            excluded_proposals_by_status=excluded_proposals,
            image_snapshot=image_snapshot,
            observation_snapshot=observation_snapshot,
            evidence_sha256=content_hash(evidence_payload),
        )

    def preview(
        self, project_id: str, definition_id: str, image_ids: list[str]
    ) -> ComputedAggregatePreview:
        definition = self.get_definition(project_id, definition_id)
        return self._build_preview(definition, image_ids)

    def calculate(
        self,
        project_id: str,
        definition_id: str,
        image_ids: list[str],
        *,
        workflow_run_id: str | None = None,
        workflow_node_run_id: str | None = None,
    ) -> ComputedMetricResult:
        definition = self.get_definition(project_id, definition_id)
        if workflow_node_run_id is not None:
            existing = self.session.scalar(
                select(ComputedMetricResult).where(
                    ComputedMetricResult.workflow_node_run_id == workflow_node_run_id
                )
            )
            if existing is not None:
                response = self.result_response(existing)
                saved_image_ids = sorted(str(item["image_id"]) for item in response.image_snapshot)
                if (
                    existing.project_id != project_id
                    or existing.definition_id != definition_id
                    or saved_image_ids != sorted(image_ids)
                    or existing.workflow_run_id != workflow_run_id
                ):
                    raise ConflictError(
                        "Workflow aggregate replay conflicts with its persisted result"
                    )
                return existing
        preview = self._build_preview(definition, image_ids)
        if preview.observation_count == 0:
            raise ValidationError(
                "Cannot persist a zero-observation aggregate because missing work and a true zero "
                "cannot yet be distinguished"
            )
        observed_at = max(
            _utc(image.updated_at) for image in self._resolve_images(project_id, image_ids)
        )
        payload = {
            **preview.model_dump(mode="json"),
            "definition_name": definition.name,
            "expression": definition.expression,
            "formula_version": definition.formula_version,
            "output_unit": definition.output_unit,
            "observed_at": observed_at.isoformat(),
            "provenance": {
                "definition_sha256": definition.definition_sha256,
                "evidence_sha256": preview.evidence_sha256,
                "selection_is_explicit": True,
                "predictions_counted": False,
            },
        }
        row = ComputedMetricResult(
            id=str(uuid4()),
            project_id=project_id,
            result_kind=RESULT_KIND,
            definition_id=definition.id,
            observed_at=observed_at,
            payload_json=payload,
            content_sha256=content_hash(payload),
            workflow_run_id=workflow_run_id,
            workflow_node_run_id=workflow_node_run_id,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def result_response(self, row: ComputedMetricResult) -> ComputedAggregateResultResponse:
        if row.result_kind != RESULT_KIND:
            raise ValidationError("Computed result is not an annotation aggregate")
        if content_hash(row.payload_json) != row.content_sha256:
            raise ConflictError("Computed aggregate result checksum mismatch")
        return ComputedAggregateResultResponse.model_validate(
            {
                **row.payload_json,
                "id": row.id,
                "project_id": row.project_id,
                "result_kind": row.result_kind,
                "content_sha256": row.content_sha256,
                "workflow_run_id": row.workflow_run_id,
                "workflow_node_run_id": row.workflow_node_run_id,
                "created_at": _utc(row.created_at),
            }
        )

    def list_results(
        self, project_id: str, *, limit: int, offset: int
    ) -> ComputedAggregateResultPage:
        self.require_project(project_id)
        query = select(ComputedMetricResult).where(
            ComputedMetricResult.project_id == project_id,
            ComputedMetricResult.result_kind == RESULT_KIND,
        )
        total = self.session.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = self.session.scalars(
            query.order_by(ComputedMetricResult.created_at, ComputedMetricResult.id)
            .limit(limit)
            .offset(offset)
        ).all()
        return ComputedAggregateResultPage(
            items=[self.result_response(row) for row in rows], total=total
        )

    def validate_result(
        self, project_id: str, result_id: str
    ) -> ComputedAggregateValidationResponse:
        self.require_project(project_id)
        row = self.session.get(ComputedMetricResult, result_id)
        if row is None or row.project_id != project_id or row.result_kind != RESULT_KIND:
            raise NotFoundError("Computed aggregate result not found")
        saved = self.result_response(row)
        definition = self.get_definition(project_id, str(saved.definition_id))
        config = definition.configuration_json or {}
        saved_images = {str(item["image_id"]): item for item in saved.image_snapshot}
        saved_observations = {str(item["id"]): item for item in saved.observation_snapshot}
        reasons: list[str] = []

        current_images: list[dict[str, Any]] = []
        for image_id in sorted(saved_images):
            previous = saved_images[image_id]
            image = self.session.get(ImageAsset, image_id)
            if image is None or image.project_id != project_id:
                reasons.append(f"image_missing:{image_id}")
                continue
            current = {
                "image_id": image.id,
                "sha256": image.sha256,
                "annotation_revision": image.annotation_revision,
                "annotation_status": image.annotation_status,
                "group_key": image.group_key,
            }
            current_images.append(current)
            if image.annotation_status != previous.get("annotation_status"):
                reasons.append(f"image_review_status_changed:{image_id}")
            if image.group_key != previous.get("group_key"):
                reasons.append(f"image_group_key_changed:{image_id}")
            if image.sha256 != previous.get("sha256"):
                reasons.append(f"image_checksum_changed:{image_id}")
            if image.annotation_revision != previous.get("annotation_revision"):
                reasons.append(f"image_annotation_revision_changed:{image_id}")

        source_kind = str(config.get("source_kind"))
        saved_label_names = {
            str(item.label_class_id): item.label_name
            for item in saved.counts_by_class
            if item.label_class_id is not None
        }
        for label_id, saved_name in sorted(saved_label_names.items()):
            label = self.session.get(LabelClass, label_id)
            if label is None or label.project_id != project_id:
                reasons.append(f"label_missing:{label_id}")
            elif label.name != saved_name:
                reasons.append(f"label_name_changed:{label_id}")
        current_observations: list[dict[str, Any]] = []
        for observation_id in sorted(saved_observations):
            previous = saved_observations[observation_id]
            observation: Annotation | MaskAnnotation | None
            if source_kind == "verified_annotations":
                observation = self.session.get(Annotation, observation_id)
            else:
                observation = self.session.get(MaskAnnotation, observation_id)
            if observation is None or observation.deleted_at is not None:
                reasons.append(f"observation_missing:{observation_id}")
                continue
            if isinstance(observation, MaskAnnotation) and observation.status != "verified":
                reasons.append(f"observation_status_changed:{observation_id}")
                continue
            current = {
                "id": observation.id,
                "image_id": observation.image_id,
                "label_class_id": observation.label_class_id,
                "source_type": observation.source_type,
                "revision": observation.revision,
            }
            current_observations.append(current)
            if observation.label_class_id != previous.get("label_class_id"):
                reasons.append(f"observation_label_changed:{observation_id}")
            if observation.revision != previous.get("revision"):
                reasons.append(f"observation_revision_changed:{observation_id}")
            if observation.source_type != previous.get("source_type"):
                reasons.append(f"observation_source_changed:{observation_id}")

        image_ids = sorted(saved_images)
        label_filter = set(config.get("label_class_ids", []))
        if source_kind == "verified_annotations":
            annotation_statement = select(Annotation).where(
                Annotation.image_id.in_(image_ids), Annotation.deleted_at.is_(None)
            )
            if label_filter:
                annotation_statement = annotation_statement.where(
                    Annotation.label_class_id.in_(label_filter)
                )
            eligible_ids = set(
                self.session.scalars(
                    annotation_statement.with_only_columns(Annotation.id).order_by(Annotation.id)
                ).all()
            )
        else:
            mask_statement = select(MaskAnnotation).where(
                MaskAnnotation.image_id.in_(image_ids),
                MaskAnnotation.deleted_at.is_(None),
                MaskAnnotation.status == "verified",
            )
            if label_filter:
                mask_statement = mask_statement.where(
                    MaskAnnotation.label_class_id.in_(label_filter)
                )
            eligible_ids = set(
                self.session.scalars(
                    mask_statement.with_only_columns(MaskAnnotation.id).order_by(MaskAnnotation.id)
                ).all()
            )
        for observation_id in sorted(eligible_ids - set(saved_observations)):
            reasons.append(f"observation_added:{observation_id}")

        proposal_statement = select(PredictionProposal).where(
            PredictionProposal.image_id.in_(image_ids)
        )
        if label_filter:
            proposal_statement = proposal_statement.where(
                PredictionProposal.label_class_id.in_(label_filter)
            )
        proposals = self.session.scalars(proposal_statement.order_by(PredictionProposal.id)).all()
        current_proposals = dict(sorted(Counter(item.review_status for item in proposals).items()))
        if current_proposals != saved.excluded_proposals_by_status:
            reasons.append("proposal_inventory_changed")
        evidence_payload = {
            "definition_sha256": definition.definition_sha256,
            "images": current_images,
            "observations": current_observations,
            "excluded_proposals_by_status": current_proposals,
        }
        current_hash = content_hash(evidence_payload)
        if current_hash != saved.evidence_sha256 and not reasons:
            reasons.append("evidence_snapshot_changed")
        return ComputedAggregateValidationResponse(
            result_id=row.id,
            current=current_hash == saved.evidence_sha256 and not reasons,
            saved_evidence_sha256=saved.evidence_sha256,
            current_evidence_sha256=current_hash,
            reasons=sorted(set(reasons)),
        )

    def export_csv(self, project_id: str) -> str:
        self.require_project(project_id)
        rows = self.session.scalars(
            select(ComputedMetricResult)
            .where(
                ComputedMetricResult.project_id == project_id,
                ComputedMetricResult.result_kind == RESULT_KIND,
            )
            .order_by(ComputedMetricResult.created_at, ComputedMetricResult.id)
        ).all()
        fieldnames = [
            "row_kind",
            "result_id",
            "definition_id",
            "definition_name",
            "source_kind",
            "grouping_level",
            "independence_contract",
            "unit_key",
            "observation_count",
            "image_count",
            "independent_unit_count",
            "mean_per_independent_unit",
            "counts_by_class_json",
            "image_ids_json",
            "observation_ids_json",
            "workflow_run_id",
            "workflow_node_run_id",
            "definition_sha256",
            "evidence_sha256",
            "content_sha256",
            "observed_at_utc",
        ]
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            item = self.result_response(row)
            definition = self.get_definition(project_id, str(item.definition_id))
            config = definition.configuration_json or {}
            all_image_ids = [str(value["image_id"]) for value in item.image_snapshot]
            common = {
                "result_id": str(item.id),
                "definition_id": str(item.definition_id),
                "definition_name": item.definition_name,
                "source_kind": item.source_kind,
                "grouping_level": item.grouping_level,
                "independence_contract": config.get("independence_contract", ""),
                "workflow_run_id": str(item.workflow_run_id) if item.workflow_run_id else "",
                "workflow_node_run_id": (
                    str(item.workflow_node_run_id) if item.workflow_node_run_id else ""
                ),
                "definition_sha256": item.definition_sha256,
                "evidence_sha256": item.evidence_sha256,
                "content_sha256": item.content_sha256,
                "observed_at_utc": item.observed_at.isoformat(),
            }
            writer.writerow(
                {
                    **common,
                    "row_kind": "overall",
                    "unit_key": "",
                    "observation_count": item.observation_count,
                    "image_count": item.image_count,
                    "independent_unit_count": item.independent_unit_count,
                    "mean_per_independent_unit": item.mean_per_independent_unit,
                    "counts_by_class_json": json.dumps(
                        [value.model_dump(mode="json") for value in item.counts_by_class],
                        sort_keys=True,
                    ),
                    "image_ids_json": json.dumps(all_image_ids),
                    "observation_ids_json": json.dumps(
                        [str(value["id"]) for value in item.observation_snapshot]
                    ),
                }
            )
            for group in item.groups:
                group_image_ids = {str(value) for value in group.image_ids}
                writer.writerow(
                    {
                        **common,
                        "row_kind": "group",
                        "unit_key": group.unit_key,
                        "observation_count": group.observation_count,
                        "image_count": len(group.image_ids),
                        "independent_unit_count": 1,
                        "mean_per_independent_unit": group.observation_count,
                        "counts_by_class_json": json.dumps(
                            [value.model_dump(mode="json") for value in group.counts_by_class],
                            sort_keys=True,
                        ),
                        "image_ids_json": json.dumps(sorted(group_image_ids)),
                        "observation_ids_json": json.dumps(
                            [
                                str(value["id"])
                                for value in item.observation_snapshot
                                if str(value["image_id"]) in group_image_ids
                            ]
                        ),
                    }
                )
        return output.getvalue()
