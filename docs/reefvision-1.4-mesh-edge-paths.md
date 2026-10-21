# ReefVision 1.4 provisional mesh-edge paths

The `mesh_surface_preview` standalone API and persisted Workflow Builder node
accept up to 16 `surface_path_vertex_pairs`, each containing two distinct
zero-based source vertex indices. The engine finds a shortest route **along
existing triangle edges**, not across triangle interiors. Results include
the source indices, traversed vertices, edge count, calibrated length in
meters, and optional common-scale uncertainty.

A disconnected pair returns `status: disconnected` with unknown length.
A vertex not referenced by any face returns `status: unreferenced_endpoint`.
Neither is assigned an artificial zero or straight-line distance. An omitted
pair list yields `surface_edge_paths: null`.

Connected routes expose `path_qc_warnings` (an empty list when no listed
defect is found). Possible flags are `nonmanifold_edge_on_path`,
`open_boundary_edge_on_path`, and `zero_length_edge_on_path`. A disconnected
or unreferenced route has `path_qc_warnings: null` because there is no route
to inspect. Standalone and saved Workflow Builder executions use the same
QC engine. Warnings require human review and do not establish biological
branch identity.

These routes are **not** coral skeleton centerlines, verified branch lengths,
biological identities, or registration between scans. Scale evidence remains
caller-supplied and unverified. Scale uncertainty is not a confidence interval
and does not include reconstruction, endpoint, or registration uncertainty.
Review is required before interpreting these provisional measurements.
