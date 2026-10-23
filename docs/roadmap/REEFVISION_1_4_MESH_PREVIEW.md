# ReefVision 1.4: bounded mesh surface preview (development only)

This first 1.4 slice does **not** import or persist full 3D assets, render a 3D viewer,
or establish validated biological surface area. It accepts at most 256,000 bytes
of ASCII OBJ or ASCII PLY text (triangles only), or 2,000 explicit XYZ vertices and 4,000
triangle faces, for a **read-only preview**. Binary PLY, mesh asset storage,
interactive viewing, branch metrics and scientific verification are future work.

Standalone endpoint:
`POST /api/v1/projects/{project_id}/spatial/mesh-preview`.

Example OBJ body (PLY uses a mutually exclusive `ply_text` field):
```json
{
  "obj_text": "v 0 0 0\nv 2 0 0\nv 0 3 0\nf 1 2 3\n",
  "meters_per_unit": 0.01,
  "calibration_method": "ruler",
  "calibration_evidence": "Ruler measurement; awaiting scientist verification",
  "relative_scale_uncertainty": 0.05
}
```

Workflow Builder: `project_source.project` -> `mesh_surface_preview.project`,
with the same request fields as node parameters. The saved, executed node
produces a checksummed `mesh_measurement_preview` artifact. A graph revision
records input geometry and evidence; **do not embed confidential or large
source assets** in graph parameters.

ASCII PLY 1.0 supports bounded XYZ scalar vertices (arbitrary property order,
with optional numeric scalar vertex properties) and a triangular vertex-index
face list. Binary encodings, other elements, and non-triangular faces are
rejected. Both the standalone API and saved Workflow Builder support PLY,
recording `provenance.source_format=ply_ascii`. This is not persistent asset
import or interactive 3D viewing.

Results report triangle surface area in m² and axis-aligned dimensions in
meters; dimensions change under rotation. QC reports boundary, nonmanifold,
and degenerate triangles. Area scale uncertainty is first-order propagation
of relative scale uncertainty (2×), **not** a confidence interval or total
measurement error. A surface containing holes may omit organism tissue.
Source geometry and calibration remain `caller_supplied_unverified`.
No volume, branch length, reidentification or ecological growth claims.

Tests:
`pytest apps/api/reefvision/tests/test_spatial_mesh_preview_v14.py`
and `pytest apps/api/reefvision/tests/test_spatial_mesh_workflow_v14.py`
and `pytest apps/api/reefvision/tests/test_spatial_mesh_ply_v14.py`.

Windows installer, interactive UI, GPU, real coral scans, full CI and
scientific acceptance remain release blockers.

GLB 2.0 base64 (`glb_base64`) is supported for one embedded indexed triangle
primitive without scene transforms, compression or external buffers. The same
bounded parser is used by the standalone API and saved Workflow Builder node.
Measurements remain provisional with `source_format=glb_2_0`; no persistent
3D asset storage, interactive viewer or biological validation is implied.

Mesh topology QC also reports `edge_connected_patch_count` (face patches
connected by shared edges) and `inconsistent_winding_edge_count` (shared edges
traversed in the same direction by exactly two faces). These add the warnings
`disconnected_mesh_patches` and `inconsistent_face_winding`. A patch count
above one may indicate disconnected fragments, and inconsistent winding may
invalidate assumptions of a consistently oriented closed surface. This is
diagnostic topology QC, not a validated tissue segmentation, watertightness
certificate, volume estimate, or biological identity determination.


## Bounded mesh render payload (1.4 development)

The mesh preview response now includes `preview_face_indices` (original
zero-based face indices), `preview_vertex_indices` (original vertex indices),
`preview_faces_local_indices` (triangles remapped to the preview vertex array),
`preview_vertices_in_source_frame_m`, and `preview_is_decimated`.
At most 512 triangles and 1,536 referenced vertices are returned for display.
Faces are sampled deterministically across the original face order, with the
first and last included; this is a **render-only sample**, not a representative
statistical sample of tissue or a validated mesh simplification.

All surface areas, extents, QC, uncertainty estimates and geometry hashes are
computed from the complete validated input **before** the display sample is
formed. Preview indices retain the original source indexing and face winding;
the local face indices address only the preview vertex array. Calibrated
coordinates still depend on caller-supplied, unverified scale evidence.
Sampling can omit small branches, holes, or defects and must never be used
for scientific measurement or organism reidentification. No interactive 3D
viewer, persistence, camera controls, or hardware acceptance is claimed.

Regression coverage:
`test_spatial_mesh_render_sample_v14.py` checks the 512/513-face threshold,
original-to-local index mapping, unchanged full-mesh area/uncertainty, and
standalone versus executed saved Workflow Builder payload parity.
