# ReefVision 1.4 provisional mesh-edge paths

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
