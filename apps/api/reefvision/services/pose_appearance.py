"""Freeze reviewed source crops, score immutable media, and retain explicit decisions."""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import (
    ModelRegistration,
    PoseAnimalIdentity,
    PoseAppearanceDecision,
    PoseAppearanceStudy,
    PoseIdentityAssociationRun,
    PoseIdentityObservation,
    Project,
    VideoAsset,
)
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.domain.pose_appearance import rank
from reefvision.schemas.pose_appearance import (
    AppearanceDecisionRequest,
    AppearanceObservationOption,
    AppearanceRequest,
    AppearanceResult,
    AppearanceSummary,
)
from reefvision.schemas.reviewer_lab_v15 import ReviewerLabRole
from reefvision.services.pose_appearance_evaluation import (
    eligible,
    evaluate,
    prepare_reference,
    similarity,
)
from reefvision.services.pose_evaluation import PoseEvaluationService
from reefvision.services.reefpose_validation import ReferenceService
from reefvision.services.temporal_reefpose_sources import REVIEWED
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.storage.pose_appearance import source_crops, verified_media


def observation_options(
    session: Session, project: str, limit: int, offset: int
) -> list[AppearanceObservationOption]:
    rows = session.execute(
        select(PoseIdentityObservation, VideoAsset, PoseAnimalIdentity)
        .join(
            PoseIdentityAssociationRun,
            PoseIdentityObservation.association_run_id == PoseIdentityAssociationRun.id,
        )
        .join(VideoAsset, VideoAsset.id == PoseIdentityAssociationRun.video_id)
        .join(
            PoseAnimalIdentity, PoseAnimalIdentity.id == PoseIdentityObservation.animal_identity_id
        )
        .where(
            PoseIdentityAssociationRun.project_id == project,
            PoseIdentityAssociationRun.status == "completed",
            PoseIdentityObservation.verification_state.in_(REVIEWED),
            PoseIdentityObservation.is_current.is_(True),
            PoseIdentityObservation.visibility_state == "visible",
        )
        .order_by(
            VideoAsset.original_filename,
            PoseIdentityObservation.frame_index,
            PoseIdentityObservation.id,
        )
        .offset(offset)
        .limit(limit)
    )
    return [
        AppearanceObservationOption(
            id=UUID(o.id),
            video_id=UUID(v.id),
            filename=v.original_filename,
            frame_index=o.frame_index,
            identity_name=a.display_name or a.stable_identity_key,
            revision=o.revision,
        )
        for o, v, a in rows
    ]


def model_for(session: Session, project: str, identifier: str) -> ModelRegistration:
    model = session.get(ModelRegistration, identifier)
    if (
        model is None
        or model.project_id != project
        or model.task != "pose"
        or model.provider_name != "reefpose"
    ):
        raise ValidationError(
            "Choose a locally registered native ReefPose pose model in this project"
        )
    return model


def freeze_inputs(
    session: Session, settings: Settings, project: str, request: AppearanceRequest
) -> dict[str, Any]:
    model = model_for(session, project, str(request.model_id))
    schema_id, revision, checksum = PoseEvaluationService(session, settings)._schema_identity(model)
    crops: list[dict[str, Any]] = []
    for identifier in [request.query_observation_id, *request.gallery_observation_ids]:
        obs = session.get(PoseIdentityObservation, str(identifier))
        run = session.get(PoseIdentityAssociationRun, obs.association_run_id) if obs else None
        if (
            obs is None
            or run is None
            or run.project_id != project
            or run.status != "completed"
            or not obs.is_current
            or obs.verification_state not in REVIEWED
            or obs.visibility_state != "visible"
            or not obs.animal_identity_id
        ):
            raise ValidationError(
                "Select a current, reviewed visible animal observation from this project"
            )
        if (run.pose_schema_id, run.pose_schema_revision, run.pose_schema_content_hash) != (
            schema_id,
            revision,
            checksum,
        ):
            raise ValidationError(
                "The selected observation and registered model must share an anatomy revision"
            )
        video = session.get(VideoAsset, run.video_id)
        if video is None or video.project_id != project:
            raise ValidationError("Source recording is missing from this project")
        observed_identity = session.get(PoseAnimalIdentity, obs.animal_identity_id)
        if observed_identity is None or observed_identity.association_run_id != run.id:
            raise ValidationError("Reviewed animal identity does not belong to this association")
        crop = {
            "key": obs.id,
            "video_id": video.id,
            "filename": video.original_filename,
            "video_sha256": video.sha256,
            "frame": obs.frame_index,
            "fps": video.fps,
            "bbox_xywh": list(obs.bbox_json),
            "run_id": run.id,
            "identity_id": obs.animal_identity_id,
            "identity_name": observed_identity.display_name
            or observed_identity.stable_identity_key,
            "observation_revision": obs.revision,
            "schema_sha256": checksum,
        }
        if crops and not eligible(crops[0], crop, request.minimum_gap_seconds):
            raise ValidationError(
                "Probe and gallery frames are closer than the required gap in this recording"
            )
        crops.append(crop)
    reference = None
    reference_crops: list[dict[str, Any]] = []
    if request.reference_id:
        frozen = ReferenceService(session).get(project, str(request.reference_id))
        reference_crops, reference = prepare_reference(session, model, frozen, request)
        if any(c["schema_sha256"] != checksum for c in reference_crops):
            raise ValidationError("Independent reference uses a different pose anatomy revision")
    return {
        "version": "reefpose-appearance-study-1",
        "request": request.model_dump(mode="json"),
        "model": {
            "id": model.id,
            "name": model.display_name,
            "sha256": model.sha256,
            "file_size_bytes": model.file_size_bytes,
            "schema_id": schema_id,
            "schema_revision": revision,
            "schema_sha256": checksum,
        },
        "crops": crops,
        "reference_crops": reference_crops,
        "reference": reference,
    }


def calculate(
    session: Session,
    settings: Settings,
    project: str,
    inputs: dict[str, Any],
    mapped: dict[str, str],
    check: Callable[[], None],
) -> dict[str, Any]:
    from reefvision.ml.reefpose.appearance import METHOD, AppearanceEncoder

    request = AppearanceRequest.model_validate(inputs["request"])
    pinned = inputs["model"]
    model = model_for(session, project, mapped.get(pinned["id"], pinned["id"]))
    if (model.sha256, model.file_size_bytes) != (pinned["sha256"], pinned["file_size_bytes"]):
        raise ValidationError("Pinned appearance checkpoint identity changed")
    path = verified_media(settings, model.managed_path, model.sha256, model.file_size_bytes)
    encoder = AppearanceEncoder(path, request.device)
    all_crops = inputs["crops"] + inputs["reference_crops"]
    by_video: dict[str, list[dict[str, Any]]] = {}
    for item in all_crops:
        by_video.setdefault(item["video_id"], []).append(item)
    vectors = {}
    pixels = {}
    for video_id, items in by_video.items():
        video = session.get(VideoAsset, mapped.get(video_id, video_id))
        if (
            video is None
            or video.project_id != project
            or any(
                video.sha256 != item["video_sha256"] or video.fps != item["fps"] for item in items
            )
        ):
            raise ValidationError("Frozen appearance recording identity changed")
        decoded = source_crops(
            settings,
            video,
            [(item["key"], item["frame"], item["bbox_xywh"]) for item in items],
            check,
        )
        for key, (image, bounds, sha) in decoded.items():
            check()
            vectors[key] = encoder.encode(image)
            pixels[key] = {
                "bounds_xyxy": bounds,
                "rgb_sha256": sha,
                "width": image.width,
                "height": image.height,
            }
    threshold = request.minimum_similarity
    evaluation = None
    if inputs["reference"] is not None:
        threshold, evaluation = evaluate(inputs["reference_crops"], vectors, request)
    probe, *gallery = inputs["crops"]
    choice = rank(
        [
            (item["key"], similarity(vectors[probe["key"]], vectors[item["key"]]))
            for item in gallery
        ],
        threshold,
        request.minimum_margin,
    )
    return {
        "method": METHOD,
        "checkpoint_training_step": encoder.global_step,
        "device": str(encoder.device),
        "anatomy_sha256": encoder.schema.integrity_hash,
        "minimum_similarity": threshold,
        "minimum_margin": request.minimum_margin,
        "threshold_source": "independent development partition"
        if evaluation
        else "researcher-specified",
        "time_basis": "frame index divided by nominal source FPS within each recording",
        "crop_pixels": pixels,
        "ranking": choice,
        "evaluation": evaluation,
    }


def study_row(session: Session, project: str, identifier: str) -> PoseAppearanceStudy:
    row = session.get(PoseAppearanceStudy, identifier)
    if row is None or row.project_id != project:
        raise NotFoundError("Appearance study was not found in this project")
    if canonical_json_sha256(row.payload_json) != row.content_sha256:
        raise ValidationError("Appearance study digest does not match its sealed content")
    return row


def study_summary(row: PoseAppearanceStudy) -> AppearanceSummary:
    return AppearanceSummary(
        id=UUID(row.id),
        name=row.payload_json["inputs"]["request"]["name"],
        content_sha256=row.content_sha256,
        created_at=row.created_at,
    )


def decisions(session: Session, row: PoseAppearanceStudy) -> list[PoseAppearanceDecision]:
    found = list(
        session.scalars(
            select(PoseAppearanceDecision)
            .where(PoseAppearanceDecision.study_id == row.id)
            .order_by(PoseAppearanceDecision.created_at, PoseAppearanceDecision.id)
        )
    )
    if any(canonical_json_sha256(d.payload_json) != d.content_sha256 for d in found):
        raise ValidationError("Appearance judgement digest does not match")
    return found


def _local_actor(d: PoseAppearanceDecision) -> str:
    original = str(d.payload_json["reviewer"]["member_id"])
    return d.source_id_map_json.get(original, original)


def view(
    session: Session, row: PoseAppearanceStudy, actor: ReviewerLabRole | None = None
) -> AppearanceResult:
    history = decisions(session, row)
    resolved = "awaiting independent review"
    if len(history) >= 2:

        def value(item: PoseAppearanceDecision) -> tuple[str, str | None]:
            return item.payload_json["outcome"], item.payload_json["candidate_observation_id"]

        paired = sorted(history, key=lambda d: d.role_slot)
        adjudication = next((item for item in paired if item.role_slot == "adjudication"), None)
        if adjudication:
            resolved = adjudication.payload_json["outcome"]
        else:
            resolved = value(paired[0])[0] if value(paired[0]) == value(paired[1]) else "disputed"
    visible = [
        d for d in history if len(history) >= 2 or (actor and _local_actor(d) == actor.member_id)
    ]
    return AppearanceResult(
        **study_summary(row).model_dump(),
        snapshot=row.payload_json,
        decisions=[
            {"id": d.id, "content_sha256": d.content_sha256, **d.payload_json} for d in visible
        ],
        resolution=resolved,
    )


def add_decision(
    session: Session,
    project: str,
    identifier: str,
    request: AppearanceDecisionRequest,
    actor: ReviewerLabRole,
) -> AppearanceResult:
    # Serialize independent slots, including replays of a submitted local operation.
    session.execute(update(Project).where(Project.id == project).values(id=Project.id))
    row = study_row(session, project, identifier)
    if request.study_sha256 != row.content_sha256:
        raise ConflictError("The appearance study digest changed")
    history = decisions(session, row)
    for d in history:
        if d.operation_id == str(request.operation_id):
            if d.role_revision_id != actor.id or d.payload_json[
                "request_sha256"
            ] != canonical_json_sha256(request.model_dump(mode="json")):
                raise ConflictError("This review operation already has a different judgement")
            return view(session, row, actor)
    if actor.role not in {"reviewer", "adjudicator"} or any(
        _local_actor(d) == actor.member_id for d in history
    ):
        raise ConflictError("Choose an independent active reviewer for this judgement")
    if actor.role == "reviewer":
        if len(history) >= 2:
            raise ConflictError("Both independent judgements are already recorded")
        slot = "first" if not history else "second"
    else:
        if len(history) != 2 or view(session, row, actor).resolution != "disputed":
            raise ConflictError("Adjudication requires two disagreeing independent reviews")
        slot = "adjudication"
    candidate = str(request.candidate_observation_id) if request.candidate_observation_id else None
    eligible_candidates = {item["key"] for item in row.payload_json["inputs"]["crops"][1:]}
    if candidate is not None and candidate not in eligible_candidates:
        raise ValidationError("The reviewed candidate is outside this frozen gallery")
    payload = {
        "role_slot": slot,
        "study_sha256": row.content_sha256,
        "request_sha256": canonical_json_sha256(request.model_dump(mode="json")),
        "outcome": request.outcome,
        "candidate_observation_id": candidate,
        "reason": request.reason,
        "reviewer": actor.model_dump(mode="json"),
        "adjudicated_decisions": [d.content_sha256 for d in history]
        if slot == "adjudication"
        else [],
    }
    session.add(
        PoseAppearanceDecision(
            study_id=row.id,
            role_revision_id=actor.id,
            operation_id=str(request.operation_id),
            role_slot=slot,
            payload_json=payload,
            content_sha256=canonical_json_sha256(payload),
        )
    )
    session.commit()
    return view(session, row, actor)
