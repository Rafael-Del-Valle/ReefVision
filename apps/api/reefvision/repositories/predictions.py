"""Prediction-proposal persistence operations."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from reefvision.db.models import PredictionProposal


class PredictionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, proposal: PredictionProposal) -> None:
        self.session.add(proposal)

    def add_many(self, proposals: list[PredictionProposal]) -> None:
        self.session.add_all(proposals)

    def get(self, proposal_id: str) -> PredictionProposal | None:
        return self.session.get(PredictionProposal, proposal_id)

    def list_by_ids(self, proposal_ids: list[str]) -> list[PredictionProposal]:
        if not proposal_ids:
            return []
        statement = select(PredictionProposal).where(PredictionProposal.id.in_(proposal_ids))
        proposals = list(self.session.scalars(statement))
        by_id = {proposal.id: proposal for proposal in proposals}
        return [by_id[proposal_id] for proposal_id in proposal_ids if proposal_id in by_id]

    def list_for_image(
        self,
        image_id: str,
        *,
        model_id: str | None = None,
        label_class_id: str | None = None,
        min_confidence: float | None = None,
        review_status: str | None = None,
    ) -> list[PredictionProposal]:
        statement = select(PredictionProposal).where(PredictionProposal.image_id == image_id)
        if model_id:
            statement = statement.where(PredictionProposal.model_id == model_id)
        if label_class_id:
            statement = statement.where(PredictionProposal.label_class_id == label_class_id)
        if min_confidence is not None:
            statement = statement.where(PredictionProposal.confidence >= min_confidence)
        if review_status:
            statement = statement.where(PredictionProposal.review_status == review_status)
        statement = statement.order_by(
            PredictionProposal.created_at.desc(),
            PredictionProposal.confidence.desc(),
            PredictionProposal.id,
        )
        return list(self.session.scalars(statement))

    def counts_for_image(self, image_id: str) -> dict[str, int]:
        statement = (
            select(PredictionProposal.review_status, func.count(PredictionProposal.id))
            .where(PredictionProposal.image_id == image_id)
            .group_by(PredictionProposal.review_status)
        )
        return {status: int(count) for status, count in self.session.execute(statement)}

    def has_any_for_model(self, model_id: str) -> bool:
        statement = (
            select(PredictionProposal.id).where(PredictionProposal.model_id == model_id).limit(1)
        )
        return self.session.scalar(statement) is not None
