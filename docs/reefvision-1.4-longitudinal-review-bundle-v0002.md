# Provisional longitudinal review bundle v0002

The versioned review fingerprint now binds project, specimen, observation timestamps, geometry and source bytes, coordinate frames, calibration inputs, calibration review evidence, and independent registration/reidentification notes.

A v0001 digest is not equivalent to a v0002 digest. Preserve schema version with the hash. Missing legacy provenance remains null. These caller-supplied records and deterministic hashes do not authenticate reviewers, certify calibration or identity, or substitute for immutable review persistence.

Standalone longitudinal comparisons and persisted executable Workflow Builder graphs share this provenance. Tests cover canonicalization, calibration revisions, and saved graph artifacts.

## Recomputable evidence payload

Longitudinal result provenance now includes `review_evidence_bundle` alongside
`review_evidence_bundle_schema_version` and `review_evidence_bundle_sha256` when
registration or reidentification evidence is supplied. The bundle is the exact
canonical JSON object used to compute the digest, so an independent reader can
recompute SHA-256 over UTF-8 JSON serialized with sorted keys, compact
separators, `ensure_ascii=False`, and `allow_nan=False`. With no supplied review
evidence, all three fields remain null. Saved typed Workflow Builder comparison
artifacts retain the same payload and digest as standalone comparisons.

The bundle is an auditable *snapshot of caller-supplied evidence*, not an
append-only database, authenticated reviewer signature, or authorization to
promote provisional measurements to verified biological growth. Preserve the
bundle and its schema version together; changing its contents without updating
the digest makes the artifact internally inconsistent.
