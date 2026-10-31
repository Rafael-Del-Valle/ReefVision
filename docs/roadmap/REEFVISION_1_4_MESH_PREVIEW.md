# ReefVision 1.4: bounded mesh surface preview (development only)

This 1.4 development slice does **not** import or persist full 3D assets
or establish validated biological surface area. A read-only interactive
orthographic viewer now renders **saved Workflow Builder mesh artifacts only**. It accepts at most 256,000 bytes
of ASCII OBJ or ASCII PLY text (triangles only), or 2,000 explicit XYZ vertices and 4,000
triangle faces, for a **read-only preview**. Binary PLY, mesh asset storage, direct standalone viewer integration,
branch metrics and scientific verification are future work.

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
import; saved Workflow Builder mesh artifacts can be rotated and zoomed.

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
3D asset storage, direct file-import viewer or biological validation is implied.

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
for scientific measurement or organism reidentification. The saved-artifact viewer supports yaw, pitch, and zoom controls; no asset
persistence, direct standalone upload UI, or hardware acceptance is claimed.

Regression coverage:
`test_spatial_mesh_render_sample_v14.py` checks the 512/513-face threshold,
original-to-local index mapping, unchanged full-mesh area/uncertainty, and
standalone versus executed saved Workflow Builder payload parity.

### Render-sample area coverage (development)

`preview_face_fraction` is the fraction of **triangle count** shown. The
separate `preview_surface_area_fraction` reports the proportion of the
**full-mesh triangle area** represented by sampled faces. It may be much
smaller than the face fraction when the preview omits large triangles.
`preview_sampled_surface_area_m2` reports sampled triangle area using the
same caller-supplied scale; this is display diagnostic metadata, **not** a
scientific measurement or biological tissue coverage estimate. The full
`surface_area_m2` remains computed from every validated input triangle.

When the entire mesh has zero triangle area, the area fraction is `null`
rather than an invented 100% coverage value. Render sampling can still omit
geometric or biological features even if its area fraction is high.
The standalone endpoint and executed saved Workflow Builder graph expose
the same fields; neither promotes unverified calibration or registration.

### Saved-artifact interactive mesh viewer (development)

The Workflow Builder run-detail panel now renders a bounded, read-only
orthographic SVG mesh preview for persisted `mesh_measurement_preview`
artifacts. Yaw, pitch and zoom sliders and a reset button change only the
presentation; the saved artifact, source indices, calibration evidence,
full-mesh measurements and SHA-256 provenance are not edited. The viewer
validates finite XYZ coordinates, local triangle indices, camera metadata,
and 512-face/1,536-vertex display limits before rendering. Invalid payloads
fail closed with a status message. Each polygon retains its original source
face index for inspection.

The viewer explicitly displays triangle-count and sampled-area fractions;
zero-area source geometry has undefined sampled-area coverage. Neither
coverage fraction is a biological tissue estimate. The renderer is not a
scientific 3D annotation tool, does not verify scale or registration, and
does not provide standalone direct OBJ/PLY/GLB file import or persisted asset
management. Saved workflow execution remains the source of the typed,
checksummed scientific artifact; visualization is an optional consumer.

Frontend regression coverage: `MeshArtifactViewer.test.tsx` tests rotation,
reset, immutable artifacts, invalid geometry rejection, bounded display,
and zero-area coverage. Windows installed-GUI, representative coral scans,
and full release acceptance remain outstanding.

### Selected triangle calibration-scale bounds (development)

The read-only interactive mesh viewer now reports a selected source triangle's
area in m² alongside a **scale-only interval** when the saved artifact
includes `provenance.relative_scale_uncertainty` (a caller-supplied fraction
between 0 and 1). For nominal triangle area `A` and relative scale bound
`u`, the displayed endpoints are `A(1-u)^2` and `A(1+u)^2`.
For example, a 3 m² triangle with `u=0.1` displays [2.43, 3.63] m².
This is a deterministic propagation of one multiplicative scale bound,
**not** a confidence interval, full-coral surface-area estimate, independent
calibration review, or reconstruction/registration uncertainty estimate.
A missing scale bound displays **unknown**, never a fabricated zero.
Nonfinite or out-of-range scale uncertainty fails closed; numeric overflow
withholds the interval. Rotation and zoom do not change the reported area.
The viewer consumes the same preview geometry and provenance returned by
standalone mesh analysis and persisted, typed Workflow Builder artifacts;
it does not modify either scientific artifact or saved graph.
Frontend regression tests cover known geometry, rotation invariance,
unknown versus zero uncertainty, invalid metadata, and immutability.

### Selected triangle edge-length inspection (development)

The saved-artifact viewer now reports the three sampled triangle edge lengths
in source-vertex order (1–2, 2–3, 3–1), using calibrated 3D XYZ coordinates,
not screen-space distances. When a caller supplies a relative scale bound
`u`, each edge of nominal length `L` has a deterministic **scale-only**
interval `[L(1-u), L(1+u)]`. For a 3–4–5 m triangle with `u=0.1`,
the intervals are [2.7, 3.3], [4.5, 5.5], and [3.6, 4.4] m.

These are *triangle-edge diagnostics*, **not** coral branch lengths,
centerlines, anatomical landmarks, or validated tissue dimensions. The
underlying mesh may be a bounded render-only sample; scientific full-mesh
measurements must continue to use complete source geometry. Missing scale
uncertainty is explicitly unknown rather than zero. Degenerate edges retain
zero length, while nonfinite overflow suppresses misleading measurements.
Yaw/pitch/zoom and triangle selection never modify the persisted artifact.
The standalone mesh analysis endpoint and typed, saved Workflow Builder
execution supply the same preview geometry and provenance to this read-only
viewer; no new workflow node or persisted metric is claimed.

Frontend regressions check known 3–4–5 geometry, scale-only intervals,
camera invariance, zero-length edges, missing versus zero uncertainty,
keyboard selection, and immutable scientific source data. Representative
coral scans, independently verified calibration, persistent 3D asset storage,
and installed Windows/GPU acceptance remain outstanding.
