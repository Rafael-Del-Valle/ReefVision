"""Select 2.0 only for new record types and preserve original appearance evidence."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.db.models import Job, PoseAppearanceStudy, ScientificRecord, WorkflowGraphRecord
from reefvision.db.models.multimodal import MultimodalStudy
from reefvision.domain.errors import ValidationError
from reefvision.schemas.pose_appearance import AppearanceRequest
from reefvision.services import project_exchange_multimodal_v20 as multimodal
from reefvision.storage.datasets import canonical_json_sha256

FORMAT = "2.0"
STUDIES = "pose_appearance_studies"
DECISIONS = "pose_appearance_decisions"
APPEARANCE_SECTIONS = (STUDIES, DECISIONS)
SECTIONS = (*APPEARANCE_SECTIONS, multimodal.SECTION)
WORKFLOW_TYPES = frozenset(
    {
        "reefpose_appearance_replay",
        "plugin_image_measurement",
        "measurement_review_gate",
        "multimodal_study_replay",
    }
)


def uses_v20_graph(graph: dict[str, Any]) -> bool:
    return any(
        node.get("node_type") in WORKFLOW_TYPES
        for node in graph.get("nodes", [])
        if isinstance(node, dict)
    )


def has_v20_records(session: Session, project: str) -> bool:
    graphs = select(WorkflowGraphRecord).where(WorkflowGraphRecord.project_id == project)
    measurements = (
        select(ScientificRecord.id)
        .where(
            ScientificRecord.project_id == project,
            ScientificRecord.payload_json["provenance"]["source"].as_string()
            == "ReefVision local plugin",
            ScientificRecord.payload_json["provenance"]["method"].as_string()
            == "reefvision.rgb-summary/1",
        )
        .limit(1)
    )
    return (
        session.scalar(
            select(PoseAppearanceStudy.id).where(PoseAppearanceStudy.project_id == project).limit(1)
        )
        is not None
        or session.scalar(
            select(Job.id)
            .where(Job.project_id == project, Job.job_type == "pose_appearance")
            .limit(1)
        )
        is not None
        or session.scalar(
            select(MultimodalStudy.id).where(MultimodalStudy.project_id == project).limit(1)
        )
        is not None
        or session.scalar(measurements) is not None
        or any(uses_v20_graph(record.graph_json) for record in session.scalars(graphs))
    )


def required_format(rows: dict[str, list[dict[str, Any]]]) -> bool:
    def is_measurement(scientific: dict[str, Any]) -> bool:
        evidence = scientific.get("payload_json", {}).get("provenance", {})
        return bool(
            evidence.get("source") == "ReefVision local plugin"
            and evidence.get("method") == "reefvision.rgb-summary/1"
        )

    return (
        any(rows.get(name) for name in SECTIONS)
        or any(row.get("job_type") == "pose_appearance" for row in rows.get("jobs", ()))
        or any(uses_v20_graph(r.get("graph_json", {})) for r in rows.get("workflow_graphs", ()))
        or any(is_measurement(r) for r in rows.get("scientific_records", ()))
    )


def snapshot_sources(name: str, payload: dict[str, Any]) -> dict[str, set[str]]:
    if name == DECISIONS:
        actor = payload["reviewer"]
        return {
            "reviewer_lab_members": {actor["member_id"]},
            "reviewer_lab_role_revisions": {actor["id"]},
        }
    inputs = payload["inputs"]
    sources = {
        "models": {inputs["model"]["id"]},
        "videos": {c["video_id"] for c in inputs["crops"] + inputs["reference_crops"]},
        "pose_identity_observations": {c["key"] for c in inputs["crops"]},
        "pose_identity_association_runs": {c["run_id"] for c in inputs["crops"]},
        "pose_animal_identities": {c["identity_id"] for c in inputs["crops"]},
    }
    if reference := inputs["reference"]:
        sources["reefpose_references"] = {reference["reference_id"]}
        sources["videos"].update(item["video_id"] for item in reference["annotation_sources"])
        sources["pose_training_datasets"] = {
            item["id"] for item in reference["training_lineage"]["datasets"]
        }
    return sources


def remap_appearance(
    name: str, row: dict[str, Any], values: dict[str, Any], mapping: dict[str, str]
) -> None:
    if name == multimodal.SECTION:
        multimodal.remap(row, values, mapping)
        return
    if name not in APPEARANCE_SECTIONS:
        return
    values["payload_json"] = row["payload_json"]
    previous = row["source_id_map_json"]
    values["source_id_map_json"] = {
        old: mapping[previous.get(old, old)]
        for ids in snapshot_sources(name, row["payload_json"]).values()
        for old in ids
    }


def validate_appearance_exchange(
    version: str, project: str, rows: dict[str, list[dict[str, Any]]]
) -> None:
    try:
        _validate_records(version, project, rows)
        multimodal.validate(rows)
    except (KeyError, ValueError, TypeError, IndexError, AttributeError) as exc:
        raise ValidationError("Appearance archive has malformed or unresolved evidence") from exc


def _validate_records(version: str, project: str, rows: dict[str, list[dict[str, Any]]]) -> None:
    present = required_format(rows)
    if present != (version == FORMAT) or (set(rows) & set(SECTIONS) and not present):
        raise ValidationError("The project archive version does not match its 2.0 records")
    if not present:
        return
    by_section = {
        section: {r["id"]: r for r in items if "id" in r} for section, items in rows.items()
    }
    for section in APPEARANCE_SECTIONS:
        for row in rows.get(section, []):
            payload = row["payload_json"]
            mapping = row["source_id_map_json"]
            if canonical_json_sha256(payload) != row["content_sha256"] or not isinstance(
                mapping, dict
            ):
                raise ValidationError("Appearance archive digest or source mapping is invalid")
            sources = snapshot_sources(section, payload)
            expected = {i for ids in sources.values() for i in ids}
            if set(mapping) - expected or any(
                mapping.get(i, i) not in by_section.get(kind, {})
                for kind, ids in sources.items()
                for i in ids
            ):
                raise ValidationError("Frozen appearance evidence includes an unresolved source")
            if section == DECISIONS:
                study = by_section[STUDIES][row["study_id"]]
                reviewer = payload["reviewer"]
                role = by_section["reviewer_lab_role_revisions"][row["role_revision_id"]]
                member = by_section["reviewer_lab_members"][role["member_id"]]
                gallery = {c["key"] for c in study["payload_json"]["inputs"]["crops"][1:]}
                candidate = payload["candidate_observation_id"]
                if (
                    study["content_sha256"] != payload["study_sha256"]
                    or row["role_slot"] != payload["role_slot"]
                    or row["role_revision_id"]
                    != mapping.get(payload["reviewer"]["id"], payload["reviewer"]["id"])
                    or role["member_id"]
                    != mapping.get(reviewer["member_id"], reviewer["member_id"])
                    or member["role"] != reviewer["role"]
                    or member["name"] != reviewer["name"]
                    or not role["active"]
                    or role["revision"] != reviewer["revision"]
                    or reviewer["role"]
                    != ("adjudicator" if row["role_slot"] == "adjudication" else "reviewer")
                    or payload["outcome"] not in {"different", "same", "uncertain"}
                    or (
                        candidate not in gallery
                        and (candidate is not None or payload["outcome"] != "uncertain")
                    )
                ):
                    raise ValidationError("Appearance review belongs to different frozen evidence")
                continue
            inputs = payload["inputs"]
            req = AppearanceRequest.model_validate(inputs["request"])
            model = by_section["models"][row["model_id"]]
            pin = inputs["model"]
            if (
                row["project_id"] != project
                or row["request_sha256"] != canonical_json_sha256(inputs["request"])
                or mapping.get(pin["id"], pin["id"]) != model["id"]
                or model["sha256"] != pin["sha256"]
                or model["provider_name"] != "reefpose"
                or model["task"] != "pose"
            ):
                raise ValidationError(
                    "Appearance study has conflicting model or original request provenance"
                )
            expected_keys = [
                str(req.query_observation_id),
                *(str(i) for i in req.gallery_observation_ids),
            ]
            if [c["key"] for c in inputs["crops"]] != expected_keys:
                raise ValidationError("Frozen appearance gallery differs from its original request")
            for c in inputs["crops"] + inputs["reference_crops"]:
                video = by_section["videos"][mapping.get(c["video_id"], c["video_id"])]
                if (
                    video["sha256"] != c["video_sha256"]
                    or video["fps"] != c["fps"]
                    or not 0 <= c["frame"] < video["frame_count"]
                ):
                    raise ValidationError(
                        "An appearance crop disagrees with the original recording"
                    )
            for c in inputs["crops"]:
                observation = by_section["pose_identity_observations"][
                    mapping.get(c["key"], c["key"])
                ]
                if (
                    observation["frame_index"] != c["frame"]
                    or observation["revision"] != c["observation_revision"]
                    or observation["bbox_json"] != c["bbox_xywh"]
                    or observation["association_run_id"] != mapping.get(c["run_id"], c["run_id"])
                    or observation["animal_identity_id"]
                    != mapping.get(c["identity_id"], c["identity_id"])
                ):
                    raise ValidationError("An appearance crop disagrees with its reviewed source")
            if ref := inputs["reference"]:
                target = by_section["reefpose_references"][row["reference_id"]]
                if (
                    row["reference_id"] != mapping.get(ref["reference_id"], ref["reference_id"])
                    or target["data_kind"] != ref["data_kind"]
                ):
                    raise ValidationError("Appearance reference provenance is inconsistent")
                recordings = {r["video_sha256"]: r for r in target["manifest"]["recordings"]}
                for r in ref["annotation_sources"]:
                    stored = recordings.get(r["video_sha256"], {})
                    if r["annotation_sha256"] != stored.get("annotation_sha256", {}).get(
                        r["rater_id"]
                    ) or r["split"] != stored.get("split"):
                        raise ValidationError(
                            "Appearance labels disagree with their frozen independent reference"
                        )
