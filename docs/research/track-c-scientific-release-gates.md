# Track C scientific release gates (1.4–1.5)

Status: **development / not release-ready**. This document is an acceptance checklist, not evidence that any gate passed. Preserve separate version branches and draft review; do not merge unreviewed work into `main`.

## 1.4: spatial coral measurements

| Capability | Present development surface | Required acceptance evidence |
| --- | --- | --- |
| OBJ, ASCII PLY, GLB meshes; ASCII PLY point clouds | Bounded project previews and local interactive viewers | Real-file fixture corpus, malformed/oversized input rejection, local source hash replay, installed desktop GUI smoke tests |
| Calibrated mesh area and dimensions | Caller-supplied scale, uncertainty and topology QC | Traceable scale target, independent reviewer, units and numerical reference fixtures; distinguish scale-only uncertainty from full measurement uncertainty |
| Surface edge paths | Selected mesh-edge path lengths | **Do not label anatomical branch length** until a reproducible centerline/skeleton definition, branching rules and biological reference measurements are validated |
| Longitudinal centroid and surface comparisons | Provisional registration, conservative caller bounds, standalone API and saved typed graph parity tests | Held-out paired observations, verified coordinate alignment and identity, registration uncertainty budget, repeated-measurement sensitivity |
| Organism identity/reidentification | Caller-provided specimen IDs and provisional evidence | Durable reviewed identity decisions, conflicts and merges audit trail, blinded reidentification evaluation, no inferred identity from geometry alone |
| Condition and model benchmarks | Incomplete | Biological condition definitions with expert agreement; held-out datasets, per-class uncertainty, annotation provenance and failure analysis |

**Numerical-scale acceptance boundary:** The public bounded mesh-preview contract permits relative scale uncertainty from 0% through 100%. For a valid connected surface edge length `L` with a 100% caller bound, preserve the explicitly provisional scale-only interval `[0, 2L]`; do not treat it as a confidence interval or total positional/reconstruction uncertainty. A value greater than 100% is outside this bounded input contract and must be rejected. Synthetic shortest-route ambiguity fixtures sent through the API must respect its coordinate limit (absolute coordinate at most `1e9` source units), even though direct scientific engine tests may use more extreme finite magnitudes. Keep `positive_mesh_edge_cost_rounded_away` separate from calibrated-length underflow: the former indicates non-resolvable route-cost arithmetic, while the latter indicates a positive source length rounded to zero after applying the meter scale. Independently preserve both QC flags where applicable, including in saved Workflow Builder results.

**Interpretation rules:** A closed or watertight triangle mesh does not by itself establish biologically meaningful coral volume. Surface area depends on reconstruction completeness and occlusion. A mesh edge path is not a validated anatomical branch length. A caller-supplied centroid position bound is not a confidence interval; report its assumptions, coordinate frame, units and provisional status. Never promote unreviewed calibration, source integrity metadata or registration to verified scientific evidence.

## 1.5: research analysis

The experiment designer must declare treatment assignment, randomization, nesting and **experimental unit** before selecting a model. Tank-level treatment with fragments nested in tanks cannot be treated as independent fragment-level treatment replication. Require documented contrasts, assumptions, missingness handling and multiplicity decisions. ICC must state its model/type and single-versus-average measurement interpretation; Bland–Altman must distinguish repeated measures and report limits of agreement with their uncertainty. Reviewer and model benchmarking must use held-out material and avoid training/test leakage.

Field/edge inference, mosaic drift, plugin execution, multimodal fusion, surveys, scientific QC/figures and power/sensitivity are **not accepted** until they have executable standalone implementations and typed persisted Workflow Builder nodes with reproducible inputs, provenance, human review and saved-run artifact parity tests. Offline inference must not fetch or overwrite user-trained model checkpoints.

## Evidence required before either release-ready claim

1. Backend unit/integration and scientific reference fixtures pass on the **exact branch HEAD**; negative and adversarial cases cover malformed geometry, uncertainty and identity evidence.
2. Frontend interaction and accessibility tests, saved graph planning/execution/reload, persisted artifacts and schema/migration upgrade/rollback checks pass.
3. Windows MSI and CAB build **and actual installed GUI** import/measurement/workflow smoke tests pass; GPU inference is tested on supported hardware, with CPU fallback behavior documented.
4. Human-reviewed calibration and biological ground truth are documented separately from provisional fixtures; numerical accuracy and uncertainty are reported, not inferred from green CI.
5. The exact evidence (commit, workflow run IDs, fixture/data versions, environment, reviewer and remaining limitations) is recorded in issue #76 and reviewed in PR #79 or the appropriate isolated 1.5 PR.

Green CI validates only the jobs that actually ran. A Windows build job is not proof of MSI/CAB installation or functioning GPU/GUI. No release marker should be added until every applicable gate above is evidenced.

## Executable field-validation fixture contract (planned, not yet passed)

Each paired coral observation must carry a stable specimen identifier, observation UUID, UTC capture timestamp, site/survey identifier, acquisition device, source-file SHA-256, reconstruction method/version, coordinate reference frame, calibration source and units, and reviewer decision. Record unavailable values as missing; do not manufacture a default calibration or specimen identity. Keep original source files immutable and preserve both raw and derived artifact hashes.

| Fixture | Independent reference | Acceptance assertion | Required rejection/QC |
| --- | --- | --- | --- |
| Metric scale target imaged with the specimen | Physical ruler or measured fiducial with uncertainty and dated calibration record | Recovered known lengths and surface dimensions in meters, with signed error and repeatability across independent reconstructions | Missing/contradictory units, stale calibration, nonfinite scale, unsupported uncertainty assumptions |
| Watertight geometric reference object | Known analytic area and dimensions; multiple OBJ/PLY/GLB representations | Cross-format agreement within declared numerical tolerance; distinguish numeric tolerance from biological accuracy | Reversed winding, holes, duplicate faces, degenerate triangles and false biological-volume inference |
| Branching physical coral surrogate | Independently measured centerline graph, endpoints and branch junctions | Branch lengths by named branch and total length, with explicit junction/occlusion policy; independent annotator agreement | Surface-edge geodesic presented as anatomical centerline, missing branches or ambiguous junctions |
| Repeated observation of one coral | Blindly reviewed identity, known camera pose/registration targets and repeat scans | Signed area/extent change, centroid displacement and uncertainty budgets in the target frame; saved workflow matches standalone output | Unverified transform, reused evidence bound to other geometry, nonoverlapping reconstructions, unreviewed identity |
| Different but similar coral specimens | Blinded expert adjudication and separate specimen histories | Reidentification false-match and missed-match rates with confidence bounds on held-out specimens | Automatic promotion of appearance similarity to verified identity |
| Partial/occluded reconstruction | Capture coverage reference and repeated reconstructions | Completeness and sensitivity reported alongside measured area; do not interpret missing surface as tissue loss | Occlusion, detached fragments, inconsistent sampling density or unresolved source integrity |

For every fixture, store the independent reference method, reference uncertainty, sample size, numerical tolerance chosen **before** execution, analyst/reviewer identities, software commit, platform, and failure cases. The test suite should execute the same input through the standalone scientific service and a **saved, reloaded, typed Workflow Builder graph**; compare numeric values, units, warning codes, provenance, verification state, artifact hashes and immutable run revision. A graph that merely plans successfully is insufficient.

A scientific gate passes only when the corresponding fixture data and executed results are attached to issue #76 and reviewed. CI with synthetic fixtures is necessary for regression safety but cannot substitute for measured coral reference material or installed desktop acceptance.


## Anatomical centerline acceptance protocol (1.4; proposed, not implemented)

A surface-mesh shortest path must remain labelled `surface_edge_path`, never `anatomical_branch_length`. A future anatomical measurement needs an independently reviewed centerline graph with vertices in the specimen's calibrated three-dimensional coordinate frame. For every edge record the two node IDs, physical length in meters, confidence/visibility state, and whether it crosses an occluded reconstruction. Graph nodes must distinguish root/base, junction, terminal tip, and unresolved endpoint. Explicitly store whether the specimen is a tree or contains loops; reject silent conversion of a loop into a tree.

**Deterministic graph invariants.** Reject nonfinite coordinates, negative uncertainty, duplicate node IDs, dangling edge references, self-edges, duplicate undirected edges and zero-length edges unless a reviewed exception is recorded. Compute each observed edge length from calibrated 3-D coordinates; the total observed centerline length is the sum of unique edges exactly once (not the sum of root-to-tip paths, which double-counts shared trunks). A branch is a maximal path between root/junction/tip nodes through degree-two interior nodes. Preserve the junction assignment policy and return an explicit unresolved result when a crossing or overlap cannot be adjudicated. Do not fill occluded segments with straight-line distances without a separate imputation label and uncertainty model.

**Calibration and uncertainty.** Store original vertex coordinates, source coordinate units, scale value and scale-unit provenance, scale uncertainty, reconstruction/landmark uncertainty, and reviewer approval as separate fields. If `L_raw` is a sum of edge lengths in raw units and `s` is meters per raw unit, `L_m = s * L_raw`. A scale-only absolute bound `u_s` gives `u_L,scale = L_raw * u_s`; it is *not* a complete uncertainty budget. Additional correlated landmark errors cannot be treated as independent edge errors by default. A future Monte Carlo estimate must specify the coordinate error covariance model, seed, sample count, and coverage definition; absent these, report only the bounded scale contribution and mark total uncertainty unknown. Never call a caller-supplied bound a 95% confidence interval.

**Reference and parity fixtures.** Include a straight single-edge ruler surrogate, a Y-shaped three-edge graph (shared trunk counted once), an unequal-length bifurcation, a degree-two intermediate node, a loop that must not be silently pruned, and an occluded segment that remains unresolved. Reference lengths must be computed independently of the algorithm under test and stored with source hashes and predeclared tolerances. For each fixture, compare standalone execution against a saved/reloaded typed Workflow Builder graph after execution: numerical lengths, units, branch IDs, unresolved flags, uncertainty provenance, reviewer state, graph revision, and artifact hashes. A planned graph, mock output, or green build alone is not evidence of scientific validation.

**Longitudinal restrictions.** Match branch IDs only through an explicit reviewed identity correspondence table. Report missing/occluded branches separately from confirmed biological loss; do not calculate signed growth for unmatched branches. Require comparable calibration and reconstruction coverage, with baseline/follow-up timestamps and independent registration evidence. Changes in surface sampling density or reconstruction completeness must be surfaced as QC rather than interpreted as growth or tissue loss.
