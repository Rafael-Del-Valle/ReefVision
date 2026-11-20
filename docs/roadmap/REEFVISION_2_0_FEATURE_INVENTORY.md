# ReefVision 2.0 Feature Inventory

> Generated from `REEFVISION_2_0_FEATURE_INVENTORY.json`. Do not edit by hand.

Updated: `2026-11-20T04:16:00Z`
Candidate target: `2.0`

## Status summary

| Status | Count |
| --- | ---: |
| blocked | 13 |
| explicitly_deferred | 4 |
| in_progress | 33 |
| verified | 27 |

## Features

| Version | Feature | Status | Entry point or boundary |
| --- | --- | --- | --- |
| 1.1 | Reviewed annotation and model-source comparison | verified | Research → Comparisons → Annotation sources |
| 1.1 | Current-field interpolation, streamlines, and trajectory context | verified | Research → Environmental context → Currents |
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
| 1.3 | Held-out landmark, event, timing, and count agreement reports | in_progress | Models & AI → Model Hub → ReefPose scientific validation |
| 1.3 | Publication figures, methods, and provenance records | verified | Research → Reports → Publication outputs |
| 1.3 | Representative frame-only versus temporal ReefPose comparison | blocked | The model and data lineage required for the engineering held-out label is tracked in rv13-heldout-agreement. Representative group-aware accuracy also requires independent recordings, labels and thresholds. |
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
| 1.5 | Study setup, treatments, sampling units, exclusions, and statistical plan | in_progress | Research → Study design |
| 1.5 | Offline field capture and later project reconciliation | in_progress | Project → Field capture |
| 1.5 | Local model catalog, runtime selection, and prompt-assisted configuration | in_progress | Models & AI → Model Hub |
| 1.5 | Unified detector, mask, pose, tracking, and event comparison | in_progress | Models & AI → Model comparison |
| 1.5 | Early local provider and plugin foundations | verified | Models & AI → Providers |
| 1.5 | Complete research reproducibility package | in_progress | Research → Export reproducibility package |
| 1.5 | Reviewer roles, independent queues, adjudication, and agreement | in_progress | Review → Reviewer lab |
| 1.6 | Safe class management after use | in_progress | Annotate → Classes |
| 1.6 | Class visibility, dense annotation editing, and large-gallery performance | in_progress | Annotate → View controls and gallery |
| 1.6 | Independent migration-lineage 0038 reconciliation | in_progress | Applied migration IDs are never edited. |
| 1.6 | First-run onboarding and Windows usability acceptance | in_progress | Installed first launch → Create or open project |
| 1.6 | Prioritized QC queues, reviewer assignment, bulk actions, and idempotent retry | in_progress | Review → QC queues |
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
| post-2.0 | Active SLEAP runtime, provider, and SLP interoperability | explicitly_deferred | BSD sleap-io may remain only for neutral NWB interchange after audit; native ReefPose is the supported pose path. Checkpoint 2194f2e96 passed a digest-bound MSI and six-CAB audit of 19,133 paths and 11,977 nested Python entries. Repeat the payload audit on the final candidate. |
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
- Entry point: Research → Environmental context → Currents
- Workflow Builder: `required`

Acceptance checks:

- **verified** — Render bounded RK4 flow geometry and withhold trajectory matching when UTC, depth, datum, or compatible field evidence is missing. (`rv11-current-visualization-check`)

Evidence:

- `source`: Reference-field interpolation, termination, and overlay tests. — `https://github.com/Rafael-Del-Valle/ReefVision/pull/71` (`rv11-current-src`)
- `browser`: none recorded
- `windows_installed`: none recorded
- `physical_hardware`: none recorded
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
- `browser`: Three complete synthetic tanks with unequal nested organism counts produced differences of 1, 3 and 5 mm. A fourth incomplete tank was excluded. The mean was 3 mm, standard error 1.15470054 mm and 95% interval -1.96827542 to 7.96827542 mm with 2 degrees of freedom. Three JSON downloads and 15 original file hashes matched. Calculate, Download and Save recheck the reviewed source before exposing the result or saving a graph. — `apps/web/tests/e2e/paired-growth-contrast-live.spec.ts` (`rv11-paired-desktop`)
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
- `browser`: none recorded
- `windows_installed`: Installed 1.2 to 1.3 upgrade and rollback evidence. — `https://github.com/Rafael-Del-Valle/ReefVision/pull/87` (`rv13-exchange-win`)
- `physical_hardware`: none recorded
- `representative_data`: none recorded

### rv13-heldout-agreement: Held-out landmark, event, timing, and count agreement reports

- Target: `1.3`
- Status: `in_progress`
- Dependencies: `rv13-temporal-refinement-review`, `rv13-event-summaries`
- Entry point: Models & AI → Model Hub → ReefPose scientific validation
- Workflow Builder: `required`

Acceptance checks:

- **verified** — Publish paired landmark error, event precision/recall, timing/count error, exclusions, and checkpoint/reference provenance. (`rv13-heldout-agreement-check`)
- **in_progress** — Carry declared independent animal and recording groups from the normal frame training workflow into an immutable checkpoint lineage. A shared group or unknown historical source must remain visible in the evaluation status. (`rv13-audited-frame-training-groups`)

Evidence:

- `source`: Deterministic scoring, pairing, report-hash, and stale-source tests. — `https://github.com/Rafael-Del-Valle/ReefVision/pull/87` (`rv13-agreement-src`)
- `browser`: none recorded
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
- `physical_hardware`: none recorded
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

Evidence:

- `source`: Deterministic mesh fixtures cover calibrated scale exponents, extents, surface area, topology, conditional enclosed volume, uncertainty intervals, paths, numerical integrity, and explicit withhold reasons. — `apps/api/reefvision/tests/test_spatial_mesh_primitives_v14.py` (`rv14-geometric-known-fixtures`)
- `source`: Calibration review and source bindings reject stale, mismatched, self-reviewed, or altered measurement evidence while preserving unverified status. — `apps/api/reefvision/tests/test_spatial_mesh_calibration_review_v14.py` (`rv14-geometric-review-binding`)
- `browser`: Workflow Builder exposes a project-owned original picker, scale, calibration evidence, uncertainty, specimen/observation/frame context, and an explicit warning that geometric routes are not anatomical branch lengths. — `apps/web/src/features/workflow-graphs/ScientificNodeControls.test.tsx` (`rv14-geometric-guided-ui`)
- `windows_installed`: none recorded
- `physical_hardware`: none recorded
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

Evidence:

- `source`: Real ancestry merge, unique Alembic graph, schema-fingerprinted legacy upgrades, ambiguity rejection, backup verification, and downgrade/upgrade regressions. — `docs/roadmap/REEFVISION_1_4_MIGRATION_RECONCILIATION.md` (`rv14-lineage-source`)
- `browser`: none recorded
- `windows_installed`: Exact-head source 36c80224a Windows acceptance passed a published 1.0.3 upgrade with schema migration, persistence, Project Exchange, uninstall, and data retention. This is partial evidence and does not substitute for representative 1.3 and legacy draft-1.4 profiles. — `https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/44072770396` (`rv14-lineage-win-103`)
- `windows_installed`: Exact-head source 36c80224a passed all three installed synthetic profiles. Verified 1.3 MSI upgrade, 0038 and 0039 profile migration, evidence preservation, exchange round trips, and backup restoration. The historical 1.3 build rejected the upgraded schema and the upgraded database hash remained unchanged. — `https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/44072770396` (`rv14-lineage-win-synthetic`)
- `physical_hardware`: none recorded
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
- `physical_hardware`: none recorded
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
- Status: `in_progress`
- Dependencies: `rv13-study-assignments`, `rv11-repeated-measures-analysis`
- Entry point: Research → Study design
- Workflow Builder: `required`

Acceptance checks:

- **in_progress** — Create and freeze a study design with nesting, repeated measures, exclusions, estimands, and analysis choices before reporting. (`rv15-experimental-design-check`)

Evidence:

- `source`: none recorded
- `browser`: none recorded
- `windows_installed`: none recorded
- `physical_hardware`: none recorded
- `representative_data`: none recorded

### rv15-field-capture: Offline field capture and later project reconciliation

- Target: `1.5`
- Status: `in_progress`
- Dependencies: `rv14-versioned-spatial-assets`, `rv13-acquisition-qc`
- Entry point: Project → Field capture
- Workflow Builder: `required`

Acceptance checks:

- **in_progress** — Capture media/metadata offline, preserve clocks/source hashes, reconcile duplicates, and retain conflicts for review. (`rv15-field-capture-check`)

Evidence:

- `source`: none recorded
- `browser`: none recorded
- `windows_installed`: none recorded
- `physical_hardware`: none recorded
- `representative_data`: none recorded

### rv15-model-catalog-runtime: Local model catalog, runtime selection, and prompt-assisted configuration

- Target: `1.5`
- Status: `in_progress`
- Dependencies: `rv15-provider-foundations`
- Entry point: Models & AI → Model Hub
- Workflow Builder: `required`

Acceptance checks:

- **in_progress** — Select explicit local models/runtimes, retain hashes and compatibility, and treat generated configuration as reviewable input. (`rv15-model-catalog-runtime-check`)

Evidence:

- `source`: none recorded
- `browser`: none recorded
- `windows_installed`: none recorded
- `physical_hardware`: none recorded
- `representative_data`: none recorded

### rv15-model-comparison: Unified detector, mask, pose, tracking, and event comparison

- Target: `1.5`
- Status: `in_progress`
- Dependencies: `rv12-human-model-counts`, `rv13-heldout-agreement`, `rv15-model-catalog-runtime`
- Entry point: Models & AI → Model comparison
- Workflow Builder: `required`

Acceptance checks:

- **in_progress** — Compare compatible models on the same immutable holdout with task-specific metrics, paired differences, exclusions, and disagreement navigation. (`rv15-model-comparison-check`)

Evidence:

- `source`: none recorded
- `browser`: none recorded
- `windows_installed`: none recorded
- `physical_hardware`: none recorded
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
- `physical_hardware`: none recorded
- `representative_data`: none recorded

### rv15-reproducibility-package: Complete research reproducibility package

- Target: `1.5`
- Status: `in_progress`
- Dependencies: `rv15-experimental-design`, `rv15-reviewer-lab`, `rv15-model-comparison`
- Entry point: Research → Export reproducibility package
- Workflow Builder: `required`

Acceptance checks:

- **in_progress** — Export methods, study/review/model identities, immutable inputs, environments, exclusions, results, and verification manifests; reject tampering on import. (`rv15-reproducibility-package-check`)

Evidence:

- `source`: none recorded
- `browser`: none recorded
- `windows_installed`: none recorded
- `physical_hardware`: none recorded
- `representative_data`: none recorded

### rv15-reviewer-lab: Reviewer roles, independent queues, adjudication, and agreement

- Target: `1.5`
- Status: `in_progress`
- Dependencies: `rv13-acquisition-qc`
- Entry point: Review → Reviewer lab
- Workflow Builder: `required`

Acceptance checks:

- **in_progress** — Assign blinded reviews, preserve independent decisions, adjudicate disagreement, and export agreement with role/revision provenance. (`rv15-reviewer-lab-check`)

Evidence:

- `source`: none recorded
- `browser`: none recorded
- `windows_installed`: none recorded
- `physical_hardware`: none recorded
- `representative_data`: none recorded

### rv16-class-management: Safe class management after use

- Target: `1.6`
- Status: `in_progress`
- Dependencies: `rv15-reproducibility-package`
- Entry point: Annotate → Classes
- Workflow Builder: `not_applicable`

Acceptance checks:

- **in_progress** — Rename, retire, reorder safely, and prevent silent class-index changes in annotations, datasets, checkpoints, and exports. (`rv16-class-management-check`)

Evidence:

- `source`: none recorded
- `browser`: none recorded
- `windows_installed`: none recorded
- `physical_hardware`: none recorded
- `representative_data`: none recorded

### rv16-class-visibility-dense-editing: Class visibility, dense annotation editing, and large-gallery performance

- Target: `1.6`
- Status: `in_progress`
- Dependencies: `rv16-class-management`
- Entry point: Annotate → View controls and gallery
- Workflow Builder: `not_applicable`

Acceptance checks:

- **in_progress** — Filter/solo classes, preserve hidden geometry, and meet declared interaction budgets on dense images and large galleries. (`rv16-class-visibility-dense-editing-check`)

Evidence:

- `source`: none recorded
- `browser`: none recorded
- `windows_installed`: none recorded
- `physical_hardware`: none recorded
- `representative_data`: none recorded

### rv16-lineage-reconciliation: Independent migration-lineage 0038 reconciliation

- Target: `1.6`
- Status: `in_progress`
- Dependencies: `rv14-lineage-upgrade`
- Entry point: Not user-facing
- Workflow Builder: `not_applicable`

Acceptance checks:

- **in_progress** — Diagnose both 0038 histories from schema/content, preserve rows/indexes/IDs/assets, and reject unknown or inconsistent databases without mutation. (`rv16-lineage-reconciliation-check`)

Evidence:

- `source`: none recorded
- `browser`: none recorded
- `windows_installed`: none recorded
- `physical_hardware`: none recorded
- `representative_data`: none recorded

### rv16-onboarding-installer: First-run onboarding and Windows usability acceptance

- Target: `1.6`
- Status: `in_progress`
- Dependencies: `rv16-class-visibility-dense-editing`, `rv16-lineage-reconciliation`
- Entry point: Installed first launch → Create or open project
- Workflow Builder: `not_applicable`

Acceptance checks:

- **in_progress** — Complete clean install, first project/import/annotation/review/export, upgrade, relaunch, rollback, uninstall, keyboard, DPI, and offline checks. (`rv16-onboarding-installer-check`)

Evidence:

- `source`: none recorded
- `browser`: none recorded
- `windows_installed`: none recorded
- `physical_hardware`: none recorded
- `representative_data`: none recorded

### rv16-qc-queues-bulk-retry: Prioritized QC queues, reviewer assignment, bulk actions, and idempotent retry

- Target: `1.6`
- Status: `in_progress`
- Dependencies: `rv15-reviewer-lab`
- Entry point: Review → QC queues
- Workflow Builder: `required`

Acceptance checks:

- **in_progress** — Prioritize and assign review, apply bounded bulk decisions transactionally, and retry without duplicate scientific records. (`rv16-qc-queues-bulk-retry-check`)

Evidence:

- `source`: none recorded
- `browser`: none recorded
- `windows_installed`: none recorded
- `physical_hardware`: none recorded
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

- `source`: none recorded
- `browser`: none recorded
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
- `windows_installed`: none recorded
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
