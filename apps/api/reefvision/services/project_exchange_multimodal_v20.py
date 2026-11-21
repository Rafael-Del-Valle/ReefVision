"""Preserve source-coordinate multimodal receipts across consecutive portable copies."""

from typing import Any

from reefvision.domain.errors import ValidationError
from reefvision.domain.multimodal import paired_difference
from reefvision.schemas.bioacoustics import AudioReportRead
from reefvision.schemas.multimodal import MultimodalRequest
from reefvision.services.multimodal import audio_evidence
from reefvision.storage.datasets import canonical_json_sha256

SECTION = "multimodal_studies"


def sources(snapshot: dict[str, Any]) -> dict[str, set[str]]:
    req = snapshot["request"]
    boxes = snapshot["boxes"]
    return {
        "bioacoustic_reports": {req["audio_report_id"]},
        "multispectral_indices": {e["index_id"] for e in req["exposures"]},
        "ecology_identity_annotation_evidence": {b["link_id"] for b in boxes},
        "ecology_identity_image_evidence": {b["image_link_id"] for b in boxes},
        "images": {b["image_id"] for b in boxes},
        "annotations": {b["annotation_id"] for b in boxes},
        "ecology_identity_revisions": {b["organism_revision_id"] for b in boxes},
        "reviewer_lab_members": {snapshot["reviewer"]["member_id"]},
        "reviewer_lab_role_revisions": {snapshot["reviewer"]["id"]},
    }


def remap(row: dict[str, Any], values: dict[str, Any], mapping: dict[str, str]) -> None:
    previous = row["source_id_map_json"]
    snapshot = row["snapshot_json"]
    values["snapshot_json"] = snapshot
    values["source_id_map_json"] = {
        old: mapping[previous.get(old, old)] for ids in sources(snapshot).values() for old in ids
    }


def validate(rows: dict[str, list[dict[str, Any]]]) -> None:
    if not rows.get(SECTION):
        return
    sections = {name: {r["id"]: r for r in items if "id" in r} for name, items in rows.items()}
    for row in rows[SECTION]:
        snapshot = row["snapshot_json"]
        mapping = row["source_id_map_json"]
        req = MultimodalRequest.model_validate(snapshot["request"])
        if (
            canonical_json_sha256(snapshot) != row["content_sha256"]
            or canonical_json_sha256(snapshot["request"]) != row["request_sha256"]
            or row["operation_id"] != str(req.operation_id)
        ):
            raise ValidationError("Multimodal study conflicts with its original request or digest")
        declared = sources(snapshot)
        expected = {i for ids in declared.values() for i in ids}
        if set(mapping) - expected or any(
            mapping.get(i, i) not in sections.get(k, {}) for k, ids in declared.items() for i in ids
        ):
            raise ValidationError("Multimodal archive has unresolved source identities")

        def local(key: str, ids: dict[str, str] = mapping) -> str:
            return ids.get(key, key)

        actor = snapshot["reviewer"]
        role = sections["reviewer_lab_role_revisions"][row["role_revision_id"]]
        member = sections["reviewer_lab_members"][role["member_id"]]
        if (
            role["id"] != local(actor["id"])
            or member["id"] != local(actor["member_id"])
            or member["role"] != actor["role"]
            or not role["active"]
            or role["revision"] != actor["revision"]
        ):
            raise ValidationError("Multimodal alignment reviewer differs from the signed role")
        audio = sections["bioacoustic_reports"][row["audio_report_id"]]
        typed = AudioReportRead(
            id=audio["id"],
            project_id=audio["project_id"],
            asset_id=audio["asset_id"],
            snapshot=audio["snapshot_json"],
            report_sha256=audio["report_sha256"],
            created_at=audio["created_at"],
        )
        if (
            local(str(req.audio_report_id)) != audio["id"]
            or audio_evidence(typed) != snapshot["audio"]
        ):
            raise ValidationError(
                "Multimodal alignment differs from its frozen acoustic clock or review"
            )
        for exposure, box in zip(req.exposures, snapshot["boxes"], strict=True):
            link = sections["ecology_identity_annotation_evidence"][local(box["link_id"])]
            annotation = sections["annotations"][local(box["annotation_id"])]
            organism = sections["ecology_identity_revisions"][local(box["organism_revision_id"])]
            image = sections["ecology_identity_image_evidence"][local(box["image_link_id"])]
            index = sections["multispectral_indices"][local(str(exposure.index_id))]
            revisions = [annotation]
            if annotation["revision"] != box["annotation_revision"]:
                revisions.extend(
                    item
                    for event in rows.get("annotation_events", [])
                    if event["annotation_id"] == annotation["id"]
                    for item in (event["before_json"], event["after_json"])
                    if isinstance(item, dict)
                )
            geometry_bound = any(
                source.get("revision") == box["annotation_revision"]
                and [source.get(key) for key in ("x_min", "y_min", "x_max", "y_max")]
                == box["bounds_xyxy"]
                for source in revisions
            )
            if (
                not geometry_bound
                or link["id"] != local(str(exposure.annotation_evidence_id))
                or link["image_evidence_id"] != image["id"]
                or link["annotation_id"] != local(box["annotation_id"])
                or link["annotation_revision"] != box["annotation_revision"]
                or image["image_id"] != local(box["image_id"])
                or image["image_sha256"] != box["image_sha256"]
                or (organism["organism_key"], organism["revision"])
                != (box["organism_key"], box["organism_revision"])
                or index["content_sha256"] != exposure.index_sha256
            ):
                raise ValidationError(
                    "Multimodal spatial, organism or optical provenance disagrees"
                )
        result = snapshot["result"]
        if (
            result["status"] not in {"withheld", "available"}
            or (result["status"] == "withheld") != bool(result["reasons"])
            or result["exposed_minus_control"]
            != (None if result["reasons"] else paired_difference(result["observations"]))
        ):
            raise ValidationError(
                "Multimodal result disagrees with its withheld state or observed contrast"
            )
