# ReefVision 1.4 provisional mesh-edge paths

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
