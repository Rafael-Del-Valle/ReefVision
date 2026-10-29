# ReefVision 1.4 — first project-scoped 3D source persistence slice

The local-only `POST /api/v1/projects/{project_id}/spatial/assets` accepts
multipart OBJ, PLY, or GLB originals (8 MiB maximum). Exact source bytes
are stored under the managed project directory with an immutable SHA-256
digest, byte count, filename, format, and timestamp in SQLite. Identical
bytes of the same format deduplicate within one project. List, detail,
and byte-content retrieval are project-scoped. Content reads recheck the
stored byte length and SHA-256 and reject missing or modified originals.
The managed filesystem path is never exposed by the API.

The verified reader rejects symbolic-link originals and reads at most the
8 MiB import limit plus one byte before checking the actual byte count and
SHA-256. This avoids unbounded reads if a source grows between filesystem
metadata inspection and the read. A matching digest establishes byte integrity
only; it does not establish scale or biological identity.

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

Independent calibration review evidence can be attached to either an imported
OBJ mesh or an imported PLY point cloud using the existing source/geometry,
observation, coordinate-frame, calibration, and reviewer bindings. The same
provisional evidence is retained in saved executable Workflow Builder nodes;
regression tests compare standalone and persisted artifacts and reject reviews
reused after a scale change. Even a reviewer decision of `supports_scale`
remains unverified QC, not proof of scale, specimen identity, or registration.

The Workflow Graph workspace now has an interactive project-scoped source
picker and import/preview panel. It can display provisional mesh or ASCII PLY
point-cloud previews. Calibration method is selected explicitly from ruler,
photogrammetry control, instrument, or other/unknown; the default is
**other/unknown**, never an invented ruler observation. Changing the method,
scale, uncertainty, source, or evidence invalidates the displayed preview.
These fields are caller-supplied metadata, not independent verification.

Longitudinal mesh comparison also recomputes expected **bounding-box diagonal**
scale-only intervals from each timepoint's recorded relative calibration
uncertainty. A purported interval that is narrower or wider than its source
calibration permits is rejected rather than used to infer apparent change.
A recorded unknown uncertainty cannot be paired with an invented interval.
This mirrors the existing squared-scale check for surface area; neither
interval is a statistical confidence interval or evidence of coral growth.
Standalone comparison and saved typed Workflow Builder execution share this
validation, with regression coverage for both observation positions. Both
observations are checked independently even when one lacks a scale interval:
missing early bounds withhold the combined interval, but cannot conceal a
fabricated later interval. This rule applies to both surface area and
bounding-box diagonal scale bounds, and does not certify biological growth.

This remains an initial persistence and preview slice, **not** a finished asset
workspace. An 8 MiB stored source may still exceed the existing bounded mesh
parser limits (256,000 text characters or 350,000 GLB base64 characters);
such sources are retained but cannot yet be previewed. Large-file streaming,
migration/Windows installation verification, and all remaining scientific
release gates remain open. No asset is automatically calibrated, registered,
or biologically verified.
