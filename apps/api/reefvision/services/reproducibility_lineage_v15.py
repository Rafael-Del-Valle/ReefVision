"""Resolve immutable research proof by content identity in a local project."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.db.models.project_exchange_package import ProjectExchangePackage
from reefvision.domain.errors import ConflictError
from reefvision.domain.reproducibility_v15 import HISTORICAL_PROOFS
from reefvision.schemas.reproducibility_v15 import ReproducibilityManifest, ReproducibilityProof
from reefvision.storage.datasets import canonical_json_sha256

PACKAGE_OPTION = "reproducibility"


def project_proofs(session: Session, project_id: str) -> list[ReproducibilityProof]:
    indexed = {}
    for package in session.scalars(
        select(ProjectExchangePackage).where(
            ProjectExchangePackage.project_id == project_id,
            ProjectExchangePackage.status == "complete",
        )
    ):
        candidates = list(package.manifest_json.get(HISTORICAL_PROOFS, []))
        research = package.options_json.get(PACKAGE_OPTION, {})
        if research.get("manifest") is not None:
            manifest = ReproducibilityManifest.model_validate(research["manifest"])
            if (
                canonical_json_sha256(manifest.model_dump(mode="json"))
                != research["manifest_sha256"]
            ):
                raise ConflictError("Stored reproducibility manifest checksum differs")
            candidates.append(manifest.proof.model_dump(mode="json"))
        for row in candidates:
            proof = ReproducibilityProof.model_validate(row)
            if (
                canonical_json_sha256(proof.model_dump(mode="json", exclude={"proof_sha256"}))
                != proof.proof_sha256
            ):
                raise ConflictError("Stored reproducibility proof checksum differs")
            indexed[proof.proof_sha256] = proof
    return [indexed[digest] for digest in sorted(indexed)]
