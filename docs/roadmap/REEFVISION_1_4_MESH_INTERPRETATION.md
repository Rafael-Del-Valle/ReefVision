# ReefVision 1.4 — mesh measurement interpretation

A connected triangle patch is a geometric component, not an identified coral colony. A disconnected mesh may contain multiple fragments, reconstruction artifacts, or both. Do not interpret aggregate surface area as an individual organism's area without human verification of patch membership.

Unreferenced vertices must not change calibrated dimensions. Preserve the original geometry hash and report the excluded-vertex count. Calibration uncertainty reflects only scale uncertainty, not photogrammetric reconstruction, segmentation, occlusion, or tissue-boundary error.

Any longitudinal growth comparison must require reviewed organism identity, comparable calibration and acquisition methods, and explicit provenance for each timepoint. Current mesh previews remain provisional, including saved Workflow Builder artifacts.

Per-edge-connected-patch areas are reported in square meters, ordered by the first
face in each patch. Their scale uncertainties assume a common relative scale error;
these are not independent confidence intervals. Patch indices are not persistent
organism identities and must not be used to infer biological growth or survival.

Per-patch global-axis dimensions (meters) and their scale-only uncertainty are
calculated from vertices referenced by that patch's faces. These bounding-box
extents do not measure skeletal branch length or guarantee anatomical alignment;
comparison across timepoints requires a reviewed common coordinate frame.

Per-patch degenerate-triangle counts localize zero-area faces without silently
removing them from the input geometry or claiming a valid enclosed surface.
They must be reviewed alongside topology warnings before biological interpretation.

Open-boundary edge lengths are reported in meters both for the entire mesh and
for each edge-connected patch. Shared interior edges are excluded. These lengths
measure exposed mesh edges (which may reflect incomplete photogrammetry), **not**
coral branch lengths, colony perimeter, or verified tissue boundaries. Scale-only
uncertainty is a common multiplicative error; absent scale uncertainty stays
unknown rather than being treated as zero. Human review remains required.

New `boundary_edge_length_scale_interval_m` and
`edge_connected_patch_boundary_length_scale_intervals_m` fields provide exact
lower/upper bounds for a **shared multiplicative calibration-scale error**:
`[L(1-u), L(1+u)]` for relative scale uncertainty `u`. They are not
confidence intervals or estimates of mesh reconstruction uncertainty. Unknown
`u` yields null intervals, while explicitly zero uncertainty yields
`[L, L]`. The standalone endpoint and persisted `mesh_surface_preview`
Workflow Builder node share this calculation and preserve unverified
calibration provenance.

Exact per-patch geometry SHA-256 fingerprints are calculated from sorted triangle
coordinates, ignoring source vertex numbering, triangle order, and winding. They
support audit of unchanged geometry through standalone and saved Workflow Builder
analyses. Fingerprints are **not** persistent organism identities, registration,
or proof of biological reidentification; any coordinate change may change a hash.

Area-weighted surface centroids are calculated from triangle areas, not the
average of all mesh vertices. They are reported in calibrated meters relative
to the **unregistered source-coordinate origin** for each edge-connected patch
and for the aggregate surface. A patch with zero total triangle area has an
undefined centroid (null), accompanied by a QC warning. Reported centroid
uncertainty includes only multiplicative scale uncertainty relative to that
origin; unknown scale uncertainty remains null. It does **not** include
registration, reconstruction, coordinate-origin, navigation, or biological
localization error. Do not interpret a centroid displacement between surveys
as growth, movement, or reidentification without reviewed registration and
organism identity.

Global-axis bounding-box diagonals are calibrated lengths spanning each mesh
or edge-connected patch's axis-aligned bounding box. They are upper bounds on
pairwise distances between referenced vertices, not observed biological branch
lengths or Feret diameters. They depend on orientation, and comparisons across
time require reviewed registration, calibration, and organism identity.
Uncertainty is scale-only; missing uncertainty remains null, not zero.

## Point-cloud chord integrity in decimated previews

The standalone ASCII PLY/XYZ point-cloud endpoint and the executable, saved
`point_cloud_preview` Workflow Builder node use the same bounded measurement
service. Selected point-pair chords refer to **original point indices**, not
the 512-point visualization sample. New artifacts persist the two calibrated
endpoint coordinates and their chord distance even if display decimation omits
one or both endpoints. The read-only viewer now checks the internal agreement
of those stored coordinates and reported chord distances, and cross-checks
sampled endpoints where available. Malformed or contradictory metadata fails
closed. Older artifacts without embedded endpoints remain displayable, but a
chord with an unsampled endpoint cannot be cross-checked by the viewer.

This check detects inconsistent **saved artifact metadata**; it does not
independently validate the original scan, its point correspondence, coordinate
registration, or calibration. All chords remain provisional straight-line
distances, **not** anatomical coral branch lengths. The source-order geometry
fingerprint is an audit aid, not an organism identity or a review decision.

## Boundary-cycle topology QC

The mesh engine now distinguishes **closed boundary-edge cycles** from
**noncycle boundary components** in each edge-connected patch. Only edges
incident to exactly one triangle participate. A connected boundary graph
counts as one loop only when every referenced boundary vertex has degree two.
Branches, pinches, and open chains are counted separately rather than being
misrepresented as complete cycles.

The fields `boundary_loop_count`, `noncycle_boundary_component_count`,
`edge_connected_patch_boundary_loop_counts`, and
`edge_connected_patch_noncycle_boundary_component_counts` preserve these
diagnostics in standalone API responses and executed saved Workflow Builder
artifacts. A noncycle component adds the `noncycle_mesh_boundary_components`
QC warning. Existing surface-area, boundary-length, and enclosed-volume
calculations are unchanged; open surfaces already have their provisional
enclosed volume withheld.

These are **combinatorial properties of the indexed triangle mesh**, not
biological holes, coral branching structures, proof of watertight geometry,
or a measure of reconstruction completeness. Duplicate positions with
different vertex indices and nonmanifold edges can affect topology; review
them alongside existing QC warnings. The imported coordinate frame and
calibration remain unverified. Tests exercise a closed tetrahedron, an open
square, a nonmanifold pinched boundary, and disconnected triangle patches
through the measurement engine, standalone API, and persisted executable
Workflow Builder graphs.


## Provisional longitudinal mesh comparison (Track C)

The standalone project endpoint `POST /api/v1/projects/{project_id}/spatial/mesh-longitudinal-comparison`
accepts `before` and `after` mesh-preview requests. The typed executable
`mesh_longitudinal_comparison` Workflow Builder node accepts two persisted
`mesh_measurement_preview` artifacts, one on each named input port, and
persists a `mesh_longitudinal_comparison` artifact. Both paths delegate to
the same conservative comparison engine.

Both observations must have matching nonempty **provisional** specimen IDs,
different nonempty observation IDs, strictly increasing timezone-aware UTC
timestamps, and matching project scope. The output reports elapsed days,
surface-area difference (later minus earlier), and percent difference when
the earlier area is positive. When both observations include scale-only area
intervals, the difference interval uses the conservative endpoints
`[later_min - earlier_max, later_max - earlier_min]`. Percent-change bounds
use the corresponding extreme ratios when the earlier lower bound is positive.
Missing uncertainty stays missing, never zero.

**This is not verified coral growth or re-identification.** Matching
caller-supplied IDs are not human-reviewed identity evidence. The engine does
not infer coordinate registration, biological condition, reconstruction
completeness, correlated calibration errors, or uncertainty due to sampling.
The output retains both source geometry hashes and calibration evidence,
unverified flags, and explicit QC warnings. A researcher must independently
review identity, geometry quality, scale, and comparable survey methods before
interpreting area differences biologically. No model weights, assets, or
research data are transmitted to a cloud service.

### Calibration-only changes across timepoints

The provisional comparison now reports `before_meters_per_mesh_unit`,
`after_meters_per_mesh_unit`, and
`calibration_scale_ratio_after_to_before` from the original preview
provenance. If both observations have different calibration scales, the
comparison emits `calibration_scale_changed_between_observations`. If their
**source geometry SHA-256 fingerprints are identical** despite a scale
change, it additionally emits
`identical_geometry_rescaled_not_biological_growth`. A change in the
reported calibrated surface area can therefore arise entirely from
recalibration of an unchanged reconstruction, not biological growth.

Malformed present scales (including booleans, nonpositive values, and
nonfinite values) are rejected. Missing legacy scale metadata remains null,
with `calibration_scale_metadata_unavailable` rather than a fabricated
ratio. Fingerprint equality only detects byte-equivalent source geometry;
it does not establish coral identity or geometric registration. Scale-only
uncertainty bounds are not statistical confidence intervals, and a shared
calibration error may correlate measurements across surveys. Standalone and
persisted Workflow Builder comparisons use the same validation and warnings.

### Scale-normalized reconstruction area ratio (provisional)

The comparison additionally reports
`scale_normalized_surface_area_ratio_after_to_before`, calculated as
`(after_area / before_area) / (after_meters_per_unit / before_meters_per_unit)^2`.
The engine evaluates this in log space to avoid overflowing intermediate
squared-scale terms. An identical mesh recalibrated from 1 to 2 meters per
source unit has four times the reported physical area but a normalized ratio
of **1**, not evidence of growth. The same-scale example with twice the
reconstructed area has a normalized ratio of **2**.

This is a descriptive **reconstruction-geometry diagnostic**, not an
independently validated biological change. Ratios between different scans
are not scientifically comparable unless their source-unit conventions,
reconstruction methods, organism identities, and coordinate registration
are independently reviewed. The output therefore emits
`scale_normalized_area_ratio_requires_common_units_and_registration`
when available. Missing calibration or a zero baseline produces `null`
and `scale_normalized_area_ratio_unavailable`; unrepresentably extreme
positive ratios remain `null` with
`scale_normalized_area_ratio_out_of_numeric_range`, never an invented
zero. A genuinely zero later area can yield a descriptive ratio of zero.
No uncertainty beyond nominal scale is estimated for this diagnostic.
The standalone endpoint and persisted typed Workflow Builder node use
the same engine and have matching regression assertions.

### Scale-normalized bounding-box diagonal ratio (provisional)

The longitudinal comparison also reports
`scale_normalized_bounding_box_diagonal_ratio_after_to_before`:
`(later_diagonal / earlier_diagonal) / (later_scale / earlier_scale)`.
It uses log-space arithmetic for positive extents. For the same reconstruction
rescaled from 1 to 2 meters per source unit, the physical diagonal doubles
but the scale-normalized ratio is **1**. This is a geometric diagnostic,
not a coral branch length, growth rate, or organism reidentification result.

Missing scales or extents and a zero earlier diagonal yield `null` with
`scale_normalized_extent_ratio_unavailable`. A truly zero later diagonal
can yield zero; positive ratios that overflow or underflow the numeric
range yield `null` with `scale_normalized_extent_ratio_out_of_numeric_range`.
When available, the result carries
`scale_normalized_extent_ratio_requires_common_units_and_registration`.
No coordinate registration, common mesh-unit convention, biological identity,
reconstruction uncertainty, or calibration verification is inferred.
The metric is computed by the shared engine for the standalone endpoint
and saved typed Workflow Builder graphs. Regression tests cover rescaling,
changed geometry, absent evidence, zero baselines, numeric extremes, and
saved-workflow artifact parity.


### Source-frame provenance and registration QC (Track C)

A mesh-preview request may now include an optional `coordinate_frame_id` source
label (1–128 ASCII letters, digits, underscore, dot, colon or hyphen, starting
with an alphanumeric character). The standalone endpoint and persisted
`mesh_surface_preview` Workflow Builder node carry this label into the
observation provenance. A longitudinal comparison records both labels and
emits `coordinate_frame_metadata_unavailable` when either is absent,
`coordinate_frames_differ_registration_required` when they differ, or
`matching_coordinate_frame_id_not_registration_proof` when they match.

These are **caller-provided labels**, not coordinate transforms, registration
residuals, control-point evidence, or human approval. Matching names do not
prove spatial alignment; `coordinate_registration_verified` remains false.
Mismatches require registration review before comparing axis-aligned extents,
centroids or biological change. Malformed present labels are rejected by both
request validation and the shared longitudinal calculation engine. Existing
artifacts without labels remain readable and receive the missing-evidence QC
warning. API and saved-workflow tests assert identical comparison artifacts.

### Longitudinal reconstruction topology QC (Track C)

The shared comparison engine now retains five integer diagnostics from each
mesh preview: `face_count`, `edge_connected_patch_count`,
`boundary_edge_count`, `nonmanifold_edge_count`, and
`degenerate_face_count`. It reports
`before_reconstruction_topology_counts`,
`after_reconstruction_topology_counts`, and
`reconstruction_topology_changed_fields` in both standalone and persisted
Workflow Builder comparison artifacts.

A change in any *available* count emits
`reconstruction_topology_changed_requires_review`. Missing fields in older
saved artifacts remain null and emit
`reconstruction_topology_comparison_incomplete`; absent evidence is not
interpreted as a zero count. Malformed present counts (including booleans,
negative values, fractional numbers, and strings) are rejected rather than
silently coerced. Regression tests cover API topology drift, malformed and
legacy records, and saved-workflow output parity.

Topology changes can arise from meshing, occlusion, reconstruction parameters,
sampling, or segmentation. They **do not** establish colony fragmentation,
new branch growth, tissue loss, mortality, biological condition, or organism
re-identification. These diagnostics do not independently verify registration,
calibration, source files, or observation identity; all biological
interpretation requires human review.

### Cross-field topology integrity for persisted observations

The shared longitudinal engine rejects impossible combinations of **present**
reconstruction metadata: more edge-connected patches than faces, zero patches
with a positive face count, more degenerate faces than total faces, or more
boundary/nonmanifold edges than three times the face count. These are
combinatorial bounds for indexed triangle meshes, not biological thresholds.
Malformed observations fail rather than producing misleading longitudinal
changes; the same comparison engine is used by the standalone API and the
executable persisted Workflow Builder graph.

Older observations with missing face counts or other topology fields remain
readable. Missing metadata stays null and triggers
`reconstruction_topology_comparison_incomplete`; it is not silently replaced
with zero or marked scientifically verified. Regression cases cover impossible
counts in either observation and partial legacy artifacts. These checks do
not verify source geometry, coordinate registration, organism identity, or
biological growth.

### Extreme positive calibration-scale ratio QC

A calibration-scale ratio is meaningful only when both source scales are
strictly positive and their quotient is representable as a finite, positive
floating-point number. Very different positive scales can overflow to infinity
or underflow to zero. Neither result is a measured zero calibration ratio.
The shared longitudinal engine now withholds these unrepresentable quotients
as `null` and emits `calibration_scale_ratio_out_of_numeric_range`.
The original per-observation scales remain in the comparison artifact for
audit; normalized geometric ratios retain their separate log-space QC.

The standalone API and persisted typed Workflow Builder use the same engine.
Regression coverage exercises both overflow and positive underflow with
saved-workflow artifact parity. The new QC does not verify the calibration,
common source units, spatial registration, specimen identity, or biological
change; all observations remain provisional and subject to human review.

### Large finite longitudinal area changes (Track C)

The provisional longitudinal comparison computes relative surface-area change by
**dividing the finite area difference by the positive baseline before
multiplying by 100**. This avoids an intermediate floating-point overflow
when the percentage is representable even though `100 * area_difference`
is not. For example, a change from `1e307` to `2e307` square meters in a
synthetic legacy comparison is reported as `100%`, not withheld as null.
Regression tests cover positive and negative finite percentages. Such values
are numeric stress tests, not biologically plausible coral measurements or
validated field observations. The existing standalone API and executable,
persisted Workflow Builder share this comparison engine and retain their
artifact-parity regression. Scientific identity, calibration, registration,
and biological growth remain unverified.

### Registration residual relative to reconstructed extent (Track C)

When caller-supplied pairwise registration evidence is present and both mesh
previews report positive axis-aligned bounding-box diagonals, the longitudinal
comparison records `registration_residual_to_smaller_extent_ratio`: the
claimed RMS registration residual in meters divided by the **smaller** of the
two reconstructed diagonals in meters. This dimensionless value is a screening
diagnostic, not an estimate of registration uncertainty or accuracy. Values at
least 1 emit `registration_residual_at_least_smaller_mesh_extent` to prioritize
independent inspection. No biological or registration acceptance threshold is
implied by smaller values.

Missing or zero diagonals yield `null` and
`registration_residual_extent_ratio_unavailable`. A positive ratio outside
finite floating-point range yields `null` and
`registration_residual_extent_ratio_out_of_numeric_range`, never a false zero
or infinity. The original RMS, correspondence count, method, frame IDs and
evidence note remain in provenance. These measurements are **unverified**,
axis-aligned diagonals are orientation-dependent, and residuals can hide
registration bias or missing anatomy. The standalone endpoint and persisted
typed Workflow Builder use the same calculation, with saved-workflow parity
and direct numerical QC regression coverage.

### Registration-frame surface-centroid comparison (Track C)

When the caller supplies a validated rigid source-to-target transform and both
mesh previews have finite triangle-area-weighted surface centroids, the
longitudinal engine transforms the earlier centroid into the later observation's
coordinate frame. It reports
`registered_surface_centroid_offset_target_frame_m` (a signed XYZ offset in
target-frame meters) and `registered_surface_centroid_separation_m` (its
Euclidean magnitude). The underlying imported mesh geometry is **not** changed.

The results are explicitly provisional: surface-centroid shifts can result
from different mesh coverage, occlusion, reconstruction quality, or calibration,
even when the organism is stationary. They are **not** measured organism
movement, branch growth, or verified reidentification. The output retains
`coordinate_registration_verified: false` and
`specimen_identity_verified: false`; QC includes
`registered_centroid_offset_not_verified_biological_movement` and
`registered_centroid_position_uncertainty_not_estimated`. No displacement
confidence interval is invented from calibration-only scale bounds.

Missing centroids or a missing transform produce null results; malformed
nonfinite, Boolean, or non-XYZ centroids are rejected when used for transformed
comparison. Standalone API and saved typed Workflow Builder graphs use the
same calculation and are checked for complete artifact parity. Human review
of both specimen identity and spatial registration is required before
interpreting any difference biologically.

### Dated independent specimen reidentification review (Track C)

Optional `independent_reviewed_at_utc` records when a separately identified
reviewer assessed a provisional pairwise specimen match. The timestamp must
include a timezone and accompany a complete reviewer ID, decision, and note.
The shared longitudinal comparison rejects a review dated **before** the
later observation, including when equivalent instants are written with
different UTC offsets. Existing undated reviewer decisions remain readable
but emit `reidentification_independent_review_timestamp_unavailable`.
Review records are revalidated before execution, including after in-memory
mutation, to prevent stale or backdated audit evidence.

This is a chronology and attribution check, **not** cryptographic
authentication, proof that the reviewer examined the images, or verified
organism identity. A supporting review still leaves
`specimen_identity_verified: false`. Both standalone analysis and executable
persisted Workflow Builder graphs use the same comparison engine; regression
coverage checks dated review provenance, invalid chronology, legacy QC,
and saved-workflow artifact parity.

### Project-scoped provisional reidentification evidence (Track C)

Optional `project_id` in `MeshReidentificationEvidence` binds a provisional
specimen match to the project containing both reconstructed observations.
Even matching observation labels, specimen IDs, source geometry fingerprints,
and timestamps cannot justify importing a match from another project.
The shared longitudinal engine rejects mismatched project bindings.
Older records without `project_id` remain readable but emit
`reidentification_project_binding_unavailable` for scientific review.

This is a caller-supplied project-scope check, not cryptographic evidence of
identity, a verified specimen match, or a substitute for independent review.
The standalone endpoint and persisted typed Workflow Builder graphs share
the same validation and provisional provenance; regression coverage checks
cross-project rejection, legacy QC, mutated evidence, and saved artifact parity.


### Machine-readable registration-review withholding provenance (Track C)

Longitudinal mesh artifacts now retain two explicit Boolean provenance flags:
`registered_centroid_comparison_withheld_due_to_registration_dispute` and
`registered_centroid_comparison_withheld_due_to_inconclusive_registration_review`.
They distinguish an independent review that **disputes** alignment from one
that cannot determine alignment. A supporting review, an absent review, and
missing registration evidence leave both flags `false`; none of these states
constitutes verified registration. A disputed or inconclusive decision sets
its corresponding flag to `true` and withholds transformed-centroid offsets,
separations, associated caller-bound intervals, and RMS ratios as `null`.
The original mesh measurements, transform diagnostics, reviewer attribution,
and QC warnings remain available for audit.

These flags describe why a derived diagnostic was withheld, **not** whether
coral movement was absent or the registration was scientifically validated.
Standalone analysis and saved executable typed Workflow Builder graphs share
the same comparison engine; regression assertions verify the flags and full
persisted-artifact parity for supported, disputed, and inconclusive reviews.

### Calibration-scale-bound registration evidence (Track C)

A geometry SHA-256 fingerprint identifies reconstruction geometry, not the
physical scale applied to it. An imported mesh can be recalibrated without
changing its vertex/face fingerprint. Optional paired
`source_meters_per_mesh_unit` and `target_meters_per_mesh_unit` values now
bind a caller-supplied registration to the exact scale of each observation.
Providing only one scale is invalid. A mismatch rejects the comparison rather
than silently applying a meter-valued transform to recalibrated geometry.

Legacy evidence without either scale remains readable, but emits
`registration_calibration_scale_binding_unavailable` as scientific QC. These
scale bindings are **caller-supplied consistency checks**, not verified
calibration, accurate alignment, or proof of biological growth. Standalone
comparison and executable persisted Workflow Builder graphs use the same
validation and preserve evidence in provenance; tests cover a successful
scale-bound saved workflow, stale-scale rejection with identical geometry,
incomplete bindings, and flagged legacy evidence.


### Calibration-provenance-bound registration evidence (Track C)

A calibration can be reinterpreted without changing the imported triangles,
meters-per-unit value, or numerical uncertainty. The registration evidence
schema therefore accepts an optional **complete quartet**:
`source_calibration_method`, `target_calibration_method`,
`source_calibration_evidence`, and `target_calibration_evidence`.
All four must be supplied together and must exactly match the corresponding
mesh preview provenance. A revised method or supporting evidence string rejects
reuse of a stale registration, even when both geometry fingerprints and scales
remain unchanged. These strings are audit bindings, not evidence that the
calibration itself is accurate.

Legacy registrations without this quartet remain readable with the explicit
`registration_calibration_provenance_binding_unavailable` QC warning. Partial
or malformed quartets are rejected. The standalone longitudinal API and saved,
typed Workflow Builder graph use the same comparison engine, and a saved-workflow
regression exercises a fully bound registration. No calibration, spatial
alignment, organism identity, or biological growth is marked verified.
