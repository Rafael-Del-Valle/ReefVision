# ReefVision 1.1 Release-Candidate Scientific Completion Design

## Scope and decision

This increment closes the largest scientifically defensible portions of the remaining geographic, comparison-heatmap, and ocean-current roadmap. It extends the existing immutable computed-metric, environmental-analysis, workflow, export, and project-exchange infrastructure. It does not add a competing scientific-record store or modify migrations `0038` through `0042`.

The implementation must keep observed and predicted evidence distinct, preserve complete input snapshots and hashes, report unknown uncertainty as unknown, reject cross-project or stale inputs, and use deterministic algorithms with explicit versions. Analyses are descriptive. They do not imply organism-environment causation or independent biological replicates.

## Considered approaches

### 1. Extend existing scientific result systems (selected)

Geographic and annotation-comparison results use dedicated `geographic_pairwise` and `annotation_comparison` discriminators within the existing immutable computed-result tables; current-derived analyses use the environmental-analysis conventions. These are not scalar formula inputs: each discriminator has its own typed response dispatch, exchange validator/remapper, and post-import integrity check. Workflow artifacts invoke the same calculation services as standalone routes.

This has the smallest schema and migration risk, preserves one provenance model, and makes replay/currentness behavior consistent with already-shipped aggregate, mask, lunar, and tidal analyses.

### 2. Add one generic scientific-analysis table

This would simplify discriminated result storage, but duplicates the existing computed/environmental systems and requires another migration and exchange path. It is rejected.

### 3. Add tables per scientific domain

This offers strong relational constraints but creates multiple migrations, route families, and remapping implementations for data already represented safely by immutable JSON snapshots. It is rejected for this release candidate.

## Checkpoint A: geographic measurement correctness

The duplicate Vincenty implementation is replaced by the repository's GeographicLib-backed WGS84 inverse calculation, including antipodal and near-antipodal inputs. A typed pairwise calculation accepts exactly two project-owned, fresh, EPSG:4326 observations and returns distance in metres and initial true-north bearing. Georeferenced observations have dedicated snapshot/currentness rules rather than scientific-record bindings. The result snapshots both source observations and their configuration/calibration/telemetry evidence.

Endpoint uncertainty is propagated only when both endpoints declare compatible independent one-sigma horizontal uncertainty. The distance standard uncertainty is the root-sum-square of endpoint sigmas. Shared/correlated, ambiguous, or missing uncertainty produces `null` and a machine-readable reason. Bearing uncertainty remains unavailable unless a validated model exists. Existing ambiguous radius values are never reinterpreted.

CSV and GeoJSON exports retain source IDs, coordinates, units, algorithm version, input hash, and uncertainty status. GeoPackage remains explicitly deferred unless an independent reader is available in the supported runtime. A new additive lifecycle endpoint/envelope exposes stale/configuration state while preserving the legacy detail response. Exchange imports preserve historical pairwise snapshots but mark them non-current because imported geographic observations are deliberately stale; recalculation requires freshly recomputed coordinates.

## Checkpoint B: annotation comparison and heatmaps

The comparison contract names two explicit evidence sources and an optional reference side. Supported source kinds are canonical reviewed boxes, boxes from exactly one prediction job/model snapshot, and verified masks. It compares like geometry only. Boxes use deterministic class-aware one-to-one IoU matching with stable tie-breaking. Masks use exact source-pixel row-run unions/intersections. Per-class results include A/B counts, signed and absolute differences, matched/unmatched counts, IoU summaries, and reference-relative percent only when the denominator is nonzero. `null` plus a reason represents undefined percentages.

False-positive/false-negative labels are emitted only when the user explicitly names a reference side; otherwise the result uses neutral unmatched-A/unmatched-B terminology. Reviewer-to-reviewer claims are unavailable unless independent reviewer identities and evidence sets exist. `created_by=local_user` is not treated as reviewer identity.

The comparison heatmap visualizes spatial disagreement derived from the same saved calculation rather than recomputing a different population. Source inventories and hashes include exactly the evidence used. Result metadata states that images, not individual annotations, are the independent sampling units.

## Checkpoint C: current streamlines and trajectory context

A deterministic current-field integrator operates on one pinned cache snapshot with a single UTC instant, depth/datum, coordinate frame, and acquisition identity. Rectilinear axes must be finite, strictly monotonic, and unique. Bilinear interpolation requires four valid compatible corners; it never bridges missing/land cells or extrapolates.

Streamlines use versioned RK4 integration with bounded seed count, step, vertex count, and path length. Geographic displacement converts east/north metres to latitude/longitude locally and terminates at domain, missing data, stagnation, dateline/polar safety, or configured limits. Output includes every vertex speed, termination reason, settings, and source hash and is labelled flow geometry, not an organism trajectory.

Trajectory overlay consumes persisted georeferenced observations only when absolute UTC is present. Depth matching additionally requires an explicit compatible depth `ScientificRecord` with unit, datum, time, and provenance; platform altitude and Copernicus surface labels are never interpreted as organism depth. Without that record, depth matching is unavailable. Tracks split at stale/missing points, nonpositive time, excessive gaps, or dateline discontinuities. Matching reports time/depth/distance offsets and exclusions under explicit tolerances. It is descriptive environmental context, never a causal claim.

## Checkpoint D: integration and release evidence

Each calculation is exposed through typed FastAPI contracts and the relevant React workspace. Every new workflow node is added to `WorkflowDataType`, the node registry and executable-node set, handler dispatch, and exchange kind-to-node mapping. Saved workflows call the same service, and project exchange remaps every live identifier atomically while preserving immutable snapshots and hashes. CSV/JSON/GeoJSON exports carry provenance, QC, units, and limitations. Currentness validation recomputes source/configuration hashes rather than relying on timestamps.

Focused backend tests cover independent astronomical/geodesic fixtures, deterministic matching, zero denominators, missing grid cells, interpolation and RK4 reference fields, offline/cache behavior, workflow replay, and exchange tamper/rollback cases. Frontend tests cover successful, unavailable, empty, and validation states. Only after focused checks pass are checkpoints committed and pushed; exact-SHA GitHub CI remains the release authority for full suites and installers.

## Explicit limitations

- Existing video georeferencing is a flat-surface approximation and is not survey-grade without independently surveyed validation.
- Absolute UTC/VFR and per-organism depth are absent for legacy observations, so those records are excluded from time/depth trajectory matching.
- Independent reviewer identity is not stored reliably in legacy annotation rows; no reviewer-performance claim is made.
- GeoPackage is optional and deferred if the shipped environment lacks a verified writer and independent reader.
- Streamlines describe the Eulerian model field and do not establish organism behavior or environmental causation.
