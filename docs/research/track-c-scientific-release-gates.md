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
