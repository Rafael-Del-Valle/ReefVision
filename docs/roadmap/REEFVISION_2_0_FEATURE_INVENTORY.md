# ReefVision 2.0 Feature Inventory

> Generated from `REEFVISION_2_0_FEATURE_INVENTORY.json`. Do not edit by hand.

Updated: `2026-11-20T20:54:09Z`
Candidate target: `2.0`

## Status summary

| Status | Count |
| --- | ---: |
| blocked | 17 |
| explicitly_deferred | 4 |
| in_progress | 21 |
| verified | 35 |

## Features

| Version | Feature | Status | Entry point or boundary |
| --- | --- | --- | --- |
| 1.1 | Reviewed annotation and model-source comparison | verified | Research → Comparisons → Annotation sources |
| 1.1 | Current-field interpolation, streamlines, and trajectory context | verified | Project → Data & annotation → Environmental Context → Analyses → Ocean current map |
| 1.1 | Offline-pinned NOAA/Copernicus and tidal/lunar context | verified | Project → Data & annotation → Environmental Context |
| 1.1 | Project Exchange, backup, upgrade, and rollback integrity | verified | Project menu → Project Exchange / Backup |
| 1.1 | Projective density on a declared surveyed reference plane | blocked | Project → Data & annotation → Computed Metrics → Open verified mask coverage |
| 1.1 | Repeated-measures scientific analysis | blocked | Organisms & ecology → Reviewed analyses → saved growth analysis → Repeated measures |
| 1.1 | Versioned scientific records, provenance, and computed metrics | verified | Open project → Research → Scientific records |
| 1.1 | Telemetry and geographic measurements with uncertainty | verified | Research → Scientific records → Geographic measurements |
| 1.1 | Standalone and saved Workflow Builder parity for 1.1 science | verified | Video & automation → Workflow Builder |
| 1.2 | Abundance, density, and population summaries | verified | Research → Organisms & ecology → Population summaries |
| 1.2 | Reviewed connected coral branch graph | verified | Research → Organisms & ecology → Branch graph |
| 1.2 | Calibration snapshots and annotation revision evidence | verified | Research → Measurements → Calibration |
| 1.2 | Installed coral mask review and verified promotion | verified | Annotate → Segmentation → Prediction review |
| 1.2 | Ecology exports and reproducibility packages | verified | Research → Export analysis package |
| 1.2 | Experimental-unit and grouping safeguards | verified | Research → Organisms & ecology → Population summaries → Unit checks |
| 1.2 | Paired human–model count comparison | verified | Models & AI → Model Hub → Human–model comparison |
| 1.2 | Reviewed organism identity registry and source links | verified | Research → Organisms & ecology → Identity registry |
| 1.2 | Independent validation of calibrated coral measurements | blocked | Synthetic geometry is reported separately. |
| 1.2 | Calibrated two-date growth workflow | verified | Research → Organisms & ecology → Longitudinal growth |
| 1.3 | Acquisition-quality review and exclusions | verified | Review → Acquisition QC |
| 1.3 | Reviewed biological event summaries | verified | Research → Organisms & ecology → Event summaries |
| 1.3 | 1.3 temporal/scientific exchange, upgrade, and restore | verified | Project menu → Project Exchange / Backup |
| 1.3 | Held-out landmark, event, timing, and count agreement reports | verified | Models & AI → Model Hub → ReefPose scientific validation |
| 1.3 | Publication figures, methods, and provenance records | verified | Research → Reports → Publication outputs |
| 1.3 | Representative frame-only versus temporal ReefPose comparison | blocked | The separate prespecified five-group source fixture measured mean landmark errors of 5.575 and 4.006 px. Frame and temporal count errors were +8 and +14. The two-group fixture with 24 of 48 coordinates and no common anatomical pair frames is retained. Field accuracy remains open. |
| 1.3 | Reviewed study, treatment, site, tank, and sampling-unit assignments | verified | Research → Organisms & ecology → Study assignments |
| 1.3 | Frozen temporal ReefPose datasets and checkpoint training | verified | Models & AI → Training → Temporal ReefPose |
| 1.3 | Temporal ReefPose refinement and explicit frame review | verified | Video & automation → Video & tracking → Native temporal ReefPose |
| 1.4 | Reviewed 3D organism matching across acquisitions | blocked | 3D scientific task → Organism correspondence |
| 1.4 | Anatomical coral branch-length measurement | blocked | Home → project → Video & automation → Workflow builder → select project mesh → Anatomical branch length |
| 1.4 | Reviewed biological-condition measurements | blocked | Home → project → Video & automation → Workflow builder → select project original → Condition review |
| 1.4 | Reviewed extents, dimensions, area, surface paths, and conditional volume | verified | 3D scientific task → Measurements |
| 1.4 | Validated 1.3 to 1.4 ancestry, migration, exchange, and rollback | blocked | Installed upgrade and Project menu → Backup / Exchange |
| 1.4 | Reviewed longitudinal 3D change | blocked | 3D scientific task → Longitudinal comparison |
| 1.4 | Reviewed 3D registration transforms and calibration evidence | blocked | 3D scientific task → Registration review |
| 1.4 | Representative 3D field validation | blocked | Known synthetic geometry is reported separately. |
| 1.4 | Windows 11 Smart App Control compatibility | blocked | Keep this check separate from standard hosted Windows acceptance; a green hosted runner does not establish Smart App Control compatibility. |
| 1.4 | Bounded OBJ/PLY/GLB mesh and point-cloud preview | verified | Open project → Video & automation → Workflow builder → Project-owned 3D originals |
| 1.4 | Persistent versioned 3D project assets | verified | Open project → Video & automation → Workflow builder → Project-owned 3D originals → Import 3D original |
| 1.5 | Study setup, treatments, sampling units, exclusions, and statistical plan | blocked | Research → Study design |
| 1.5 | Offline field capture and later project reconciliation | blocked | Project → Field capture |
| 1.5 | Local model catalog, runtime selection, and prompt-assisted configuration | verified | Models & AI → Model Hub |
| 1.5 | Unified detector, mask, pose, tracking, and event comparison | blocked | Models & AI → Model comparison |
| 1.5 | Early local provider and plugin foundations | verified | Models & AI → Providers |
| 1.5 | Complete research reproducibility package | verified | Research → Export reproducibility package |
| 1.5 | Reviewer roles, independent queues, adjudication, and agreement | blocked | Review → Reviewer lab |
| 1.6 | Safe class management after use | verified | Annotate → Classes |
| 1.6 | Class visibility, dense annotation editing, and large-gallery performance | verified | Annotate → View controls and gallery |
| 1.6 | Independent migration-lineage 0038 reconciliation | verified | Applied migration IDs are never edited. |
| 1.6 | First-run onboarding and Windows usability acceptance | verified | Installed first launch → Create or open project |
| 1.6 | Prioritized QC queues, reviewer assignment, bulk actions, and idempotent retry | verified | Review → QC queues |
| 1.7 | Local cross-project monitoring summaries | in_progress | Research → Monitoring → Project summaries |
| 1.7 | Recorded, simulated, and physical acquisition sources | in_progress | Project → Acquisition sources |
| 1.7 | Durable recurring acquisition, inference, QC, and report schedules | in_progress | Video & automation → Schedules |
| 1.7 | Environmental and biological monitoring with reviewed anomaly proposals | in_progress | Research → Monitoring |
| 1.8 | Bioacoustics import, annotation, review, and aligned analysis | in_progress | Project assets → Import audio → Review |
| 1.8 | Domain-shift and group-aware performance comparison | in_progress | Models & AI → Model comparison → Domain shift |
| 1.8 | Multispectral import, calibration, visualization, and analysis | in_progress | Project assets → Import multispectral image |
| 1.8 | Taxonomy proposals, review, and detectability evaluation | in_progress | Research → Organisms & ecology → Taxonomy and detectability |
| 1.8 | Reversible underwater image correction and model-input transforms | in_progress | Annotate → Image adjustments |
| 1.9 | Full release ancestry, migration, and exchange integration | in_progress | Draft #78 contains only a narrow pose planner repair. |
| 1.9 | Supported OS, GPU, provider, format, and project compatibility matrix | in_progress | Help → Diagnostics and compatibility |
| 1.9 | End-to-end detection, segmentation, pose, tracking, and scientific workflows | in_progress | Create/open project → Import → Annotate/Model → Review → Research → Export |
| 1.9 | Large-project/video performance and restart/resume resilience | in_progress | Normal project, gallery, video, import, and job flows |
| 2.0 | CLI, Python SDK, and headless infer/benchmark/export | in_progress | Help → Automation API / installed reefvision CLI |
| 2.0 | Local compute resource scheduling, checkpointing, cancel, resume, and retry | in_progress | Models & AI → Jobs and resources |
| 2.0 | Experiment registry and research package lineage | in_progress | Research → Experiments |
| 2.0 | Modular contextual panels, saved layouts, and safe reset | in_progress | Workspace → Panels / Reset layout |
| 2.0 | Multimodal identity, time, coordinates, calibration, provenance, and shared analysis | in_progress | Research → Multimodal analysis |
| 2.0 | Versioned local plugin manifests, capability contracts, and failure isolation | in_progress | Models & AI → Plugins and providers |
| 2.0 | Appearance-based ReefPose re-identification across long gaps or videos | blocked | Video & automation → Video & tracking → Identity review |
| 2.0 | 2.0 security, update/offline release, and complete user journeys | in_progress | Installed first launch and Help → Diagnostics / Updates |
| 2.0 | Typed, versioned Workflow Builder with guided forms and human gates | in_progress | Video & automation → Workflow Builder |
| post-2.0 | Cloud accounts, hosted storage, and real-time collaboration | explicitly_deferred | Local cross-project summaries and offline exchange remain in scope. |
| post-2.0 | Hyperspectral imagery | explicitly_deferred | Multispectral remains in scope. |
| post-2.0 | Active SLEAP runtime, provider, and SLP interoperability | explicitly_deferred | BSD sleap-io may remain only for neutral NWB interchange after audit; native ReefPose is the supported pose path. Checkpoint 2194f2e96 passed a digest-bound MSI and six-CAB audit of 19,133 paths and 11,977 nested Python entries. Local 92e355b6a built from the optional NWB development environment carried wheel metadata and two CLI declarations although the vendor module was absent. The Windows release staging regression covers this input. Repeat the payload audit on the final candidate. |
| post-2.0 | Stereo reconstruction | explicitly_deferred | 3D import, measurement, and matching remain in scope. |

## Feature evidence

### rv11-annotation-source-comparison: Reviewed annotation and model-source comparison

- Target: `1.1`
- Status: `verified`
- Dependencies: `rv11-scientific-record-foundation`
- Entry point: Research → Comparisons → Annotation sources
- Workflow Builder: `required`

Acceptance checks:

- **verified** — Compare compatible source-pixel boxes or masks with stable matching and explicit undefined denominators. (`rv11-annotation-source-comparison-check`)

Evidence:

- `source`: Class-aware IoU and exact mask-union regression evidence. — `https://github.com/Rafael-Del-Valle/ReefVision/pull/71` (`rv11-compare-src`)
- `browser`: none recorded
- `windows_installed`: none recorded
- `physical_hardware`: none recorded
- `representative_data`: none recorded

### rv11-current-visualization: Current-field interpolation, streamlines, and trajectory context

- Target: `1.1`
- Status: `verified`
- Dependencies: `rv11-environmental-context`
- Entry point: Project → Data & annotation → Environmental Context → Analyses → Ocean current map
- Workflow Builder: `required`

Acceptance checks:

- **verified** — Render bounded RK4 flow geometry and withhold trajectory matching when UTC, depth, datum, or compatible field evidence is missing. (`rv11-current-visualization-check`)

Evidence:

- `source`: Reference-field interpolation, termination, and overlay tests. — `https://github.com/Rafael-Del-Valle/ReefVision/pull/71` (`rv11-current-src`)
- `source`: Standalone and saved RK4 reject unsupported longitude extents and mixed acquisitions. Reordering a compatible grid preserves its input hash. Unassessed sources retain their QC status and uncertainty disclosure when the result is saved. — `apps/api/reefvision/tests/test_workflow_current_streamline.py` (`rv11-current-shared-evidence`)
- `browser`: A generated 2 by 2 cache supplied four current vectors. The desktop exported signed values, calculated four streamlines, reopened the saved analysis and retained its unassessed input QC and uncertainty notes. — `docs/REEFVISION_1.4.0_REPORT.md#offline-currents-and-mesh-precision` (`rv11-current-offline-reopen`)
- `windows_installed`: none recorded
- `physical_hardware`: The actual dd29e0088 Windows desktop opened an offline fixture, exported four signed CSV rows, reopened the map with identical file bytes, and displayed the saved Current streamlines result with unassessed QC. The MSI and its six cabinets were locally built and administratively extracted. — `docs/REEFVISION_1.4.0_REPORT.md#ordinary-windows-account-and-delivered-downloads` (`rv11-current-packaged-offline`)
- `representative_data`: none recorded

### rv11-environmental-context: Offline-pinned NOAA/Copernicus and tidal/lunar context

- Target: `1.1`
- Status: `verified`
- Dependencies: `rv11-scientific-record-foundation`
- Entry point: Project → Data & annotation → Environmental Context
- Workflow Builder: `required`

Acceptance checks:

- **verified** — Use a pinned cache snapshot, expose missing/offline data, and retain source hashes and UTC context. (`rv11-environmental-context-check`)

Evidence:

- `source`: Deterministic offline/cache fixtures and provenance tests. — `https://github.com/Rafael-Del-Valle/ReefVision/pull/71` (`rv11-env-src`)
- `source`: Rejected duplicate UTC timestamps and invalid refresh provenance preserve the previous offline cache and associated scientific records. Both NOAA observations and predictions were exercised with controlled provider responses. — `docs/REEFVISION_1.4.0_REPORT.md#offline-currents-and-mesh-precision` (`rv11-cache-rejected-refresh`)
- `browser`: The normal Environmental Context workspace downloaded 240 temperature observations from NOAA Key West station 8724580 on 2024-06-01 UTC. Offline import after reopening returned the identical records, units, acquisition time, source and content hashes. — `docs/roadmap/REEFVISION_1_4_INTEGRATION_AUDIT.md` (`rv11-noaa-public-cache`)
- `windows_installed`: none recorded
- `physical_hardware`: none recorded
- `representative_data`: none recorded

### rv11-project-exchange-backup: Project Exchange, backup, upgrade, and rollback integrity

- Target: `1.1`
- Status: `verified`
- Dependencies: `rv11-scientific-record-foundation`
- Entry point: Project menu → Project Exchange / Backup
- Workflow Builder: `not_applicable`

Acceptance checks:

- **verified** — Preserve valid historical evidence and stale status, reject tampering, and create a new result only on explicit recalculation. (`rv11-project-exchange-backup-check`)

Evidence:

- `source`: Stale-aggregate regression and exchange integrity fixes at validated SHA 55451990. — `https://github.com/Rafael-Del-Valle/ReefVision/pull/71` (`rv11-exchange-src`)
- `browser`: none recorded
- `windows_installed`: Published 1.0.3 upgrade and verified pre-upgrade backup rollback. — `https://github.com/Rafael-Del-Valle/ReefVision/pull/71` (`rv11-exchange-win`)
- `physical_hardware`: none recorded
- `representative_data`: none recorded

### rv11-projective-density: Projective density on a declared surveyed reference plane

- Target: `1.1`
- Status: `blocked`
- Dependencies: `rv11-telemetry-geographic-measurements`
- Entry point: Project → Data & annotation → Computed Metrics → Open verified mask coverage
- Workflow Builder: `required`
- Missing input: An approved projective-density method, surveyed reference-plane fixtures with scale/calibration uncertainty, expected density values, and independent reviewer thresholds.

Acceptance checks:

- **blocked** — Compare computed projective density with independently surveyed plane area and propagate calibration/reference uncertainty. (`rv11-projective-density-check`)
- **verified** — Calculate density over a declared synthetic reference plane, exclude other classes and targets outside the region, then compare the standalone result, two saved graph runs and CSV. (`rv11-projective-density-fixture-check`)

Evidence:

- `source`: A declared homography gives known clipped physical areas and rejects a transform crossing the horizon. — `apps/api/reefvision/tests/test_computed_mask_coverage.py` (`rv11-density-fixture-source`)
- `browser`: Two eligible masks over 1.40625 cm² give 1.422222 masks/cm² in the normal workspace, saved workflow and CSV. The clipped target union is 0.9375 cm². — `apps/web/tests/e2e/projective-density-live.spec.ts` (`rv11-density-fixture-browser`)
- `windows_installed`: none recorded
- `physical_hardware`: none recorded
- `representative_data`: none recorded

### rv11-repeated-measures-analysis: Repeated-measures scientific analysis

- Target: `1.1`
- Status: `blocked`
- Dependencies: `rv11-scientific-record-foundation`
- Entry point: Organisms & ecology → Reviewed analyses → saved growth analysis → Repeated measures
- Workflow Builder: `required`
- Missing input: An approved repeated-measures study design, unit/nesting and missingness rules, representative repeated observations, preregistered estimand, and independent statistical review thresholds.

Acceptance checks:

- **blocked** — Analyze declared independent units and repeated observations without treating images or organisms as independent replicates. (`rv11-repeated-measures-analysis-check`)
- **verified** — Compute a declared two-visit comparison for complete independent units on frozen calibrated observations. Preserve missingness, nesting, design and source hashes in the same desktop and saved-workflow result. (`rv11-paired-two-visit-engineering`)

Evidence:

- `source`: Reviewed fixture organisms, dates and calibrations exercise per-unit differences, standard error and the t interval. Live analysis and imported receipts reject a colony and its fragments split across independent units. Two Exchange transfers retain the historical report while replays bind to the copied sources. — `apps/api/reefvision/tests/test_paired_growth_contrast.py` (`rv11-paired-reviewed-source`)
- `browser`: Three complete synthetic tanks with unequal nested organism counts produced differences of 1, 3 and 5 mm. A fourth incomplete tank was excluded. The mean was 3 mm, standard error 1.15470054 mm and 95% interval -1.96827542 to 7.96827542 mm with 2 degrees of freedom. Three JSON downloads and 15 original file hashes matched. Source desktop journeys also verified site, colony and recording designs with different nesting, missingness and exclusions. Four independent generated time-lapse video originals each preserved the capture-frame membership and source hash. Calculate, Download and Save recheck the reviewed source before exposing the result or saving a graph. — `apps/web/tests/e2e/paired-growth-contrast-live.spec.ts` (`rv11-paired-desktop`)
- `windows_installed`: none recorded
- `physical_hardware`: none recorded
- `representative_data`: none recorded

### rv11-scientific-record-foundation: Versioned scientific records, provenance, and computed metrics

- Target: `1.1`
- Status: `verified`
- Dependencies: None
- Entry point: Open project → Research → Scientific records
- Workflow Builder: `required`

Acceptance checks:

- **verified** — Create, reopen, exchange, and replay a provenance-pinned scientific record without mutating source media. (`rv11-scientific-record-foundation-check`)

Evidence:

- `source`: Validated 1.1 head 55451990 and exact-head CI evidence. — `https://github.com/Rafael-Del-Valle/ReefVision/pull/71` (`rv11-foundation-src`)
- `browser`: Normal project navigation and Workflow Builder acceptance. — `https://github.com/Rafael-Del-Valle/ReefVision/pull/71` (`rv11-foundation-ui`)
- `windows_installed`: Installed 1.1 acceptance and upgrade/rollback evidence. — `https://github.com/Rafael-Del-Valle/ReefVision/pull/71` (`rv11-foundation-win`)
- `physical_hardware`: none recorded
- `representative_data`: none recorded

### rv11-telemetry-geographic-measurements: Telemetry and geographic measurements with uncertainty

- Target: `1.1`
- Status: `verified`
- Dependencies: `rv11-scientific-record-foundation`
- Entry point: Research → Scientific records → Geographic measurements
- Workflow Builder: `required`

Acceptance checks:

- **verified** — Compute distance and bearing only from compatible pinned coordinates and report unavailable uncertainty explicitly. (`rv11-telemetry-geographic-measurements-check`)

Evidence:

- `source`: Independent geodesic fixtures and workflow replay at validated 1.1 head. — `https://github.com/Rafael-Del-Valle/ReefVision/pull/71` (`rv11-geo-src`)
- `browser`: none recorded
- `windows_installed`: none recorded
- `physical_hardware`: none recorded
- `representative_data`: none recorded

### rv11-workflow-parity: Standalone and saved Workflow Builder parity for 1.1 science

- Target: `1.1`
- Status: `verified`
- Dependencies: `rv11-scientific-record-foundation`
- Entry point: Video & automation → Workflow Builder
- Workflow Builder: `required`

Acceptance checks:

- **verified** — Save, reopen, execute, and exchange every automation-appropriate 1.1 scientific operation with identical validation. (`rv11-workflow-parity-check`)

Evidence:

- `source`: Saved graph parity and stale-evidence rejection tests. — `https://github.com/Rafael-Del-Valle/ReefVision/pull/71` (`rv11-wf-src`)
- `browser`: none recorded
- `windows_installed`: none recorded
- `physical_hardware`: none recorded
- `representative_data`: none recorded

### rv12-abundance-density: Abundance, density, and population summaries

- Target: `1.2`
- Status: `verified`
- Dependencies: `rv12-organism-identity`, `rv12-calibration-evidence`
- Entry point: Research → Organisms & ecology → Population summaries
- Workflow Builder: `required`

Acceptance checks:

- **verified** — Summarize reviewed organisms with declared sampled area and withhold density when area/unit evidence is missing. (`rv12-abundance-density-check`)

Evidence:

- `source`: Population denominator and missing-area tests. — `https://github.com/Rafael-Del-Valle/ReefVision/pull/85` (`rv12-density-src`)
- `browser`: none recorded
- `windows_installed`: none recorded
- `physical_hardware`: none recorded
- `representative_data`: none recorded

### rv12-branch-graph: Reviewed connected coral branch graph

- Target: `1.2`
- Status: `verified`
- Dependencies: `rv12-coral-mask-review`, `rv12-calibration-evidence`
- Entry point: Research → Organisms & ecology → Branch graph
- Workflow Builder: `required`

Acceptance checks:

- **verified** — Extract, edit, review, reopen, and exchange a connected branch graph without changing its mask source. (`rv12-branch-graph-check`)

Evidence:

- `source`: Branch topology, revision, and exchange tests. — `https://github.com/Rafael-Del-Valle/ReefVision/pull/85` (`rv12-branch-src`)
- `browser`: none recorded
- `windows_installed`: Installed branch graph acceptance. — `https://github.com/Rafael-Del-Valle/ReefVision/pull/85` (`rv12-branch-win`)
- `physical_hardware`: none recorded
- `representative_data`: none recorded

### rv12-calibration-evidence: Calibration snapshots and annotation revision evidence

- Target: `1.2`
- Status: `verified`
- Dependencies: `rv12-organism-identity`
- Entry point: Research → Measurements → Calibration
- Workflow Builder: `required`

Acceptance checks:

- **verified** — Pin units, scale, transform, source hash, revision, and reviewer before projected measurements are reportable. (`rv12-calibration-evidence-check`)

Evidence:

- `source`: Calibration snapshot and stale-revision regression tests. — `https://github.com/Rafael-Del-Valle/ReefVision/pull/85` (`rv12-calibration-src`)
- `browser`: none recorded
- `windows_installed`: none recorded
- `physical_hardware`: none recorded
- `representative_data`: none recorded

### rv12-coral-mask-review: Installed coral mask review and verified promotion

- Target: `1.2`
- Status: `verified`
- Dependencies: `rv12-calibration-evidence`
- Entry point: Annotate → Segmentation → Prediction review
- Workflow Builder: `not_applicable`

Acceptance checks:

- **verified** — Review a source-pixel predicted mask in the installed application and explicitly accept, correct, or reject it. (`rv12-coral-mask-review-check`)

Evidence:

- `source`: Mask review and transactional promotion regressions. — `https://github.com/Rafael-Del-Valle/ReefVision/pull/85` (`rv12-mask-src`)
- `browser`: none recorded
- `windows_installed`: Installed coral mask review acceptance. — `https://github.com/Rafael-Del-Valle/ReefVision/pull/85` (`rv12-mask-win`)
- `physical_hardware`: none recorded
- `representative_data`: none recorded

### rv12-ecology-exports: Ecology exports and reproducibility packages

- Target: `1.2`
- Status: `verified`
- Dependencies: `rv12-abundance-density`, `rv12-two-date-growth`
- Entry point: Research → Export analysis package
- Workflow Builder: `required`

Acceptance checks:

- **verified** — Export and restore methods, inputs, units, exclusions, revisions, and hashes without changing verified state. (`rv12-ecology-exports-check`)

Evidence:

- `source`: Exchange and restore preservation tests. — `https://github.com/Rafael-Del-Valle/ReefVision/pull/85` (`rv12-export-src`)
- `browser`: none recorded
- `windows_installed`: Installed upgrade, exchange, and restore acceptance. — `https://github.com/Rafael-Del-Valle/ReefVision/pull/85` (`rv12-export-win`)
- `physical_hardware`: none recorded
- `representative_data`: none recorded

### rv12-experimental-unit-safeguards: Experimental-unit and grouping safeguards

- Target: `1.2`
- Status: `verified`
- Dependencies: `rv12-organism-identity`
- Entry point: Research → Organisms & ecology → Population summaries → Unit checks
- Workflow Builder: `required`

Acceptance checks:

- **verified** — Reject incompatible unit aggregation and prevent images or repeated observations from inflating independent sample size. (`rv12-experimental-unit-safeguards-check`)

Evidence:

- `source`: Grouping, unit-balance, and leakage regression tests. — `https://github.com/Rafael-Del-Valle/ReefVision/pull/85` (`rv12-unit-src`)
- `browser`: none recorded
- `windows_installed`: none recorded
- `physical_hardware`: none recorded
- `representative_data`: none recorded

### rv12-human-model-counts: Paired human–model count comparison

- Target: `1.2`
- Status: `verified`
- Dependencies: `rv12-experimental-unit-safeguards`
- Entry point: Models & AI → Model Hub → Human–model comparison
- Workflow Builder: `required`

Acceptance checks:

- **verified** — Pair counts on stable reviewed units, retain exclusions and raw pairs, and avoid undefined percent denominators. (`rv12-human-model-counts-check`)

Evidence:

- `source`: Paired-count and exclusion tests. — `https://github.com/Rafael-Del-Valle/ReefVision/pull/85` (`rv12-count-src`)
- `browser`: none recorded
- `windows_installed`: none recorded
- `physical_hardware`: none recorded
- `representative_data`: none recorded

### rv12-organism-identity: Reviewed organism identity registry and source links

- Target: `1.2`
- Status: `verified`
- Dependencies: `rv11-scientific-record-foundation`
- Entry point: Research → Organisms & ecology → Identity registry
- Workflow Builder: `required`

Acceptance checks:

- **verified** — Create reviewed identity revisions, link source observations, and preserve disputed/unresolved candidates. (`rv12-organism-identity-check`)

Evidence:

- `source`: Validated 1.2 identity/revision tests at SHA 14eb83eb. — `https://github.com/Rafael-Del-Valle/ReefVision/pull/85` (`rv12-identity-src`)
- `browser`: Installed identity workflow navigation evidence. — `https://github.com/Rafael-Del-Valle/ReefVision/pull/85` (`rv12-identity-ui`)
- `windows_installed`: none recorded
- `physical_hardware`: none recorded
- `representative_data`: none recorded

### rv12-representative-calibrated-validation: Independent validation of calibrated coral measurements

- Target: `1.2`
- Status: `blocked`
- Dependencies: `rv12-two-date-growth`, `rv12-branch-graph`
- Entry point: Not user-facing
- Workflow Builder: `not_applicable`
- Missing input: Independently reviewed calibrated coral images or scans, reference branch/growth measurements, calibration uncertainty, preregistered tolerances, and an authorized scientific reviewer.

Acceptance checks:

- **blocked** — Compare branch and growth outputs against independent calibrated coral references under preregistered tolerances. (`rv12-representative-calibrated-validation-check`)

Evidence:

- `source`: none recorded
- `browser`: none recorded
- `windows_installed`: none recorded
- `physical_hardware`: none recorded
- `representative_data`: none recorded

### rv12-two-date-growth: Calibrated two-date growth workflow

- Target: `1.2`
- Status: `verified`
- Dependencies: `rv12-organism-identity`, `rv12-calibration-evidence`, `rv12-branch-graph`
- Entry point: Research → Organisms & ecology → Longitudinal growth
- Workflow Builder: `required`

Acceptance checks:

- **verified** — Compare the same reviewed organism at two dates using compatible calibration and revision evidence, with explicit missingness and uncertainty. (`rv12-two-date-growth-check`)

Evidence:

- `source`: Deterministic calibrated growth and stale-input tests. — `https://github.com/Rafael-Del-Valle/ReefVision/pull/85` (`rv12-growth-src`)
- `browser`: none recorded
- `windows_installed`: Installed calibrated two-date workflow acceptance. — `https://github.com/Rafael-Del-Valle/ReefVision/pull/85` (`rv12-growth-win`)
- `physical_hardware`: none recorded
- `representative_data`: none recorded

### rv13-acquisition-qc: Acquisition-quality review and exclusions

- Target: `1.3`
- Status: `verified`
- Dependencies: `rv13-study-assignments`
- Entry point: Review → Acquisition QC
- Workflow Builder: `required`

Acceptance checks:

- **verified** — Record reviewable QC decisions and exclusions without rewriting source observations. (`rv13-acquisition-qc-check`)

Evidence:

- `source`: QC revision and downstream staleness tests. — `https://github.com/Rafael-Del-Valle/ReefVision/pull/87` (`rv13-qc-src`)
- `browser`: none recorded
- `windows_installed`: none recorded
- `physical_hardware`: none recorded
- `representative_data`: none recorded

### rv13-event-summaries: Reviewed biological event summaries

- Target: `1.3`
- Status: `verified`
- Dependencies: `rv13-study-assignments`, `rv12-organism-identity`
- Entry point: Research → Organisms & ecology → Event summaries
- Workflow Builder: `required`

Acceptance checks:

- **verified** — Count confirmed complete events over measured valid time and retain exclusions and unit compatibility. (`rv13-event-summaries-check`)

Evidence:

- `source`: Event-window, missing-frame, and grouped-unit tests. — `https://github.com/Rafael-Del-Valle/ReefVision/pull/87` (`rv13-event-src`)
- `browser`: none recorded
- `windows_installed`: none recorded
- `physical_hardware`: none recorded
- `representative_data`: none recorded

### rv13-exchange-restore: 1.3 temporal/scientific exchange, upgrade, and restore

- Target: `1.3`
- Status: `verified`
- Dependencies: `rv13-temporal-dataset-training`, `rv13-publication-reports`
- Entry point: Project menu → Project Exchange / Backup
- Workflow Builder: `not_applicable`

Acceptance checks:

- **verified** — Upgrade 1.2, preserve temporal/scientific evidence in exchange, and restore a verified pre-upgrade backup. (`rv13-exchange-restore-check`)

Evidence:

- `source`: Migration, dependency, evidence-hash, and unknown-head tests. — `https://github.com/Rafael-Del-Valle/ReefVision/pull/87` (`rv13-exchange-src`)
- `source`: The same original verified backup that previously failed can be restored with every member at its original path. A regression exercises interrupted publication, cancellation recovery and existing marker names. — `docs/validation/restored-projects-3a9ce1622.json` (`rv13-repeat-restore-source-3a9`)
- `browser`: none recorded
- `windows_installed`: Installed 1.2 to 1.3 upgrade and rollback evidence. — `https://github.com/Rafael-Del-Valle/ReefVision/pull/87` (`rv13-exchange-win`)
- `physical_hardware`: none recorded
- `representative_data`: none recorded

### rv13-heldout-agreement: Held-out landmark, event, timing, and count agreement reports

- Target: `1.3`
- Status: `verified`
- Dependencies: `rv13-temporal-refinement-review`, `rv13-event-summaries`
- Entry point: Models & AI → Model Hub → ReefPose scientific validation
- Workflow Builder: `required`

Acceptance checks:

- **verified** — Publish paired landmark error, event precision/recall, timing/count error, exclusions, and checkpoint/reference provenance. (`rv13-heldout-agreement-check`)
- **verified** — Carry declared independent animal and recording groups from the normal frame training workflow into an immutable checkpoint lineage. A shared group or unknown historical source must remain visible in the evaluation status. (`rv13-audited-frame-training-groups`)

Evidence:

- `source`: Deterministic scoring, pairing, report-hash, and stale-source tests. — `https://github.com/Rafael-Del-Valle/ReefVision/pull/87` (`rv13-agreement-src`)
- `source`: Scratch-train and register a native frame model through a saved graph, freeze reviewed temporal sequences and rerun the same paired metrics. Disjoint declared groups qualify as held out. Shared recordings and shared animals are exposed. Missing declarations keep the report exploratory. — `scripts/verify_reefpose_temporal_lineage_live.py` (`rv13-audited-frame-group-fixture`)
- `browser`: Open a project and select Video & tracking, enter the recording and animal IDs on a source track, verify the pose, freeze supervised training data, then select reviewed identities and partitions for four temporal sequences. — `apps/web/tests/e2e/reefpose-lineage-grouping-live.spec.ts` (`rv13-audited-frame-group-browser`)
- `windows_installed`: none recorded
- `physical_hardware`: none recorded
- `representative_data`: none recorded

### rv13-publication-reports: Publication figures, methods, and provenance records

- Target: `1.3`
- Status: `verified`
- Dependencies: `rv13-study-assignments`, `rv13-event-summaries`
- Entry point: Research → Reports → Publication outputs
- Workflow Builder: `required`

Acceptance checks:

- **verified** — Reopen and export figures and methods pinned to immutable inputs, choices, exclusions, and software hashes. (`rv13-publication-reports-check`)

Evidence:

- `source`: Publication replay, stale-source, and export tests. — `https://github.com/Rafael-Del-Valle/ReefVision/pull/87` (`rv13-report-src`)
- `browser`: none recorded
- `windows_installed`: none recorded
- `physical_hardware`: none recorded
- `representative_data`: none recorded

### rv13-representative-temporal-comparison: Representative frame-only versus temporal ReefPose comparison

- Target: `1.3`
- Status: `blocked`
- Dependencies: `rv13-heldout-agreement`
- Entry point: Not user-facing
- Workflow Builder: `not_applicable`
- Missing input: Representative held-out recordings with independent landmark/event labels, the same compatible registered upstream ReefPose checkpoint, and preregistered landmark/event/timing/count thresholds.

Acceptance checks:

- **blocked** — Compare frame-only and temporal ReefPose on the same held-out recordings and upstream checkpoint, including missed events. (`rv13-representative-temporal-comparison-check`)

Evidence:

- `source`: none recorded
- `browser`: none recorded
- `windows_installed`: none recorded
- `physical_hardware`: RTX 3090 native WebView2 fixture on packaged 78a02c20c exercised training, registration, refinement, review and comparison on 12 common frames. Frame and temporal scored 24 coordinates apiece and both missed the one complete event. The report recorded exploratory lineage. — `docs/REEFVISION_1.4.0_REPORT.md#packaged-reefpose-comparison-on-the-rtx-3090` (`rv13-packaged-exploratory-rtx`)
- `physical_hardware`: Two source CUDA studies used frozen, disjoint animal and recording declarations. The five-group study scored all 240 coordinates, seven complete reference events and 120 common frames. The two-group study retained the unsupported anatomical frames and unavailable event timing. — `docs/REEFVISION_1_3_HELDOUT_AGREEMENT.md#five-held-out-synthetic-recordings` (`rv13-declared-disjoint-cuda`)
- `physical_hardware`: The 92e355b6a packaged RTX 3090 worker trained from scratch and scored 240 of 240 landmark positions and 120 of 120 shared anatomical frames on five separately generated held-out recording/animal groups. Mean errors were 5.575 and 4.006 px. Of seven complete reference events, frame missed seven with 15 extra. Temporal missed four with 18 extra. Independent animal labels and field acceptance remain open. — `https://github.com/Rafael-Del-Valle/ReefVision/pull/92#issuecomment-7032104053` (`rv13-packaged-frozen-five`)
- `physical_hardware`: Engineering evidence on five independent generated groups in the official 1.5 package. All 240 coordinates were scored. Mean frame-only and refined errors were 5.575 and 4.006 px. Against seven synthetic events, frame-only missed seven and added fifteen. The refined model missed four and added eighteen. Representative independent labels and thresholds remain open. — `docs/REEFVISION_1.5.0_REPORT.md` (`rv13-representative-temporal-comparison-physical-3c8e2d070`)
- `physical_hardware`: The native RTX 3090 fixture used separate development and held-out groups. Across five test recordings, 120 frames and 240 coordinates, frame-only and temporal mean errors were 5.575 and 4.006 source pixels. Matched events rose from 0 to 3 of seven, missed events fell from 7 to 4 and extra events rose from 15 to 18. Independent field acceptance remains open. — `docs/validation/windows-workflows-83b0a98b2.json` (`rv13-representative-temporal-comparison-physical-83b0`)
- `representative_data`: none recorded

### rv13-study-assignments: Reviewed study, treatment, site, tank, and sampling-unit assignments

- Target: `1.3`
- Status: `verified`
- Dependencies: `rv12-experimental-unit-safeguards`
- Entry point: Research → Organisms & ecology → Study assignments
- Workflow Builder: `required`

Acceptance checks:

- **verified** — Review and freeze study assignments with explicit unit nesting and preserve them through exchange. (`rv13-study-assignments-check`)

Evidence:

- `source`: Validated 1.3 assignment revision tests at SHA f44053a9. — `https://github.com/Rafael-Del-Valle/ReefVision/pull/87` (`rv13-study-src`)
- `browser`: none recorded
- `windows_installed`: none recorded
- `physical_hardware`: none recorded
- `representative_data`: none recorded

### rv13-temporal-dataset-training: Frozen temporal ReefPose datasets and checkpoint training

- Target: `1.3`
- Status: `verified`
- Dependencies: `rv12-organism-identity`, `rv13-acquisition-qc`
- Entry point: Models & AI → Training → Temporal ReefPose
- Workflow Builder: `required`

Acceptance checks:

- **verified** — Freeze leakage-aware sequences, train a causal or centered temporal model, and register checkpoint/data/config hashes. (`rv13-temporal-dataset-training-check`)

Evidence:

- `source`: Sequence grouping, causal isolation, training, checkpoint reload, cancel/resume tests. — `https://github.com/Rafael-Del-Valle/ReefVision/pull/87` (`rv13-temporal-train-src`)
- `browser`: none recorded
- `windows_installed`: none recorded
- `physical_hardware`: On the official Windows 1b0f29cff package, two real training jobs on the RTX 3090 registered the same immutable checkpoint. Project Exchange recovered both training histories, their metrics, the original producing run and the identical checkpoint bytes. — `docs/REEFVISION_1.4.0_REPORT.md#official-windows-build-and-recovery-at-1b0f29cff` (`rv13-packaged-repeat-exchange`)
- `physical_hardware`: The official 1.5 Windows sidecar trained and registered native frame and temporal checkpoints on a physical RTX 3090 using disjoint generated recording groups. The native Temporal panel then ran a 24-frame causal refinement with zero future-frame use. Physical receipt SHA-256 9539c37a38e7c3a486bfd3503c5d2c1647783869a0ce8ae74059ad61cbd4f637. — `docs/REEFVISION_1.5.0_REPORT.md` (`rv13-temporal-dataset-training-physical-3c8e2d070`)
- `representative_data`: none recorded

### rv13-temporal-refinement-review: Temporal ReefPose refinement and explicit frame review

- Target: `1.3`
- Status: `verified`
- Dependencies: `rv13-temporal-dataset-training`
- Entry point: Video & automation → Video & tracking → Native temporal ReefPose
- Workflow Builder: `required`

Acceptance checks:

- **verified** — Run chunk-consistent refinement, compare source-pixel landmarks, and explicitly accept, correct, or reject frames. (`rv13-temporal-refinement-review-check`)

Evidence:

- `source`: Refinement, boundary context, identity/revision staleness, and review tests. — `https://github.com/Rafael-Del-Valle/ReefVision/pull/87` (`rv13-refine-src`)
- `browser`: none recorded
- `windows_installed`: Installed 1.2 to 1.3 temporal workflow acceptance. — `https://github.com/Rafael-Del-Valle/ReefVision/pull/87` (`rv13-refine-win`)
- `physical_hardware`: none recorded
- `representative_data`: none recorded

### rv14-3d-organism-matching: Reviewed 3D organism matching across acquisitions

- Target: `1.4`
- Status: `blocked`
- Dependencies: `rv12-organism-identity`, `rv14-registration-transforms`
- Entry point: 3D scientific task → Organism correspondence
- Workflow Builder: `required`
- Missing input: Representative repeated 3D acquisitions with independently labeled specimen identities, authorized observer/reviewer/adjudicator roles, an ambiguity protocol, and preregistered false-match and missed-match thresholds.

Acceptance checks:

- **blocked** — Review accepted, rejected, disputed, and unresolved specimen correspondences before longitudinal comparison. (`rv14-3d-organism-matching-check`)
- **verified** — Record provisional identity review against dated project originals. A disputed match withholds change and reopening preserves the supplied decision and both source digests. (`rv14-correspondence-project-replay-check`)

Evidence:

- `source`: Synthetic correspondence tests bind project, specimen, observations, times, original assets, source bytes and parsed geometry; they enforce independent reviewers, chronology, and supporting/disputing/inconclusive outcomes. — `apps/api/reefvision/tests/test_spatial_mesh_reidentification_geometry_binding_v14.py` (`rv14-matching-binding-source`)
- `browser`: Record provisional identity review against dated project originals. A disputed match withholds change and reopening preserves the supplied decision and both source digests. — `apps/web/tests/e2e/project-spatial-comparison-live.spec.ts` (`rv14-correspondence-project-replay`)
- `browser`: Workflow Builder exposes observation-pair evidence, method, observer, accepted/rejected/disputed/unresolved outcomes, and separate independent-review attribution. — `apps/web/src/features/workflow-graphs/ScientificNodeControls.test.tsx` (`rv14-matching-guided-ui`)
- `windows_installed`: none recorded
- `physical_hardware`: none recorded
- `representative_data`: none recorded

### rv14-anatomical-branch-length: Anatomical coral branch-length measurement

- Target: `1.4`
- Status: `blocked`
- Dependencies: `rv14-geometric-measurements`
- Entry point: Home → project → Video & automation → Workflow builder → select project mesh → Anatomical branch length
- Workflow Builder: `required`
- Missing input: An approved anatomical endpoint/centerline rubric, independently measured reference branches with scale evidence, repeatability study, preregistered error thresholds, and authorized adjudicator.

Acceptance checks:

- **blocked** — Apply a declared endpoint/centerline method and meet independent reference and repeatability thresholds before using the anatomical label. (`rv14-anatomical-branch-length-check`)
- **verified** — Validate and replay a source-bound investigator-declared centerline, with named endpoints, ordered coordinates, operator, reference length and repeatability evidence. Report provisional length and scale-only uncertainty. (`rv14-centerline-project-engineering-check`)

Evidence:

- `source`: Validate and replay a source-bound investigator-declared centerline, with named endpoints, ordered coordinates, operator, reference length and repeatability evidence. Report provisional length and scale-only uncertainty. — `apps/api/reefvision/tests/test_spatial_anatomical_branch_v14.py` (`rv14-centerline-project-source`)
- `browser`: Validate and replay a source-bound investigator-declared centerline, with named endpoints, ordered coordinates, operator, reference length and repeatability evidence. Report provisional length and scale-only uncertainty. — `apps/web/tests/e2e/anatomical-branch-live.spec.ts` (`rv14-centerline-project-browser`)
- `windows_installed`: none recorded
- `physical_hardware`: none recorded
- `representative_data`: none recorded

### rv14-biological-condition: Reviewed biological-condition measurements

- Target: `1.4`
- Status: `blocked`
- Dependencies: `rv14-versioned-spatial-assets`, `rv13-study-assignments`
- Entry point: Home → project → Video & automation → Workflow builder → select project original → Condition review
- Workflow Builder: `required`
- Missing input: An approved biological-condition rubric and observation unit, representative labeled specimens, independent reviewer authority, disagreement/adjudication rule, and preregistered reliability/accuracy thresholds.

Acceptance checks:

- **blocked** — Record condition against a versioned biological rubric with source evidence, independent review, disagreement/adjudication, revision, uncertainty, and export/replay. (`rv14-biological-condition-check`)
- **verified** — Record an observation under a frozen, investigator-supplied rubric, attribute disagreement and adjudication, reopen the original, and export a report with its revision history and stated uncertainty. (`rv14-condition-project-engineering-check`)
- **verified** — Restore multiple frozen rubric versions, verify historical workflow reports against the observation ledger and their producing nodes, and preserve original revision identities across two exchanges. (`rv14-condition-exchange-ledger-check`)

Evidence:

- `source`: Record an observation under a frozen, investigator-supplied rubric, attribute disagreement and adjudication, reopen the original, and export a report with its revision history and stated uncertainty. — `apps/api/reefvision/tests/test_spatial_condition_v14.py` (`rv14-condition-project-source`)
- `source`: Restore multiple frozen rubric versions, verify historical workflow reports against the observation ledger and their producing nodes, and preserve original revision identities across two exchanges. — `apps/api/reefvision/tests/test_spatial_condition_v14.py` (`rv14-condition-exchange-ledger`)
- `browser`: Record an observation under a frozen, investigator-supplied rubric, attribute disagreement and adjudication, reopen the original, and export a report with its revision history and stated uncertainty. — `apps/web/tests/e2e/spatial-condition-live.spec.ts` (`rv14-condition-project-browser`)
- `windows_installed`: none recorded
- `physical_hardware`: none recorded
- `representative_data`: none recorded

### rv14-geometric-measurements: Reviewed extents, dimensions, area, surface paths, and conditional volume

- Target: `1.4`
- Status: `verified`
- Dependencies: `rv14-versioned-spatial-assets`
- Entry point: 3D scientific task → Measurements
- Workflow Builder: `required`

Acceptance checks:

- **verified** — Match known geometry and scale exponents, report topology/QC/uncertainty, and withhold invalid area or volume claims. (`rv14-geometric-measurements-check`)
- **verified** — Keep exact planar zero distinct from a true positive volume below source-unit precision. Preserve a representable calibrated volume and give an actionable failure when calibration cannot recover it in standalone and saved workflows. (`rv14-mesh-coplanar-scale-recovery`)

Evidence:

- `source`: Deterministic mesh fixtures cover calibrated scale exponents, extents, surface area, topology, conditional enclosed volume, uncertainty intervals, paths, numerical integrity, and explicit withhold reasons. — `apps/api/reefvision/tests/test_spatial_mesh_primitives_v14.py` (`rv14-geometric-known-fixtures`)
- `source`: Calibration review and source bindings reject stale, mismatched, self-reviewed, or altered measurement evidence while preserving unverified status. — `apps/api/reefvision/tests/test_spatial_mesh_calibration_review_v14.py` (`rv14-geometric-review-binding`)
- `source`: A noncollinear triangle whose area underflows is rejected by the standalone API and saved graph. A representable reference of 5e-201 is reproduced using zero absolute tolerance, and two saved executions retain the same scientific payload digest. — `apps/api/reefvision/tests/test_spatial_mesh_area_underflow_v14.py` (`rv14-mesh-area-representability`)
- `source`: The previous desktop returned zero for a closed nearly planar tetrahedron with nonzero volume within the floating-point range. Both windings now agree with an independent exact rational oracle, the exactly planar control remains zero, and standalone plus two saved workflow runs preserve the provisional measure and its source. — `apps/api/reefvision/tests/test_spatial_mesh_enclosed_volume_v14.py` (`rv14-geometric-measurements-recover-volume-cancellation`)
- `source`: The project API regression imports the tiny closed OBJ, verifies its structural receipt and original, rejects a still-unrepresentable unit-scale measurement and returns the independently calculated positive value at scale 1,000,000. Forty-nine focused backend cases passed. — `https://github.com/Rafael-Del-Valle/ReefVision/blob/1d3942662ba2c4a75c30c59acf37851be51ce3e1/apps/api/reefvision/tests/test_spatial_asset_parse_jobs_v14.py` (`rv14-geometry-import-and-calibration-1d3942662`)
- `source`: The signed volume matched 448 independently evaluated tetrahedral permutations and a bounded 3,996-face bipyramid. The source fixture covers four vertex origins, both windings, exact planar zero, calibrated recovery of a positive source underflow and a true overflow. — `docs/validation/mesh-volume-8821ed9a1.json` (`rv14-volume-winding-rational-8821`)
- `browser`: Workflow Builder exposes a project-owned original picker, scale, calibration evidence, uncertainty, specimen/observation/frame context, and an explicit warning that geometric routes are not anatomical branch lengths. — `apps/web/src/features/workflow-graphs/ScientificNodeControls.test.tsx` (`rv14-geometric-guided-ui`)
- `browser`: The ordinary source desktop imported all three generated OBJs, exercised four calibrated previews, reopened both saved graphs, repeated each and downloaded the Exchange package. All three originals and six typed artifacts verified against the source-browser receipt with SHA-256 c46681c4df9075abb7bbdb17c228b05107fce72174eb236c16255428542ef388. — `docs/REEFVISION_1.5.0_REPORT.md` (`rv14-geometry-project-replay-1d3942662`)
- `browser`: From the project's 3D assets, the researcher imported the same OBJ, measured both windings, supplied scale uncertainty, reopened the graph, ran it twice and downloaded the project. Both measurements now match the exact volume, the planar control withholds volume, and the exports preserve the three originals and six saved artifacts. — `docs/validation/mesh-volume-8821ed9a1.json` (`rv14-volume-winding-guided-8821`)
- `windows_installed`: The shipped #96 sidecar and two saved runs reported 170.66666666666666 cubic metres for four exactly coplanar source vertices at the supported scale of 999,998.1 metres per unit. Both downloaded artifacts had SHA-256 c4c7af4515773c08a00abc067dee820fe78eb53e80db7722cc719f6ff732351b. — `https://github.com/Rafael-Del-Valle/ReefVision/pull/96` (`rv14-mesh-coplanar-calibration-3c8e2d070`)
- `windows_installed`: On the physical Windows host, the MSI-extracted desktop and sidecar reproduced the four previews and both saved graphs. The locally built MSI had SHA-256 5d1f9def34983f23b1d0755a0df549d2cb44148f52b21a0d77a85cc686cc59c7. Its exported ZIP contained 63 verified sections, three originals and six result artifacts, and retained both controlled failures without measurement artifacts. — `docs/validation/spatial-calibration-1d3942662.json` (`rv14-geometry-package-replay-1d3942662`)
- `windows_installed`: The original b846f57e9 sidecar passed eight standalone enclosure cases and sixteen saved runs. Both polygon windings recovered 1.6666666667e-313 cubic metres after calibration with identical export hashes. Positive source volumes still below representability returned a controlled failure and exact planar controls remained zero. Both new donor regressions passed on the integrated source. — `https://github.com/Rafael-Del-Valle/ReefVision/pull/97` (`rv14-positive-volume-recovery-1787cd57c-on-b846f57e9`)
- `physical_hardware`: In the packaged 1.5 WebView2, both OBJ windings and a double-precision PLY yielded 3.7007434154171883e-9 cubic metres at fixture scale. The planar control withheld the value. An actual reopen reproduced all four artifact checksums. Physical receipt SHA-256 91cc3210fe28a508a20cea48fb60ffdb988648389071357938184997870c54b7. — `https://github.com/Rafael-Del-Valle/ReefVision/pull/96` (`rv14-physical-volume-3c8e2d070`)
- `physical_hardware`: The corrected local MSI's native Windows desktop reproduced the calibrated mesh result through both saved runs and retained the original files in Project Exchange. — `docs/validation/mesh-volume-8821ed9a1.json` (`rv14-volume-winding-local-msi-8821`)
- `physical_hardware`: The original GitHub MSI reproduced the corrected finite volume, scale bounds, planar control and saved replay on physical Windows. Its matching cabinet and executable identities were verified before opening the project. — `docs/validation/mesh-volume-8821ed9a1.json` (`rv14-volume-winding-original-msi-8821`)
- `representative_data`: none recorded

### rv14-lineage-upgrade: Validated 1.3 to 1.4 ancestry, migration, exchange, and rollback

- Target: `1.4`
- Status: `blocked`
- Dependencies: `rv13-exchange-restore`, `rv14-versioned-spatial-assets`
- Entry point: Installed upgrade and Project menu → Backup / Exchange
- Workflow Builder: `not_applicable`
- Missing input: Representative validated-1.3 and legacy draft-1.4 Windows data profiles, including a verified pre-upgrade backup for each, that can be upgraded by the final-candidate installer and exercised through Project Exchange and rollback/restore.

Acceptance checks:

- **verified** — Merge validated 1.3 without editing applied migration bodies, disambiguate both supported numeric histories from schema fingerprints, preserve rows and IDs, and reject ambiguous or unknown histories without mutation. (`rv14-lineage-source-check`)
- **blocked** — Using an installer built from the final candidate SHA, upgrade representative 1.3 and legacy draft-1.4 profiles, exchange the integrated records, and restore a verified pre-upgrade backup. (`rv14-lineage-installed-check`)
- **verified** — Run the exact candidate installer against deterministic 1.3, legacy 0038, and legacy 0039 fixtures, preserve the seeded evidence, round-trip Project Exchange, and restore verified backups. Confirm that the genuine historical 1.3 installer rejects the upgraded database without changing it. (`rv14-lineage-installed-synthetic-check`)
- **verified** — Restore a verified backup created by the accepted 1.3 executable through the production frozen 1.4 sidecar. Reopen a separate copy with the old executable and reject checksum-valid backups with unknown or future schemas. (`rv14-packaged-restore-resources`)

Evidence:

- `source`: Real ancestry merge, unique Alembic graph, schema-fingerprinted legacy upgrades, ambiguity rejection, backup verification, and downgrade/upgrade regressions. — `docs/roadmap/REEFVISION_1_4_MIGRATION_RECONCILIATION.md` (`rv14-lineage-source`)
- `source`: Locally built production Windows sidecar 63fd94bfc restored a checksum-authenticated f44053a90 backup. All inventory bytes matched, the exact old executable reopened the recovery and accepted a write, and two unsupported backups returned HTTP 409 before creating a destination. — `docs/roadmap/REEFVISION_1_4_MIGRATION_RECONCILIATION.md#packaged-backup-recovery-on-a-disposable-copy` (`rv14-frozen-restore-real`)
- `source`: A copied generated 1.4 profile preserved classes, geometry, units, review events, both actual local weights, seven files and both project snapshots through the 1.5 source migrator. The original physical 1.4 app reopened a restored database byte-identical to its backup. — `docs/REEFVISION_1.5.0_REPORT.md` (`rv14-lineage-upgrade-rich-14-to-15-restore`)
- `source`: Twenty-five focused backup and recovery checks passed across two runs on the integrated source. Six real worker exits covered partial copies, publication, cancellation, changed output or another job's receipt. The same job verifies all published content before recording success. — `https://github.com/Rafael-Del-Valle/ReefVision/commit/1776cd4ad7b54ca03fedaf892db0e064230c4b76` (`rv14-restore-restart-worker-b846f57e9`)
- `browser`: From System status, create a managed backup, verify it, restore into a new folder, then read the independent SQLite copy and compare IDs, annotations, original bytes and inventory digests. The native fixture passed on the 78a02c20c shell with the production-script fixed 63fd94bfc sidecar. — `apps/web/tests/e2e/backup-restore-live.spec.ts` (`rv14-system-restore-ui`)
- `windows_installed`: Exact-head source 36c80224a Windows acceptance passed a published 1.0.3 upgrade with schema migration, persistence, Project Exchange, uninstall, and data retention. This is partial evidence and does not substitute for representative 1.3 and legacy draft-1.4 profiles. — `https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/44072770396` (`rv14-lineage-win-103`)
- `windows_installed`: Exact-head source 36c80224a passed all three installed synthetic profiles. Verified 1.3 MSI upgrade, 0038 and 0039 profile migration, evidence preservation, exchange round trips, and backup restoration. The historical 1.3 build rejected the upgraded schema and the upgraded database hash remained unchanged. — `https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/44072770396` (`rv14-lineage-win-synthetic`)
- `windows_installed`: Installed candidate 72254d9a0 passed the published 1.0.3 upgrade, both historical numeric profile fixtures, and rollback using the genuine f44053a90 1.3 installer. The old reader preserved the upgraded database digest and reopened its separately restored pre-upgrade backup. The richer 1.3 fixture also showed that the packaged product Restore action still required the later resource-path fix. — `https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/44677664711` (`rv14-exact-87-installed`)
- `windows_installed`: The local MSI built from 92e355b6a restored a verified backup created by the accepted f44053a90 executable through the production Restore action. IDs, source bytes, scientific records and checkpoint survived upgrade and Project Exchange. The old executable refused the newer database unchanged and wrote successfully in the recovered 1.3 profile. The material was a generated fixture. — `https://github.com/Rafael-Del-Valle/ReefVision/pull/92#issuecomment-7032104053` (`rv14-rich-87-restore`)
- `windows_installed`: On a disposable profile, the official 1b0f29cff sidecar migrated the accepted 1.3 fixture, exchanged its reviewed data and model hash, and returned HTTP 200 for managed restore. The original 1.3 binary preserved the upgraded database on refusal and wrote successfully after recovery. All five authenticated backup entries were rehashed. — `docs/REEFVISION_1.4.0_REPORT.md#official-windows-build-and-recovery-at-1b0f29cff` (`rv14-official-f440-rich-restore`)
- `windows_installed`: The official 1b0f29cff six-CAB MSI passed ten GUI journeys and all fourteen exercised install, restart, Exchange, uninstall and retention stages using its ordinary Windows profile. Byte-verified native downloads succeeded with the default inspector open. The four predecessor upgrades passed separately. Representative prior-user profiles remain open. — `https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/44693974894` (`rv14-ordinary-profile-installed-ten`)
- `windows_installed`: Official 1.4 MSI plus six cabinets. Clean install, backup recovery and four supported upgrades passed on disposable generated profiles. — `https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/44697377337` (`rv14-lineage-upgrade-msi-fb2276c87`)
- `windows_installed`: The 1.5 MSI passed clean installation, upgrades from published 1.0.3 and validated 1.4 and 1.3, and both historical 1.4 draft schema fixtures. A separately restored verified backup reopened in the older application. A generated two-project fixture on the physical host preserved both checkpoints and all seven project files. — `https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/44722744547` (`rv14-windows-lineage-3c8e2d070`)
- `windows_installed`: The 9645531ea local MSI sidecar restored the verified 3c8e2d070 backup using the normal Backup API. All 312 files matched. Eight reopened projects retained 41 data fingerprints, 52 images, two videos and five available registered checkpoints. SQLite remained byte-identical, SHA-256 1819e2e76f3735c51adb34498475fea101908e199425dc8e61db8fd630f95d61. — `https://github.com/Rafael-Del-Valle/ReefVision/pull/96` (`rv14-restore-eight-projects-9645531ea`)
- `windows_installed`: Two historical revisions independently recorded 0038. The 1.5 package preserved the generated 68 degrees Fahrenheit observation, original uncertainty, normalized units and calibration from science commit e1cd11d38. It refused QC revision d4dc3a3aa before opening an API port and preserved all three audit events and the original database bytes. — `https://github.com/Rafael-Del-Valle/ReefVision/pull/96` (`rv14-historical-science-qc-controls-3c8e2d070`)
- `physical_hardware`: The locally built 54756d0cf MSI on Windows 11 with long paths disabled restored 398 and 400 files from consecutive backups and retained a 286-character path and its original SHA-256. An earlier archive restored all 794 members, including its 397 nested recovery members. Local MSI SHA-256 af597ff725585c098957c47c25989e6c0fbb06225d0a17cfdd4ad01ac0dfdfca. — `https://github.com/Rafael-Del-Valle/ReefVision/pull/97` (`rv14-restore-long-cycle-54756d0cf`)
- `physical_hardware`: On the b846f57e9 MSI-extracted Windows sidecar, stopping the worker with 31 staged files left the destination unpublished. Restart resumed the same job, verified all 395 files and 107,232,142 bytes, removed its stage and preserved a separately owned stage. A second interrupted job with a persisted cancellation finished cancelled with no published target. Local MSI SHA-256 ac85ed3b5168e47405a5ac3af6342e4e47cf3c908d7e6fd573529ced26a4af4b. — `https://github.com/Rafael-Del-Valle/ReefVision/pull/97` (`rv14-packaged-restore-replay-b846f57e9`)
- `physical_hardware`: The original 1.5 MSI restored 398 then 400 files in two physical desktop cycles. An independently interrupted 395-file restore resumed the same job, matched all file hashes, and preserved its original archive and unrelated staging data. — `https://github.com/Rafael-Del-Valle/ReefVision/pull/97` (`rv14-restore-original-msi-restart-b846f57e9`)
- `representative_data`: none recorded

### rv14-longitudinal-3d-change: Reviewed longitudinal 3D change

- Target: `1.4`
- Status: `blocked`
- Dependencies: `rv14-geometric-measurements`, `rv14-3d-organism-matching`
- Entry point: 3D scientific task → Longitudinal comparison
- Workflow Builder: `required`
- Missing input: The representative paired acquisitions, independent registration controls, independently labeled organism correspondences, authorized review/adjudication roles, and preregistered longitudinal error and repeatability thresholds required by the two blocked dependencies.

Acceptance checks:

- **blocked** — Report change only for reviewed correspondence, compatible frames/units, and pinned measurement revisions with propagated uncertainty. (`rv14-longitudinal-3d-change-check`)
- **verified** — Enter from Home, import two dated project meshes, compare calibrated geometry, review, save, reopen, run the identical revision twice and export the result with matching source and artifact hashes. (`rv14-longitudinal-project-replay-check`)
- **verified** — Exchange two acquired meshes, reopen the original comparison and its original receipt, then rerun the saved graph under the restored asset identities with identical measured change and original byte hashes. (`rv14-longitudinal-exchange-receipt-check`)

Evidence:

- `source`: Deterministic comparisons enforce observation chronology, source and calibration fingerprints, frame and registration evidence, specimen correspondence, conservative scale-uncertainty intervals, topology QC, and stale review-bundle rejection. — `apps/api/reefvision/tests/test_spatial_mesh_longitudinal_v14.py` (`rv14-longitudinal-source`)
- `source`: Exchange two acquired meshes, reopen the original comparison and its original receipt, then rerun the saved graph under the restored asset identities with identical measured change and original byte hashes. — `apps/api/reefvision/tests/test_spatial_mesh_workflow_exchange_v14.py` (`rv14-longitudinal-exchange-receipt`)
- `browser`: Enter from Home, import two dated project meshes, compare calibrated geometry, review, save, reopen, run the identical revision twice and export the result with matching source and artifact hashes. — `apps/web/tests/e2e/project-spatial-comparison-live.spec.ts` (`rv14-longitudinal-project-replay`)
- `browser`: Saved Workflow Builder graphs provide contextual registration and organism-correspondence controls while preserving exact transforms, hashes, times and uncertainty in the same node's advanced controls. — `apps/web/src/features/workflow-graphs/ScientificNodeControls.test.tsx` (`rv14-longitudinal-guided-ui`)
- `windows_installed`: none recorded
- `physical_hardware`: none recorded
- `representative_data`: none recorded

### rv14-registration-transforms: Reviewed 3D registration transforms and calibration evidence

- Target: `1.4`
- Status: `blocked`
- Dependencies: `rv14-versioned-spatial-assets`
- Entry point: 3D scientific task → Registration review
- Workflow Builder: `required`
- Missing input: Representative paired 3D acquisitions with independently measured control correspondences and scale evidence, an authorized independent registration reviewer/adjudicator, and preregistered residual and alignment-error thresholds.

Acceptance checks:

- **blocked** — Review transform direction, frame, units, residuals, correspondences, uncertainty, and reject stale or incompatible evidence. (`rv14-registration-transforms-check`)
- **verified** — Save both dated surveys, their source hashes, measured registration residual, correspondence count and local review in a graph and export the resulting evidence on replay. (`rv14-registration-project-replay-check`)

Evidence:

- `source`: Synthetic registration tests validate rigid source-to-target transforms, residual and correspondence metadata, calibration/source/geometry bindings, review independence and chronology, uncertainty bounds, and stale-evidence rejection. — `apps/api/reefvision/tests/test_spatial_mesh_registration_geometry_binding_v14.py` (`rv14-registration-binding-source`)
- `browser`: Save both dated surveys, their source hashes, measured registration residual, correspondence count and local review in a graph and export the resulting evidence on replay. — `apps/web/tests/e2e/spatial-guided-workflow-live.spec.ts` (`rv14-registration-project-replay`)
- `browser`: Workflow Builder exposes frames, method, residual, correspondence count, evidence note, and accepted/rejected/disputed/unresolved review states with separate operator and reviewer attribution. — `apps/web/src/features/workflow-graphs/ScientificNodeControls.test.tsx` (`rv14-registration-guided-ui`)
- `browser`: Enter an exact 4 × 4 source-to-target matrix and three meter error bounds from the selected project mesh. A 90-degree rotation plus translation gave provisional centroid separation 0.266796843 m with caller bounds 0.166796843–0.366796843 m. An incomplete matrix blocked preview and a nonrigid matrix returned 422. Two saved runs matched the standalone artifact and Exchange preserved the original receipt. — `apps/web/tests/e2e/project-spatial-comparison-live.spec.ts` (`rv14-registration-project-rigid`)
- `windows_installed`: none recorded
- `physical_hardware`: none recorded
- `representative_data`: none recorded

### rv14-representative-spatial-validation: Representative 3D field validation

- Target: `1.4`
- Status: `blocked`
- Dependencies: `rv14-longitudinal-3d-change`, `rv14-anatomical-branch-length`, `rv14-biological-condition`
- Entry point: Not user-facing
- Workflow Builder: `not_applicable`
- Missing input: An authorized representative scan corpus (OBJ/PLY/GLB and point clouds) with acquisition envelopes, source/reference measurements, repeat specimens, condition labels, reviewer authority, target Windows/GPU configurations, and public or redacted evidence destinations.

Acceptance checks:

- **blocked** — Validate supported formats/sizes, geometry, matching, longitudinal change, branch length, and condition on independently reviewed specimens and installed Windows hardware. (`rv14-representative-spatial-validation-check`)

Evidence:

- `source`: none recorded
- `browser`: none recorded
- `windows_installed`: none recorded
- `physical_hardware`: none recorded
- `representative_data`: none recorded

### rv14-smart-app-control-compatibility: Windows 11 Smart App Control compatibility

- Target: `1.4`
- Status: `blocked`
- Dependencies: None
- Entry point: Not user-facing
- Workflow Builder: `not_applicable`
- Missing input: A suitable disposable Windows 11 device with Smart App Control enforcement enabled and the exact final-candidate installer. The available physical host runs Windows 11 build 26300 with VerifiedAndReputablePolicyState=0 (off). Enforcement evidence requires launching the verified MSI and app on an enforcing device and recording the signature and Code Integrity event if blocked.

Acceptance checks:

- **blocked** — On a suitable disposable Windows 11 device with Smart App Control enforcement enabled, launch the exact final-candidate installer and installed application; if enforcement blocks launch, inspect Code Integrity event 3077 and record the blocked file and signature status. (`rv14-smart-app-control-compatibility-check`)

Evidence:

- `source`: none recorded
- `browser`: none recorded
- `windows_installed`: none recorded
- `physical_hardware`: Windows 11 build 26300 reported VerifiedAndReputablePolicyState 0, off. The exact MSI c6e92040617eb055c4ee62afcca86af709ebe73d02602165d474e1259582e05e, desktop executable and sidecar were unsigned. Enforcement acceptance requires a machine with that policy enabled. — `https://github.com/Rafael-Del-Valle/ReefVision/pull/96` (`rv14-policy-3c8e2d070`)
- `physical_hardware`: The physical Windows 11 host reported Smart App Control off. The original candidate MSI, desktop and sidecar were unsigned. Acceptance on a Windows 11 device enforcing Smart App Control remains open. — `https://github.com/Rafael-Del-Valle/ReefVision/pull/97` (`rv14-policy-original-msi-off-b846f57e9`)
- `representative_data`: none recorded

### rv14-spatial-preview: Bounded OBJ/PLY/GLB mesh and point-cloud preview

- Target: `1.4`
- Status: `verified`
- Dependencies: `rv13-exchange-restore`
- Entry point: Open project → Video & automation → Workflow builder → Project-owned 3D originals
- Workflow Builder: `required`

Acceptance checks:

- **verified** — Open supported bounded geometry through normal project navigation and preserve coordinate/unit warnings and preview limits. (`rv14-spatial-preview-check`)

Evidence:

- `source`: Focused spatial frontend suite covers bounded local and project-owned mesh/point-cloud previews, source validation, and warnings (46 tests). — `apps/web/src/features/workflow-graphs` (`rv14-spatial-preview-src`)
- `browser`: Application-shell acceptance opens a project, selects Video & automation then Workflow builder, finds Project-owned 3D originals and its import control, and confirms no new top-level 3D tab. — `apps/web/src/App.test.tsx` (`rv14-spatial-preview-ui`)
- `windows_installed`: Exact-SHA 1.4.0 installed acceptance passed and the packaged application was separately opened under an isolated profile through Home → project → Video & automation → Workflow builder → Project-owned 3D originals; mesh/point-cloud controls and scientific warnings were visible without a top-level 3D tab. — `https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/43792901192` (`rv14-spatial-preview-win`)
- `physical_hardware`: none recorded
- `representative_data`: none recorded

### rv14-versioned-spatial-assets: Persistent versioned 3D project assets

- Target: `1.4`
- Status: `verified`
- Dependencies: `rv14-spatial-preview`
- Entry point: Open project → Video & automation → Workflow builder → Project-owned 3D originals → Import 3D original
- Workflow Builder: `required`

Acceptance checks:

- **verified** — Import immutable source bytes, persist UUID/hash/units/frame/transform/calibration/review revisions, and exchange or reject tampered assets. (`rv14-versioned-spatial-assets-check`)

Evidence:

- `source`: Project-scoped immutable source bytes, UUID/SHA binding, path and metadata integrity, append-only calibration-review replay, malformed/empty/oversized rejection, and tamper rejection are covered by focused backend tests. — `apps/api/reefvision/tests/test_spatial_source_assets_v14.py` (`rv14-spatial-assets-src`)
- `source`: Additive b14_spatial_0040 stores append-only unit, frame, affine transform, calibration, local review, predecessor, source-hash, and integrity-hash metadata revisions while keeping authentication and verification flags false. — `apps/api/reefvision/tests/test_spatial_asset_metadata_revisions_v14.py` (`rv14-spatial-assets-metadata`)
- `source`: Every import queues a durable bounded structural parse job; valid mesh and point-cloud results remain explicitly uncalibrated/unreviewed, malformed and altered originals fail closed, duplicate imports deduplicate, and result hashes reject local or archive tampering. — `apps/api/reefvision/tests/test_spatial_asset_parse_jobs_v14.py` (`rv14-spatial-assets-parse`)
- `source`: Project Exchange round-trip remaps spatial source/review/metadata/parse UUIDs, restores verified original bytes, recomputes remapped evidence hashes, requires originals, and rejects altered bytes, review evidence, metadata evidence, or parse results. — `apps/api/reefvision/tests/test_spatial_asset_project_exchange_v14.py` (`rv14-spatial-assets-exchange`)
- `browser`: Normal project navigation exposes project-owned import, background structural parse status/QC, and append-only unit/frame metadata controls inside Workflow builder; focused UI tests exercise the path without a new top-level tab. — `apps/web/src/features/workflow-graphs/ProjectSpatialAssetPreview.test.tsx` (`rv14-spatial-assets-ui`)
- `windows_installed`: Exact-SHA disposable Windows clean-install and published 1.0.3-upgrade runs passed schema migration, project persistence/restart, Project Exchange, uninstall, and data retention for 1.4.0; packaged UI inspection separately confirmed project-owned import and metadata/preview controls. — `https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/43792901192` (`rv14-spatial-assets-win`)
- `physical_hardware`: none recorded
- `representative_data`: none recorded

### rv15-experimental-design: Study setup, treatments, sampling units, exclusions, and statistical plan

- Target: `1.5`
- Status: `blocked`
- Dependencies: `rv13-study-assignments`, `rv11-repeated-measures-analysis`
- Entry point: Research → Study design
- Workflow Builder: `required`
- Missing input: A prespecified representative study with independent units and calibrated repeated visits, allocation, sampling effort and independent statistical review.

Acceptance checks:

- **blocked** — Create and freeze a study design with nesting, repeated measures, exclusions, estimands, and analysis choices before reporting. Evaluate the design, units, exclusions and estimate on an independently prespecified representative study. (`rv15-experimental-design-check`)
- **verified** — Create and freeze the prospective design on generated repeated sampling units, reopen the assigned roster, and reproduce the saved analysis checksum twice. (`rv15-experimental-design-installed-fixture-workflow`)

Evidence:

- `source`: 15 integrated source tests covered freeze, original-growth recomputation, two successive Exchange copies, new revisions and tamper rejection. — `https://github.com/Rafael-Del-Valle/ReefVision/commit/2e22871795784f528c9ef27511d7cd93f9d01afb` (`rv15-experimental-design-design-exchange`)
- `browser`: Fixture roster and calibrated two-visit analysis frozen, reopened, exported and replayed twice. Receipt SHA-256 20a008c011cd3987e63588134af72e125867746f31a23a1f605e4b5a57aa0577. — `https://github.com/Rafael-Del-Valle/ReefVision/pull/95` (`rv15-experimental-design-design-replay`)
- `windows_installed`: Standard-user WebView2 on the clean Windows install from 3c8e2d070. The researcher froze a prospective roster, bound reviewed measures, reopened it and obtained matching saved runs. — `https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/44722744547/job/136258835916` (`rv15-experimental-design-installed-3c8e2d070`)
- `windows_installed`: The original 1.5 MSI opened Research in a fresh standard-user WebView2 session. The generated repeated-unit study was saved, reopened and replayed with its frozen roster and exclusions. — `https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/44748544977/job/136346825319` (`rv15-study-clean-research-b846f57e9`)
- `physical_hardware`: none recorded
- `representative_data`: none recorded

### rv15-field-capture: Offline field capture and later project reconciliation

- Target: `1.5`
- Status: `blocked`
- Dependencies: `rv14-versioned-spatial-assets`, `rv13-acquisition-qc`
- Entry point: Project → Field capture
- Workflow Builder: `required`
- Missing input: Authorized original field image/video and companion field log with a documented device clock or unknown clock state, source identity, duplicate and conflict for independent comparison. Use Data & annotation → Field capture.

Acceptance checks:

- **verified** — Capture media/metadata offline, preserve clocks/source hashes, reconcile duplicates, and retain conflicts for review. (`rv15-field-capture-check`)
- **blocked** — Reconcile an authorized real offline acquisition batch against its independent field log and clock basis. (`rv15-field-capture-field-acceptance`)

Evidence:

- `source`: PNG/MP4 bytes, known and unknown clocks, reviewed conflicts, canonical media and the original report checksum survived two project copies. — `https://github.com/Rafael-Del-Valle/ReefVision/commit/d3ef97c768e41c9c6b910da90af0fea6308cce3a` (`rv15-field-capture-field-exchange`)
- `browser`: Project Field capture imported, reconciled and replayed a transferred batch twice. Receipt SHA-256 17280d51612a426c43902079c0e72db3637514765d87b31b05b83c8012ee341b. — `https://github.com/Rafael-Del-Valle/ReefVision/pull/95` (`rv15-field-capture-field-replay`)
- `windows_installed`: Standard-user WebView2 on the clean Windows install from 3c8e2d070. The researcher imported offline PNG/MP4 fixtures, retained clock uncertainty and a conflict decision, then replayed the reconciled batch twice. — `https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/44722744547/job/136258835916` (`rv15-field-capture-installed-3c8e2d070`)
- `windows_installed`: The installed Research journey imported generated local originals, recorded the field clock and reconciliation decision, and replayed the transferred batch. Independent field logs remain required. — `https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/44748544977/job/136346825319` (`rv15-field-clean-research-b846f57e9`)
- `physical_hardware`: The physical Windows desktop preserved the generated field batch after restore and replay, with signed report SHA-256 b83b00e9035c7dbdc4a98b0325ada2d8082d6d2daf2358c059a690e43f3f15ed. Official MSI SHA-256 c6e92040617eb055c4ee62afcca86af709ebe73d02602165d474e1259582e05e. — `https://github.com/Rafael-Del-Valle/ReefVision/pull/96` (`rv15-field-capture-physical-3c8e2d070`)
- `representative_data`: none recorded

### rv15-model-catalog-runtime: Local model catalog, runtime selection, and prompt-assisted configuration

- Target: `1.5`
- Status: `verified`
- Dependencies: `rv15-provider-foundations`
- Entry point: Models & AI → Model Hub
- Workflow Builder: `required`

Acceptance checks:

- **verified** — Select explicit local models/runtimes, retain hashes and compatibility, and treat generated configuration as reviewable input. (`rv15-model-catalog-runtime-check`)

Evidence:

- `source`: Saved selection pins bytes, class map, provider, runtime, device and effective settings. Queued jobs and graph replay reject changed weights. Two imports restored live class/model references. — `https://github.com/Rafael-Del-Valle/ReefVision/commit/886973882c5519c0975ba4e680b4fe910450d2a6` (`rv15-model-catalog-runtime-runtime-pin`)
- `source`: A marked early 1.5 model-review profile upgraded through the desktop migrator twice. Its record UUIDs, UTC timestamp, original signed snapshot and checkpoint SHA-256 survived. Database foreign-key checks found zero violations. A copy with unprovable source identity rolled back without changes. — `https://github.com/Rafael-Del-Valle/ReefVision/commit/ebce490b1e153fcdaf84c0b4c7c13721b12b7b6f` (`rv15-model-catalog-runtime-early-schema-recovery`)
- `source`: The earlier original signed runtime selection reopened with its exact digest through two project restorations. A separate current review was required to infer. Remapped project, model and classes were verified before execution. — `docs/REEFVISION_1.5.0_REPORT.md` (`rv15-model-catalog-runtime-legacy-model-review`)
- `browser`: Direct Model Hub inference and two Detection Inference graph runs matched the source-pixel boxes, labels and scores for all nine CPU and ten CUDA predictions to six decimals on independently trained fixture checkpoints. — `https://github.com/Rafael-Del-Valle/ReefVision/pull/95` (`rv15-model-catalog-runtime-direct-graph-replay`)
- `windows_installed`: Standard-user WebView2 on the clean Windows install from 3c8e2d070. The researcher inspected and approved a local runtime configuration, ran direct inference and repeated the selection in a saved graph. — `https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/44722744547/job/136258835916` (`rv15-model-catalog-runtime-installed-3c8e2d070`)
- `physical_hardware`: Packaged CUDA on the physical RTX 3090. Direct inference and two saved runs agreed on 9 proposals, with SHA-256 4428cc1865bc9b57380597ea920b021630cd0640dbca579c5db107d58b31e812. Official MSI SHA-256 c6e92040617eb055c4ee62afcca86af709ebe73d02602165d474e1259582e05e. — `https://github.com/Rafael-Del-Valle/ReefVision/pull/96` (`rv15-model-catalog-runtime-physical-3c8e2d070`)
- `physical_hardware`: The original installer payload opened Models on the physical RTX 3090. A reviewed locally trained detector completed direct inference and two saved graph runs, each with nine matched proposals. Both saved digests were b0dc4cea1b7b7cfaab2329547230f56107a9ee2c8224f79ff37c508730f52f48. — `https://github.com/Rafael-Del-Valle/ReefVision/pull/97` (`rv15-runtime-original-msi-rtx-b846f57e9`)
- `physical_hardware`: In the packaged Workflow Builder two saved CPU runs used the reviewed checkpoint and only the two frozen validation images, excluded four training images and returned the same 15 proposals with independent IDs. — `docs/validation/restored-projects-3a9ce1622.json` (`rv15-frozen-detector-runtime-3a9`)
- `representative_data`: none recorded

### rv15-model-comparison: Unified detector, mask, pose, tracking, and event comparison

- Target: `1.5`
- Status: `blocked`
- Dependencies: `rv12-human-model-counts`, `rv13-heldout-agreement`, `rv15-model-catalog-runtime`
- Entry point: Models & AI → Model comparison
- Workflow Builder: `required`
- Missing input: Independent reviewed stills and held-out animal recordings, compatible registered checkpoints, frozen groups and prespecified scoring thresholds.

Acceptance checks:

- **blocked** — Compare compatible models on the same immutable holdout with task-specific metrics, paired differences, exclusions, and disagreement navigation. Compare task-specific errors and exclusions with independent labels, compatible registered checkpoints and prespecified held-out scoring margins. (`rv15-model-comparison-check`)
- **verified** — Run compatible registered local models on frozen fixture groups, inspect disagreements from the normal desktop, replay the saved result twice and retain the paired report and exports. (`rv15-model-comparison-installed-fixture-workflow`)

Evidence:

- `source`: Two distinct CPU-trained checkpoints scored three untouched originals in two frozen groups. Fixture SHA-256 cdae9f6bcbfe7e78f29a547cc69f9e235970206bce9bb1c574035989c493b987. Source tests also cover instance and semantic masks. — `https://github.com/Rafael-Del-Valle/ReefVision/commit/6b762ff4ede777ef9a57ae8e630b6a9c692bfdbf` (`rv15-model-comparison-paired-stills`)
- `source`: Pose, tracking and event comparisons preserve held-out recording groups, prove checkpoint lineage, reject changed observations and retain comparable outcomes after Exchange. — `https://github.com/Rafael-Del-Valle/ReefVision/commit/fa3f3c4cd0ed6455eeb344a9bae8ca7c6f598bb2` (`rv15-model-comparison-paired-video`)
- `source`: Two successive native project imports preserved the scored comparisons and original source references across detector, mask, pose, tracking and event tasks. Modified source and mask content were rejected before importing. — `https://github.com/Rafael-Del-Valle/ReefVision/commit/deaf079f12d392f63ed70108c38e35fec6d23247` (`rv15-model-comparison-comparison-project-exchange`)
- `source`: A comparison authored by the 8155cc78a application retained its original score through two imports and four saved graph replays. Ambiguous or absent original output evidence kept the history readable and prevented verified package claims. — `docs/REEFVISION_1.5.0_REPORT.md` (`rv15-model-comparison-legacy-input-evidence`)
- `browser`: Models & AI compared two locally trained detectors on three originals in two frozen groups, exported both formats, reopened the differing original by hash and ran the saved comparison twice. The restored native evidence also covers recorded pose, tracking and event comparisons. — `https://github.com/Rafael-Del-Valle/ReefVision/commit/8155cc78a07081cdecc5bfd780aa713c8615b0d6` (`rv15-model-comparison-paired-disagreement-editor`)
- `browser`: In Chromium the project Model comparison workspace accepted both independently scored model reports, decoded the correct H.264 originals, and reopened a pose disagreement at frame 2 and an event disagreement in another video at 0.2 seconds. Both tested original hashes matched the frozen reference. — `docs/REEFVISION_1.5.0_REPORT.md` (`rv15-model-comparison-playable-video-seek`)
- `browser`: A real Chromium project compared two independently scratch-trained CPU segmentation models on six untouched images in two frozen groups. The models returned 12 and 46 polygons and missed all reference instances at the chosen match threshold. The direct report, exports and two saved runs retained the same result. — `docs/REEFVISION_1.5.0_REPORT.md` (`rv15-model-comparison-actual-instance-masks`)
- `windows_installed`: Standard-user WebView2 on the clean Windows install from 3c8e2d070. The researcher opened an original from the paired-group disagreement report, exported the results and repeated the saved comparison. — `https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/44722744547/job/136258835916` (`rv15-model-comparison-installed-3c8e2d070`)
- `windows_installed`: The original clean MSI compared two locally trained detectors on untouched held-out fixtures. The saved comparison ran twice in standard-user WebView2. Independent label and performance acceptance remains open. — `https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/44748544977/job/136346825319` (`rv15-paired-clean-research-b846f57e9`)
- `physical_hardware`: The packaged RTX 3090 ran both registered segmentation checkpoints on the same six held-out fixture images in two groups with twelve reference masks. Two saved executions reproduced artifact SHA-256 74edffb4568870ecee97e0a7401e8f55d04d50844ba8fa2c26686ba2619c7958. The redacted physical receipt has SHA-256 82a6f7a7ee1f6c39e37abac9f01cf2f8715193c9046ea189838dbf5fea04cc7e. — `https://github.com/Rafael-Del-Valle/ReefVision/pull/96` (`rv15-model-comparison-native-mask-pairs-3c8e2d070`)
- `physical_hardware`: On b846f57e9 a physical RTX 3090 ran three generated-fixture source checks with CUDA 12.1. Direct native ReefPose evaluation, a queued two-model comparison and offline training through registration and inference passed. The comparison report had SHA-256 965d4d6907496f326147a814e484356221575592304d6288f5da840dc57b11e4. — `https://github.com/Rafael-Del-Valle/ReefVision/pull/97` (`rv15-model-comparison-source-cuda-b846f57e9`)
- `representative_data`: none recorded

### rv15-provider-foundations: Early local provider and plugin foundations

- Target: `1.5`
- Status: `verified`
- Dependencies: `rv13-temporal-dataset-training`
- Entry point: Models & AI → Providers
- Workflow Builder: `required`

Acceptance checks:

- **verified** — Discover local provider manifests, expose capabilities/availability, isolate failures, and preserve unavailable provider records without executing unknown code. (`rv15-provider-foundations-check`)

Evidence:

- `source`: Strict inspect-only manifest discovery, API exposure, failure isolation, and metadata-only Workflow Builder snapshots passed the exact-head source gates. — `https://github.com/Rafael-Del-Valle/ReefVision/pull/88` (`rv15-provider-foundations-src`)
- `browser`: Home → open project → Models & AI → Providers passed component and Playwright acceptance; local manifests remain non-executable and unavailable records remain visible. — `https://github.com/Rafael-Del-Valle/ReefVision/pull/88` (`rv15-provider-foundations-ui`)
- `windows_installed`: Exact-head clean-install and published-1.0.3 upgrade runs discovered the seeded manifest with its source digest and returned blocked inspect-only preflight from the packaged API. — `https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/43843151701` (`rv15-provider-foundations-win`)
- `windows_installed`: The exact #96 installed sidecar discovered the local manifest with SHA-256 85039895db897e51178732d13c712d1a7e485bad54fbff5451025e6936c5fd27 and returned a blocked execution preflight for the inspect-only declaration. — `https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/44722744547/job/136258835916` (`rv15-provider-installed-3c8e2d070`)
- `physical_hardware`: none recorded
- `representative_data`: none recorded

### rv15-reproducibility-package: Complete research reproducibility package

- Target: `1.5`
- Status: `verified`
- Dependencies: `rv15-experimental-design`, `rv15-reviewer-lab`, `rv15-model-comparison`
- Entry point: Research → Export reproducibility package
- Workflow Builder: `required`

Acceptance checks:

- **verified** — Export methods, study/review/model identities, immutable inputs, environments, exclusions, results, and verification manifests; reject tampering on import. (`rv15-reproducibility-package-check`)

Evidence:

- `source`: Research export combines the frozen design, sealed independent review, paired model comparison, model hashes, methods, environment and exclusions with a native project archive. Tests cover repeated restore, weights and media omissions, aliased field originals, and rejection of inconsistent reports before import. — `https://github.com/Rafael-Del-Valle/ReefVision/commit/d126bff406518811490c4abdb177aa73d45c2c15` (`rv15-reproducibility-package-offline-research-archive`)
- `browser`: Six ordinary project journeys completed. The 64,711-byte Research ZIP contained none of the omitted checkpoint bytes in any of its 112 native archive members. Two original saved graph runs and a third after import returned the same payload SHA-256 fdfcb169edd1a8e6c67aaddcbb979e01470286afd53a07e2b8901bca62e9d84a. — `https://github.com/Rafael-Del-Valle/ReefVision/commit/74645f2dff3e369f9d05152e0b7841e0afc65f8d` (`rv15-reproducibility-package-download-inspect-reopen`)
- `browser`: The source desktop at b846f57e9 completed all six Research and ten preserved generated-fixture journeys on the first try. The package kept one original archive member. Two local saved runs and the restored graph produced the same SHA-256 60bacecfac281aeaf5aa2efdb6d7595864eabb0400d88054ee59dcf531836e0f. The restored project carried no reviewer credential. — `https://github.com/Rafael-Del-Valle/ReefVision/pull/97` (`rv15-research-package-restored-replay-b846f57e9`)
- `windows_installed`: Standard-user WebView2 on the clean Windows install from 3c8e2d070. The downloaded Research package bound design, role-attributed reviews and model results. Two saved runs and a restored run reproduced the proof. A shared original occupied one native archive member. — `https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/44722744547/job/136258835916` (`rv15-reproducibility-package-installed-3c8e2d070`)
- `windows_installed`: The original installed Research workspace exported and reimported a package containing the study, reviewer and model receipts. Its restored graph completed through the ordinary application. — `https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/44748544977/job/136346825319` (`rv15-package-clean-research-b846f57e9`)
- `physical_hardware`: none recorded
- `representative_data`: none recorded

### rv15-reviewer-lab: Reviewer roles, independent queues, adjudication, and agreement

- Target: `1.5`
- Status: `blocked`
- Dependencies: `rv13-acquisition-qc`
- Entry point: Review → Reviewer lab
- Workflow Builder: `required`
- Missing input: A frozen representative sample, task rubric, independent reviewers and adjudicator, and a prespecified agreement threshold.

Acceptance checks:

- **blocked** — Assign blinded reviews, preserve independent decisions, adjudicate disagreement, and export agreement with role/revision provenance. Measure agreement and adjudicated discrepancies on an independently labeled representative review set under a prespecified rubric. (`rv15-reviewer-lab-check`)
- **verified** — Assign two locally identified fixture reviewers, persist their blinded decisions, adjudicate disagreement with a separately authorized role and reproduce the sealed report twice. (`rv15-reviewer-lab-installed-fixture-workflow`)

Evidence:

- `source`: Separate reviewer roles submitted independent decisions, followed by attributed adjudication and an immutable agreement report. — `https://github.com/Rafael-Del-Valle/ReefVision/commit/ac87ce0aca0766686af72be34be6c3d71ee196ef` (`rv15-reviewer-lab-blinded-ledger`)
- `browser`: Two blinded fixture roles agreed on one of two images. Cohen's kappa was zero. Two saved replays preserved the sealed result. Receipt SHA-256 71f638f5ed0ddbf28c99b3292d55a8f8fc1b065c55b5fc6b54c4d59ce809f0ed. — `https://github.com/Rafael-Del-Valle/ReefVision/pull/95` (`rv15-reviewer-lab-role-replay`)
- `windows_installed`: Standard-user WebView2 on the clean Windows install from 3c8e2d070. The reviewer workspace retained independent signed decisions and adjudication, then reopened its agreement report. — `https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/44722744547/job/136258835916` (`rv15-reviewer-lab-installed-3c8e2d070`)
- `windows_installed`: The ordinary Research workspace assigned blinded observations on a generated sample, recorded disagreement and adjudication and replayed the sealed agreement on the original installer. — `https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/44748544977/job/136346825319` (`rv15-review-clean-research-b846f57e9`)
- `physical_hardware`: none recorded
- `representative_data`: none recorded

### rv16-class-management: Safe class management after use

- Target: `1.6`
- Status: `verified`
- Dependencies: `rv15-reproducibility-package`
- Entry point: Annotate → Classes
- Workflow Builder: `not_applicable`

Acceptance checks:

- **verified** — Rename, retire, reorder safely, and prevent silent class-index changes in annotations, datasets, checkpoints, and exports. (`rv16-class-management-check`)

Evidence:

- `source`: Thirty-five backend checks cover class use, archived classes, reassignment and protected historical records. — `docs/validation/research-workflows-1-6.json` (`rv16-class-safe-writes`)
- `browser`: Classes retained the frozen manifest and exported YOLO mapping after a reviewed reassignment and reopen. Polygon and image-level references prevented deletion. — `docs/validation/research-workflows-1-6.json` (`rv16-class-frozen-export`)
- `windows_installed`: On the original 1.6 MSI under an ordinary Windows account, the class lifecycle test passed. The researcher reviewed the reassignment, reopened the project and verified the earlier frozen export. — `https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/44768324452/job/136420579045` (`rv16-class-management-original-msi-used-classes`)
- `windows_installed`: The corrected original MSI passed the standard-user class lifecycle, including explicit reassignment after annotations exist and reopening the frozen export. — `docs/validation/installed-workflows-a580042e8.json` (`rv16-class-management-original-a580042e8`)
- `physical_hardware`: In native Classes, confirmed reassignment advanced the live annotation from revision 2 to 3. Mask and image-classification references remained protected. The frozen dataset manifest and YOLO mapping survived reopening. — `docs/validation/windows-workflows-83b0a98b2.json` (`rv16-class-management-physical-83b0`)
- `representative_data`: none recorded

### rv16-class-visibility-dense-editing: Class visibility, dense annotation editing, and large-gallery performance

- Target: `1.6`
- Status: `verified`
- Dependencies: `rv16-class-management`
- Entry point: Annotate → View controls and gallery
- Workflow Builder: `not_applicable`

Acceptance checks:

- **verified** — Filter/solo classes, preserve hidden geometry, and meet declared interaction budgets on dense images and large galleries. (`rv16-class-visibility-dense-editing-check`)

Evidence:

- `source`: 175 video tests exercised draft and persisted editing. A source-built WebView2 journey preserved a hidden mask and untouched keyframe and rejected a stale revision. — `docs/validation/research-workflows-1-6.json` (`rv16-video-edits-source`)
- `browser`: On 5,000 decoded fixture images, 24 cards appeared in 106.6 ms and the first thumbnail in 143.1 ms. The 1,500-box editor supported selection, hide, solo, undo, redo and reopen. — `docs/validation/research-workflows-1-6.json` (`rv16-gallery-canvas`)
- `windows_installed`: The standard-user 1.6 installation passed the dense image, native decision and reversible video tests with hidden geometry preserved. A physical MSI run on the same source preserved 1,500 boxes including 750 hidden boxes in the 5,000-image fixture. — `https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/44768324452/job/136420579045` (`rv16-class-visibility-dense-editing-original-msi-dense-image-video`)
- `windows_installed`: The corrected original MSI passed dense still and video editing under an ordinary account. The physical package retained 1,500 existing boxes, including 750 hidden boxes, on a 5,000-image fixture. — `docs/validation/installed-workflows-a580042e8.json` (`rv16-class-visibility-dense-editing-original-a580042e8`)
- `physical_hardware`: Physical WebView2 opened 24 of 5,000 gallery images in 75.8 ms. The focused image and filmstrip decoded in 207.9 ms. A new annotation survived save and reopen with 1,500 prior boxes and 750 hidden boxes preserved. The separate image, mask and video editing trials produced explicit 409 conflicts and preserved drafts on Cancel. — `docs/validation/windows-workflows-83b0a98b2.json` (`rv16-class-visibility-dense-editing-physical-83b0`)
- `representative_data`: none recorded

### rv16-lineage-reconciliation: Independent migration-lineage 0038 reconciliation

- Target: `1.6`
- Status: `verified`
- Dependencies: `rv14-lineage-upgrade`
- Entry point: Not user-facing
- Workflow Builder: `not_applicable`

Acceptance checks:

- **verified** — Diagnose both 0038 histories from schema/content, preserve rows/indexes/IDs/assets, and reject unknown or inconsistent databases without mutation. (`rv16-lineage-reconciliation-check`)

Evidence:

- `source`: Six populated profiles from original scientific, QC and 1.5 software retained all original columns, rows, file hashes and foreign keys across migration and two opens. Seventy migration, backup and compatibility tests passed. — `docs/validation/research-workflows-1-6.json` (`rv16-independent-0038-families`)
- `browser`: none recorded
- `windows_installed`: Original 1.6 and 1.5 MSI payloads preserved both historical 0038 schemas and QC 0039 through 0041, with separate old-reader restore and an unchanged mixed-history refusal. — `docs/validation/compact-windows-review-a580042e8.json` (`rv16-lineage-reconciliation-historical-original-83b0a98b2`)
- `windows_installed`: The unchanged original Windows verifier migrated each historical 0038 family and QC 0039–0041. Five separate restores reopened in the matching original reader, preserving the prior rows and files. The ambiguous profile was refused with unchanged bytes. — `https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/44768324452/job/136432743297` (`rv16-lineage-reconciliation-original-five-schema-recovery`)
- `windows_installed`: On this original MSI the five historical scientific and QC schemas upgraded and restored, the ambiguous profile stayed unchanged, and the validated 1.5 upgrade reopened a separate backup in the previous reader. — `docs/validation/installed-workflows-a580042e8.json` (`rv16-lineage-reconciliation-original-a580042e8`)
- `physical_hardware`: Both 0038 database histories and QC revisions 0039 through 0041 retained all prior table fingerprints, ID bindings and managed files. Five verified backup restorations rehashed 42 files. The older native readers reopened the backups. A mixed profile refused startup byte-identically. — `docs/validation/windows-workflows-83b0a98b2.json` (`rv16-lineage-reconciliation-physical-83b0`)
- `representative_data`: none recorded

### rv16-onboarding-installer: First-run onboarding and Windows usability acceptance

- Target: `1.6`
- Status: `verified`
- Dependencies: `rv16-class-visibility-dense-editing`, `rv16-lineage-reconciliation`
- Entry point: Installed first launch → Create or open project
- Workflow Builder: `not_applicable`

Acceptance checks:

- **verified** — Complete clean install, first project/import/annotation/review/export, upgrade, relaunch, rollback, uninstall, keyboard, DPI, and offline checks. (`rv16-onboarding-installer-check`)

Evidence:

- `source`: none recorded
- `browser`: At 960 by 640 CSS pixels and 150% scale, a new researcher used the keyboard to create a project, imported an original, annotated, undid and redid, reviewed, reopened and downloaded YOLO. No external HTTP attempts were recorded. — `docs/validation/research-workflows-1-6.json` (`rv16-first-use-compact`)
- `browser`: The corrected source-built WebView2 opened the first project, imported the original, reviewed the annotation, downloaded YOLO data and reopened the saved result. — `docs/validation/compact-windows-review-a580042e8.json` (`rv16-onboarding-installer-native-first-use-a580042e8`)
- `browser`: From System status the researcher restored the previously refused 38-member backup and a fresh 37-member backup, saw the new receipt and reopened the existing QC project in a separate application. — `docs/validation/restored-projects-3a9ce1622.json` (`rv16-repeated-recovery-source-3a9`)
- `windows_installed`: The original 1.6 MSI installed, launched, exported a reviewed annotation, reopened it after restart and uninstalled under outbound deny. Both ordinary and SYSTEM controls recorded 149 denied observations over 147 seconds. — `docs/validation/compact-windows-review-a580042e8.json` (`rv16-onboarding-installer-offline-83b0a98b2`)
- `windows_installed`: The same original MSI passed compact keyboard and DPI first use under an ordinary account, offline import, annotation, export and reopen, clean removal with retention, and a separate 1.5 upgrade and verified prior-reader rollback. — `docs/validation/compact-windows-review-a580042e8.json` (`rv16-onboarding-original-offline-upgrade-83b0a98b2`)
- `windows_installed`: The corrected original MSI passed standard-user first use, the compact keyboard handoff, offline export and reopening after restart. The published 1.0.3 and validated 1.5 upgrades passed, including the old-reader rollback. — `docs/validation/installed-workflows-a580042e8.json` (`rv16-onboarding-installer-original-a580042e8`)
- `windows_installed`: The original installer completed clean ordinary-user annotation, review, export and recovery, with separate upgrade and rollback checks across the supported historical profiles. — `docs/validation/restored-projects-3a9ce1622.json` (`rv16-original-installed-3a9`)
- `windows_installed`: An ordinary user installed the original MSI under measured outbound denial, reviewed a box, exported it, reopened it in a fresh desktop process and uninstalled successfully. — `docs/validation/restored-projects-3a9ce1622.json` (`rv16-offline-original-3a9`)
- `physical_hardware`: The native packaged first launch at 960 by 640 CSS pixels and emulated 150% scaling preserved keyboard focus and dismissal. The researcher imported image and video, edited, undid and redid, reviewed, exported YOLO and reopened. The browser attempted zero external HTTP requests. A separate eight-project 1.5 backup reopened with all 303 project files. — `docs/validation/windows-workflows-83b0a98b2.json` (`rv16-onboarding-installer-physical-83b0`)
- `physical_hardware`: The locally built Windows desktop restored both generations, preserved both historical metadata digests and reopened all seven projects in a separate launch. — `docs/validation/restored-projects-3a9ce1622.json` (`rv16-repeated-recovery-local-production-3a9`)
- `physical_hardware`: The desktop extracted from the original GitHub MSI restored both generations from System status and reopened the existing QC project on physical Windows. — `docs/validation/restored-projects-3a9ce1622.json` (`rv16-repeated-recovery-original-windows-3a9`)
- `representative_data`: none recorded

### rv16-qc-queues-bulk-retry: Prioritized QC queues, reviewer assignment, bulk actions, and idempotent retry

- Target: `1.6`
- Status: `verified`
- Dependencies: `rv15-reviewer-lab`
- Entry point: Review → QC queues
- Workflow Builder: `required`

Acceptance checks:

- **verified** — Prioritize and assign review, apply bounded bulk decisions transactionally, and retry without duplicate scientific records. (`rv16-qc-queues-bulk-retry-check`)

Evidence:

- `source`: Seven Project Exchange tests verified stable retry identity, source ownership, damaged data refusal, and two saved frozen QC runs in each of two generations of imported projects. — `docs/validation/research-workflows-1-6.json` (`rv16-frozen-qc-exchange`)
- `browser`: The ordinary Review workspace froze evidence, assigned and annotated items, bulk-started reviews and replayed the guided graph twice. A retry in a new backend process changed zero records. — `docs/validation/research-workflows-1-6.json` (`rv16-frozen-qc-review`)
- `browser`: With the inspector open, the source-built Windows desktop reached the ranked assignment at 1056 and 1440 CSS pixels. The ordinary review, frozen replays and project recovery completed. — `docs/validation/compact-windows-review-a580042e8.json` (`rv16-qc-queues-bulk-retry-compact-review-a580042e8`)
- `windows_installed`: The corrected original MSI passed the ranked reviewer assignment and bounded bulk action under an ordinary Windows account. The saved QC graph ran twice, and after Project Exchange the reopened queue retained the completed item, five audit events and one keyed bulk request. — `docs/validation/installed-workflows-a580042e8.json` (`rv16-qc-queues-bulk-retry-original-a580042e8`)
- `physical_hardware`: The packaged native Review workspace froze a ranked queue, assigned items and confirmed completion. Two saved runs executed. ZIP exchange preserved five ledger events, a keyed bulk request and two original images; a reopened graph completed in the restored project. — `docs/validation/windows-workflows-83b0a98b2.json` (`rv16-qc-queues-bulk-retry-physical-83b0`)
- `representative_data`: none recorded

### rv17-cross-project-monitoring: Local cross-project monitoring summaries

- Target: `1.7`
- Status: `in_progress`
- Dependencies: `rv17-monitoring-alerts`
- Entry point: Research → Monitoring → Project summaries
- Workflow Builder: `required`

Acceptance checks:

- **in_progress** — Compare compatible local projects without merging identities, schemas, units, or scientific review state. (`rv17-cross-project-monitoring-check`)

Evidence:

- `source`: none recorded
- `browser`: none recorded
- `windows_installed`: none recorded
- `physical_hardware`: none recorded
- `representative_data`: none recorded

### rv17-device-sources: Recorded, simulated, and physical acquisition sources

- Target: `1.7`
- Status: `in_progress`
- Dependencies: `rv15-field-capture`, `rv17-durable-schedules`
- Entry point: Project → Acquisition sources
- Workflow Builder: `required`

Acceptance checks:

- **in_progress** — Configure simulated/recorded sources and consent-gated physical devices with clock, identity, retry, and source provenance. (`rv17-device-sources-check`)

Evidence:

- `source`: none recorded
- `browser`: none recorded
- `windows_installed`: none recorded
- `physical_hardware`: none recorded
- `representative_data`: none recorded

### rv17-durable-schedules: Durable recurring acquisition, inference, QC, and report schedules

- Target: `1.7`
- Status: `in_progress`
- Dependencies: `rv16-qc-queues-bulk-retry`
- Entry point: Video & automation → Schedules
- Workflow Builder: `required`

Acceptance checks:

- **in_progress** — Persist schedules, recover after restart, deduplicate runs, cancel safely, and surface storage/delay/failure state. (`rv17-durable-schedules-check`)

Evidence:

- `source`: Two hard process interruptions on Windows preserved one job and output set. All 31 focused service tests passed. — `docs/validation/durable-schedules-e60ed5503.json` (`rv17-scheduler-atomic-queue`)
- `source`: The production worker completed and paused one acquisition, frozen inference, QC and reviewed report schedule on recorded or generated material. — `docs/validation/durable-schedules-e60ed5503.json` (`rv17-scheduler-four-purposes`)
- `source`: Completed schedule and receipt remained bound to the same frozen run inputs after two Project Exchange generations. The integrated scheduling tests passed 26 cases. — `docs/validation/durable-schedules-e60ed5503.json` (`rv17-scheduler-transfer`)
- `browser`: The source browser reopened the same saved schedule after a cold restart, inspected its catch-up job and two ranked images, downloaded the receipt and replayed it twice with the same output digest. A paused schedule stayed empty. — `docs/validation/durable-schedules-e60ed5503.json` (`rv17-scheduler-desktop-restart`)
- `windows_installed`: none recorded
- `physical_hardware`: none recorded
- `representative_data`: none recorded

### rv17-monitoring-alerts: Environmental and biological monitoring with reviewed anomaly proposals

- Target: `1.7`
- Status: `in_progress`
- Dependencies: `rv17-durable-schedules`, `rv11-environmental-context`, `rv13-event-summaries`
- Entry point: Research → Monitoring
- Workflow Builder: `required`

Acceptance checks:

- **in_progress** — Detect data drift/drop/delay and proposed biological/environmental anomalies, link evidence, and require review before scientific use. (`rv17-monitoring-alerts-check`)

Evidence:

- `source`: none recorded
- `browser`: none recorded
- `windows_installed`: none recorded
- `physical_hardware`: none recorded
- `representative_data`: none recorded

### rv18-bioacoustics: Bioacoustics import, annotation, review, and aligned analysis

- Target: `1.8`
- Status: `in_progress`
- Dependencies: `rv17-device-sources`, `rv15-reviewer-lab`
- Entry point: Project assets → Import audio → Review
- Workflow Builder: `required`

Acceptance checks:

- **in_progress** — Preserve original audio, annotate source time, align clocks explicitly, review proposals, and export provenance. (`rv18-bioacoustics-check`)

Evidence:

- `source`: none recorded
- `browser`: none recorded
- `windows_installed`: none recorded
- `physical_hardware`: none recorded
- `representative_data`: none recorded

### rv18-domain-shift: Domain-shift and group-aware performance comparison

- Target: `1.8`
- Status: `in_progress`
- Dependencies: `rv15-model-comparison`, `rv18-underwater-correction`
- Entry point: Models & AI → Model comparison → Domain shift
- Workflow Builder: `required`

Acceptance checks:

- **in_progress** — Compare frozen acquisition groups without leakage and report uncertainty, missing groups, and training/selection overlap. (`rv18-domain-shift-check`)

Evidence:

- `source`: none recorded
- `browser`: none recorded
- `windows_installed`: none recorded
- `physical_hardware`: none recorded
- `representative_data`: none recorded

### rv18-multispectral: Multispectral import, calibration, visualization, and analysis

- Target: `1.8`
- Status: `in_progress`
- Dependencies: `rv18-underwater-correction`, `rv12-calibration-evidence`
- Entry point: Project assets → Import multispectral image
- Workflow Builder: `required`

Acceptance checks:

- **in_progress** — Preserve bands and calibration, render selected composites, align source coordinates, and withhold incompatible indices. (`rv18-multispectral-check`)

Evidence:

- `source`: none recorded
- `browser`: none recorded
- `windows_installed`: none recorded
- `physical_hardware`: none recorded
- `representative_data`: none recorded

### rv18-taxonomy-detectability: Taxonomy proposals, review, and detectability evaluation

- Target: `1.8`
- Status: `in_progress`
- Dependencies: `rv12-organism-identity`, `rv15-reviewer-lab`
- Entry point: Research → Organisms & ecology → Taxonomy and detectability
- Workflow Builder: `required`

Acceptance checks:

- **in_progress** — Review taxonomy proposals and estimate detectability only from declared sampling/observation evidence with uncertainty and assumptions. (`rv18-taxonomy-detectability-check`)

Evidence:

- `source`: none recorded
- `browser`: none recorded
- `windows_installed`: none recorded
- `physical_hardware`: none recorded
- `representative_data`: none recorded

### rv18-underwater-correction: Reversible underwater image correction and model-input transforms

- Target: `1.8`
- Status: `in_progress`
- Dependencies: `rv16-class-visibility-dense-editing`
- Entry point: Annotate → Image adjustments
- Workflow Builder: `required`

Acceptance checks:

- **in_progress** — Preview reversible corrections, retain original pixels and transform provenance, and map annotations/predictions exactly to source pixels. (`rv18-underwater-correction-check`)

Evidence:

- `source`: none recorded
- `browser`: none recorded
- `windows_installed`: none recorded
- `physical_hardware`: none recorded
- `representative_data`: none recorded

### rv19-ancestry-integration: Full release ancestry, migration, and exchange integration

- Target: `1.9`
- Status: `in_progress`
- Dependencies: `rv16-lineage-reconciliation`, `rv18-multispectral`, `rv18-bioacoustics`
- Entry point: Not user-facing
- Workflow Builder: `not_applicable`

Acceptance checks:

- **in_progress** — Integrate all validated predecessor histories, preserve unknown provider/plugin metadata, and pass upgrade/downgrade/exchange/restore matrices. (`rv19-ancestry-integration-check`)

Evidence:

- `source`: none recorded
- `browser`: none recorded
- `windows_installed`: none recorded
- `physical_hardware`: none recorded
- `representative_data`: none recorded

### rv19-compatibility-matrix: Supported OS, GPU, provider, format, and project compatibility matrix

- Target: `1.9`
- Status: `in_progress`
- Dependencies: `rv19-performance-resilience`, `rv15-provider-foundations`
- Entry point: Help → Diagnostics and compatibility
- Workflow Builder: `not_applicable`

Acceptance checks:

- **in_progress** — Publish exact supported configurations from fresh installed evidence and provide actionable unavailable states for unsupported combinations. (`rv19-compatibility-matrix-check`)

Evidence:

- `source`: none recorded
- `browser`: none recorded
- `windows_installed`: none recorded
- `physical_hardware`: none recorded
- `representative_data`: none recorded

### rv19-end-to-end-workflows: End-to-end detection, segmentation, pose, tracking, and scientific workflows

- Target: `1.9`
- Status: `in_progress`
- Dependencies: `rv19-ancestry-integration`, `rv15-model-comparison`
- Entry point: Create/open project → Import → Annotate/Model → Review → Research → Export
- Workflow Builder: `required`

Acceptance checks:

- **in_progress** — Complete each primary workflow in the installed app and saved Workflow Builder without bypassing review or provenance gates. (`rv19-end-to-end-workflows-check`)

Evidence:

- `source`: none recorded
- `browser`: none recorded
- `windows_installed`: none recorded
- `physical_hardware`: none recorded
- `representative_data`: none recorded

### rv19-performance-resilience: Large-project/video performance and restart/resume resilience

- Target: `1.9`
- Status: `in_progress`
- Dependencies: `rv19-end-to-end-workflows`, `rv17-durable-schedules`
- Entry point: Normal project, gallery, video, import, and job flows
- Workflow Builder: `required`

Acceptance checks:

- **in_progress** — Meet declared launch/scroll/import/video budgets and recover safely from restart, cancellation, provider failure, low storage, and offline install. (`rv19-performance-resilience-check`)

Evidence:

- `source`: none recorded
- `browser`: none recorded
- `windows_installed`: none recorded
- `physical_hardware`: none recorded
- `representative_data`: none recorded

### rv20-cli-sdk-headless: CLI, Python SDK, and headless infer/benchmark/export

- Target: `2.0`
- Status: `in_progress`
- Dependencies: `rv20-plugin-sdk`, `rv20-compute-scheduling`
- Entry point: Help → Automation API / installed reefvision CLI
- Workflow Builder: `required`

Acceptance checks:

- **in_progress** — Create/open projects and run pinned inference, benchmark, workflow, and export operations headlessly with the same validation and structured errors as the GUI. (`rv20-cli-sdk-headless-check`)

Evidence:

- `source`: none recorded
- `browser`: none recorded
- `windows_installed`: none recorded
- `physical_hardware`: none recorded
- `representative_data`: none recorded

### rv20-compute-scheduling: Local compute resource scheduling, checkpointing, cancel, resume, and retry

- Target: `2.0`
- Status: `in_progress`
- Dependencies: `rv17-durable-schedules`, `rv20-workflow-builder`
- Entry point: Models & AI → Jobs and resources
- Workflow Builder: `required`

Acceptance checks:

- **in_progress** — Queue CPU/GPU work within declared limits, expose contention/progress, checkpoint safely, and resume/retry without duplicate results. (`rv20-compute-scheduling-check`)

Evidence:

- `source`: none recorded
- `browser`: none recorded
- `windows_installed`: none recorded
- `physical_hardware`: none recorded
- `representative_data`: none recorded

### rv20-experiment-registry: Experiment registry and research package lineage

- Target: `2.0`
- Status: `in_progress`
- Dependencies: `rv15-reproducibility-package`, `rv20-cli-sdk-headless`
- Entry point: Research → Experiments
- Workflow Builder: `required`

Acceptance checks:

- **in_progress** — Register immutable inputs/configuration/environment/results, compare runs, reopen packages, and preserve lineage through exchange. (`rv20-experiment-registry-check`)

Evidence:

- `source`: none recorded
- `browser`: none recorded
- `windows_installed`: none recorded
- `physical_hardware`: none recorded
- `representative_data`: none recorded

### rv20-modular-layout: Modular contextual panels, saved layouts, and safe reset

- Target: `2.0`
- Status: `in_progress`
- Dependencies: `rv16-onboarding-installer`, `rv20-workflow-builder`
- Entry point: Workspace → Panels / Reset layout
- Workflow Builder: `not_applicable`

Acceptance checks:

- **in_progress** — Rearrange relevant panels, persist valid layouts, recover missing-plugin panels, reset safely, and preserve keyboard/DPI accessibility. (`rv20-modular-layout-check`)

Evidence:

- `source`: none recorded
- `browser`: none recorded
- `windows_installed`: none recorded
- `physical_hardware`: none recorded
- `representative_data`: none recorded

### rv20-multimodal-analysis: Multimodal identity, time, coordinates, calibration, provenance, and shared analysis

- Target: `2.0`
- Status: `in_progress`
- Dependencies: `rv18-bioacoustics`, `rv18-multispectral`, `rv14-3d-organism-matching`, `rv20-workflow-builder`
- Entry point: Research → Multimodal analysis
- Workflow Builder: `required`

Acceptance checks:

- **in_progress** — Align compatible modalities with explicit identity/clock/frame/calibration evidence and withhold shared analysis when contracts conflict. (`rv20-multimodal-analysis-check`)

Evidence:

- `source`: none recorded
- `browser`: none recorded
- `windows_installed`: none recorded
- `physical_hardware`: none recorded
- `representative_data`: none recorded

### rv20-plugin-sdk: Versioned local plugin manifests, capability contracts, and failure isolation

- Target: `2.0`
- Status: `in_progress`
- Dependencies: `rv15-provider-foundations`, `rv19-compatibility-matrix`
- Entry point: Models & AI → Plugins and providers
- Workflow Builder: `required`

Acceptance checks:

- **in_progress** — Install/enable/disable compatible local plugins, isolate crashes/permissions, preserve unavailable records, and reject incompatible manifests safely. (`rv20-plugin-sdk-check`)

Evidence:

- `source`: none recorded
- `browser`: none recorded
- `windows_installed`: none recorded
- `physical_hardware`: none recorded
- `representative_data`: none recorded

### rv20-reefpose-long-gap-reidentification: Appearance-based ReefPose re-identification across long gaps or videos

- Target: `2.0`
- Status: `blocked`
- Dependencies: `rv12-organism-identity`, `rv13-temporal-refinement-review`, `rv15-reviewer-lab`, `rv15-model-comparison`
- Entry point: Video & automation → Video & tracking → Identity review
- Workflow Builder: `required`
- Missing input: An approved appearance re-identification model/protocol, held-out recordings with stable independent cross-gap/video identity labels, ambiguity/adjudication rules, target hardware, and preregistered false-match and missed-match thresholds.

Acceptance checks:

- **blocked** — Propose and review cross-gap/video identity candidates and report false matches, missed matches, ambiguity, calibration, and provenance on held-out identities. (`rv20-reefpose-long-gap-reidentification-check`)

Evidence:

- `source`: none recorded
- `browser`: none recorded
- `windows_installed`: none recorded
- `physical_hardware`: none recorded
- `representative_data`: none recorded

### rv20-release-journeys: 2.0 security, update/offline release, and complete user journeys

- Target: `2.0`
- Status: `in_progress`
- Dependencies: `rv20-experiment-registry`, `rv20-modular-layout`, `rv20-multimodal-analysis`
- Entry point: Installed first launch and Help → Diagnostics / Updates
- Workflow Builder: `not_applicable`

Acceptance checks:

- **in_progress** — Pass first-time, still-image, video, returning-researcher, plugin, and headless journeys plus signed/offline install, upgrade, rollback, diagnostics, and security review. (`rv20-release-journeys-check`)

Evidence:

- `source`: none recorded
- `browser`: none recorded
- `windows_installed`: none recorded
- `physical_hardware`: none recorded
- `representative_data`: none recorded

### rv20-workflow-builder: Typed, versioned Workflow Builder with guided forms and human gates

- Target: `2.0`
- Status: `in_progress`
- Dependencies: `rv20-plugin-sdk`, `rv19-end-to-end-workflows`
- Entry point: Video & automation → Workflow Builder
- Workflow Builder: `required`

Acceptance checks:

- **in_progress** — Build from guided forms or graph editing, validate typed edges, pin inputs/plugins, execute safely, pause at review gates, reopen, exchange, and replay. (`rv20-workflow-builder-check`)

Evidence:

- `source`: none recorded
- `browser`: none recorded
- `windows_installed`: none recorded
- `physical_hardware`: none recorded
- `representative_data`: none recorded

### scope-cloud-collaboration: Cloud accounts, hosted storage, and real-time collaboration

- Target: `post-2.0`
- Status: `explicitly_deferred`
- Dependencies: None
- Entry point: Not user-facing
- Workflow Builder: `deferred`
- Deferral: Owner placed cloud collaboration outside 2.0.

Acceptance checks:

- **not_applicable** — Confirm 2.0 remains local-first and does not require cloud identity, storage, or collaboration services. (`scope-cloud-collaboration-check`)

Evidence:

- `source`: none recorded
- `browser`: none recorded
- `windows_installed`: none recorded
- `physical_hardware`: none recorded
- `representative_data`: none recorded

### scope-hyperspectral: Hyperspectral imagery

- Target: `post-2.0`
- Status: `explicitly_deferred`
- Dependencies: None
- Entry point: Not user-facing
- Workflow Builder: `deferred`
- Deferral: Owner explicitly deferred hyperspectral beyond 2.0.

Acceptance checks:

- **not_applicable** — Confirm supported builds make no hyperspectral acquisition or analysis claim while preserving unknown historical metadata. (`scope-hyperspectral-check`)

Evidence:

- `source`: none recorded
- `browser`: none recorded
- `windows_installed`: none recorded
- `physical_hardware`: none recorded
- `representative_data`: none recorded

### scope-sleap-active-support: Active SLEAP runtime, provider, and SLP interoperability

- Target: `post-2.0`
- Status: `explicitly_deferred`
- Dependencies: None
- Entry point: Not user-facing
- Workflow Builder: `deferred`
- Deferral: Active support is retired pending an authoritative resolution of the sleap-nn v0.3.3 GPLv3 LICENSE versus BSD package-metadata inconsistency and a new approved distribution audit.

Acceptance checks:

- **verified** — Remove active runtime/provider/SLP support, preserve historical records as unavailable, and retain only audited neutral NWB interchange. (`scope-sleap-source-retirement-check`)
- **blocked** — Inspect a Windows installer built from the final candidate SHA and confirm that neither sleap-nn nor an active SLP runtime is packaged. (`scope-sleap-installed-payload-check`)

Evidence:

- `source`: Retired models are unavailable to new evaluation, image, video and saved pose workflow jobs while their histories remain readable. Native COCO, DeepLabCut CSV and Ultralytics exchange passed without the optional codec. The pinned optional NWB round trip and historical-file checks ran in the 41-test integration suite. — `docs/THIRD_PARTY_SLEAP_AUDIT.md` (`scope-sleap-source-retirement`)
- `browser`: none recorded
- `windows_installed`: The official six-CAB 1b0f29cff build had zero retired-runtime findings across 19,133 payload files and 11,984 frozen Python modules. A separate five-CAB build from the optional development environment passed across 19,186 files and 12,296 modules. The final 2.0 payload audit remains open. — `docs/REEFVISION_1.4.0_REPORT.md#official-windows-build-and-recovery-at-1b0f29cff` (`scope-sleap-1b0-package-audit`)
- `windows_installed`: The official 1.4.0 MSI and six cabinets at fb2276c87 contained 19,133 inspected paths and 11,984 nested Python entries. The payload audit found zero retired runtime components and no bundled model assets. The 2.0 payload requires its own audit. — `https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/44697377337` (`scope-sleap-active-support-official-fb2276c87`)
- `physical_hardware`: none recorded
- `representative_data`: none recorded

### scope-stereo-reconstruction: Stereo reconstruction

- Target: `post-2.0`
- Status: `explicitly_deferred`
- Dependencies: None
- Entry point: Not user-facing
- Workflow Builder: `deferred`
- Deferral: Owner placed stereo reconstruction outside 2.0.

Acceptance checks:

- **not_applicable** — Confirm 2.0 accepts supported 3D assets but does not claim stereo reconstruction. (`scope-stereo-reconstruction-check`)

Evidence:

- `source`: none recorded
- `browser`: none recorded
- `windows_installed`: none recorded
- `physical_hardware`: none recorded
- `representative_data`: none recorded
