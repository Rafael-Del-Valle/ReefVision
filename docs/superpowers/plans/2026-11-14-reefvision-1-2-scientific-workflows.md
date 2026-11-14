# ReefVision 1.2 Scientific Workflows Implementation Plan

**Goal.** Finish reviewed scientific workflows on the ReefPose integration branch.

**Architecture.** Reuse stored skeletons, ecological identity registrations, ReefPose identity assignments, and Workflow Builder. Scientific decisions append immutable records with evidence hashes and separate read-time currency checks. Exchange continues to import a distinct project.

**Spec.** The 1.2 roadmap, connected branch measurement specification, and PR #85 remaining acceptance criteria.

- [ ] In `db/models/coral_graph.py` and a migration after `b12_integrated_0001`, persist graph reviews, correspondence and saved growth. In `services/coral_graph*.py`, preserve stable unchanged branch and junction IDs, validate source ownership and geometry, and make graph operations and gap dispositions explicit.
- [ ] In `schemas/coral_graph.py` and `api/routes/coral_graph.py`, expose project-scoped graph and correspondence history, calculation and exports. Regression tests cover rejected edits, old snapshots, calibration and chronology, stale revisions and cross-project rejection.
- [ ] In the mask editor and Ecology workspace, wire graphical edits, review and two-date comparison. Register a Workflow Builder computation that shares the standalone review-aware service and never implicitly reviews evidence.
- [ ] In the ecology pose link and analysis modules, persist reviewed identity links and investigator-selected ecological analyses, then wire into the same workspace. Test alternative identities, interruptions, outdated links, replicate aggregation, denominators and workflow replay.
- [ ] In the project exchange service, preserve the integrated scientific graph and validate identifiers, evidence, archive members and missing assets before import. Exercise malformed packages and a new-project re-export.
- [ ] Verify migrations, legacy upgrades, backup and restore, the full backend and frontend, native GPU, live Chromium and required Windows CI on the pushed PR head.
