"""Conservative, explicit verified-data-to-training workflow.

The Annotation table contains only saved/accepted boxes; predictions live in a
separate table. Masks additionally require status=verified. Whole-image review is
required so partially annotated images are not silently trained as background.
"""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import Project, TrainingRun
from reefvision.domain.errors import ValidationError
from reefvision.schemas.dataset_versions import DatasetVersionCreateRequest, SplitRatios
from reefvision.schemas.project_learning import (
    LearningClassCount,
    LearningConfig,
    LearningImproveResponse,
    LearningStatus,
)
from reefvision.schemas.training import TrainingDraftWriteRequest, TrainingRunCreateRequest
from reefvision.services.measurement_aware_dataset_versions import (
    MeasurementAwareDatasetVersionService,
)
from reefvision.services.segmentation_training import SegmentationTrainingService


class ProjectLearningService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.datasets = MeasurementAwareDatasetVersionService(session, settings)
        self.training = SegmentationTrainingService(session, settings)

    def _latest_run(self, project_id: str, task: str) -> TrainingRun | None:
        return self.session.scalar(
            select(TrainingRun)
            .where(
                TrainingRun.project_id == project_id,
                TrainingRun.task == task,
                TrainingRun.evaluation_config_json["project_learning"].as_string().is_not(None),
            )
            .order_by(TrainingRun.created_at.desc(), TrainingRun.id.desc())
            .limit(1)
        )

    def _snapshot_request(
        self, config: LearningConfig, previous: TrainingRun | None
    ) -> DatasetVersionCreateRequest:
        parent_id = previous.dataset_version_id if previous else None
        return DatasetVersionCreateRequest(
            name="Verified project learning",
            notes="Reviewed images only; candidates require evaluation before model selection.",
            eligible_annotation_statuses=["reviewed"],
            split_method="group_random",
            requested_ratios=SplitRatios(
                train=1 - config.validation_fraction, validation=config.validation_fraction, test=0
            ),
            split_seed=config.seed,
            parent_version_id=parent_id,
            reuse_parent_assignments=parent_id is not None,
        )

    def status(self, project_id: str, config: LearningConfig) -> LearningStatus:
        project = self.datasets._project(project_id)
        latest = self._latest_run(project_id, config.task)
        candidates = self.datasets._eligible_images(project_id, ["reviewed"])
        blockers: list[str] = []
        warnings = [
            "Readiness thresholds are minimum safeguards, not a guarantee of useful accuracy.",
            "Only Reviewed images contribute; pending proposals are never labels.",
            "Backend and checkpoint checks run before queuing. No weights are downloaded.",
            "No automatic model activation; candidate versus incumbent evaluation remains manual.",
        ]
        split_counts: dict[str, int] = {"train": 0, "validation": 0}
        counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        if len(candidates) < config.minimum_images:
            blockers.append(
                f"Need at least {config.minimum_images} reviewed images; found {len(candidates)}."
            )
        try:
            plan = self.datasets._plan_splits(candidates, self._snapshot_request(config, latest))
        except ValidationError as exc:
            blockers.append(str(exc))
            plan = None
        if plan is not None:
            warnings.extend(plan.warnings)
            masks = self.datasets._masks_for_images([item.image.id for item in candidates])
            for candidate in candidates:
                split = plan.assignments[candidate.image.id]
                split_counts[split] = split_counts.get(split, 0) + 1
                if config.task == "detect":
                    for annotation in candidate.annotations:
                        counts[annotation.label_class_id][split] += 1
                    if masks.get(candidate.image.id) and not candidate.annotations:
                        blockers.append(
                            "Reviewed mask-only images need bounding-box labels for detection; "
                            "choose polygon segmentation or add reviewed boxes."
                        )
                else:
                    for mask in masks.get(candidate.image.id, []):
                        if mask.geometry_kind == "polygon" and mask.label_class_id is not None:
                            counts[mask.label_class_id][split] += 1
                        else:
                            blockers.append(
                                "Raster masks cannot train the polygon instance-segmentation "
                                "backend without losing geometry; use the semantic workspace."
                            )
                    if candidate.annotations and not masks.get(candidate.image.id):
                        blockers.append(
                            "Reviewed box-only images need verified polygon masks for segmentation."
                        )
        classes = [
            LearningClassCount(
                label_class_id=label.id,
                class_name=label.name,
                count=sum(counts[label.id].values()),
                train_count=counts[label.id].get("train", 0),
                validation_count=counts[label.id].get("validation", 0),
            )
            for label in project.label_classes
            if label.is_active or label.id in counts
        ]
        if not classes:
            blockers.append("Create project classes and verify examples before training.")
        for item in classes:
            if item.count < config.minimum_objects_per_class:
                blockers.append(
                    f"{item.class_name}: need {config.minimum_objects_per_class} verified objects; "
                    f"found {item.count}."
                )
            if not item.train_count or not item.validation_count:
                blockers.append(
                    f"{item.class_name}: verified objects must occur in both train and validation "
                    "on separate acquisition groups."
                )
        if not split_counts["train"] or not split_counts["validation"]:
            blockers.append(
                "Need separate train and validation images without splitting any group."
            )
        active = self.session.scalar(
            select(TrainingRun.id)
            .where(
                TrainingRun.project_id == project_id,
                TrainingRun.status.in_(["queued", "running", "cancel_requested"]),
            )
            .limit(1)
        )
        if active is not None:
            blockers.append("A training run is already active; wait or cancel it in Training.")
        return LearningStatus(
            ready=not blockers,
            config=config,
            blockers=list(dict.fromkeys(blockers)),
            warnings=list(dict.fromkeys(warnings)),
            reviewed_image_count=len(candidates),
            eligible_object_count=sum(item.count for item in classes),
            per_class_counts=classes,
            split_counts=split_counts,
            latest_run=self.training.get_run(latest.id) if latest else None,
        )

    def improve(self, project_id: str, config: LearningConfig) -> LearningImproveResponse:
        # Acquire SQLite's writer reservation before checking for concurrent launches.
        # This no-op update changes no scientific data and serializes this composite action.
        self.session.execute(
            update(Project).where(Project.id == project_id).values(updated_at=Project.updated_at)
        )
        readiness = self.status(project_id, config)
        if not readiness.ready:
            self.session.rollback()
            return LearningImproveResponse(readiness=readiness)
        try:
            latest = self._latest_run(project_id, config.task)
            version = self.datasets.create_version(
                project_id, self._snapshot_request(config, latest), commit=False
            )
            payload = TrainingDraftWriteRequest(
                name="Improve predictions from verified annotations",
                dataset_version_id=version.id,
                task=config.task,
                provider_id="ultralytics",
                architecture=config.architecture
                or ("yolo11.yaml" if config.task == "detect" else "yolo11-seg.yaml"),
                initial_checkpoint_source=(
                    "registered_model" if config.initial_checkpoint_model_id else "scratch"
                ),
                initial_checkpoint_model_id=config.initial_checkpoint_model_id,
                device=config.device,
                random_seed=config.seed,
                training_config={
                    "epochs": config.epochs,
                    "batch": config.batch,
                    "imgsz": config.imgsz,
                    "workers": 0,
                    "val": True,
                },
                evaluation_config={
                    "split": "validation",
                    "project_learning": {
                        "config": config.model_dump(mode="json"),
                        "automatic_promotion": False,
                        "verification_policy": "reviewed_images_verified_annotations_only",
                    },
                },
                resource_limits={"max_workers": 0, "allowed_devices": [config.device]},
            )
            preflight = self.training.preflight(project_id, payload)
            if preflight.status == "blocked":
                self.session.rollback()
                readiness.ready = False
                readiness.blockers.extend(preflight.blockers)
                return LearningImproveResponse(readiness=readiness, preflight=preflight)
            draft = self.training.create_draft(project_id, payload, commit=False)
            run = self.training.create_run(
                project_id, TrainingRunCreateRequest(draft_id=draft.id), commit=False
            )
            self.session.commit()
            return LearningImproveResponse(
                readiness=readiness, dataset_version=version, run=run, preflight=preflight
            )
        except Exception:
            self.session.rollback()
            raise
