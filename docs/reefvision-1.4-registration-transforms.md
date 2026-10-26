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
