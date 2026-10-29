# ReefVision 1.4 — first project-scoped 3D source persistence slice

The local-only `POST /api/v1/projects/{project_id}/spatial/assets` accepts
multipart OBJ, PLY, or GLB originals (8 MiB maximum). Exact source bytes
are stored under the managed project directory with an immutable SHA-256
digest, byte count, filename, format, and timestamp in SQLite. Identical
bytes of the same format deduplicate within one project. List, detail,
and byte-content retrieval are project-scoped. Content reads recheck the
stored byte length and SHA-256 and reject missing or modified originals.
The managed filesystem path is never exposed by the API.

The project 3D preview client rejects inconsistent source-format/kind pairs
(PLY is `mesh_or_point_cloud`; OBJ/GLB are `mesh`), empty, fractional, or
oversized reported source byte counts, and forged source verification flags
before requesting analysis. These checks do not replace server-side ownership,
byte-length, and SHA-256 verification. Invalid preview requests reject through
the asynchronous API contract, allowing callers and saved-workflow UIs to
handle errors without mistaking a synchronous exception for an artifact.

PLY is `mesh_or_point_cloud` because the extension alone does not establish
topology. Raw imports are **unreviewed**, not parsed, calibrated, registered,
or biologically identified. No delete or remote publishing operation exists.

Mesh measurement now also accepts a project-owned `asset_id` in the existing
`POST /api/v1/projects/{project_id}/spatial/mesh-preview` request or in a
saved `mesh_surface_preview` Workflow Builder node. The standalone
`mesh-longitudinal-comparison` endpoint also resolves each observation's
project-owned asset reference through the same verified source reader.
`asset_id` is mutually
exclusive with inline OBJ/PLY/GLB/triangle geometry. At **execution time**,
ReefVision verifies project ownership, source byte count and SHA-256 before
resolving the original into the same bounded measurement engine used for
inline inputs. An optional caller-supplied `expected_source_payload_sha256`
must agree with the stored original. Results include
`provenance.spatial_source_asset_id` and the source digest, while retaining
`caller_supplied_unverified` measurement status. Saved graphs store the ID,
not a second copy of the original bytes; missing or tampered files fail closed.

Project-owned ASCII PLY **point clouds** can now use the same `asset_id`
contract in the standalone `spatial/point-cloud-preview` endpoint and in
saved, executable `point_cloud_preview` Workflow Builder nodes. An asset ID
cannot be combined with inline PLY or XYZ points. Each execution verifies
project ownership, original byte length and SHA-256, optional expected digest,
and the PLY source format before running the existing point-cloud engine.
The bounded point-cloud parser accepts only ASCII PLY with vertex-only XYZ
(and optional RGB), not mesh faces or inferred surfaces. Results record the
project asset ID and SHA-256, plus `project_source_original_unreviewed` QC.
The standalone and persisted-graph paths use the same resolver and engine;
saved graphs retain the ID, not a second copy of source bytes. Tests cover
artifact equality, cross-project rejection, altered originals, and mixed
inline/stored geometry. Matching digests do **not** verify physical scale,
coordinate registration, specimen identity, or biological branch length.

The Workflow Graph workspace now has an interactive project-scoped source
picker and import/preview panel. It can display provisional mesh or ASCII PLY
point-cloud previews. Calibration method is selected explicitly from ruler,
photogrammetry control, instrument, or other/unknown; the default is
**other/unknown**, never an invented ruler observation. Changing the method,
scale, uncertainty, source, or evidence invalidates the displayed preview.
These fields are caller-supplied metadata, not independent verification.

This remains an initial persistence and preview slice, **not** a finished asset
workspace. An 8 MiB stored source may still exceed the existing bounded mesh
parser limits (256,000 text characters or 350,000 GLB base64 characters);
such sources are retained but cannot yet be previewed. Large-file streaming,
migration/Windows installation verification, and all remaining scientific
release gates remain open. No asset is automatically calibrated, registered,
or biologically verified.
