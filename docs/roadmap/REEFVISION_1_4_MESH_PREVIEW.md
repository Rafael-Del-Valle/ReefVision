# ReefVision 1.4: bounded mesh surface preview (development only)

This first 1.4 slice does **not** import or persist full 3D assets, render a 3D viewer,
or establish validated biological surface area. It accepts at most 256,000 bytes
of ASCII OBJ or ASCII PLY text (triangles only), or 2,000 explicit XYZ vertices and 4,000
triangle faces, for a **read-only preview**. Binary PLY/GLB, mesh asset storage,
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
