# ReefVision 1.4 — first project-scoped 3D source persistence slice

The local-only `POST /api/v1/projects/{project_id}/spatial/assets` accepts
multipart OBJ, PLY, or GLB originals (8 MiB maximum). Exact source bytes
are stored under the managed project directory with an immutable SHA-256
digest, byte count, filename, format, and timestamp in SQLite. Identical
bytes of the same format deduplicate within one project. List, detail,
and byte-content retrieval are project-scoped. Content reads recheck the
stored byte length and SHA-256 and reject missing or modified originals.
The managed filesystem path is never exposed by the API.
On each verified read, the server also requires the persisted source kind to
match the format's import classification (OBJ/GLB: mesh; PLY:
mesh_or_point_cloud). Corrupted format/kind metadata fails closed even if the
original bytes and SHA-256 remain unchanged. Standalone measurement and saved
executable Workflow Builder replay both enforce this rule; regression tests
cover all three formats and require failed workflows to publish no measurement
artifact. This does not verify mesh topology, calibration, or specimen identity.

The verified reader also rechecks the original filename's import-time
lexical safety and case-insensitive extension against the recorded OBJ/PLY/GLB
format. A corrupted database filename (including an unsafe parent path,
empty name, or mismatched extension) fails before content retrieval, standalone
measurement, or execution of a saved typed Workflow Builder graph, even when
the original bytes and digest remain intact. Regression cases cover each
source format and require failed workflows to produce no measurement artifact.
This protects audit metadata consistency; it does not authenticate the
original submitter or prove specimen identity.

The verified reader rejects symbolic-link originals and reads at most the
8 MiB import limit plus one byte before checking the actual byte count and
SHA-256. This avoids unbounded reads if a source grows between filesystem
metadata inspection and the read. Permission and I/O errors during path
inspection or the bounded original read are rejected as invalid source
evidence, rather than returning an unexpected server error. OBJ mesh and PLY
point-cloud regressions cover original-content retrieval, standalone previews,
and previously saved executable Workflow Builder graphs: failed replays must
not publish a measurement artifact. These checks are not atomic against
concurrent filesystem changes. A matching digest establishes byte integrity
only; it does not establish scale or biological identity.

The longitudinal comparison engine also rejects an explicitly recorded
zero-byte imported OBJ, PLY, or GLB original, even when its source digest was
not independently checked. A nonempty imported file cannot have a zero-byte
count. Historical preview records that omit the byte count remain readable;
absence is unknown, not a claimed empty file. Tests cover all three formats
and retain conservative duplicate-source withholding. This validation does
not authenticate caller-supplied hashes or establish independent surveys.

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
OBJ/GLB mesh or an imported PLY point cloud using the existing source/geometry,
observation, coordinate-frame, calibration, and reviewer bindings. An optional
`reviewed_spatial_source_asset_id` binds the caller-supplied review to the
specific project-owned imported original in addition to its byte digest.
A mismatched asset ID fails closed, even when another project's original has
identical bytes. Older reviews without an asset ID remain readable but receive
`independent_calibration_review_source_asset_unbound` QC. This extra binding
is enforced when a project-owned asset is resolved; inline-only previews do
not establish an asset identity. The same provisional evidence is retained in
saved executable Workflow Builder nodes; regression tests compare standalone
and persisted artifacts, reject cross-project asset-review replay, and reject
reviews reused after a scale change. The stale-scale regression also replays
a previously saved typed workflow and requires a failed run with no published
mesh or point-cloud measurement artifact, not merely standalone API rejection.
Even a reviewer decision of
`supports_scale` remains unverified QC, not proof of scale, specimen identity,
reviewer authentication, or registration. This does not yet persist a separate
versioned scientific review record.

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

### Asset-bound longitudinal reidentification evidence

Optional paired `before_spatial_source_asset_id` and
`after_spatial_source_asset_id` fields now bind provisional human specimen
matching notes to the actual project-owned OBJ/PLY/GLB originals. Both must
be supplied together as canonical lowercase UUIDs. A matching source-file
SHA-256 alone is insufficient to identify a specific import. Reusing evidence
with another asset ID is rejected, including when an observation is replayed
through a saved, typed Workflow Builder graph. Historical evidence without
the pair remains readable but receives
`reidentification_spatial_source_asset_binding_unavailable` when a stored
asset was used. Inline-only meshes have no asset identity to bind.

The standalone longitudinal endpoint and persisted executable workflow
share the same comparison engine. Regression coverage checks correct,
mismatched, partial and legacy asset bindings and exact saved-artifact parity.
These IDs provide provenance consistency, **not** authenticated human review,
verified organism identity, independent observations, or biological growth.
A durable versioned reviewer ledger and full installed-Windows/GPU scientific
acceptance are still required before release.

## Inline OBJ comments in provisional mesh previews

Bounded OBJ triangle parsing accepts standard `#` comments at the end of
vertex and triangular-face records, as well as standalone comment lines.
Comments do not contribute geometry, calibrated area, uncertainty, or mesh
paths. The original UTF-8 bytes (including comments) still determine the
source-payload SHA-256; identical geometry exported with different comments
can therefore share a geometry digest but **must not** share a source digest.
This is not an identity, registration, or calibration verification. Invalid
vertex layouts and non-triangular faces remain rejected. Standalone preview
and saved executable typed Workflow Builder graph regression tests cover
commented imports, exact source-digest parity, and unchanged measurements.

## OBJ face attribute declaration bounds

When a bounded OBJ import contains `vt` texture-coordinate or `vn` normal
records before a triangle, face references to that declared attribute type
must resolve within the records available at the face. Positive and negative
relative indices are supported; zero, malformed tokens, and references beyond
the declaration count fail closed. This prevents stale export indices from
silently becoming apparently valid calibrated mesh measurements. Older OBJ
files that include face attribute references but no corresponding `vt` or
`vn` declarations remain supported for backward compatibility; those
undeclared references are syntax-checked only. Texture coordinates and normals
are not used for area, branch length, or scale calibration. Nevertheless,
the bounded parser now validates declaration structure and numeric finiteness:
`vt` accepts one to three finite coordinates and `vn` requires exactly
three finite coordinates. Malformed, nonnumeric, NaN, and infinite
declarations fail closed before they can authorize face references. The
parser does not verify that normals have unit length or match the surface,
and it does not interpret texture coordinates as physical measurements.
Standalone API previews and persisted typed Workflow Builder execution share
the parser. Tests require rejected source references to fail a saved workflow
without publishing a measurement artifact; valid signed relative attribute
references retain identical standalone and workflow scientific provenance.
None of these checks establishes verified scale, biological identity, or
independent human review.

### Bounded ASCII PLY triangle face index widths

The local 1.4 mesh importer accepts standard signed and unsigned 8-, 16-,
and 32-bit integer types for a PLY `property list uchar <type>
vertex_indices` declaration (including `char`/`uchar`, `short`/`ushort`,
`int`/`uint` and their `int8`/`uint8`/`int16`/`uint16`/`int32`/`uint32`
aliases). Each parsed index must fit its declared integer type **and**
reference an existing vertex; the face list count remains exactly three.
This enables common compact triangle exports without silently accepting
out-of-range source tokens. Standalone measurement and executable saved typed
Workflow Builder graphs use the same parser, with regression coverage for
valid widths, invalid widths, and failed workflow runs that publish no
measurement artifact. No mesh topology, calibration, or biological identity
is independently verified by an accepted integer index.

### GLB numeric schema integrity for scientific previews

The bounded GLB 2.0 importer requires JSON integer types for TRIANGLES
primitive mode (`4`), position/index accessor component types, and any
explicit buffer-view byte stride. A JSON floating-point value such as `4.0`,
`5126.0`, or `12.0` is not a valid substitute, even if numerically equal.
An explicitly supplied accessor `normalized` flag must be a JSON boolean;
`false` is permitted and `true` remains unsupported. This prevents malformed
GLB metadata from silently entering calibrated measurements. The same parser
is used by standalone preview and persisted typed Workflow Builder execution;
regressions require invalid saved runs to fail without publishing a mesh
measurement artifact. Accepted GLB geometry is still provisional and does
not independently verify scale, biological identity, or registration.

The GLB JSON parser also rejects nonstandard nonfinite constants (`NaN`,
`Infinity`, `-Infinity`) and otherwise-valid JSON numeric exponents such as
`1e400` or `-1e400` that overflow to infinity in Python, including in ignored
metadata. These invalid numbers must not enter a scientific import simply
because the affected metadata is not used for geometry. Embedded BIN padding bytes
beyond the declared buffer length must be zero. The original imported bytes
and their SHA-256 remain unchanged. Regression coverage includes standalone
scientific analysis and saved executable typed Workflow Builder rejection,
with no measurement artifact published on failure. These checks establish
format integrity, not scientific calibration or independent biological review.

## Non-indexed GLB 2.0 TRIANGLES previews

The bounded GLB 2.0 mesh parser accepts both explicitly indexed triangle
primitives and standard non-indexed `TRIANGLES` (primitive mode 4). When the
`indices` attribute is absent, each consecutive triplet of `POSITION`
vertices is treated as one independent triangle; vertex counts that are not
multiples of three fail closed. Triangle strips and fans, scene transforms,
external buffers, compression, and sparse or unsupported geometry remain
unsupported rather than being interpreted as biological measurements.
The source format and original-file SHA-256 remain distinct from canonical
geometry provenance. Regression tests require equivalent indexed/non-indexed
geometry to agree and require standalone analysis and persisted executable
typed Workflow Builder artifacts to agree; incomplete triplets must fail
without publishing measurement artifacts. All reported scale and geometry
remain provisional pending independent calibration and scientific review.

## GLB buffer-view role integrity

When a GLB 2.0 `bufferView` explicitly declares a `target`, the
bounded importer requires `34962` (ARRAY_BUFFER) for a POSITION accessor
and `34963` (ELEMENT_ARRAY_BUFFER) for an index accessor. Missing targets
remain valid as permitted by glTF; noninteger, boolean, or contradictory
targets fail closed rather than interpreting index data as vertices or vice
versa. Correctly targeted exports retain the same geometry and measurement
provenance as equivalent exports without explicit targets. Direct parser,
standalone API, and saved executable typed Workflow Builder regressions cover
accepted and rejected cases. These checks do not validate physical scale,
biological specimen identity, or human reviewer authentication.

## Unsigned-byte GLB triangle index compatibility

The bounded GLB 2.0 mesh importer now supports all three glTF triangle-index
component types: `UNSIGNED_BYTE` (`5121`), `UNSIGNED_SHORT` (`5123`), and
`UNSIGNED_INT` (`5125`). Indexed triangles still require complete groups of
three indices, and every index must refer to a decoded vertex. This allows
compact valid coral-mesh exports without converting their index buffers.
Parser, standalone preview, and persisted executable typed Workflow Builder
regressions compare byte-indexed geometry and measurement provenance against
short-indexed equivalents. Out-of-bounds byte indices fail closed in both
execution paths without publishing a mesh measurement artifact. No new
calibration, registration, specimen identification, or reviewer verification
is inferred from a valid GLB index format.

### GLB 2.0 buffer alignment and typed-workflow parity

The bounded GLB triangle importer accepts four-byte-aligned `bufferView`
starts for float32 `POSITION` data even when the start is not a multiple of
12 bytes (the complete VEC3 width). An accessor's own offset must align to
its **component** width, not the whole vector. This avoids rejecting valid
reconstruction exports with four-byte prefix padding. All offsets remain
bounded by the declared embedded buffer and view lengths; no scene transforms,
external buffers, sparse accessors, or unbounded vertex layouts are inferred.

Malformed `bufferView` starts and index-buffer `byteStride` declarations
are rejected rather than interpreted as measured coral geometry. Tests cover
aligned and misaligned files through the parser, standalone API and persisted,
executable typed Workflow Builder graph, including failure without publishing
measurement artifacts. Passing import checks does not establish calibrated
scale, verified organism identity, reconstruction accuracy, or human review.

## GLB POSITION accessor bounds and provenance

For bounded GLB 2.0 triangle imports, optional `POSITION` accessor `min` and
`max` arrays must contain three finite, bounded JSON numbers (not booleans).
When present, each axis must agree with the extrema recomputed from decoded
float32 vertices within a small exporter-rounding tolerance (relative 1e-6,
absolute 1e-8). Missing bounds remain supported. A contradictory or malformed
bound fails closed before provisional surface area or dimensions are reported.
These metadata values are not used as independent measurements or evidence
of physical scale, registration, specimen identity, or human verification.

Regression tests cover valid and malformed bounds through direct parsing,
standalone scientific API execution, and saved executable typed Workflow
Builder graphs. Failed graph execution must not publish a mesh measurement
artifact; valid bounds must preserve the geometry digest and surface area.

## Interleaved GLB 2.0 POSITION accessors (1.4 development)

Bounded GLB imports now decode float32 VEC3 `POSITION` accessors whose
`bufferView.byteStride` is an integer from 12 through 252 bytes, divisible
by four. This supports common interleaved vertex records with additional
per-vertex bytes, while only the decoded XYZ positions contribute to
surface area, dimensions, topology, or source geometry fingerprints. The
accessor must fit fully inside its declared buffer view, including the
last strided vertex; a four-byte-aligned POSITION accessor may start after
other bytes in each record, but its XYZ values cannot cross a stride
boundary.
Index accessors remain tightly packed and reject `byteStride`.

Missing stride metadata still means tightly packed positions. Invalid
strides (including booleans, floats, undersized, misaligned, and oversized
values) or truncated views fail closed. Parser, standalone API, and
persisted executable typed Workflow Builder tests cover matching geometry,
source provenance, and failure without publishing a mesh measurement
artifact. This does not add scene transforms, compressed geometry,
external buffers, sparse accessors, verified scale, biological identity,
or authenticated scientific review. Original source bytes remain distinct
from canonical geometry and are never replaced by a derived mesh.

## GLB minimum-reader version and index extrema integrity

For glTF 2.0 previews, an optional `asset.minVersion` must explicitly be the
string `"2.0"`; malformed types and newer minimum-reader requirements fail
closed instead of being treated as compatible. Optional index-accessor `min`
and `max` metadata must be JSON integers, not numerically equal floats or
booleans, and must agree with the decoded unsigned index buffer. Missing
optional fields remain supported. This avoids trusting malformed exporter
metadata when preparing provisional coral surface measurements.

Parser regressions cover valid and invalid metadata. The same rejection is
exercised through standalone project-scoped analysis and saved executable
typed Workflow Builder graphs; failed runs must not publish a mesh measurement
artifact. These checks validate source-format consistency only. They do not
verify physical calibration, organism identity, growth, or scientific review.

## GLB morph-weight safety for provisional coral measurements

The bounded GLB 2.0 mesh preview rejects `node.weights` and `mesh.weights`
metadata rather than silently measuring undeformed base vertices when a source
claims morph-target weights. Morph-target primitives were already unsupported;
this additional check fails closed for contradictory or malformed exporters.
It does not add morph-target animation, skinning, registration, or transform
support. Direct parser regressions and standalone API plus persisted executable
typed Workflow Builder rejection tests require no measurement artifact for
these inputs. Existing valid unweighted GLB previews remain unchanged.

An accepted source remains caller-calibrated and biologically unverified.
Geometry digests and source-byte provenance are not proof of coral identity,
branch growth, registration, or independently reviewed scale.

## GLB explicit identity matrix compatibility (1.4 development)

The bounded glTF 2.0 importer now accepts a node-level, column-major 4-by-4
`matrix` only when its 16 finite numeric entries are **exactly the identity**.
This supports exports that explicitly serialize a no-op scene transform without
silently applying an unverified translation, rotation, or scale. A matrix cannot
be combined with node-level TRS fields. Nonidentity, Boolean, incomplete, and
unbounded matrices fail closed before calibrated measurements are published.

Direct parser tests and standalone project-scoped API versus persisted,
executable typed Workflow Builder tests check accepted geometry fingerprints,
area parity, and rejection without a measurement artifact. This is source-format
compatibility only: accepted geometry remains provisionally calibrated,
biological identity and registration remain unverified, and the preview does
not evaluate general scene transforms, animation, or skinning.
