# ReefVision 1.4 — independent 3D calibration review and imported source identity

A mesh_surface_preview request may include an independently attributed calibration_review record. The reviewer must differ from the calibration operator, including case-only variations of the identifier. Review decisions are supports_scale, disputes_scale, or inconclusive. All remain **caller-supplied, unverified** audit evidence: even supports_scale never changes calibration_verified=false or measurement_status=caller_supplied_unverified.

The review binds to a geometry SHA-256, specimen/observation IDs, observation timestamp, calibration method, evidence, meters-per-unit, and relative scale uncertainty. It must not predate the observation. For imported OBJ, ASCII PLY, or GLB, the reviewer can additionally set reviewed_source_payload_sha256 to provenance.source_payload_sha256 from the inspected preview. This binds to the exact source bytes, including edits that preserve parsed geometry. GLB hashes decoded binary bytes, not base64 transport text. Mismatches fail closed.

Legacy imported-file reviews without reviewed_source_payload_sha256 remain readable but carry independent_calibration_review_source_bytes_unbound QC warning. Indexed triangles have no imported source bytes and cannot claim this binding. This hash is not a persistent asset, a signature, proof of reviewer identity, or verified physical calibration. The separate expected_source_payload_sha256 request field guards replay independently.

The standalone project-scoped spatial/mesh-preview endpoint and the saved executable typed mesh_surface_preview Workflow Builder node use the same analysis function. Tests cover source-byte edits preserving geometry, legacy warnings, invalid hashes, case-only reviewer/operator collisions, and saved-workflow parity. Persistent project assets, authenticated reviewers, validated branch lengths, and installed Windows acceptance remain outside this slice.

## ASCII PLY point-cloud review

The same independently attributed `calibration_review` evidence is now accepted for bounded `point_cloud_preview` analyses. It binds to the point-cloud geometry SHA-256, specimen and observation metadata, observation time, scale, method, evidence, and scale uncertainty. For ASCII PLY imports, `reviewed_source_payload_sha256` binds the review to the submitted UTF-8 PLY bytes; changing a comment or RGB values without changing XYZ coordinates invalidates the review. Legacy imported-file reviews without a source-byte digest remain readable with the explicit `independent_calibration_review_source_bytes_unbound` QC warning. Raw XYZ points have no imported-file digest and cannot claim one.

The project-scoped standalone point-cloud endpoint and persisted, executable, typed `point_cloud_preview` Workflow Builder node share this validation. Regression coverage includes changed bytes with identical XYZ, stale calibration/observation evidence, independent reviewer attribution, disputed reviews, legacy records, and saved-workflow parity and rejection. A supporting review is **not** certification: `calibration_verified=false`, `measurement_status=caller_supplied_unverified`, and source-frame/identity verification remain unchanged. The hash identifies submitted bytes, not a stored asset or authenticated reviewer.

## Coordinate-frame review binding (provisional)

A reviewer may supply `reviewed_coordinate_frame_id` to bind a mesh or point-cloud calibration review to the exact caller-provided `coordinate_frame_id` label. A mismatch is rejected before a standalone artifact or saved Workflow Builder measurement can succeed. If a source frame label exists but a legacy review omits this binding, the preview reports `independent_calibration_review_coordinate_frame_unbound` without discarding historical evidence. A review without any source frame label remains valid as legacy unregistered evidence.

The frame label is **not** proof of coordinate registration, physical origin, survey alignment, biological identity, or calibration accuracy. `coordinate_registration_verified` and `calibration_verified` remain false. Tests exercise changed frame labels, legacy warnings, standalone-versus-persisted workflow parity, and rejection of invalid saved workflows.

## Revalidation of mutable review evidence

Already-constructed Pydantic review instances can be modified after their initial schema validation. Both standalone 3D mesh and point-cloud preview engines now revalidate the complete independent calibration review record immediately before checking source bindings or recording provenance. This rejects later changes that make the reviewer identical to the operator (including case-only differences), replace a supported decision with an unknown status, blank the audit note, invalidate source hashes or coordinate-frame labels, or make the scale invalid. Existing valid and legacy records retain their previous semantics. The same engines execute persisted, typed Workflow Builder nodes, so saved-workflow artifacts retain standalone parity. Revalidation prevents invalid audit evidence from being accepted; it does **not** authenticate the reviewer, establish calibration accuracy, or turn provisional measurements into verified observations.

## Longitudinal surface-area interval integrity

The provisional `mesh_longitudinal_comparison` engine now checks each
available `surface_area_scale_interval_m2` against that observation's
`provenance.relative_scale_uncertainty`. The lower and upper endpoints must
match the source preview's nominal area multiplied by `(1 - u)^2` and
`(1 + u)^2`, respectively. A fabricated narrower or wider interval is
rejected rather than used to understate uncertainty in cross-timepoint
differences. A supplied interval is also rejected when the source explicitly
reports unknown scale uncertainty. Malformed uncertainty metadata is rejected.

Missing intervals remain unavailable, not zero-uncertainty evidence. Older
artifacts without the provenance uncertainty field remain readable; they
cannot be retrospectively audited against that field. These are **scale-only
bounds**, not statistical confidence intervals: they exclude reconstruction,
registration, segmentation, and specimen-identity uncertainty. Standalone
comparisons and persisted typed Workflow Builder comparisons use the same
validation engine and preserve provisional status.

## Longitudinal independent-review replay safeguards

The `mesh_longitudinal_comparison` standalone endpoint and persisted, executable typed Workflow Builder node reject registration and specimen-reidentification review timestamps preceding either bound observation. Saved-graph regression tests also reject case-only reviewer/operator aliases (including `OPERATOR-1` versus `operator-1` and `OBSERVER-1` versus `observer-1`) without emitting a comparison artifact. Accepted comparisons preserve the caller-supplied review record, its original timestamp, and provisional verification flags in the saved artifact. These tests cover consistency of saved execution, **not** authenticated reviewer identity, durable review-record versioning, registration accuracy, or verified biological reidentification.


## Imported 3D original identity binding

Project-owned OBJ, PLY, and GLB originals are stored under a path derived from
the immutable asset ID and recorded format. Source retrieval now rejects a
database record whose managed path no longer matches that identity, even when
an alternate file inside the same project contains byte-identical content and
would pass the stored SHA-256 digest. This prevents a metadata/path substitution
from silently changing the meaning of an imported asset reference.

Regression tests cover OBJ mesh and ASCII PLY point-cloud previews through
both standalone project endpoints and previously saved, executable typed
Workflow Builder graphs. A substituted path must fail before a scientific
measurement artifact is emitted. This is an integrity and reproducibility
guard, **not** proof of original acquisition, authenticated operator identity,
physical calibration, or verified coral specimen identity.

## Symlink-safe replay of imported originals

Before resolving a managed source path, the 1.4 asset reader checks each
lexical path component for filesystem symlinks. This closes a distinct
same-data-root substitution route: a symlink at the expected original path
could otherwise resolve to a different file containing byte-identical data,
passing the digest check while bypassing the intended asset-path identity.
The check applies to OBJ meshes, PLY meshes/point clouds, and GLB meshes,
including standalone previews and persisted executable Workflow Builder
graphs. Regression cases require a symlinked original to fail without
emitting a scientific measurement artifact.

This is a best-effort check of the filesystem state at read time, **not**
an atomic defense against an attacker who can concurrently mutate the data
directory between validation and opening a file. Project storage still
requires appropriate operating-system access controls. A matching SHA-256
digest and path are not evidence of verified calibration, acquisition
authenticity, or confirmed specimen identity.
