"""Persistence helpers for Training workspace records."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, load_only

from reefvision.db.models import ExperimentRecord, TrainingDraft, TrainingRun


class TrainingRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add_draft(self, draft: TrainingDraft) -> None:
        self.session.add(draft)

    def get_draft(self, draft_id: str) -> TrainingDraft | None:
        return self.session.get(TrainingDraft, draft_id)

    def list_drafts(self, project_id: str) -> list[TrainingDraft]:
        statement = (
            select(TrainingDraft)
            .where(TrainingDraft.project_id == project_id)
            .order_by(TrainingDraft.updated_at.desc(), TrainingDraft.created_at.desc())
        )
        return list(self.session.scalars(statement))

    def list_draft_summaries(self, project_id: str) -> list[TrainingDraft]:
        statement = (
            select(TrainingDraft)
            .options(
                load_only(
                    TrainingDraft.id,
                    TrainingDraft.project_id,
                    TrainingDraft.name,
                    TrainingDraft.run_name,
                    TrainingDraft.dataset_version_id,
                    TrainingDraft.task,
                    TrainingDraft.catalog_model_id,
                    TrainingDraft.provider_id,
                    TrainingDraft.architecture,
                    TrainingDraft.initial_checkpoint_source,
                    TrainingDraft.validation_state_json,
                    TrainingDraft.created_at,
                    TrainingDraft.updated_at,
                )
            )
            .where(TrainingDraft.project_id == project_id)
            .order_by(TrainingDraft.updated_at.desc(), TrainingDraft.created_at.desc())
        )
        return list(self.session.scalars(statement))

    def delete_draft(self, draft: TrainingDraft) -> None:
        self.session.delete(draft)

    def add_run(self, run: TrainingRun) -> None:
        self.session.add(run)

    def get_run(self, run_id: str) -> TrainingRun | None:
        return self.session.get(TrainingRun, run_id)

    def get_run_by_job_id(self, job_id: str) -> TrainingRun | None:
        statement = select(TrainingRun).where(TrainingRun.job_id == job_id)
        return self.session.scalar(statement)

    def list_runs(self, project_id: str) -> list[TrainingRun]:
        statement = (
            select(TrainingRun)
            .where(TrainingRun.project_id == project_id)
            .order_by(TrainingRun.created_at.desc(), TrainingRun.id.desc())
        )
        return list(self.session.scalars(statement))

    def add_experiment(self, experiment: ExperimentRecord) -> None:
        self.session.add(experiment)

    def get_experiment(self, experiment_id: str) -> ExperimentRecord | None:
        return self.session.get(ExperimentRecord, experiment_id)

    def get_experiment_for_run(self, training_run_id: str) -> ExperimentRecord | None:
        statement = select(ExperimentRecord).where(ExperimentRecord.training_run_id == training_run_id)
        return self.session.scalar(statement)

    def list_experiments(self, project_id: str) -> list[ExperimentRecord]:
        statement = (
            select(ExperimentRecord)
            .where(ExperimentRecord.project_id == project_id)
            .order_by(ExperimentRecord.created_at.desc(), ExperimentRecord.id.desc())
        )
        return list(self.session.scalars(statement))
