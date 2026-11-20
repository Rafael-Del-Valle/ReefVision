"""Portable scientific proof and transport manifest for a research package."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from reefvision.schemas.model_runtime import Digest
from reefvision.schemas.project_exchange import ProjectExchangeImportResponse

EvidenceSection = Literal[
    "study", "review", "comparison", "models", "methods", "environment", "exclusions"
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReproducibilitySelection(StrictModel):
    study_design_id: UUID
    reviewer_report_id: UUID
    comparison_id: UUID


class ReproducibilityCreate(ReproducibilitySelection):
    include_media: bool = True
    include_model_weights: bool = False


class EvidenceReference(StrictModel):
    id: UUID
    content_sha256: Digest


class ProofEvidence(StrictModel):
    study: EvidenceReference
    review: EvidenceReference
    comparison: EvidenceReference


class ReproducibilityPin(StrictModel):
    proof_sha256: Digest


class ReproducibilityProofBody(StrictModel):
    schema_version: Literal["reefvision-research-proof-1"] = "reefvision-research-proof-1"
    evidence: ProofEvidence
    section_sha256: dict[EvidenceSection, Digest]


class ReproducibilityProof(ReproducibilityProofBody, ReproducibilityPin):
    pass


class ManifestEntry(StrictModel):
    path: str
    size_bytes: int = Field(ge=0)
    sha256: Digest


class SourceOmission(StrictModel):
    kind: Literal["image", "video", "model", "spatial_source", "field_capture"]
    record_id: str
    name: str
    sha256: Digest
    requires_relink_for: list[str]


class ReproducibilityManifest(StrictModel):
    format_name: Literal["reefvision-reproducibility"] = "reefvision-reproducibility"
    format_version: Literal["1.5"] = "1.5"
    proof: ReproducibilityProof
    exchange_manifest_sha256: Digest
    entries: list[ManifestEntry]
    omitted_sources: list[SourceOmission]
    included_media_count: int = Field(ge=0)


class ReproducibilityPackage(StrictModel):
    id: UUID
    project_id: UUID
    direction: Literal["export", "import"]
    status: Literal["queued", "running", "complete", "failed"]
    job_id: UUID | None
    manifest: ReproducibilityManifest | None = None
    manifest_sha256: Digest | None = None
    proof_sha256: Digest | None = None
    error_message: str | None = None


class ReproducibilityQueued(StrictModel):
    package: ReproducibilityPackage
    job_id: UUID


class ReproducibilityInspection(StrictModel):
    compatible: bool
    project_name: str | None = None
    manifest: ReproducibilityManifest | None = None
    manifest_sha256: Digest | None = None
    errors: list[str] = Field(default_factory=list)


class ReproducibilityImport(ProjectExchangeImportResponse):
    reproducibility_package_id: UUID
    proof_sha256: Digest
    omitted_sources: list[SourceOmission]
