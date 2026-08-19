from types import SimpleNamespace
from typing import Any, cast

import pytest

from reefvision.jobs.workflow_probability_only_active_learning import (
    _probability_only_active_learning,
)


def _input_artifact(*image_ids: str) -> Any:
    return SimpleNamespace(payload_json={"image_ids": list(image_ids)})


def test_probability_only_least_confidence_does_not_require_embedding_model() -> None:
    outputs = _probability_only_active_learning(
        cast(Any, None),
        cast(Any, SimpleNamespace(project_id="project-1")),
        {
            "strategy": "least_confidence",
            "maximum_items": 1,
            "probabilities": {
                "image-confident": [0.95, 0.05],
                "image-uncertain": [0.55, 0.45],
            },
            "probability_source": "classification_predictions",
        },
        [_input_artifact("image-confident", "image-uncertain")],
    )

    artifact_type, payload = outputs["review_batch"]
    assert artifact_type == "review_batch"
    assert payload["embedding_model_id"] is None
    assert payload["selected_image_ids"] == ["image-uncertain"]
    assert payload["provenance"]["probability_only"] is True
    assert payload["provenance"]["probability_source"] == "classification_predictions"


def test_probability_only_candidates_can_come_directly_from_probability_map() -> None:
    outputs = _probability_only_active_learning(
        cast(Any, None),
        cast(Any, SimpleNamespace(project_id="project-1")),
        {
            "strategy": "entropy",
            "maximum_items": 2,
            "probabilities": {
                "image-a": [0.5, 0.5],
                "image-b": [0.8, 0.2],
            },
        },
        [],
    )

    _artifact_type, payload = outputs["review_batch"]
    assert payload["candidate_count"] == 2
    assert set(payload["selected_image_ids"]) == {"image-a", "image-b"}


def test_diversity_strategy_still_requires_embedding_model() -> None:
    with pytest.raises(RuntimeError, match="embedding_model_id"):
        _probability_only_active_learning(
            cast(Any, None),
            cast(Any, SimpleNamespace(project_id="project-1")),
            {
                "strategy": "k_center",
                "maximum_items": 1,
                "probabilities": {"image-a": [0.5, 0.5]},
            },
            [_input_artifact("image-a")],
        )
