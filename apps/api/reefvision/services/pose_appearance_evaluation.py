"""Independent frozen reference preparation and recording/animal denominators."""

import math
from collections import Counter, defaultdict
from typing import Any
from unicodedata import normalize

from sqlalchemy.orm import Session

from reefvision.db.models import ModelRegistration, ReefPoseReference
from reefvision.domain.errors import ValidationError
from reefvision.domain.pose_appearance import calibration, rank, rates
from reefvision.schemas.pose_appearance import AppearanceRequest
from reefvision.services.reefpose_validation import frozen_recording
from reefvision.services.temporal_reefpose_sources import frame_training_lineage


def normalized(value: str) -> str:
    return normalize("NFKC", value).strip().casefold()


def prepare_reference(
    session: Session,
    model: ModelRegistration,
    reference: ReefPoseReference,
    request: AppearanceRequest,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    lineage = frame_training_lineage(session, model)
    if not lineage["complete"] or not lineage.get("declared_groups"):
        raise ValidationError(
            "Held-out scoring needs frozen animal and recording groups for training and selection"
        )
    training_digests = {r["sha256"] for r in lineage["recordings"]}
    training_groups = {
        normalized(token) for recording in lineage["recordings"] for token in recording["groups"]
    }
    partitions: dict[tuple[str, str], str] = {}
    crops: list[dict[str, Any]] = []
    excluded: Counter[str] = Counter()
    annotation_sources = []
    for raw in reference.manifest["recordings"]:
        record = frozen_recording(raw)
        annotation = next(
            (r for r in record.annotations if r.rater_id == request.reference_rater), None
        )
        if annotation is None:
            raise ValidationError("Selected reference rater must cover every recording")
        if not all(r.blinded for r in record.annotations if not r.adjudicates):
            raise ValidationError(
                "Appearance scoring requires independently blinded reference labels"
            )
        if reference.data_kind == "biological" and not annotation.adjudicates:
            raise ValidationError(
                "Biological scoring requires adjudicated cross-recording identities"
            )
        group = normalized(record.group_id)
        identifiers = {normalized(item.id) for item in record.individuals}
        for kind, token in [("recording", group), *(("animal", value) for value in identifiers)]:
            if partitions.setdefault((kind, token), record.split) != record.split:
                raise ValidationError(
                    "An animal or recording occurs in both development and held-out testing"
                )
            if {f"group:{kind}:{token}", f"group:{token}", f"{kind}:{token}"} & training_groups:
                raise ValidationError(
                    "A reference animal or recording overlaps training or model selection"
                )
        if record.video_sha256 in training_digests:
            raise ValidationError("Reference media overlaps model training or selection")
        annotation_sources.append(
            {
                "video_id": str(record.video_id),
                "video_sha256": record.video_sha256,
                "group": record.group_id,
                "split": record.split,
                "rater_id": annotation.rater_id,
                "adjudicates": annotation.adjudicates,
                "annotation_sha256": raw["annotation_sha256"][annotation.rater_id],
            }
        )
        by_animal: dict[str, list[Any]] = defaultdict(list)
        for pose in annotation.poses:
            if pose.state != "scored" or pose.bbox is None:
                excluded[pose.state] += 1
            else:
                by_animal[pose.individual_id].append(pose)
        for animal, poses in sorted(by_animal.items()):
            ordered = sorted(poses, key=lambda p: p.frame)
            # Each recording/animal contributes its first and last scored appearance.
            selected = [ordered[0], ordered[-1]] if len(ordered) > 1 else [ordered[0]]
            excluded["intermediate_scored_frames"] += len(ordered) - len(selected)
            for pose in selected:
                crops.append(
                    {
                        "key": f"reference-{len(crops) + 1}",
                        "video_id": str(record.video_id),
                        "video_sha256": record.video_sha256,
                        "frame": pose.frame,
                        "bbox_xywh": list(pose.bbox),
                        "split": record.split,
                        "animal": normalized(animal),
                        "recording_group": record.group_id,
                        "schema_sha256": record.schema_sha256,
                        "fps": raw["video_geometry"]["fps"],
                    }
                )
    if len(crops) > 512:
        raise ValidationError("This reference exceeds 512 first/last appearance crops per study")
    if {c["split"] for c in crops} != {"development", "test"}:
        raise ValidationError(
            "Independent appearance evaluation needs development and test observations"
        )
    return crops, {
        "reference_id": reference.id,
        "reference_sha256": reference.manifest_sha256,
        "data_kind": reference.data_kind,
        "rater": request.reference_rater,
        "annotation_sources": annotation_sources,
        "sample_rule": "first and last scored crop per animal per recording",
        "reference_exclusions": dict(excluded),
        "training_lineage": lineage,
    }


def eligible(a: dict[str, Any], b: dict[str, Any], gap: float) -> bool:
    if a["video_sha256"] != b["video_sha256"]:
        return True
    return bool(abs(a["frame"] - b["frame"]) / a["fps"] >= gap)


def similarity(a: list[float], b: list[float]) -> float:
    return min(1.0, max(-1.0, math.fsum(x * y for x, y in zip(a, b, strict=True))))


def evaluate(
    crops: list[dict[str, Any]], vectors: dict[str, list[float]], request: AppearanceRequest
) -> tuple[float, dict[str, Any]]:
    scores: dict[str, dict[str, float]] = {}
    genuine: list[float] = []
    impostor: list[float] = []
    for probe in crops:
        gallery: dict[str, float] = {}
        for other in crops:
            if other["split"] != probe["split"] or not eligible(
                probe, other, request.minimum_gap_seconds
            ):
                continue
            score = similarity(vectors[probe["key"]], vectors[other["key"]])
            animal = other["animal"]
            gallery[animal] = max(gallery.get(animal, -1.0), score)
        scores[probe["key"]] = gallery
        if probe["split"] == "development":
            for animal, score in gallery.items():
                (genuine if animal == probe["animal"] else impostor).append(score)
    try:
        threshold = calibration(genuine, impostor, request.maximum_development_false_rate)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc

    def summarize(split: str) -> dict[str, Any]:
        rows = []
        states: Counter[str] = Counter()
        groups: dict[str, list[Any]] = defaultdict(list)
        animals: dict[str, list[Any]] = defaultdict(list)
        probes = []
        for probe in (c for c in crops if c["split"] == split):
            gallery = scores[probe["key"]]
            if not gallery:
                states["no_eligible_gallery"] += 1
                continue
            ranking = rank(list(gallery.items()), threshold, request.minimum_margin)
            states[ranking["state"]] += 1
            known = {probe["animal"]} & gallery.keys()
            row = (known, set(gallery), ranking["selected"])
            rows.append(row)
            groups[probe["recording_group"]].append(row)
            animals[probe["animal"]].append(row)
            probes.append({"crop": probe["key"], "reference_animal": probe["animal"], **ranking})
        return {
            "counts": rates(rows),
            "decisions": dict(states),
            "scored_animals": len(animals),
            "scored_recording_groups": len(groups),
            "by_animal": {key: rates(items) for key, items in animals.items()},
            "by_recording_group": {key: rates(items) for key, items in groups.items()},
            "probes": probes,
        }

    development = summarize("development")
    heldout = summarize("test")
    if not heldout["counts"]["probes"]:
        raise ValidationError(
            "The held-out reference has no eligible cross-gap or cross-video gallery"
        )
    if (
        request.maximum_heldout_false_rate is not None
        and request.maximum_heldout_missed_rate is not None
    ):
        counts = heldout["counts"]
        limits = {
            "false_match_rate": request.maximum_heldout_false_rate,
            "missed_match_rate": request.maximum_heldout_missed_rate,
        }
        heldout["prespecified_targets"] = {
            metric: {
                "limit": limit,
                "within_limit": None if counts[metric] is None else counts[metric] <= limit,
            }
            for metric, limit in limits.items()
        }
    return threshold, {
        "development": development,
        "heldout": heldout,
        "development_genuine": len(genuine),
        "development_impostor": len(impostor),
        "maximum_development_false_rate": request.maximum_development_false_rate,
        "method": (
            "Use the maximum eligible gallery score per known identity and select at most "
            "one link per probe. False matches use impostor galleries. Missed matches "
            "use eligible genuine galleries, including ambiguity and abstention."
        ),
    }
