# ReefVision 1.4 provisional mesh-edge paths

## Conditional planar footprint for a scientist-selected closed mesh trace

A closed surface-edge trace can now yield a **provisional planar enclosed
footprint** only when the exact source-XYZ audit identifies a plane and the
simple-perimeter check rules out nonadjacent crossings, contacts, overlapping or
reused edges, coincident nonadjacent waypoints, adjacent backtracking and zero
segments. Open paths, noncoplanar loops, undefined planes and non-simple loops
retain **null** footprint fields rather than an arbitrary polygon area.

Three fields preserve the distinction between coordinate geometry and
calibrated science:

- `closed_loop_source_planar_enclosed_area_mesh_units2`: unsigned enclosed
  area in squared *imported source-coordinate units*, calculated using an
  origin-translated exact-rational 3D vector shoelace before finite binary64
  serialization. The result is insensitive to reversing the trace or choosing
  a different start vertex and works for source planes not aligned with XY.
- `closed_loop_planar_enclosed_area_m2`: that provisional footprint multiplied
  by the **square** of the caller-supplied isotropic meters-per-unit scale.
- `closed_loop_planar_enclosed_area_scale_only_interval_m2`: conditional
  marginal bounds at scales `scale * (1 - u)` and `scale * (1 + u)`,
  **squared** for the same shared relative scale uncertainty `u`. The bound
  is not a statistical confidence interval. It is null when no relative scale
  uncertainty is provided or when its positive bounds cannot be represented.

Nonzero exact source area that rounds to zero or overflows on float conversion
is reported as null with
`closed_surface_trace_source_planar_area_unrepresentable`. A finite positive
source footprint whose calibrated square-meter value underflows or overflows
is likewise withheld with
`closed_surface_trace_calibrated_planar_area_unrepresentable`; unresolved
bounds use `closed_surface_trace_planar_area_interval_unrepresentable`.
This prevents numerical zero from masquerading as an observed absence of
area. All three values remain null when a trace is not a simple planar loop.

**Do not interpret this as coral 3D surface area, measured biological
cross-sectional area, a watertight-volume estimate, verified anatomical
branch width, coral health, or a new identification.** It is only the planar
region bounded by a researcher's chosen source-geometry polygon. The
original OBJ/PLY/GLB mesh, explicit selected indices, calibration evidence,
QC, full-resolution provenance and `human_review_verified: false` are
preserved. Scientific acceptance requires independently inspected geometry,
physical calibration, and a reviewer-confirmed biological contour.

Synthetic tests cover triangle footprints, reversed/rotated winding,
a non-XY source plane, maximum shared scale uncertainty, exclusion of
crossing/contact/overlap/nonplanar/open selections, and source versus
calibrated area underflow. Executable typed persisted `mesh_surface_preview`
Workflow Builder fixtures compare the **complete** saved scientific result
and provenance against the standalone project-scoped API. Tests do not
replace field measurements, Windows MSI/CAB installed GUI checks, or GPU
acceptance.


## Scale-qualified area-equivalent circle diameter

Exactly planar, non-self-intersecting, researcher-selected closed mesh traces
also report a provisional **area-equivalent circle diameter**: the diameter
of a circle with the same source-plane footprint, `D = 2 sqrt(A / pi)`.
It is not a fitted circle or a measured diameter between two coral landmarks.

- `closed_loop_source_planar_equivalent_diameter_mesh_units`: source-coordinate
  circle-equivalent diameter; independent of isotropic calibration and of
  reversal or cyclic rotation of the trace vertices.
- `closed_loop_planar_equivalent_diameter_m`: equivalent diameter in meters
  using the caller-supplied positive isotropic scale.
- `closed_loop_planar_equivalent_diameter_scale_only_interval_m`: conditional
  **linear** uncertainty bounds at `D * scale * (1 - u)` and
  `D * scale * (1 + u)`. These are not statistical confidence bounds and
  exclude reconstruction error, contour selection, point-placement error and
  observer variation. A lower zero bound is legitimate only for `u = 1`.

All three fields are null for open, nonplanar, self-crossing, touching,
overlapping, degenerate, or otherwise non-simple selections, or when the
source area cannot be represented reliably. If a nominal positive value or
its uncertainty interval is numerically unrepresentable, the affected output
is null with an explicit `closed_surface_trace_*planar_diameter*unrepresentable`
QC warning; there is no false zero. **A linear diameter may be representable
even if its squared calibrated footprint underflows**, so the two diagnostics
are assessed independently. None of these fields certifies coral branch
width, skeletal thickness, growth, specimen condition or anatomical identity;
all results retain `human_review_verified: false`.

Synthetic right-triangle references at two scales, a triangle in the YZ
plane, reversed and cyclically rotated vertex order, full-scale uncertainty,
invalid loops, and numerical underflow exercise the field. The persisted,
typed, executable `mesh_surface_preview` Workflow Builder regression checks
that the complete saved output and provenance match the standalone API.
Physical calibration, independent contour review, installed Windows GUI and
GPU acceptance are still required before scientific release.

## Duplicate triangle exclusion versus direct topology diagnostics

The direct `mesh_surface_edge_traces` measurement engine can identify
`duplicate_triangle_segment_indices` for a deliberately malformed face list.
This diagnostic is **not** permission to publish an area or execute a preview
on duplicate faces. The complete `measure_mesh_preview` pipeline rejects
repeated indexed triangles because they would double-count surface area;
the project-scoped standalone API must reject that input as well. A saved,
typed `mesh_surface_preview` workflow may retain the researcher's input,
but execution must fail without emitting a `mesh_measurement_preview`
artifact. This keeps invalid topology from becoming apparently valid saved
scientific measurements.

Likewise, source-XYZ seam aliases can repeat more than one edge within a
single vertex-ID-unique trace. For example, visiting the same two coordinate
segments in reverse order produces both reuse pairs `[1, 2]` and `[0, 3]`,
not only the last pair. The reported reused source length and dimensionless
fraction must include **both** later traversals, without automatically
subtracting either from the researcher's selected route. These diagnostics
remain unreviewed geometry, not anatomical centerline or organism identity.

The synthetic regression distinguishes diagnostic-only engine behavior from
the public preview's fail-closed validation, checks a failed persisted typed
workflow emits no false measurement artifact, and covers both alias traversal
orders. These are automated checks, **not** field validation, installed-GUI
acceptance, or human verification of biological condition.



## Split-vertex geometric seams in imported triangle meshes

An OBJ/PLY/GLB reconstruction may duplicate vertex IDs along an otherwise
coincident source-XYZ triangle edge (for example at a UV or material seam).
A selected mesh surface trace can therefore appear to traverse a single-face
indexed boundary even though another face uses the same physical endpoint
coordinates with **different source indices**. Treating the indexed
face-incidence count as proof of a real external coral boundary can be wrong.

Each trace now also reports `geometric_edge_face_incidence_counts`, the
number of source triangle-edge occurrences with exactly equal unordered
endpoint XYZ pairs, in trace segment order. A positive-length segment where
that count exceeds `mesh_edge_face_incidence_counts` is identified by its
zero-based index in `split_vertex_seam_segment_indices`, with warning
`split_vertex_geometric_seam_on_surface_trace`. Exact coordinates, not
a fuzzy weld tolerance, define the match. Zero-length edges retain their
separate degeneracy QC and are excluded from split-seam flagging.

**No mesh repair is performed.** Geometric coincidence may reflect an
intentional export seam, duplicate reconstruction, overlapping faces, or
erroneous geometry; neither the count nor the warning certifies topological
connectivity, anatomical branch length, biological condition or identity.
The indexed vertex path, original face incidence, calibrated measurements,
scale-only uncertainty, provenance and `human_review_verified: false` remain
unchanged. Prior saved artifacts without these fields are not retroactively
interpreted as seam-free.

Synthetic tests cover two distinct triangles sharing equal source XYZ edge
endpoints but no vertex IDs, a genuinely shared indexed edge (no false split
seam), scale invariance, and equality of standalone mesh-preview and
executable, typed, persisted Workflow Builder results. Installed Windows
GUI, independent coral reconstruction and GPU acceptance are still pending.


## Indexed triangle-edge topology along selected traces

A selected surface trace now includes `mesh_edge_face_incidence_counts`,
one original-mesh triangular-face count per traversed indexed edge. Four
zero-based segment-index arrays localize the corresponding existing QC:
`open_boundary_segment_indices` (one incident face),
`nonmanifold_segment_indices` (more than two faces),
`duplicate_triangle_segment_indices` (an indexed triangle duplicated in
the source mesh), and `inconsistent_winding_segment_indices` (two incident
faces that traverse the shared indexed edge in the same direction). The
arrays align with `vertex_indices` and `segment_lengths_m`; for example,
segment 0 connects trace waypoint indices 0 and 1.

Before this change, a warning such as
`nonmanifold_edge_on_surface_trace` identified the trace as suspect but
not which portion needed inspection. Now a reviewer can locate that indexed
edge in the full-resolution source mesh without deriving topology from
decimated display triangles or making assumptions about the coral. Existing
aggregate warning names, measured distances, scale-only uncertainty,
calibration evidence, and `human_review_verified: false` are unchanged.

These are **indexed mesh** counts, not a watertightness guarantee: imported
OBJ/PLY/GLB seams with duplicated XYZ coordinates can separate faces into
different vertex IDs, and an apparently ordinary incidence of two does not
rule out poor reconstruction, self-intersection, or incorrect biological
identity. No automatic repair, centerline certification, growth estimate,
or species-condition interpretation is implied. Historical saved artifacts
without the arrays remain unverified rather than presumed defect-free.

Scientific regressions exercise boundary edges, a duplicated face,
same-direction winding, and a three-face nonmanifold edge. The same fields
are checked through the standalone mesh preview and executed, typed,
persisted `mesh_surface_preview` Workflow Builder graphs, including
measurement/provenance parity. Synthetic test coverage does not validate
field reconstruction quality or native Windows GPU/installed-GUI behavior.

## Reused geometric edges in a scientist-selected trace

Imported OBJ/PLY/GLB meshes can carry distinct indexed vertices at exactly
the same XYZ positions, for example along a duplicated reconstruction seam.
An ordered surface trace may therefore revisit a **positive-length geometric
edge** even when its vertex indices are unique. The trace engine now compares
the unordered endpoint positions of every source-frame segment and emits
`repeated_geometric_segment_index_pairs`, a list of
`[first_segment_index, repeated_segment_index]` pairs using zero-based
segment offsets, and `surface_trace_reused_geometric_segment` in
`qc_warnings` when a segment is reused. The audit is insensitive to edge
direction and to a common calibration scale. It deliberately excludes
zero-length segments, which retain their separate zero-length QC.

This is an **exact-coordinate** duplication check, not a tolerance-based
3D intersection finder or a verified anatomical centerline. Near-coincident
segments and overlapping subsegments with different endpoints may remain
undetected. The full trace and unadjusted total are preserved for review;
ReefVision does **not** silently subtract segments or assert a corrected
biological branch length. Historical artifacts without the field remain
provisional and should not be treated as proof of geometric uniqueness.

Synthetic fixtures with distinct indexed seam vertices and nonduplicate
triangular faces exercise same-direction and reverse repeated-edge
traversals. The project-scoped standalone mesh-preview endpoint and
executable, typed, persisted Workflow Builder graph assert the same full
measurement and provenance, including unverified human review. Neither
synthetic coverage nor a passing CI gate establishes field accuracy.

## Scale-only intervals when a real trace edge underflows

A real positive source-frame edge can become `0.0` after multiplication by
an extremely small meter-per-mesh-unit scale. For a nonzero imported distance,
a generated `[0.0, 0.0]` interval would misleadingly claim an exact physical
zero. The provisional surface-trace engine now records such calibrated
segment underflow in `qc_warnings` and preserves its original positive
`source_segment_lengths_mesh_units`; when uncertainty was supplied, it
withholds the entire `segment_length_scale_only_intervals_m` and
`cumulative_length_scale_only_intervals_m` collections (null), preserving
the existing array-of-pairs contract rather than mixing unknown and numeric
bounds. If the positive entire source trace also underflows, its
`length_scale_only_interval_m` is null. A representable positive total
retains its scale-only total interval, even if an individual tiny segment
requires withholding the segment/waypoint collection.

A **genuinely zero-length** source edge is different: it retains its valid
`[0.0, 0.0]` scale-only bounds, and its zero-length topology QC. Missing
uncertainty remains null even without underflow; zero supplied uncertainty
does not make an underflowed positive measurement exact. No such interval is
a statistical confidence interval or proof of reconstructed anatomy.

Synthetic scientific tests cover both cases with direct engine calls and a
representable full-mesh preview containing an underflowed edge. A standalone
API request and a saved, typed, executable Workflow Builder graph must agree
on all numerical fields, source geometry, QC, calibration provenance, and
`human_review_verified: false`. Hardware accuracy, independent field
calibration, and coral centerline identity require separate review.

## Raw mesh-coordinate evidence independent of calibration

Caller-selected surface-edge traces now persist three additional audit fields:
`source_segment_lengths_mesh_units` (one distance per indexed edge),
`source_trace_length_mesh_units` (the sum of source-frame edge lengths when
representable), and `source_endpoint_chord_mesh_units` (source-frame endpoint
separation). These values are measured before multiplying by
`meters_per_unit`. A positive source segment therefore remains visible in
the saved scientific artifact even when an extremely small calibration
underflows its `segment_lengths_m` to zero. Source totals too large for a
finite binary64 result are **null**, accompanied by
`surface_trace_source_length_unrepresentable` QC; no Infinity or invented
precision is serialized.

These are **native imported mesh coordinate units**, not validated meters,
millimeters, coral branch lengths, or independent ground-truth landmarks.
The existing calibrated meter fields, scale-only intervals, numerical QC,
calibration provenance, original vertex indices and unverified reviewer
status remain intact. In particular, a calibrated physical zero caused by
underflow is **not** evidence that the underlying source edge has zero
length. Researchers must review reconstruction geometry, acquisition scale
and calibration before interpreting physical growth or comparing dates.
These added audit fields are carried identically by the standalone
`mesh-preview` API and an executed, persisted, typed `mesh_surface_preview`
Workflow Builder graph; synthetic regressions cover both paths and a
positive imported source segment whose calibrated meter representation
underflows.

## Exact-cost route alternatives (provisional QC)

A shortest mesh-edge route need not be geometrically unique: a square mesh can
have two equally short perimeter paths with different waypoint sequences and
potentially different turning-angle summaries. The shared 1.4 engine now
reports `shortest_route_alternatives_status` on every requested route:

- `multiple_exact_equal_cost_routes`: at least two edge paths reach the
  selected endpoint with the same accumulated binary64 cost **and** equal
  exact sums of their stored binary64 edge weights; also emits
  `multiple_equal_cost_mesh_routes` in `path_qc_warnings`. This says
  nothing about exact distances in the underlying continuous surface.
- `no_exact_equal_cost_alternative_detected`: exactly one minimum-cost path
  was found by the strictly positive-weight, bounded graph search. This is
  **not** proof that the biological path or an approximately equal-cost
  route is unique.
- `unassessable_zero_length_edges`: the route's **connected mesh component**
  contains at least one zero-length edge. This guard applies even when that
  edge is outside the selected route, because zero-weight cycles invalidate
  simple positive-weight path counting. Connected routes now also emit
  `zero_length_mesh_edge_in_connected_component` in `path_qc_warnings`,
  even when the selected path avoids the zero-length edge. This is a
  component-level uniqueness caution, distinct from
  `zero_length_edge_on_path`, which records traversal of an actual zero-length
  edge. Zero-length edges in **disconnected** components cannot affect this
  route and do not suppress its diagnostic.
- `unassessable_floating_point_cost_resolution`: the bounded search
  encounters a positive edge whose cost disappears in binary64 addition,
  **or** encounters competing rounded-equal route costs whose exact sums
  of represented edge weights differ. Both tiny edges after long paths
  and tiny prefixes before long edges can produce false ties. This status
  emits `positive_mesh_edge_cost_rounded_away` in `path_qc_warnings`
  instead of asserting a mathematically exact alternative. Zero-length-edge
  ambiguity takes precedence. The selected path remains provisional.
- `null`: disconnected or unreferenced endpoints have no route to compare.

Shortest-path multiplicity is counted only to two; exponential counts are not
persisted. A deterministic tie-breaking route remains available for inspection,
but its turning angles and vertex sequence cannot be interpreted as a uniquely
identified coral branch when alternative paths tie. The diagnostic compares
**recorded floating-point path costs**, with no asserted tolerance,
reconstruction-error model, independent calibration review, or biological
centerline verification. The resolution guard also compares suspect rounded ties using exact
rational sums of the **already rounded binary64 edge lengths**; this avoids
a false exact-tie claim when a small prefix was lost before adding a huge
edge. It does not reconstruct exact real-valued Euclidean distances, model
uncertainty, or certify near-tie uniqueness. A near tie may remain undetected.

An overflowing positive-weight candidate cannot improve any finite
route, so the search defers overflow errors until it has explored the
remaining representable candidates. This matters even **before** a finite
destination has been discovered: a far-away reverse edge can overflow while
another valid route is still waiting in the queue. If the endpoints share a
mesh component but no representable finite accumulated route can be found,
the engine fails closed rather than misreporting a disconnected surface.
Truly disconnected endpoints remain disconnected even if an unrelated
explored component contains an overflowing detour. Direct-engine numerical
regressions exercise cases near binary64 limits; ordinary API and persisted
Workflow Builder preview inputs are independently bounded to much smaller
source coordinates and continue sharing the same path engine and provenance.
Calibration uncertainty bounds are checked independently after a valid
finite route is selected.

The project-scoped standalone preview and executable typed persisted
`mesh_surface_preview` Workflow Builder graph share this implementation.
Regression checks cover tied and untied routes, unresolved zero-length edges,
component-wide zero-edge warnings on clean selected routes, disconnected
zero-edge component isolation, workflow planning, saved execution of both
isolated and ordinary meshes, artifact/provenance equality, and unchanged
provisional status. Historical artifacts without this field remain valid and
must not be retroactively relabeled as unique.

Direct scientific-engine callers are now held to the same strict
calibration-input semantics as the public mesh-preview schema: Boolean values
cannot stand in for a numeric meter-per-unit scale or a scale uncertainty,
and unrepresentable Python integers fail closed with a controlled validation
error. Direct path geometry also rejects Boolean, string, null and
unrepresentably large integer vertex coordinates with a controlled error,
including vertices not referenced by any face. This closes an input-integrity
gap for callers that bypass the public schema without altering valid integer
or floating-point geometry, API/workflow provenance, or the provisional
measurement/review status. A relative uncertainty **equal to 1.0 (100%) is supported**; values
above 1.0 are invalid. The supported 100% boundary yields scale-only length
intervals of [0, 2L], not confidence intervals. Prior stale regression
expectations for the boundary and for zero-length connected-component QC
were corrected after inspecting exact-head Actions failures. These changes
do not validate field calibration, anatomical branch identity, or biological
measurements.

The `mesh_surface_preview` standalone API and persisted Workflow Builder node
accept up to 16 `surface_path_vertex_pairs`, each containing two distinct
zero-based source vertex indices. The engine finds a shortest route **along
existing triangle edges**, not across triangle interiors. Results include
the source indices, traversed vertices, edge count, calibrated length in
meters, optional common-scale uncertainty, and exact lower/upper scale-only
intervals for both the traversed route and endpoint chord. When relative
scale uncertainty is unknown, interval fields are null. Disconnected and
unreferenced routes never receive numeric intervals. The intervals apply
the same multiplicative scale uncertainty to both lengths; they are not
statistical confidence intervals.

Connected routes also export `path_vertices_in_source_frame_m`, an ordered
calibrated XYZ polyline corresponding one-to-one to `path_vertex_indices`.
These coordinates use the original, unregistered mesh axes and include all
traversed route vertices even when the display mesh is decimated. The polyline
are rendered as read-only polylines over the interactive mesh preview,
including vertices omitted from sampled triangles. Invalid or legacy route
coordinate evidence is not drawn; the sampled mesh remains viewable. Neither
route display nor triangle decimation changes full-mesh measurements. Disconnected and unreferenced routes return null; legacy
artifacts without this field remain readable. Coordinates are not a verified
coral centerline, georeferenced track, or biological branch identity.

Connected routes additionally report ordered `path_edge_lengths_m` (one calibrated
geometric distance for each consecutive pair in `path_vertex_indices`) and
`path_edge_length_scale_intervals_m` (one lower/upper common-scale interval
per edge when relative scale uncertainty was supplied; otherwise null).
These segments allow reviewers to inspect where a shortest route travels on
the original mesh, rather than treating only its total as evidence. Their
sum approximates the route length subject to floating-point rounding.
Disconnected and unreferenced routes return null for both segment fields,
not empty arrays that could be mistaken for measured zero-length paths.
The intervals share a single calibration uncertainty and must **not** be
interpreted as independent edge-specific errors or confidence intervals.
No segment is automatically accepted as a biological branch or centerline.

Connected routes also carry `path_turn_angles_deg`, one source-frame
**geometric turning angle per route waypoint**, and `maximum_turn_angle_deg`.
Angles use the incoming and outgoing edge direction: a straight continuation
is 0 degrees, a right-angle bend is 90 degrees, and the mathematical range is
0–180 degrees. The first and last route waypoints have null turning angles;
an interior waypoint with either adjacent edge of zero length is also null,
rather than falsely recording a straight route. When a route contains no
defined interior angle, its maximum is null. Disconnected and unreferenced
routes use null for both fields. Source-frame unit vectors make these
angles invariant to a common positive calibration scale; no angle-specific
uncertainty interval is asserted. The quantities remain **provisional mesh-edge
geometry**, not validated anatomical centerlines, biological joint angles,
coral health, or growth. They are produced by the common standalone and typed
persisted Workflow Builder measurement engine with unchanged provenance.

Connected routes additionally expose `total_absolute_geometric_turn_deg`, the
sum of all interior mesh-polyline turning angles. This is a **scale-invariant
path-bending descriptor**, not a signed net orientation change, curvature
per unit length, or a biological condition score. A single-edge route and a
fully straight route return 0 degrees; disconnected routes and routes with
any undefined interior angle return null, rather than disguising missing
evidence as zero. The value is computed from full-resolution route geometry
in both the standalone mesh preview and saved executable Workflow Builder
artifacts. Legacy artifacts without the field remain valid historical
measurements; the new aggregate is not independently verified anatomical
evidence.

The interactive route inspector also presents the saved
`total_absolute_geometric_turn_deg` aggregate, but **only** after checking
it against the sum of individually validated interior turns reconstructed
from the complete persisted route polyline. Contradictory, nonfinite, negative,
or missing aggregate measurements display **unknown**; an explicitly saved
null aggregate accompanying a genuinely undefined interior turn displays
**undefined**, not zero. A valid single-edge path displays 0 degrees. Older
artifacts without the aggregate stay inspectable without fabricating a value.
The aggregate remains provisional geometric bending—not calibrated curvature,
coral condition, anatomical branch length, or reviewed biological evidence.
This is read-only GUI inspection of the common standalone API / persisted
Workflow Builder artifact, without modifying provenance or stored results.

The interactive mesh viewer also exposes each saved route waypoint's
`path_turn_angles_deg` alongside its calibrated cumulative distance and
preceding edge length. The display requires one value per waypoint, null
endpoints, finite interior angles within 0–180 degrees (or null for undefined
angles), and a `maximum_turn_angle_deg` consistent with the non-null turns.
Malformed, missing, or contradictory evidence is shown as **unknown**, never
recalculated from the decimated preview or silently treated as a verified
anatomical result. Valid endpoint or zero-length-adjacent turns are shown as
**undefined**. Tiny valid nonzero turns are retained at scientific precision.
These are read-only provisional source-frame geometric measurements, not
coral branch curvature, reidentification, condition, or growth results.

Saved angles must also agree with turns independently reconstructed from
the **complete persisted calibrated source-frame route polyline** (not from
sampled display triangles). A maximum angle can agree with a stale or altered
angle array, so internal maximum consistency alone is insufficient. The
inspector rejects contradictory geometric turns, missing interior values for
nonzero adjacent segments, and non-null turns at zero-length segments. If
coordinate subtraction, normalization, or subnormal arithmetic cannot
reproduce the source-frame angle reliably, angle inspection stays
**unknown**, while the geometric route remains visible. Valid undefined
turns at endpoints and genuine zero-length segments remain distinct from
unknown. This check does not replace saved measurements, confer biological
verification, or cover uncertainties arising from reconstruction or
landmark selection.

The interactive route inspector now prefers the persisted per-edge lengths
and per-edge scale-only bounds instead of differencing cumulative lengths,
which can discard precision on very long routes. When older artifacts omit
per-edge arrays, the viewer retains its legacy cumulative-length fallback.
Persisted edge lengths must be finite, nonnegative, the correct array length,
and consistent with the saved total and any usable cumulative array.
Persisted edge intervals are checked against their shared calibration factor.
When an explicitly supplied edge field is inconsistent, that segment
measurement or interval is shown as **unknown** rather than silently replaced
with a freshly calculated value. Renderable provisional route coordinates
remain available for inspection, and no saved scientific artifact is changed.
Standalone API and saved Workflow Builder artifacts already export these
per-edge arrays from the same engine; the inspector is a read-only consumer.

A disconnected pair returns `status: disconnected` with unknown length.
A vertex not referenced by any face returns `status: unreferenced_endpoint`.
Neither is assigned an artificial zero or straight-line distance. An omitted
pair list yields `surface_edge_paths: null`.

Connected routes expose `path_qc_warnings` (an empty list when no listed
defect is found). Topology flags include `nonmanifold_edge_on_path`,
`open_boundary_edge_on_path`, `inconsistent_winding_edge_on_path`, and
`zero_length_edge_on_path`. The winding flag is emitted when a traversed edge
has exactly two incident faces that traverse their shared edge in the same
direction. A mesh-wide winding warning alone cannot establish that a selected
route crosses the defective edge; this route-specific flag makes that evidence
reviewable in both standalone and saved workflow artifacts. Numerical
flags include `geometric_detour_ratio_overflow`,
`calibrated_path_length_underflow`, and
`calibrated_endpoint_chord_underflow`. A disconnected or unreferenced route
has `path_qc_warnings: null` because there is no route to inspect.

The dimensionless geometric detour ratio is calculated from source mesh units
to avoid precision loss from tiny calibrated lengths. When a nonzero source
length becomes zero in meters through floating-point underflow, the route
retains its connected status but reports a QC warning; a chord that underflows
also forces the detour ratio to null rather than implying a verified physical
zero-length endpoint. This does not correct an under-resolved calibration.
Standalone and saved Workflow Builder executions use the same QC engine.
Warnings require human review and do not establish biological branch identity.

These routes are **not** coral skeleton centerlines, verified branch lengths,
biological identities, or registration between scans. Scale evidence remains
caller-supplied and unverified. Scale uncertainty is not a confidence interval
and does not include reconstruction, endpoint, or registration uncertainty.
Review is required before interpreting these provisional measurements.

## Independent saved-route geometric consistency QC

The interactive viewer now independently compares the complete persisted
calibrated source-frame route polyline with its saved total geometric length,
**each** supplied segment length, and **each** supplied cumulative waypoint
distance. Checking each edge is necessary because incorrect edge lengths can
still sum to a plausible total. Relative, scale-aware numeric agreement is
used without an absolute tolerance that would misclassify microscopic routes.
Finite XYZ coordinates whose differences or accumulated length overflow are
**unverifiable**, not certified. A missing or malformed total is also
unverifiable. Malformed explicitly supplied segment or cumulative arrays and
contradictory finite measurements are shown as **inconsistent**, with a
human-review warning. Older artifacts with no segment/cumulative arrays can
still be assessed against their reported total.

This independent QC is **read-only inspection** of the original numerical
evidence from the common standalone API and executable persisted Workflow
Builder preview artifacts. The underlying shared measurement engine,
source hashes, calibration and workflow persistence are unchanged. A
**consistent** result establishes only numerical agreement between reported
measurements and available saved source-frame coordinates, not verified
calibration, registration, anatomical centerline, organism identity, or
biological condition. An inconsistent result leaves the saved route geometry
visible for investigation; no user data or provenance is silently rewritten.

## Provenance parity for direct, API, and saved-workflow previews

The pure geometry measurement function returns core calibration and geometry
provenance. The project-scoped standalone API additionally records source
format, imported-payload integrity status, observation metadata, specimen
identity and coordinate-frame verification flags. These additional fields
must not be silently dropped or interpreted as verified scientific evidence.

For route-underflow regression coverage, the core provenance keys must agree
between the direct engine and the standalone API. The **entire** enriched
standalone provenance record, including explicit false verification flags,
must then match the persisted typed Workflow Builder measurement artifact.
The same checks also preserve the route-level numerical QC warnings and
representable calibrated area; this is reproducibility of provisional
measurements, **not** independent calibration or anatomical validation.


## Caller-selected contiguous surface edge traces (provisional)

The mesh preview also accepts up to 16 optional `surface_trace_vertex_paths`
(each an ordered sequence of 2–128 distinct **zero-based parsed vertex indices**).
Unlike `surface_path_vertex_pairs`, which chooses a shortest route between two
endpoints, a selected trace follows **exactly the specified consecutive mesh
triangle edges**. A path such as `[0, 2, 1]` therefore retains the scientist's
explicit detour even if `[0, 1]` is a shorter edge. Non-adjacent vertices,
repeated vertices, bad indices and excessive trace sizes are rejected rather
than silently bridged, truncated or converted to fabricated measurements.

The standalone preview and executable, typed, persisted `mesh_surface_preview`
Workflow Builder node both emit `surface_edge_traces`. Each trace stores the
ordered vertex IDs, complete calibrated source-frame coordinates (including
vertices omitted from a decimated visual preview), segment and cumulative
lengths, total geometric trace length, scale-only interval when supplied,
topological QC flags and explicit `human_review_verified: false`. An omitted
trace list returns null. The same preview artifact preserves geometry and
import-source checksums, caller calibration, source coordinate frame and
unverified scientific provenance; saved-workflow tests compare the entire
enriched provenance and trace evidence against the standalone API.

This is **a manually selected mesh *surface* polyline**, not a coral skeletal
centerline, verified anatomical branch length, observed growth, or a
biologically reviewed annotation. The system does not infer anatomical meaning
from who submitted the vertices. A trace crossing an open boundary, nonmanifold
edge, zero-length edge or calibrated underflow carries specific QC. Additionally,
`duplicate_triangle_on_surface_trace` identifies a traversed edge
belonging to repeated triangle records (including reversed duplicates) in
the direct trace helper. The full standalone preview and saved workflow
**reject duplicated triangle geometry without producing a measurement artifact**,
so this warning does not authorize a duplicate-mesh result. Synthetic rejection
regressions separately exercise identical indexed triangles, reversed indexed
triangles, and triangles with distinct vertex IDs but identical source XYZ
geometry. Each must fail in the direct preview, project API, and executed,
typed, persisted Workflow Builder graph; no invalid measurement artifact may
survive a failed run. The lower-level trace helper still exposes provisional
indexed/geometric incidence diagnostics, not an approved mesh measurement. By contrast,
`inconsistent_winding_edge_on_surface_trace` flags a shared edge used
in the same orientation by exactly two distinct triangles; that QC warning is
preserved in both standalone and executed saved-workflow outputs. Neither finding
is anatomical evidence or an independent biological observation. In addition,
`nonadjacent_coincident_surface_trace_vertices` warns when two different,
nonconsecutive parsed vertices in the selected trace have exactly identical
source XYZ coordinates. The trace can return to the same physical point while
having distinct indices and positive-length edges; this is an *exact-coordinate*
QC diagnostic, not a tolerance-based self-intersection test, an anatomical
centerline check, or proof of organism identity. Standalone and saved executable
Workflow Builder tests preserve this warning without changing review status.
The scale interval applies one common positive calibration factor across the complete
trace. It is neither a sampling-based confidence interval nor an estimate of
reconstruction, localization, topology or inter-observer uncertainty. A 100%
relative scale uncertainty yields [0, 2L] for representable nominal length L.
Independent anatomical and calibration acceptance remains mandatory.

### Endpoint chord and geometric detour for provisional surface traces

Caller-selected surface-edge traces report `endpoint_chord_length_m`, the
straight-line Euclidean distance between the first and last selected source
vertices, multiplied once by the meter calibration. `geometric_detour_ratio`
is the dimensionless source-frame trace length divided by the source-frame
endpoint separation, *only* when that separation is positive and the ratio
is numerically representable. On a straight trace the ideal ratio is 1; bends can
increase it. This is not a coral branch tortuosity estimate or a verified
anatomical measurement. It does not account for reconstruction, landmark
selection, viewing geometry, or independent biological replicates.

`endpoint_chord_scale_only_interval_m` applies the same single caller-provided
calibration uncertainty to the chord; it is `null` when uncertainty is absent
and is not a statistical confidence interval. Because the trace length and
chord share the same scale, the ratio is scale invariant and **must not** be
assigned an artificial independent scale-error interval. The shared helper
now computes the physical chord as source-frame endpoint distance multiplied
once by the scale, and the dimensionless ratio from source-frame distances.
Subtracting independently rounded calibrated endpoint coordinates can erase
a real source-frame separation and previously produce an incorrect zero
chord and missing ratio. The exported calibrated waypoint coordinates are
preserved for visualization; they must not silently redefine the measurement.

Three distinct states are explicitly flagged: truly coincident source-frame
endpoints produce `surface_trace_zero_endpoint_chord`; a positive source
chord that underflows after calibration produces
`calibrated_surface_trace_endpoint_chord_underflow`; and endpoints whose
calibrated visualization coordinates coincide despite a representable
positive physical chord produce
`surface_trace_endpoint_chord_display_coordinate_collapse`. In the last
case the positive calibrated measurement and dimensionless ratio remain
available, but visual interpretation needs review. A **truly coincident
source chord** always yields a null ratio with an exact [0, 0] scale-only
interval. A **positive source chord whose calibrated meter value underflows**
retains a finite source-frame detour ratio when that ratio is representable,
but the misleading meter-scale [0, 0] interval is withheld (null) even when
scale uncertainty was supplied. The QC warning remains mandatory because
the exported meter chord is numerically zero rather than physically zero.
When a positive source chord produces a nonfinite/unrepresentable ratio,
`surface_trace_detour_ratio_unrepresentable` is reported and the ratio
remains null. A null ratio is never assigned an artificial zero or infinity. None of these diagnostics is an uncertainty interval or
biological validation.

The source geometry, human-review status, and full provenance stay unchanged.
Direct measurement, standalone API, and executed persisted typed Workflow
Builder graphs share this computation. Regression tests challenge calibrated
scale changes, selected bends, zero-chord endpoints, subnormal chord
underflow with both finite and unrepresentable source-frame detours,
missing uncertainty, and saved-workflow artifact/provenance parity. The
underflow-with-finite-ratio fixture uses nondegenerate source triangles and
representable calibrated surface area, so it exercises the standalone API
and an executed, typed, persisted Workflow Builder graph—not only a helper.

### Segment and waypoint scale-only uncertainty for selected traces

Each selected trace now records `segment_length_scale_only_intervals_m`
and `cumulative_length_scale_only_intervals_m` alongside its existing
total-length interval. Arrays align respectively with consecutive triangle
edges and with all waypoints (including the initial zero). For nominal
distance `L` and one shared relative calibration-scale uncertainty `u`,
each interval is `[L(1-u), L(1+u)]`. With `u = 0`, all intervals are
exact-width; with `u = 1`, representable bounds span `[0, 2L]`.
If calibration uncertainty was not supplied, both arrays are `null`
rather than made-up exact or confidence limits.

Because the **same scale factor** applies to every segment and waypoint,
these intervals are correlated; they are **not** independent errors that
can be combined in quadrature. They do not include edge-selection,
photogrammetry, anatomy, survey registration or reviewer uncertainty.
They accompany the original source geometry and explicitly unverified
human-review status, not a verified coral skeletal centerline. The
standalone API and executable persisted typed Workflow Builder graph share
the engine, and scientific regression cases check per-segment/waypoint
bounds, unknown/zero/100% uncertainty, artifact equality and provenance.

Numerical precision QC: a positive calibrated segment can be too small to
increment an already large cumulative floating-point distance. In that case
`surface_trace_cumulative_distance_resolution_loss` flags the unresolved
waypoint increment. The individual positive `segment_lengths_m` value is
retained; subtracting adjacent `cumulative_lengths_m` values would lose this
segment. This warning is distinct from calibrated segment underflow (a positive
source edge becoming exactly zero after scaling), and does not certify an
anatomical branch or provide an uncertainty estimate. Regression coverage
includes standalone preview and saved, executed Workflow Builder artifacts,
with matching trace QC and full unverified provenance.

An additional preview-coordinate integrity check preserves the distinction
between an indexed edge's **source-frame measured length** and its plotted
waypoints. When two consecutive, distinct source positions have positive
source edge length but independently calibrated display XYZ round to the
**same** coordinates, the trace records their zero-based positions in
`display_coordinate_collapsed_segment_indices` and adds
`surface_trace_segment_display_coordinate_collapse` to `qc_warnings`.
The original positive `segment_lengths_m` is preserved; it must not be
silently changed to zero to match the drawn polyline. This is not identical
to physical segment underflow or a cumulative-distance precision warning.
The direct measurement and project-scoped API use the same helper as saved,
executed typed Workflow Builder runs, with a synthetic regression requiring
identical artifacts, provenance and explicitly unverified human review. This
is **numerical representation QC**, not proof of anatomical branch length.

Direct scientific calls to the surface-trace measurement helper now perform
strict numeric checks even without FastAPI/Pydantic: Boolean or textual scale
values, invalid scale uncertainty, huge integers that overflow binary64, and
non-finite or implicitly coerced vertex coordinates are rejected with
controlled validation errors. **All** imported vertices are checked,
including unused vertices outside the selected trace, so results cannot
silently bypass source-geometry QC. The API and saved typed Workflow Builder
graph continue to use the shared helper and already enforce their request
schemas. This strengthens provisional numeric integrity; it does not validate
calibration or biological anatomy. Regression tests include malformed direct
inputs and the separately executed saved-workflow provenance comparisons.

### Selected-trace full-reversal QC (provisional)

A caller-selected route can double back along a physical mesh edge even when
its vertex indices are all distinct, its coordinates do not repeat, and every
segment has positive length. When an interior **computed binary64 turning
angle** is 180 degrees, the shared measurement engine adds
`surface_trace_180_degree_geometric_turn` to the trace's QC warnings.
The measured trace, ordered waypoints, segment lengths, endpoint chord and
calibration provenance remain intact; none is silently shortened or rewritten.
A source-coordinate reversal is a **geometric warning**, not proof of a
biological branch doubling back. Floating-point rounding can report 180
degrees for a nearly reversing direction; this is not an exact intersection
solver and has no asserted angular tolerance or uncertainty model.
Other near-reversals may not trigger this warning.

Synthetic regression coverage distinguishes this case from coincident indexed
vertices and zero-length edges. The project-scoped standalone mesh preview
and an executed, typed, persisted Workflow Builder graph must return identical
trace evidence and provenance with `human_review_verified: false`. Historical
artifacts are not retroactively changed or declared anatomically validated.

### Precision regression and acceptance note

A small, bounded mesh fixture with a genuinely nonzero binary64 endpoint
separation but identical calibrated display endpoint coordinates now exercises
the same scientific output through direct measurement, the project-scoped
standalone endpoint, and an **executed saved typed Workflow Builder graph**.
The saved measurement and provenance must match the standalone response
exactly, retain human-review status as unverified, and surface display
coordinate collapse as QC. A separate direct-engine fixture distinguishes
positive source chord underflow from truly coincident endpoints. These are
synthetic numerical tests, **not** held-out biological or installed-GUI
validation; historical artifacts remain historical evidence and are not
silently rewritten.

### Scale-invariant geometric segment reuse audit

Selected surface-edge traces expose
`reused_geometric_segment_source_length_mesh_units` (the sum of second and
subsequent traversals of identical nonzero source-coordinate edges) and
`reused_geometric_segment_fraction_of_trace` (that source-length contribution
divided by the total selected source trace length). The existing
`repeated_geometric_segment_index_pairs` records the earliest matching segment
and each later matching segment, independent of index aliases or traversal
direction. An unrepeated positive trace reports zero reuse and zero fraction;
a zero-length or numerically unrepresentable source total yields a null
fraction rather than a fabricated zero. An unrepresentable reused-source
sum is likewise null, and a repeated trace with an unavailable fraction
also reports `surface_trace_reuse_fraction_unrepresentable`.

Both outputs are source-coordinate **QC diagnostics**, not an instruction to
subtract repeated segments from the measured trace or a corrected coral
branch length. The fraction is dimensionless and is unchanged by one shared
positive calibration scale; it does not receive a spurious independent
scale-error interval. Source mesh units remain unspecified until
calibration is independently reviewed. Existing original total-length,
uncertainty, geometry fingerprint, model/reviewer provenance and
`human_review_verified: false` are unchanged. Tests cover forward and
reversed seam aliases, positive scales, zero reuse, and complete standalone
versus executed persisted typed Workflow Builder artifact/provenance parity.
These are synthetic QC checks, not held-out biological or installed-GUI
validation.

### Fixed-width source-coordinate key contract

Geometric edge incidence, seam orientation, and repeated-traversal QC use
immutable **three-coordinate** source XYZ keys. The standalone scientific
engine accepts validated vertex triples supplied as either Python tuples or
JSON-style lists; converting either representation to a fixed-width key must
preserve exact source values, original imported vertex indices, winding
direction, and existing geometric QC. This prevents malformed static typing
from concealing a runtime list-versus-tuple discrepancy; it does **not** weld
vertices, impose a spatial tolerance, or certify a reconstructed coral branch.
Synthetic direct-call regressions exercise both input representations and both
opposing and conflicting split-vertex seam winding. Existing project-scoped
standalone and executed typed persisted Workflow Builder comparison tests
remain the acceptance route for saved artifact and provenance parity.


### Source-frame detour ratios with overflowing total lengths

A selected mesh trace may have individually representable finite XYZ edge
lengths and a valid calibrated length, while the sum of its unscaled source
edge lengths exceeds binary64 range. In that case
`source_trace_length_mesh_units` remains **null** with
`surface_trace_source_length_unrepresentable` QC, but the dimensionless
`geometric_detour_ratio` can still be finite when the endpoint chord is
also large. The shared measurement engine now recovers only that ratio using
exact rational accumulation of the already-validated source edge lengths
divided by the **source-frame** endpoint chord. The same common calibration
cancels. Genuine division overflow or a zero source chord still produces a
null ratio and explicit `surface_trace_detour_ratio_unrepresentable` or
`surface_trace_zero_endpoint_chord` QC; no infinity is persisted.

Synthetic direct-engine regressions cover recoverable sum overflow and a
truly unrepresentable ratio; existing standalone preview and **executed,
typed, persisted Workflow Builder** regressions verify shared-engine results
and saved provenance parity for representable preview inputs. Extremely large
meshes may independently fail whole-preview area or centroid numeric checks,
so these direct-engine fixtures do **not** establish whole-preview support
for arbitrary source magnitudes. Ratios remain provisional geometric detours,
not anatomical branch length, biological condition, reidentification, or
held-out scientific validation.


### Explicit closed surface-edge loops (provisional)

A scientist may now supply a bounded existing-edge trace such as
`surface_trace_vertex_paths: [[0, 1, 2, 0]]` to measure the selected **closed
surface perimeter**. Only the final waypoint may repeat the initial indexed
vertex, and at least three distinct vertices are required. Interior index
revisits, two-vertex backtracks, malformed faces, or nonexistent selected
edges remain rejected. The original indexed geometry is never welded.

`is_closed_surface_loop: true` distinguishes intentional endpoint closure
from an open trace whose different indices happen to have coincident XYZ.
The start/end return is not counted as an unexplained nonadjacent spatial
revisit. The unique closing turn is reported at waypoint zero; the duplicated
last waypoint has a null turn, so `total_absolute_geometric_turn_deg` counts
each geometric corner **once**. Segment lengths, cumulative distances,
scale-only uncertainty intervals, imported vertex indices, and calibration
provenance retain their existing meaning. Zero endpoint chord and undefined
detour ratio remain explicit: the loop's perimeter-to-chord ratio is not
defined.

The warning `closed_surface_trace_not_verified_anatomical_contour` is
mandatory. Closure does **not** establish a polyp outline, coral branch
cross-section, planarity, enclosed area/volume, organism identity, or
independent biological measurement. Neither the area enclosed by the trace
nor a biological contour is inferred. Scale intervals are calibration-only,
not observer or shape uncertainty. The same measurement engine serves the
standalone project-scoped API and executable typed persisted Workflow Builder
graphs; synthetic tests check both paths, complete artifact/provenance parity,
and invalid interior revisits. A separate metamorphic regression reverses the
selected loop winding and rotates the starting vertex: each must preserve the
same perimeter, scale-only interval, and one-turn-per-corner aggregate while
its ordered vertex and angle arrays remain tied to the caller's chosen order.
Both reversed and rotated cases also execute through saved typed workflows;
neither transform establishes contour correspondence across biological samples.
This is not held-out biological, Windows installed-GUI, or physical GPU
acceptance evidence.


### Exact submitted-coordinate coplanarity for closed traces

The provisional closed-loop diagnostic now includes
`closed_loop_source_exact_coplanarity` and
`closed_loop_source_noncoplanar_waypoint_offsets`. For a selected closed
mesh-edge loop, ReefVision identifies a noncollinear source-XYZ reference
triple and checks all distinct waypoints against its plane using exact
rational arithmetic on the **submitted binary64 coordinates**. The repeated
terminal waypoint is excluded. `true` means exactly coplanar submitted
coordinates, `false` identifies at least one out-of-plane waypoint, and
`null` means a reference plane cannot be defined because all source
waypoints are collinear/coincident (or the trace is open). The zero-based
offsets locate outliers relative to the selected trace ordering, **not**
a registered organism or a measured anatomical landmark.

`closed_surface_trace_exact_source_noncoplanarity` and
`closed_surface_trace_source_reference_plane_undefined` are explicit QC
warnings. This is **not** tolerance-based planarity testing: reconstruction
noise or one changed floating-point bit may trigger an exact mismatch.
Neither a `true` nor `null` status permits computing a biological
cross-sectional area, surface patch, planar projection, signed winding or
verified anatomical contour. Geometry remains unchanged, calibration and
scale-only perimeter intervals are preserved, and
`human_review_verified: false` is never promoted.

Synthetic tests cover a planar triangle, a noncoplanar closed tetrahedral
edge loop under both orientation reversal and start rotation, and
collinear-waypoint indeterminacy (direct engine only). The noncoplanar case
also runs through the persisted, executable typed Workflow Builder graph;
the standalone API and saved workflow must produce identical measurement
artifacts and provenance. This remains synthetic geometric QC, **not**
field-measured anatomical, installed Windows GUI, or GPU validation.

### Exact proper segment-crossing audit for source-planar closed loops

When a caller-selected closed surface trace is **exactly coplanar** in its
submitted source coordinates, ReefVision now reports
`closed_loop_source_proper_crossing_segment_pairs`. Each zero-based
`[earlier, later]` pair identifies two **nonadjacent** selected perimeter
segments with a strict interior-to-interior crossing. The common first/last
waypoint is excluded from crossing candidates. A reproducible nondegenerate
2D projection of the exact source plane and rational orientation predicates
avoid adding an arbitrary near-intersection tolerance.

The warning `closed_surface_trace_source_proper_self_intersection`
requires explicit scientific inspection. The saved pairs are `[]` when
the source-planar trace has no **proper** crossing. They are **null** when
the trace is open, noncoplanar, or lacks a definable source plane; null must
not be interpreted as a simple loop. Endpoint-to-interior contacts,
nonadjacent endpoint coincidences, and collinear overlap are **outside this
strict crossing diagnostic** and are not certified absent. Even `[]`
does not verify topological simplicity, reconstruction quality, an anatomical
coral cross-section, enclosed area, or organism-level condition.

A synthetic planar bow-tie perimeter is tested in both winding directions
and with a rotated start index; a YZ-plane reference checks that the
implementation does not assume an XY camera projection. The bow-tie
fixture also executes through an explicitly saved, typed Workflow Builder
graph, with exact comparison of its persisted trace artifact and provenance
to the standalone project-scoped API. The original mesh, calibration,
scale-only perimeter interval, QC, and
`human_review_verified: false` remain unmodified. These are **synthetic**
mesh integrity checks, not held-out biological or installed-GUI/GPU
acceptance.

### Exact endpoint-contact and collinear-overlap audit for closed traces

An exactly source-planar selected loop now reports two additional fields,
`closed_loop_source_touching_segment_pairs` and
`closed_loop_source_collinear_overlap_segment_pairs`. Both contain
zero-based pairs of **nonadjacent** source-loop segment indices; the
geometrically adjacent first and closing segments are excluded. Touching
means the segments meet at a point, including one segment endpoint lying
within another segment. Collinear overlap means the two segments share a
**positive-length** portion of the same geometric line. A collinear single
point is classified as touching, not as overlap. Both are distinct from the
existing strict interior-to-interior proper crossing diagnostic.

The implementation uses exact rational orientation, bounding-interval,
and on-segment predicates after deterministic source-plane projection,
without physical proximity thresholds or coordinate snapping. The three
fields return `[]` only for an assessable exactly planar loop with no
intersections of the corresponding type. They return `null` for an open
loop, a noncoplanar loop, or an undefined source plane; an empty proper
crossing list alone must **never** be read as a simple contour. Positive
findings produce `closed_surface_trace_source_nonadjacent_segment_contact`
or `closed_surface_trace_source_collinear_segment_overlap` QC warnings.

Synthetic tests include positive-length coincident subsegments and
nonadjacent endpoint-to-interior contacts at two calibration scales.
The same case runs in a saved, typed, executable Workflow Builder graph,
which must persist the exact same measurement and provenance as the
standalone project-scoped API. This evidence neither changes source mesh
topology nor certifies anatomical contour simplicity, coral area, branch
centerlines, calibration adequacy, organism identity, or biological growth.
`human_review_verified` remains false. Installed Windows GUI, physical
GPU, and independent biological validation are separate release gates.

### Conservative simple-planar-perimeter audit (source geometry only)

The selected closed mesh-edge trace now reports
`closed_loop_source_is_simple_planar_perimeter`: `true` only when the
submitted source coordinates are exactly coplanar, every source edge is
nonzero, and the existing nonadjacent crossing, contact, overlap, repeated
geometric-edge and coincident-waypoint audits are clear. The new exact
rational adjacent-edge backtrack audit prevents a path that reverses over
its immediately preceding edge from being classified as simple. Such
waypoints are reported as zero-based
`closed_loop_source_local_backtrack_waypoint_offsets` and produce
`closed_surface_trace_source_adjacent_backtrack` QC.

A self-intersecting, touching, overlapping, or degenerate assessable
planar loop reports `false`. Open, noncoplanar, or source-plane-undefined
traces report `null` (unassessable), not `false` or a misleading clean
result. Winding direction, loop start offset, and common positive
calibration scales do not change simplicity, although reported waypoint
offsets follow the original source order. No polygon area is inferred or
certified: source-planar simplicity is **not** evidence of an anatomical
coral contour, projected tissue area, branch length, calibration accuracy,
or biological condition. All measurements retain their original
calibration/provenance and `human_review_verified: false`.

Synthetic two-scale direct-engine tests cover an exact adjacent reversal.
Existing planar, nonplanar, crossing, touching and overlapping fixtures
also exercise the flag through the standalone API and persisted typed
Workflow Builder graph, requiring complete measurement and provenance
parity. These are not independent biological, Windows installed-GUI, or
physical GPU release validations.

### Source-planar perimeter compactness (provisional shape only)

An exactly source-planar, geometrically simple, researcher-selected closed
edge trace also reports
`closed_loop_source_planar_isoperimetric_quotient`, computed as
`4 * pi * source_enclosed_area / source_perimeter²`. This dimensionless
shape descriptor uses the original mesh source coordinates; a shared
positive calibration scale cancels, as do changing the starting waypoint
and reversing traversal. A perfect circle has the limiting value 1;
a nondegenerate polygon must have a positive value below 1. The value
is **not** a physical area, biological condition score, coral cross-section
classification, validated organism morphology, or anatomical centerline
measurement.

The quotient is only emitted when the source polygon passes existing
planarity, simplicity, nonzero-segment and intersection QC, and both
its positive enclosed area and perimeter are numerically representable.
It is `null` for open, nonplanar, crossing, touching, overlapping,
degenerate, or source-area-unrepresentable traces. A finite source area
with an unrepresentable quotient produces the
`closed_surface_trace_planar_compactness_unrepresentable` warning
instead of a false numeric zero, infinity, or spurious circularity.
The implementation evaluates `4*pi*(sqrt(area)/perimeter)²` to avoid
unnecessary squared-perimeter overflow; it is still subject to
binary64 output limits and does not claim uncertainty from the
reconstruction or endpoint-placement process.

Two independently specified right-triangle references, including
one embedded in the YZ plane, and reversed/rotated closure tests
check shape invariance. Invalid-loop tests check withholding.
The same field is evaluated in saved, typed, executable Workflow
Builder graphs, with full measurement and provenance equality
against the standalone API. `human_review_verified` stays false;
independent contour annotation, specimen-level repeatability,
installed Windows GUI, and physical GPU validation remain separate
release requirements.

### Maximum source-planar selected-vertex chord (provisional extent)

A geometrically simple, exactly source-planar, caller-selected closed
mesh-edge contour now reports the largest pairwise straight-line distance
between its distinct source vertices:
`closed_loop_source_planar_maximum_vertex_chord_mesh_units`,
`closed_loop_source_planar_maximum_vertex_chord_waypoint_offsets`,
`closed_loop_planar_maximum_vertex_chord_m`, and
`closed_loop_planar_maximum_vertex_chord_scale_only_interval_m`.
The closing duplicate of the first waypoint is excluded. Waypoint offsets
refer to the submitted trace, not canonicalized biological landmarks; ties
select the first maximizing pair in that submitted order. The numerical span
is unchanged by reversing direction, rotating the starting waypoint, or
changing only the shared positive calibration, except for the expected
linear scaling of the meter value and its uncertainty interval.

For a simple planar polygon, its greatest straight-line separation is
attained by a pair of vertices, so this is a bounded, geometrically
interpretable selected-contour dimension. It is **not** a verified organism
length, coral branch width, Feret minimum width, anatomical diameter, or
reconstructed three-dimensional tissue surface. Source coordinates, rather
than rounded viewer coordinates, determine both the selected pair and span.
An open, noncoplanar, intersecting, or otherwise nonsimple trace returns
`null` for all four fields. A nonrepresentable positive source span is
withheld with
`closed_surface_trace_source_planar_maximum_chord_unrepresentable`;
calibrated span or interval overflow/underflow is separately reported
without replacing an unknown physical measurement with zero or infinity.
Absent scale-uncertainty evidence gives a `null` interval, not a
zero-uncertainty claim.

Analytical right-triangle references (including a triangle embedded in the
YZ plane), reversed and rotated waypoint cases, full 100% scale uncertainty,
non-simple and nonplanar rejection, and tiny linear measurements independently
check this diagnostic. A saved, typed, executable Workflow Builder regression
requires its persisted measurement artifact and provenance to equal the
standalone project-scoped API result. These synthetic tests do **not**
satisfy held-out coral annotation, independent calibration, installed Windows
GUI, physical GPU or release-readiness acceptance. The output remains
`human_review_verified: false`.

### Source-plane filled-outline centroid (provisional coordinate anchor)

Exactly planar, geometrically simple, caller-selected closed surface-edge
contours expose `closed_loop_source_planar_centroid_mesh_units` and
`closed_loop_planar_centroid_m`. These are XYZ geometric centroids of the
**filled source-plane polygon**, not means of its perimeter vertices.
Signed shoelace weights from an exact-rational source-coordinate projection
determine all three axes, including XZ and YZ contours. Translation,
winding reversal, and changing the start vertex preserve the underlying
centroid; the meter coordinates apply the same caller-selected calibration.

The coordinate is **not** an organism location, coral attachment point,
tissue center of mass, reidentification decision, anatomical landmark, or
verified frame registration. It is a nominal coordinate, not a positional
confidence interval. Scale uncertainty, camera/mesh reconstruction error,
source-frame alignment, and human contour placement require separate
scientific treatment; no new uncertainty model is invented.

Open, noncoplanar, self-intersecting and otherwise nonsimple contours
return `null` for both coordinates. An exactly valid polygon can have
a squared area below binary64 representation yet have a representable
linear centroid coordinate; centroid calculation is independent of the
serialized area. Unrepresentable values are withheld with explicit
`closed_surface_trace_source_planar_centroid_unrepresentable` or
`closed_surface_trace_calibrated_planar_centroid_unrepresentable` QC,
rather than fabricated zero coordinates. Original mesh geometry,
calibration provenance and `human_review_verified: false` are preserved.

Analytical XY and YZ triangle references, reversed and rotated paths,
area underflow, non-simple loops, and standalone versus executable,
typed, persisted Workflow Builder graph comparisons provide synthetic
regression coverage. Biological verification, independent calibration,
installed Windows GUI and physical GPU acceptance remain outstanding.

### Selected route cumulative-distance precision (provisional QC)

A selected mesh-edge route now reports
`path_cumulative_lost_positive_segment_indices`: zero-based positions of
**positive calibrated segments** whose addition leaves the preceding
binary64 cumulative distance unchanged. A connected route with no such loss
reports `[]`; a disconnected or unreferenced route reports `null`.
Affected routes emit `positive_selected_mesh_segment_lost_in_cumulative_distance`
within `path_qc_warnings`. Original segment lengths, source vertex order,
and calibration-scale intervals are retained; the cumulative totals are *not*
silently repaired or mislabeled as exact. This pinpoints route-local loss
separately from component-wide shortest-path ambiguity.

An independent four-vertex synthetic mesh inside the public source-coordinate
bounds includes a positive 1e-8 m segment following 1e9 m, whose cumulative
binary64 total cannot advance. Direct service, standalone project API and
twice-executed persisted typed Workflow Builder regressions check identical
route diagnostics, full saved measurement artifacts and SHA-256 hashes.
The warning is numerical reconstruction QC, not an independently measured
coral branch length, biological growth, reidentification, calibration
verification, or source acquisition uncertainty. The installed Windows GUI,
physical GPU, human review, and representative coral validation gates remain
open.

### Exact audit of calibrated route-segment accumulation

Connected selected routes also persist
`path_calibrated_edge_sum_exact_fraction_m`, a base-10 integer or rational
numerator/denominator representing the **exact sum of the stored binary64
calibrated segment lengths** (using their exact rational values), and
`path_cumulative_total_exact_match`. A `false` result emits
`selected_mesh_route_cumulative_roundoff_disagrees_with_exact_edge_sum`.
Disconnected/unreferenced pairs retain `null` for both diagnostics. A route
with a positive segment rounded away from its displayed cumulative trace
therefore retains auditable evidence of the omitted contribution, while an
exactly representable route reports an exact match. The exact fraction is
*not* an estimate of latent physical precision, a new shortest path, a
statistical uncertainty interval, or a biological centerline. It summarizes
only already-rounded calibrated segment floats, and requires the same
independent calibration, specimen identity and scientist review as other
mesh geometry products. Direct, standalone API and twice-replayed saved typed
Workflow Builder tests require complete artifact parity and stable hashes.
