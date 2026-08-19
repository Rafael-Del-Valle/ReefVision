"""Allow uncertainty-only fusion Active Learning without embedding models.

ReefVision's workflow schema intentionally makes the embeddings input optional because
least-confidence, margin, entropy, and ensemble-disagreement acquisition can operate on
reviewable prediction probabilities alone. The base science runtime still requires an
embedding model for diversity-aware strategies; this extension closes the contract gap
without weakening those requirements.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, cast

from sqlalchemy.orm import Session, sessionmaker

from reefvision.db.models import WorkflowArtifact, WorkflowRun
from reefvision.jobs import workflow_runs, workflow_science_runtime
from reefvision.ml.active_learning_selection import (
    SelectionCandidate,
    SelectionStrategy,
    select_candidates,
)

_PROBABILITY_ONLY_STRATEGIES: set[str] = {
    "uncertainty",
    "least_confidence",
    "margin",
    "entropy",
    "ensemble_disagreement",
}

_ORIGINAL_ACTIVE_LEARNING = workflow_science_runtime._workflow_active_learning


def _probability_map(configuration: dict[str, Any]) -> dict[str, tuple[float, ...]]:
    raw = configuration.get("probabilities")
    if not isinstance(raw, dict):
        return {}
    result: dict[str, tuple[float, ...]] = {}
    for image_id, values in raw.items():
        if not isinstance(values, list):
            continue
        try:
            parsed = tuple(float(value) for value in values)
        except (TypeError, ValueError):
            continue
        if parsed:
            result[str(image_id)] = parsed
    return result


def _ensemble_map(
    configuration: dict[str, Any],
) -> dict[str, tuple[tuple[float, ...], ...]]:
    raw = configuration.get("ensemble_probabilities")
    if not isinstance(raw, dict):
        return {}
    result: dict[str, tuple[tuple[float, ...], ...]] = {}
    for image_id, members in raw.items():
        if not isinstance(members, list):
            continue
        parsed_members: list[tuple[float, ...]] = []
        for member in members:
            if not isinstance(member, list):
                parsed_members = []
                break
            try:
                parsed = tuple(float(value) for value in member)
            except (TypeError, ValueError):
                parsed_members = []
                break
            if not parsed:
                parsed_members = []
                break
            parsed_members.append(parsed)
        if parsed_members:
            result[str(image_id)] = tuple(parsed_members)
    return result


def _string_map(configuration: dict[str, Any], key: str) -> dict[str, str]:
    raw = configuration.get(key)
    if not isinstance(raw, dict):
        return {}
    return {
        str(image_id): str(value)
        for image_id, value in raw.items()
        if value is not None
    }


def _class_map(configuration: dict[str, Any]) -> dict[str, tuple[str, ...]]:
    raw = configuration.get("class_ids")
    if not isinstance(raw, dict):
        return {}
    return {
        str(image_id): tuple(str(value) for value in values)
        for image_id, values in raw.items()
        if isinstance(values, list)
    }


def _probability_only_active_learning(
    factory: sessionmaker[Session],
    run: WorkflowRun,
    configuration: dict[str, Any],
    inputs: list[WorkflowArtifact],
) -> workflow_runs.ArtifactOutputs:
    strategy_name = str(configuration.get("strategy", "pareto_uncertainty_diversity")).strip()
    embedding_model_id = str(configuration.get("embedding_model_id", "")).strip()
    if embedding_model_id or strategy_name not in _PROBABILITY_ONLY_STRATEGIES:
        return _ORIGINAL_ACTIVE_LEARNING(factory, run, configuration, inputs)

    payloads = [workflow_runs._artifact_payload(item) for item in inputs]
    image_ids = workflow_runs._list_values(payloads, "image_ids")
    probabilities = _probability_map(configuration)
    ensembles = _ensemble_map(configuration)
    group_ids = _string_map(configuration, "group_ids")
    fragment_ids = _string_map(configuration, "fragment_ids")
    class_ids = _class_map(configuration)

    candidate_ids = list(
        dict.fromkeys(
            image_ids
            or sorted(
                set(probabilities)
                | set(ensembles)
                | set(group_ids)
                | set(fragment_ids)
                | set(class_ids)
            )
        )
    )
    if not candidate_ids:
        raise RuntimeError(
            "Probability-only active-learning nodes require image IDs or probability data"
        )

    raw_base_scores = configuration.get("base_scores")
    base_scores = raw_base_scores if isinstance(raw_base_scores, dict) else {}
    raw_manual_priority = configuration.get("manual_priority")
    manual_priority = (
        {str(value) for value in raw_manual_priority}
        if isinstance(raw_manual_priority, list)
        else set()
    )

    candidates: list[SelectionCandidate] = []
    for image_id in candidate_ids:
        try:
            base_score = float(base_scores.get(image_id, 0.0))
        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                f"Invalid base score for active-learning candidate {image_id}"
            ) from exc
        candidates.append(
            SelectionCandidate(
                candidate_id=image_id,
                probabilities=probabilities.get(image_id, ()),
                ensemble_probabilities=ensembles.get(image_id, ()),
                base_score=base_score,
                group_id=group_ids.get(image_id),
                fragment_id=fragment_ids.get(image_id),
                class_ids=class_ids.get(image_id, ()),
                manual_priority=image_id in manual_priority,
                metadata={"probability_only": True},
            )
        )

    strategy = cast(SelectionStrategy, strategy_name)
    results = select_candidates(
        candidates,
        budget=int(configuration.get("maximum_items", 100)),
        strategy=strategy,
        seed=int(configuration.get("seed", 0)),
        group_limit=(
            int(configuration["maximum_items_per_group"])
            if configuration.get("maximum_items_per_group") is not None
            else None
        ),
        fragment_limit=(
            int(configuration["maximum_items_per_fragment"])
            if configuration.get("maximum_items_per_fragment") is not None
            else None
        ),
        uncertainty_weight=float(configuration.get("uncertainty_weight", 0.5)),
        diversity_weight=0.0,
        density_weight=0.0,
        disagreement_weight=float(configuration.get("disagreement_weight", 0.1)),
        base_score_weight=float(configuration.get("base_score_weight", 0.1)),
        class_balance_weight=float(configuration.get("class_balance_weight", 0.1)),
    )
    serialized = [asdict(item) for item in results]
    return {
        "review_batch": (
            "review_batch",
            {
                "embedding_model_id": None,
                "strategy": strategy,
                "candidate_count": len(candidates),
                "selected_count": len(results),
                "selected_image_ids": [item.candidate_id for item in results],
                "items": serialized,
                "provenance": {
                    "selector": "reefvision.ml.active_learning_selection.select_candidates",
                    "seed": int(configuration.get("seed", 0)),
                    "probability_only": True,
                    "probability_source": str(
                        configuration.get("probability_source", "workflow_configuration")
                    ),
                },
            },
        )
    }


workflow_science_runtime._workflow_active_learning = _probability_only_active_learning
