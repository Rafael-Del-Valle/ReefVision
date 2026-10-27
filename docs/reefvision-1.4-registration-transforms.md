# ReefVision 1.4 — provisional pairwise 3D registration transforms

The standalone mesh-longitudinal comparison endpoint and the executable,
persisted `mesh_longitudinal_comparison` Workflow Builder node accept optional
`registration_evidence`. The existing source/target coordinate-frame labels,
method, RMS residual (meters), correspondence count, and evidence note remain
required when evidence is supplied.

The optional `source_to_target_transform_m` field stores a **caller-supplied**
4 × 4 rigid transform mapping coordinates from the before observation's
source frame to the after observation's target frame. Its upper-left 3 × 3
block is a right-handed orthonormal rotation; its rightmost three entries
are translations in meters. The last row is `[0, 0, 0, 1]`. Input must be
finite, 4 × 4, approximately rigid (1e-5 tolerance), and bounded to at most
1,000,000 meters translation per axis. Reflections, scale, shear, perspective
transforms, and malformed matrices are rejected. The registration RMS residual
and each transform entry must be JSON numbers (integers or decimals); strings
such as `"0.02"` and booleans such as `true` are rejected rather than silently
converted into scientific measurements. Existing JSON integer matrices remain
compatible. The comparison service also revalidates existing Pydantic evidence
objects when passed directly from Python. Mutating an already-constructed
model (including nested matrix rows) cannot bypass numeric, correspondence,
or rigid-transform checks; invalid mutations are rejected before results or
provenance are emitted. Saved Workflow Builder graphs use the same comparison
engine, while JSON inputs are validated at the API boundary.

Example (identity rotation with a provisional 0.1 m x translation):

```json
{
  "source_frame_id": "survey-before",
  "target_frame_id": "survey-after",
  "method": "landmark",
  "rms_residual_m": 0.02,
  "correspondence_count": 6,
  "evidence_note": "Six manually selected landmarks; review pending",
  "source_to_target_transform_m": [
    [1, 0, 0, 0.1],
    [0, 1, 0, 0],
    [0, 0, 1, 0],
    [0, 0, 0, 1]
  ]
}
```

The transform is **preserved in provenance** and is not applied to source
mesh vertices or calibrated surface measurements. It is applied only to the
caller-supplied surface centroid to report a provisional target-frame offset
and separation, when both centroids are available. These diagnostics cannot
certify coral movement, spatial registration, identity, branch length, growth,
or measurement accuracy. The result retains
`coordinate_registration_verified: false`, and a supplied transform adds
`registration_transform_requires_independent_review` to scientific QC.
The comparison additionally exposes two **unverified transform diagnostics**:
`registration_translation_magnitude_m` is the Euclidean norm of the three
translation entries, and `registration_rotation_angle_degrees` is the
principal rigid rotation angle in [0, 180] degrees, computed with a stable
`atan2` formulation. These are summaries of the **supplied matrix**, not
observed coral movement, growth, biological rotation, or registration quality.
A large translation can be expected when survey-frame origins differ.
Both fields are `null` when the matrix is absent; a missing matrix is not
misrepresented as an identity transform. The fields are identical in the
standalone API and persisted Workflow Builder output, which remains provisional.

An independently recorded `disputes_alignment` decision **withholds**
registered centroid offsets, separation, caller-bound intervals, and the
centroid-to-RMS ratio, even if a syntactically valid rigid matrix is present.
The submitted transform, review attribution, and transform-level rotation and
translation diagnostics remain available for audit, with explicit
`registered_surface_centroid_comparison_withheld_disputed_alignment` QC.
The same withholding now applies to an independent `inconclusive`
registration decision: uncertain alignment must not yield apparent centroid
movement or caller-bound intervals. Its distinct QC code is
`registered_surface_centroid_comparison_withheld_inconclusive_alignment`.
Original per-observation surface measurements, registration evidence, and
transform-level diagnostics remain available for review. A missing review
continues to be flagged as provisional rather than treated as a rejection.

This safeguard applies identically to the standalone endpoint and persisted,
executable typed Workflow Builder graphs. A supporting review still does not
verify registration or biological movement. Regression coverage saves and
executes disputed and inconclusive review graphs and checks exact standalone
artifact parity.

Registration evidence without a transform remains valid for backward
compatibility and adds `registration_transform_unavailable`. Existing
`registration_transform_and_accuracy_not_verified` and residual warnings
continue to apply. Missing evidence stays explicitly unavailable.

This first slice establishes a typed, audited data contract. Subsequent
work must implement reviewed registration workflows, transform application,
control-point residual checks, uncertainty propagation, and scientific
acceptance before any longitudinal biological inference. All data and
model checkpoints remain local; no pretrained weights or cloud services
are involved.

Regression coverage exercises malformed transforms, proper rotations,
standalone API output, and exact artifact parity after saving and executing
a typed Workflow Builder graph.

## Provisional reidentification evidence binding

Optional `reidentification_evidence.specimen_id` can bind the before/after
observation IDs and observer notes to the same provisional specimen label used
by the comparison. A supplied label must match both observations; evidence
from another specimen is rejected. Legacy evidence without a specimen label
remains readable but adds `reidentification_specimen_binding_unavailable` to
QC. The field is optional to avoid invalidating previously saved graphs.

The standalone endpoint and saved, executable Workflow Builder node share the
same validation and provenance. Binding a label prevents accidental reuse of
notes across specimen labels; it does **not** verify reidentification. The
`specimen_identity_verified` flag remains `false` and an independent human
review is still required. Tests cover bound and legacy evidence, cross-specimen
rejection, mutable-model revalidation, and saved-workflow artifact parity.

## Reidentification timepoint binding

The optional paired `reidentification_evidence.before_observed_at_utc` and
`after_observed_at_utc` fields bind provisional matching notes to the
**observation instants**, in addition to specimen/observation IDs and geometry
fingerprints. Both values must be timezone-aware timestamps. The comparison
normalizes instants for equality, so equivalent UTC and offset timestamps
match; a reused note whose source or target survey time changed is rejected.
Partial timestamp bindings and naive datetimes are rejected. Existing saved
records without timestamp binding remain readable, but the output adds
`reidentification_timepoint_binding_unavailable` for review.

Timestamp, geometry, and specimen binding only guard evidence consistency.
They do not verify field timestamps, identity, reconstruction registration,
biological change, or independent reviewer approval. The shared standalone
comparison and persisted typed Workflow Builder node enforce identical rules;
regression tests cover matching offsets, mismatched times, partial evidence,
legacy records, and saved-workflow artifact parity.

## Caller-supplied conservative centroid-separation error bounds

Optional `registration_evidence` fields
`source_centroid_position_error_bound_m`,
`target_centroid_position_error_bound_m`, and
`registration_alignment_error_bound_m` describe **absolute Euclidean error
radii in meters**, supplied by the researcher for the source centroid, target
centroid, and source-to-target alignment at the source centroid. All three
must be present together with a rigid transform, or all omitted. Values must
be finite, nonnegative numeric floats no greater than 1,000,000 m. The
landmark-fit RMS residual is **not** treated as an error bound.

When both surface centroids and all three caller bounds are available,
ReefVision uses the triangle inequality to emit
`registered_surface_centroid_separation_caller_bound_interval_m`:
`[max(0, d - (u_source + u_target + u_alignment)), d + u_source +
u_target + u_alignment]`, where `d` is the registered centroid separation.
The source-centroid bound is preserved by the rigid rotation. Missing bounds
produce `null` rather than an invented zero-error interval. Invalid or
incomplete evidence is rejected, including a model modified after validation.

This is a **conditional bound given the truth of the supplied error radii**,
not a statistical confidence interval, verified registration, biological
movement test, or total reconstruction uncertainty estimate. The result
retains unverified status and explicit scientific QC; calibration,
occlusion, reconstruction, and identity still require independent review.
Standalone analyses and persisted executable Workflow Builder graphs share
the same calculation and provenance, with a saved-workflow parity regression.

## Target-frame signed centroid-offset bounds

When the same three caller-supplied Euclidean error radii and rigid transform
are available, the longitudinal comparison additionally emits
`registered_surface_centroid_offset_target_frame_caller_bound_intervals_m`.
This is a three-element list, ordered **x, y, z** in the target frame, with
one `[lower_m, upper_m]` interval per signed offset component. For each
component `offset_i`, the conservative interval is
`[offset_i - u_total, offset_i + u_total]`, where
`u_total = u_source + u_target + u_alignment`. A Euclidean error radius bounds
each Cartesian component, so this calculation does not assume independent
coordinate errors, Gaussian residuals, or an estimated covariance matrix.

The component intervals are `null` if either centroid, the transform, or
complete caller bounds are unavailable, or if the separation calculation is
numerically invalid. A zero signed offset may have an interval extending in
both directions; unlike scalar separation, signed component bounds must **not**
be clipped at zero. These bounds are conditional on the researcher-provided
radii and are **not** confidence intervals, statistical movement tests,
independent registration validation, or evidence of coral growth. The existing
provisional measurement status, QC warnings, and human-verification flags are
unchanged. Standalone and persisted typed Workflow Builder executions share
the same implementation and are checked for artifact parity.

## Optional registration-to-source geometry binding

`registration_evidence.source_geometry_sha256` and
`registration_evidence.target_geometry_sha256` may now bind provisional
registration diagnostics and transforms to the **exact source and target
reconstruction fingerprints** recorded in each mesh preview. Both lowercase,
64-character hexadecimal SHA-256 strings must be supplied together. If either
differs from the corresponding observation's recorded geometry fingerprint,
the comparison is rejected rather than silently reusing a stale registration
for a different mesh with the same coordinate-frame labels.

Existing saved workflows and registration records without either fingerprint
remain executable, but the comparison adds
`registration_geometry_binding_unavailable` to scientific QC. Partially bound,
malformed, or post-validation-mutated evidence is rejected. The standalone
comparison endpoint and saved executable typed Workflow Builder node use the
same validation and retain the supplied fingerprints in provenance; a
saved-workflow regression checks exact result parity.

**Limits:** These are caller-supplied provenance fingerprints, not verified
asset hashes, landmark correspondences, calibration, or proof of successful
registration. A matching pair does not establish a correct rigid transform,
specimen identity, or biological movement. Independent human review and
scientific validation remain required; `coordinate_registration_verified`
stays `false`.

