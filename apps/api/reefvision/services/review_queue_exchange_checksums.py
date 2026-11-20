"""Queue input checksums linked through deliberate Project Exchange remapping."""

from collections.abc import Mapping
from typing import Any

from reefvision.db.models.review_queue_item import ReviewQueueItem
from reefvision.storage.datasets import canonical_json_sha256

QUEUE_IMPORT_CHECKSUM_SCHEMA = "review-queue-item-exchange-import-0001"
QUEUE_INPUT_HISTORY = "reviewer_lab_exchange_input_history"

_ITEM_JSON_FIELDS = (
    "label_class_ids",
    "model_ids",
    "related_issue_ids",
    "signal_values",
    "normalized_signals",
    "weights",
    "score_breakdown",
)
_ITEM_SCALAR_FIELDS = (
    "review_queue_id",
    "project_id",
    "dataset_version_id",
    "image_id",
    "split",
    "score",
    "rank_position",
    "highest_qc_severity",
)


def queue_item_snapshot(item: ReviewQueueItem) -> dict[str, Any]:
    return {
        field: getattr(item, field)
        for field in (
            "id",
            "input_checksum",
            *_ITEM_SCALAR_FIELDS,
            *(f"{name}_json" for name in _ITEM_JSON_FIELDS),
        )
    }


def imported_queue_item_checksum(item: Mapping[str, Any]) -> str:
    return canonical_json_sha256(
        {
            "schema_version": QUEUE_IMPORT_CHECKSUM_SCHEMA,
            **{field: item[field] for field in _ITEM_SCALAR_FIELDS},
            **{field: item[f"{field}_json"] for field in _ITEM_JSON_FIELDS},
        }
    )


def historical_queue_item_checksums(
    configuration: Mapping[str, Any], item: Mapping[str, Any]
) -> list[str]:
    """Only accept a witness linked to the current, recomputed import checksum."""
    ancestry = configuration.get(QUEUE_INPUT_HISTORY, {})
    receipt = ancestry.get(item["id"]) if isinstance(ancestry, dict) else None
    if (
        not isinstance(receipt, dict)
        or receipt.get("current") != item["input_checksum"]
        or imported_queue_item_checksum(item) != item["input_checksum"]
    ):
        return []
    digests = receipt.get("ancestors")
    if not isinstance(digests, list) or any(
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
        for value in digests
    ):
        return []
    return digests


def matches_pinned_queue_item(
    configuration: Mapping[str, Any], item: Mapping[str, Any], pinned: str | None
) -> bool:
    return item["input_checksum"] == pinned or pinned in historical_queue_item_checksums(
        configuration,
        item,
    )
