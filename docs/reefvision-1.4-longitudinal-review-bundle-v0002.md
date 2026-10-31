# Provisional longitudinal review bundles v0002–v0003

The versioned review fingerprint now binds project, specimen, observation timestamps, geometry and source bytes, coordinate frames, calibration inputs, calibration review evidence, and independent registration/reidentification notes.

A v0001 digest is not equivalent to a v0002 or v0003 digest. Current comparisons use `mesh-review-bundle-0003`, which additionally binds source import format, original byte count and integrity-check status. Preserve schema version with the hash. Missing legacy provenance remains null. These caller-supplied records and deterministic hashes do not authenticate reviewers, certify calibration or identity, or substitute for immutable review persistence.

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


## Source-integrity validation at comparison time

Longitudinal comparison now rejects malformed imported-source integrity metadata
before constructing a review fingerprint. A supplied source SHA-256 must be
64 lowercase hexadecimal characters; a supplied byte count must be a
nonnegative integer (not a boolean); and a supplied integrity-check flag must
be boolean. A `true` check flag without any source digest is contradictory
and is rejected. Older previews that omit these fields remain readable with
null audit evidence; absence is never promoted to a successful source check.

These checks protect the consistency of caller-supplied provenance. They do
not verify original file bytes, establish an authenticated reviewer, or
certify coral calibration or identity. Standalone and saved typed Workflow
Builder comparisons share the same service-level validation.


## Duplicate imported-original QC (longitudinal comparisons)

When both observation previews carry the same well-formed imported-source
SHA-256, the comparison emits
`identical_imported_source_payload_reused_across_observations`. Different
observation IDs or dates do not make the same original OBJ/PLY/GLB bytes an
independent biological survey. If their geometry fingerprints nevertheless
differ, it also emits
`identical_imported_source_payload_geometry_inconsistent` to flag a possible
reconstruction or metadata inconsistency for investigation.

These are **scientific QC warnings**, not authentication or automatic evidence
of misconduct. The source hashes are derived from the supplied originals but
do not establish their acquisition date or provenance. Different original
bytes may still produce identical triangles; the existing
`identical_geometry_fingerprint` warning remains independent. Neither case
establishes coral growth, verified identity, or calibrated measurement.
Standalone longitudinal API calls and saved executable typed Workflow Builder
graphs share the same warnings and provisional review evidence.

### Withholding nonindependent longitudinal change estimates

When two timepoints reuse the same well-formed imported-source SHA-256, the
comparison now emits
`longitudinal_change_withheld_reused_imported_source_payload` and sets
`provenance.longitudinal_change_withheld_due_to_reused_source_payload` to
`true`. It withholds cross-timepoint change, percentage change, rates,
registered centroid movement and ranked patch-change metrics as `null`.
This applies even if the same original was recalibrated to yield different
nominal surface areas or an independent reviewer supplied a match note.
The individual measured areas, topology and reconstruction QC remain
available for auditing the recalibration. An identical original is not a
second biological observation.

Different imported-source SHA-256 values do **not** prove independent
acquisition: source comments can change while geometry stays identical.
Missing legacy source hashes likewise do not prove independence. This
guard does not certify the acquisition history, calibration, identity or
source authenticity. The same withholding is exercised in standalone
analysis and saved executable typed Workflow Builder artifact tests.

## Conflicting imported-original metadata

If two observation previews report the same well-formed imported-source
SHA-256 but disagree on **both known** original byte counts or source formats,
the comparison additionally emits
`identical_imported_source_payload_metadata_inconsistent`. Identical source
bytes cannot have different lengths or different native import formats. This
is an audit warning about contradictory caller-supplied provenance, not a
biological change or proof of tampering. A missing historical byte count stays
unknown rather than triggering a fabricated conflict; a digest without its
import format is rejected earlier as orphaned metadata. An integrity-check
flag can legitimately differ between previews because an expected hash may
have been supplied in one import but not the other.

The existing duplicate-source warning remains independent, and the comparison
still labels calibration, specimen identity, and the longitudinal interpretation
as provisional. Regression coverage exercises both inconsistent metadata and
the clean duplicate-original path through a persisted typed Workflow Builder
graph; no authenticated review ledger or durable calibration record is created
by this check.

## Per-timepoint imported-source digest-check QC

Longitudinal comparisons now distinguish a recorded SHA-256 fingerprint from
checking the imported original against an independently supplied expected
SHA-256. An imported OBJ, ASCII PLY, or GLB observation with no successful
expected-digest check receives a timepoint-specific warning:
`before_imported_source_expected_digest_not_checked` or
`after_imported_source_expected_digest_not_checked`. A historical missing
check flag is treated as unchecked, not as a successful verification. Inline
indexed triangles have no imported original and do not receive this warning.

A successful byte-for-byte expected-digest comparison does **not** authenticate
acquisition, calibration, specimen identity, or reviewer credentials. Reused
source bytes still trigger longitudinal withholding even when either or both
imports have matching expected digests. Regression tests compare standalone
analysis with persisted executable typed Workflow Builder graphs for OBJ,
PLY and GLB, including mixed checked/unchecked timepoints.

## Provisional identity-label validation on replay

The standalone longitudinal comparison service now independently enforces
the mesh request contract for `specimen_id` and both `observation_id` values:
each must begin with an ASCII letter or digit and contain only ASCII letters,
digits, underscores, periods, colons or hyphens. Equal whitespace-only labels,
embedded spaces, tabs and control characters are rejected, including when a
caller mutates a previously constructed preview or replays an older artifact
without passing through request validation. The two observations must still
have distinct observation IDs and the same provisional specimen ID. A
`project_id` containing only whitespace is also rejected.

This is **identifier hygiene**, not organism reidentification or authenticated
review. It prevents ambiguous labels from silently passing the direct service
path while the standalone HTTP API and executable saved Workflow Builder use
the stricter request schema. Existing legitimate identifiers remain unchanged;
scientific calibration, acquisition history and biological identity are still
unverified. Regression coverage exercises direct replay rejection and retains
standalone/saved-workflow parity for valid labels.

## Project-bound reidentification evidence hygiene

A supplied reidentification `project_id` now follows the same 1–128 character
ASCII identifier contract as the compared mesh observations: it must start with
an ASCII letter or digit and contain only letters, digits, underscores, periods,
colons, or hyphens. Blank, whitespace-containing, control-character, oversized,
and path-like labels fail at schema validation. The shared longitudinal engine
revalidates mutated evidence models on replay, so callers cannot bypass this
check by editing an already constructed model. Legacy evidence omitting the
optional project binding remains readable and receives
`reidentification_project_binding_unavailable` scientific QC; it is not
promoted to verified specimen identity. The standalone comparison and saved,
typed Workflow Builder execution both use this shared validation path.

This guards identifier ambiguity, not authorization, authenticated reviewer
identity, or durable versioned review persistence. No automatic verification
or biological growth certification is implied.


## Imported-source bindings for provisional spatial registration

Pairwise `MeshRegistrationEvidence` now accepts optional
`source_payload_sha256` / `target_payload_sha256` and
`source_spatial_source_asset_id` / `target_spatial_source_asset_id`.
Each binding must be supplied as a complete pair. Digests must be 64
lowercase hexadecimal characters; project-owned asset IDs must match the
lowercase UUID format used by the imported-original store.

The longitudinal comparison service independently revalidates this evidence
on execution, including already-constructed and subsequently modified model
objects. A supplied pair must match both observation previews. Re-exporting
the same triangles with changed OBJ/PLY/GLB source bytes invalidates the
source-payload binding; reimporting byte-identical files under different
project asset IDs invalidates the asset binding. Geometry hashes, source-byte
digests and asset IDs are distinct consistency checks.

Historical registration records without these bindings remain readable, but
imported originals with unbound payload hashes receive
`registration_source_payload_binding_unavailable`, and project-owned
originals without bound asset IDs receive
`registration_spatial_source_asset_binding_unavailable`. The new bindings
are included in the caller-supplied review evidence snapshot and its
recomputable digest; the existing bundle schema version is unchanged because
the canonical record already includes all supplied registration fields.

Standalone comparisons and saved executable typed Workflow Builder graphs
share the same validation. Regression coverage includes changed source bytes
with unchanged geometry, reused source bytes under another asset ID,
incomplete/mutated bindings, legacy warnings, and successful/failed persisted
graph executions. These are **provisional audit controls**, not authenticated
review, certified registration, verified calibration, verified coral identity,
or proof that observations came from independent biological surveys.
