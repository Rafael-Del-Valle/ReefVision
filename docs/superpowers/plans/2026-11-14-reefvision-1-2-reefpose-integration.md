# ReefVision 1.2 and native ReefPose integration plan

**Goal.** Deliver a reviewable 1.2 development branch with native ReefPose, its reproducible scientific workflow, and scientist-facing access to the existing ecology tools.

**Architecture.** Keep the target 1.2 ecology line and bring in the existing 1.1 scientific and GUI dependencies and the standalone ReefPose implementation. Reconcile historical revisions through the online Alembic entry point. Use existing standalone and Workflow Builder contracts for the next ecological increments.

- [x] Merge the 1.1 GUI candidate and the published ReefPose source into the isolated integration branch. Combine model and router registrations in `apps/api/reefvision/{api,db}` and retain both Workflow Builder catalogs and desktop workspace entry points.
- [x] Reconcile the three migration lines in `apps/api/migrations` and test fresh, standalone 1.1, 1.2 and ReefPose upgrades. Verify resumable upgrades, rollback, and the preserved rows across each transition.
- [x] Build standalone GUI paths for registered organism identity and connected branch preview. Reuse project identity and existing skeleton API/workflow types. Keep provisional graph edits visibly distinct from saved, reviewed results.
- [x] Verify the existing Phase 1–6 entry points with isolated synthetic data and a compatible checkpoint where available. Exercise selected live browser/native paths and record the exact environment and any gates still open.
- [x] Synchronize 1.2 development metadata and the adopted AGPL-3.0-only license. Run verification, push the integration branch, and open a draft against `develop/reefvision-1.2` linked to #74, #76, #84, and the ReefPose source.
