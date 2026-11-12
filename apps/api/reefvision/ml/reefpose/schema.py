"""Immutable anatomical landmark schemas used by ReefPose checkpoints."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, ClassVar
from uuid import NAMESPACE_URL, uuid5

from reefvision.ml.reefpose.errors import ReefPoseValidationError

VisibilityState = str
VISIBILITY_STATES = frozenset({"absent", "occluded", "visible", "uncertain", "out_of_frame"})


def _required_text(value: str, field_name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ReefPoseValidationError(f"{field_name} cannot be blank")
    return normalized


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _legacy_projected_id(label: str, occurrence: int, total: int) -> str:
    slug = re.sub(r"[^a-z0-9_-]+", "_", label.casefold()).strip("_") or "landmark"
    if not slug[0].isalpha():
        slug = f"landmark_{slug}"
    return slug if total == 1 else f"{slug}_{occurrence + 1}"


@dataclass(frozen=True, slots=True)
class LandmarkDefinition:
    """One stable landmark slot, including repeated anatomical structures."""

    landmark_id: str
    name: str
    description: str | None = None
    group: str | None = None
    occurrence_index: int = 0
    symmetric_with: str | None = None
    required: bool = True
    allowed_visibility: tuple[VisibilityState, ...] = (
        "absent",
        "occluded",
        "visible",
        "uncertain",
        "out_of_frame",
    )
    default_visibility: VisibilityState = "visible"

    def __post_init__(self) -> None:
        object.__setattr__(self, "landmark_id", _required_text(self.landmark_id, "landmark_id"))
        object.__setattr__(self, "name", _required_text(self.name, "landmark name"))
        object.__setattr__(self, "description", _optional_text(self.description))
        object.__setattr__(self, "group", _optional_text(self.group))
        object.__setattr__(self, "symmetric_with", _optional_text(self.symmetric_with))
        if self.occurrence_index < 0:
            raise ReefPoseValidationError("Landmark occurrence indices cannot be negative")
        allowed = tuple(dict.fromkeys(str(item).strip() for item in self.allowed_visibility))
        if not allowed or any(item not in VISIBILITY_STATES for item in allowed):
            raise ReefPoseValidationError("Landmark visibility states are invalid")
        object.__setattr__(self, "allowed_visibility", allowed)
        if self.default_visibility not in allowed:
            raise ReefPoseValidationError(
                "Landmark default visibility must be one of its allowed visibility states"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "landmark_id": self.landmark_id,
            "name": self.name,
            "description": self.description,
            "group": self.group,
            "occurrence_index": self.occurrence_index,
            "symmetric_with": self.symmetric_with,
            "required": self.required,
            "allowed_visibility": list(self.allowed_visibility),
            "default_visibility": self.default_visibility,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> LandmarkDefinition:
        return cls(
            landmark_id=str(payload.get("landmark_id", "")),
            name=str(payload.get("name", "")),
            description=(
                str(payload["description"]) if payload.get("description") is not None else None
            ),
            group=str(payload["group"]) if payload.get("group") is not None else None,
            occurrence_index=int(payload.get("occurrence_index", 0)),
            symmetric_with=(
                str(payload["symmetric_with"])
                if payload.get("symmetric_with") is not None
                else None
            ),
            required=bool(payload.get("required", True)),
            allowed_visibility=tuple(
                str(item) for item in payload.get("allowed_visibility", VISIBILITY_STATES)
            ),
            default_visibility=str(payload.get("default_visibility", "visible")),
        )


@dataclass(frozen=True, slots=True)
class SkeletonEdge:
    """An undirected anatomical connection between stable landmark IDs."""

    source_id: str
    target_id: str
    group: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_id", _required_text(self.source_id, "source_id"))
        object.__setattr__(self, "target_id", _required_text(self.target_id, "target_id"))
        object.__setattr__(self, "group", _optional_text(self.group))
        if self.source_id == self.target_id:
            raise ReefPoseValidationError("Skeleton connections cannot be self-referential")

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "target_id": self.target_id,
            "group": self.group,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> SkeletonEdge:
        return cls(
            source_id=str(payload.get("source_id", "")),
            target_id=str(payload.get("target_id", "")),
            group=str(payload["group"]) if payload.get("group") is not None else None,
        )


@dataclass(frozen=True, slots=True)
class AnatomySchema:
    """Versioned canonical anatomy shared by data, models, and predictions."""

    SCHEMA_VERSION: ClassVar[str] = "reefpose-anatomy-0002"
    LEGACY_SCHEMA_VERSION: ClassVar[str] = "reefpose-anatomy-0001"

    schema_id: str
    name: str
    revision: int
    landmarks: tuple[LandmarkDefinition, ...]
    skeleton: tuple[SkeletonEdge, ...] = field(default_factory=tuple)
    description: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "schema_id", _required_text(self.schema_id, "schema_id"))
        object.__setattr__(self, "name", _required_text(self.name, "schema name"))
        object.__setattr__(self, "description", _optional_text(self.description))
        object.__setattr__(self, "landmarks", tuple(self.landmarks))
        object.__setattr__(self, "skeleton", tuple(self.skeleton))
        if self.revision < 1:
            raise ReefPoseValidationError("Schema revision must be at least 1")
        if not self.landmarks:
            raise ReefPoseValidationError("An anatomy schema requires at least one landmark")
        landmark_ids = [item.landmark_id for item in self.landmarks]
        if len(landmark_ids) != len(set(landmark_ids)):
            raise ReefPoseValidationError("Anatomy schema landmark IDs must be unique")
        occurrences = [(item.name.casefold(), item.occurrence_index) for item in self.landmarks]
        if len(occurrences) != len(set(occurrences)):
            raise ReefPoseValidationError(
                "Repeated landmark names must use a unique occurrence index"
            )
        known = set(landmark_ids)
        by_id = {item.landmark_id: item for item in self.landmarks}
        for landmark in self.landmarks:
            partner_id = landmark.symmetric_with
            if partner_id is None:
                continue
            partner = by_id.get(partner_id)
            if partner is None or partner.symmetric_with != landmark.landmark_id:
                raise ReefPoseValidationError(
                    "Symmetry relationships must reference reciprocal landmark IDs"
                )
        edge_keys: set[frozenset[str]] = set()
        for edge in self.skeleton:
            if edge.source_id not in known or edge.target_id not in known:
                raise ReefPoseValidationError("Skeleton connection references an unknown landmark")
            key = frozenset((edge.source_id, edge.target_id))
            if key in edge_keys:
                raise ReefPoseValidationError("Skeleton connections must be unique")
            edge_keys.add(key)

    @property
    def keypoint_count(self) -> int:
        return len(self.landmarks)

    @property
    def expanded_names(self) -> tuple[str, ...]:
        return tuple(item.name for item in self.landmarks)

    @property
    def legacy_projected_id_aliases(self) -> dict[str, str]:
        """Map GUI legacy IDs to historical UUID slots when this is a legacy projection."""

        totals = Counter(item.name for item in self.landmarks)
        aliases: dict[str, str] = {}
        for landmark in self.landmarks:
            expected_native_id = str(
                uuid5(
                    NAMESPACE_URL,
                    (
                        f"reefvision-pose:{self.schema_id}:"
                        f"{landmark.name.casefold()}:{landmark.occurrence_index}"
                    ),
                )
            )
            if landmark.landmark_id != expected_native_id:
                return {}
            aliases[
                _legacy_projected_id(
                    landmark.name,
                    landmark.occurrence_index,
                    totals[landmark.name],
                )
            ] = landmark.landmark_id
        return aliases

    def _canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "schema_id": self.schema_id,
            "name": self.name,
            "description": self.description,
            "revision": self.revision,
            "landmarks": [item.to_dict() for item in self.landmarks],
            "skeleton": [item.to_dict() for item in self.skeleton],
        }

    @property
    def integrity_hash(self) -> str:
        canonical = json.dumps(
            self._canonical_payload(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {**self._canonical_payload(), "integrity_hash": self.integrity_hash}

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> AnatomySchema:
        source_version = str(payload.get("schema_version", cls.SCHEMA_VERSION))
        if source_version not in {cls.LEGACY_SCHEMA_VERSION, cls.SCHEMA_VERSION}:
            raise ReefPoseValidationError("Unsupported ReefPose anatomy schema version")
        raw_landmarks = payload.get("landmarks")
        raw_skeleton = payload.get("skeleton", [])
        if not isinstance(raw_landmarks, list) or not isinstance(raw_skeleton, list):
            raise ReefPoseValidationError("ReefPose anatomy schema structure is invalid")
        schema = cls(
            schema_id=str(payload.get("schema_id", "")),
            name=str(payload.get("name", "")),
            description=(
                str(payload["description"]) if payload.get("description") is not None else None
            ),
            revision=int(payload.get("revision", 0)),
            landmarks=tuple(LandmarkDefinition.from_dict(item) for item in raw_landmarks),
            skeleton=tuple(SkeletonEdge.from_dict(item) for item in raw_skeleton),
        )
        expected_hash = payload.get("integrity_hash")
        if expected_hash is not None:
            valid_hashes = {schema.integrity_hash}
            if source_version == cls.LEGACY_SCHEMA_VERSION:
                extended = schema._canonical_payload()
                extended["schema_version"] = cls.LEGACY_SCHEMA_VERSION
                candidates = [extended]
                has_extended_landmark_metadata = any(
                    isinstance(item, dict)
                    and ("symmetric_with" in item or "required" in item)
                    for item in raw_landmarks
                )
                if not has_extended_landmark_metadata:
                    candidates.append(
                        {
                            **extended,
                            "landmarks": [
                                {
                                    key: value
                                    for key, value in landmark.to_dict().items()
                                    if key not in {"symmetric_with", "required"}
                                }
                                for landmark in schema.landmarks
                            ],
                        }
                    )
                for candidate in candidates:
                    valid_hashes.add(
                        hashlib.sha256(
                            json.dumps(
                                candidate,
                                sort_keys=True,
                                separators=(",", ":"),
                                ensure_ascii=False,
                            ).encode("utf-8")
                        ).hexdigest()
                    )
            if str(expected_hash) not in valid_hashes:
                raise ReefPoseValidationError(
                    "ReefPose anatomy schema integrity hash does not match"
                )
        return schema

    @classmethod
    def from_reefvision_groups(
        cls,
        *,
        name: str,
        revision: int,
        groups: list[dict[str, Any]],
        schema_id: str,
        description: str | None = None,
        skeleton: list[tuple[str, str]] | None = None,
    ) -> AnatomySchema:
        """Convert ReefVision repeated-label groups without changing their order."""

        landmarks: list[LandmarkDefinition] = []
        by_legacy_key: dict[str, str] = {}
        seen_names: set[str] = set()
        for raw in groups:
            landmark_name = _required_text(str(raw.get("name", "")), "landmark name")
            normalized_name = landmark_name.casefold()
            if normalized_name in seen_names:
                raise ReefPoseValidationError(
                    "ReefVision group names must be unique; use count for repetitions"
                )
            seen_names.add(normalized_name)
            count = int(raw.get("count", 1))
            if count < 1:
                raise ReefPoseValidationError("ReefVision landmark counts must be positive")
            for occurrence in range(count):
                stable_id = str(
                    uuid5(
                        NAMESPACE_URL,
                        f"reefvision-pose:{schema_id}:{normalized_name}:{occurrence}",
                    )
                )
                landmarks.append(
                    LandmarkDefinition(
                        landmark_id=stable_id,
                        name=landmark_name,
                        description=(
                            str(raw["description"]) if raw.get("description") is not None else None
                        ),
                        group=str(raw["group"]) if raw.get("group") is not None else None,
                        occurrence_index=occurrence,
                    )
                )
                by_legacy_key[landmark_name if count == 1 else f"{landmark_name}#{occurrence}"] = (
                    stable_id
                )
        edges: list[SkeletonEdge] = []
        for source, target in skeleton or []:
            source_id = by_legacy_key.get(source, source)
            target_id = by_legacy_key.get(target, target)
            edges.append(SkeletonEdge(source_id=source_id, target_id=target_id))
        return cls(
            schema_id=schema_id,
            name=name,
            description=description,
            revision=revision,
            landmarks=tuple(landmarks),
            skeleton=tuple(edges),
        )
