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
