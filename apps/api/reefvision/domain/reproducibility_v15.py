"""Rebuild portable research proof from validated native Exchange records."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from reefvision.domain.errors import ValidationError
from reefvision.schemas.model_runtime import RuntimeReceipt
from reefvision.schemas.paired_models_v15 import ComparisonEvidence, ComparisonRequest
from reefvision.schemas.reproducibility_v15 import (
    EvidenceReference,
    EvidenceSection,
    ProofEvidence,
    ReproducibilityProof,
    ReproducibilityProofBody,
    ReproducibilitySelection,
)
from reefvision.schemas.reviewer_lab_v15 import ReviewerLabReport
from reefvision.schemas.study_design import validate_study_design_snapshot
from reefvision.storage.datasets import canonical_json_sha256

EVIDENCE_SECTIONS: tuple[EvidenceSection, ...] = (
    "study",
    "review",
    "comparison",
    "models",
    "methods",
    "environment",
    "exclusions",
)
COMPARISON_JOB = "paired_model_comparison"
NODE_TYPE = "research_reproducibility_package"
ARTIFACT_TYPE = "research_reproducibility_proof"
HISTORICAL_PROOFS = "reproducibility_proofs"


@dataclass(frozen=True)
class ReproducibilityEvidence:
    proof: ReproducibilityProof
    sections: dict[EvidenceSection, Any]


def _row(
    rows: list[dict[str, Any]], identifier: str, project_id: str, label: str
) -> dict[str, Any]:
    matches = [row for row in rows if row["id"] == identifier and row["project_id"] == project_id]
    if len(matches) != 1:
        raise ValueError(f"Expected a single project-owned {label}")
    return matches[0]


def _portable_id(
    archived: str, original: str, digest: str, origin_ids: Mapping[str, str]
) -> EvidenceReference:
    if origin_ids.get(original, original) != archived:
        raise ValueError("Original research receipt does not map to the archived project")
    return EvidenceReference.model_validate({"id": original, "content_sha256": digest})


def derive_evidence(
    sections: dict[str, list[dict[str, Any]]],
    *,
    selection: ReproducibilitySelection,
    project_id: str,
    origin_ids: Mapping[str, str],
    verified_paired_comparison_ids: frozenset[str] = frozenset(),
) -> ReproducibilityEvidence:
    """Select local archive rows and preserve their original scientific identities."""
    try:
        study_row = _row(
            sections.get("study_design_revisions", []),
            str(selection.study_design_id),
            project_id,
            "frozen study revision",
        )
        review_row = _row(
            sections.get("reviewer_lab_reports", []),
            str(selection.reviewer_report_id),
            project_id,
            "sealed reviewer report",
        )
        job = _row(
            sections.get("jobs", []),
            str(selection.comparison_id),
            project_id,
            "comparison",
        )
        study = validate_study_design_snapshot(
            study_row["snapshot_json"], study_row["content_sha256"]
        )
        review_body = review_row["content_json"]
        review = ReviewerLabReport.model_validate(
            {**review_body, "content_sha256": review_row["content_sha256"]},
        )
        result = job["result_json"]
        comparison = result["snapshot"]
        if (
            job["job_type"] != COMPARISON_JOB
            or job["status"] != "succeeded"
            or comparison["schema_version"] != "paired-model-comparison-1.5"
            or canonical_json_sha256(comparison) != result["content_sha256"]
            or canonical_json_sha256(review_body) != review.content_sha256
            or not all(
                origin_ids.get(identifier, identifier) == project_id
                for identifier in (
                    str(study.project_id),
                    review.project_id,
                    comparison["project_id"],
                )
            )
        ):
            raise ValueError("Selected scientific evidence has invalid scope, status or digest")

        request = ComparisonRequest.model_validate(comparison["selection"])
        scored = ComparisonEvidence.model_validate(comparison["evidence"])
        if (
            request.task in ("detector", "mask")
            and not scored.inference_job_ids
            and job["id"] not in verified_paired_comparison_ids
        ):
            raise ValueError(
                "The archived comparison lacks uniquely verified evaluation outputs. "
                "Restore the original evaluation jobs and media, or create a new comparison."
            )
        if len(comparison["models"]) != 2:
            raise ValueError("Paired comparison does not bind two reviewed model identities")
        models = [RuntimeReceipt.model_validate(row["receipt"]) for row in comparison["models"]]
        if any(
            str(model.source_model_id) != row["model_id"]
            for model, row in zip(models, comparison["models"], strict=True)
        ):
            raise ValueError("Comparison model report does not match its reviewed runtime")
        references = ProofEvidence(
            study=_portable_id(
                str(selection.study_design_id),
                str(study.revision_id),
                study_row["content_sha256"],
                origin_ids,
            ),
            review=_portable_id(
                str(selection.reviewer_report_id),
                review.id,
                review.content_sha256,
                origin_ids,
            ),
            comparison=_portable_id(
                str(selection.comparison_id),
                comparison["comparison_id"],
                result["content_sha256"],
                origin_ids,
            ),
        )
        study_growth = (study_row["snapshot_json"].get("binding") or {}).get("paired_report") or {}
        comparison_exclusions = [
            {"group_id": group.group_id, **observation.model_dump(mode="json")}
            for group in scored.groups
            for observation in group.observations
            if observation.exclusion is not None
        ]
        section_values: dict[EvidenceSection, Any] = {
            "study": {
                "snapshot": study_row["snapshot_json"],
                "content_sha256": references.study.content_sha256,
            },
            "review": {**review_body, "content_sha256": review.content_sha256},
            "comparison": {
                "snapshot": comparison,
                "content_sha256": references.comparison.content_sha256,
            },
            "models": comparison["models"],
            "methods": {
                "study_declaration": study.declaration.model_dump(mode="json"),
                "review_criterion": review.plan.criterion,
                "agreement_method": review.agreement.method,
                "comparison_task": request.task,
                "comparison_method": scored.method,
                "aggregation_method": comparison["summary"]["method"],
                "evaluation_status": scored.evaluation_status,
            },
            "environment": {
                "models": [
                    {
                        "model_id": str(model.source_model_id),
                        "checkpoint_sha256": model.checkpoint_sha256,
                        "framework": model.framework,
                        "provider": model.provider_id,
                        "provider_version": model.provider_version,
                        "registration_provider_version": model.registered_provider_version,
                        "runtime": model.runtime_id,
                        "runtime_version": model.runtime_version,
                        "settings": model.settings.model_dump(mode="json"),
                    }
                    for model in models
                ],
            },
            "exclusions": {
                "study_source_exclusions": study_growth.get("source_exclusions", []),
                "study_group_exclusions": study_growth.get("group_exclusions", []),
                "comparison_exclusions": comparison_exclusions,
                "comparison_missing_pairs": [
                    {
                        "name": metric["name"],
                        "unit": metric["unit"],
                        "count": metric["missing_pairs"],
                    }
                    for metric in comparison["summary"]["metrics"]
                    if metric["missing_pairs"]
                ],
                "comparison_limitations": scored.limitations,
            },
        }
        body = ReproducibilityProofBody(
            evidence=references,
            section_sha256={
                key: canonical_json_sha256(section_values[key]) for key in EVIDENCE_SECTIONS
            },
        ).model_dump(mode="json")
        return ReproducibilityEvidence(
            proof=ReproducibilityProof.model_validate(
                {**body, "proof_sha256": canonical_json_sha256(body)}
            ),
            sections=section_values,
        )
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ValidationError(f"Invalid reproducibility evidence: {exc}") from exc


def verify_proof(
    proof: ReproducibilityProof,
    sections: dict[str, list[dict[str, Any]]],
    manifest: Mapping[str, Any],
    *,
    verified_paired_comparison_ids: frozenset[str] = frozenset(),
) -> ReproducibilityEvidence:
    local_ids = (manifest.get("origin") or {}).get("id_map", {})
    selection = ReproducibilitySelection.model_validate(
        {
            "study_design_id": local_ids.get(str(proof.evidence.study.id), proof.evidence.study.id),
            "reviewer_report_id": local_ids.get(
                str(proof.evidence.review.id), proof.evidence.review.id
            ),
            "comparison_id": local_ids.get(
                str(proof.evidence.comparison.id), proof.evidence.comparison.id
            ),
        }
    )
    evidence = derive_evidence(
        sections,
        selection=selection,
        project_id=manifest["project"]["id"],
        origin_ids=local_ids,
        verified_paired_comparison_ids=verified_paired_comparison_ids,
    )
    if evidence.proof != proof:
        raise ValidationError("Reproducibility proof differs from the underlying frozen evidence")
    return evidence


def validate_native_proofs(
    sections: dict[str, list[dict[str, Any]]],
    manifest: Mapping[str, Any],
    *,
    verified_paired_comparison_ids: frozenset[str] = frozenset(),
) -> None:
    leaves = manifest.get(HISTORICAL_PROOFS, [])
    if not isinstance(leaves, list):
        raise ValidationError("Reproducibility proof inventory is invalid")
    proofs = {}
    try:
        for raw in leaves:
            proof = ReproducibilityProof.model_validate(raw)
            if proof.proof_sha256 in proofs:
                raise ValueError("Duplicate archived reproducibility proof")
            verify_proof(
                proof,
                sections,
                manifest,
                verified_paired_comparison_ids=verified_paired_comparison_ids,
            )
            proofs[proof.proof_sha256] = proof

        artifacts = [
            row
            for row in sections.get("workflow_artifacts", [])
            if row["data_type"] == ARTIFACT_TYPE
        ]
        if artifacts:
            nodes = {row["id"]: row for row in sections.get("workflow_node_runs", [])}
            for row in artifacts:
                node = nodes[row["producer_node_run_id"]]
                proof = proofs[node["parameters_json"]["proof_sha256"]]
                body = proof.model_dump(mode="json")
                if (
                    node["node_type"] != NODE_TYPE
                    or row["producer_port_id"] != "proof"
                    or row["payload_json"] != body
                    or row["payload_sha256"] != canonical_json_sha256(body)
                ):
                    raise ValueError("Saved workflow proof differs from its archive evidence")
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise ValidationError("Archived reproducibility proof cannot be verified") from exc
