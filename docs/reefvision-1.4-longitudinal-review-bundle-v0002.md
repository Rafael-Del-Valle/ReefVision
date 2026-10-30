# Provisional longitudinal review bundle v0002

The versioned review fingerprint now binds project, specimen, observation timestamps, geometry and source bytes, coordinate frames, calibration inputs, calibration review evidence, and independent registration/reidentification notes.

A v0001 digest is not equivalent to a v0002 digest. Preserve schema version with the hash. Missing legacy provenance remains null. These caller-supplied records and deterministic hashes do not authenticate reviewers, certify calibration or identity, or substitute for immutable review persistence.

Standalone longitudinal comparisons and persisted executable Workflow Builder graphs share this provenance. Tests cover canonicalization, calibration revisions, and saved graph artifacts.
