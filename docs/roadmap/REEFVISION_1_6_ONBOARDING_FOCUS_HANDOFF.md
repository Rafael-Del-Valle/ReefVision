# ReefVision 1.6 — onboarding navigation focus handoff

**Milestone:** first-run and help-modal accessibility on local Windows desktops.

## Gap and correction

The onboarding dialog already traps focus while open and restores the
previously focused launcher on a plain **Close**, **Escape**, **Skip for now**,
or permanent dismissal. It also deliberately avoids restoring that launcher
when creating or selecting a project, allowing the next modal to autofocus.

However, the four existing destinations available after project selection
(class manager, QC review, Workflow Builder and System status) did not use
the same focus-handoff rule. When navigation mounted an autofocus control in
the target workspace, the onboarding effect cleanup could then restore
focus to the old help launcher, interrupting keyboard and screen-reader
interaction with the newly opened workspace.

**Fix:** every explicit `navigateTo` action now marks a focus handoff;
only dismissal without navigation restores the original focus. The change is
limited to modal focus behavior; it does not grant permission, change
researcher decisions, alter stored classes or annotations, or dismiss help
permanently. Existing project creation and selection behavior remains intact.

## Verification and release gates

`apps/web/src/features/onboarding/OnboardingModal.test.tsx` now mounts a
new workspace with an autofocus search field for each of the four
non-project destinations, requires the onboarding dialog to close, and
verifies the newly focused field is **not** overridden by the old help
launcher. Existing Escape, dismissal, focus trap and project handoff
regressions continue to apply.

Run frontend Vitest, TypeScript, formatting, Playwright and production build
on the exact PR SHA. Real installed Windows GUI keyboard/screen-reader
acceptance and full MSI install/upgrade/rollback are still required.
Scientific typed standalone/saved Workflow Builder QC execution, provenance,
units, retries and mandatory human review are **preserved**, not replaced;
focus handoff is UI-only and must not become a duplicate workflow node.
Release remains on HOLD pending the independent 1.1/1.6 Alembic-0038
collision, representative biology, full acceptance and researcher approval.

## Synchronous focus handoff before React unmount (2026-11-22)

The existing navigation test exercised an autofocus destination mounted after
React processed the close. There is a second real desktop sequence: a workspace
navigator may focus its own search or project input **synchronously** in the
`onNavigate` callback, while the onboarding dialog's document-level
`focusin` listener is still mounted. The old listener immediately pulled
focus back to the help dialog; after close, focus could be lost to the document
body even though the old-launcher restoration had correctly been suppressed.

The focus trap now yields **only** after the user explicitly initiates
`navigateTo`; it still recaptures background focus throughout ordinary help
and restores the launcher on non-navigation dismissal. A parameterized React
regression exercises both project-scoped Workflow Builder navigation and the
project-independent System destination, with the destination input focused
inside `onNavigate` before `onClose` unmounts the modal. This is local UI
accessibility, not a new scientific Workflow Builder operation; typed saved QC
workflows, artifacts, scientific units, provenance and researcher approval
remain unchanged. Release remains on HOLD for exact-head frontend/E2E and
backend CI, the independent 1.1/1.6 Alembic collision, biological acceptance,
physical MSI clean-install/upgrade/rollback and installed-GUI validation.
