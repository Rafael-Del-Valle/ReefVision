# ReefVision 1.6 — QC coordination workspace-navigation protection

## Existing implementation and nonduplicative scope

The existing review coordination panel already preserves per-item unsent biological notes, reviewer assignments, uncertain audit-event UUIDs and explicit close/discard review. The 1.6 executable `qc_review_queue` Workflow Builder node already supports typed queue references, saved graphs/runs, provenance and researcher-review gates. This increment does **not** duplicate that node, modify a scientific measurement, or introduce a database migration.

## Previously uncovered data-loss path

The dashboard protected queue changes, and the panel guarded its own close button, browser unload and native Tauri close. However, **App-level navigation** (Home, System status, workspace tabs, presets, detached inspector commands, assistant navigation, archive, onboarding and image editor launch) could still unmount the panel without calling its protected close control. That discarded in-memory notes and exact retry UUIDs, potentially losing the only client-side reference to an audit request already committed on the local server.

## Implementation

- `ReviewQueueDashboard` reports whether the coordination panel is open to the host; it clears the signal on panel close or unmount. The dashboard disables quick review and image-editor launch while coordination is open.
- `App` refuses project/workspace departure while coordination is open, including keyboard navigation, presets, global Home/System actions, archive, assistant navigation, onboarding, detached inspector commands, measurement and review-item editor launch. The researcher receives an explicit explanation and can return to the coordination panel.
- The researcher must close coordination using the **existing** guarded close controls. Pending or uncertain audit events still block closing; unsent drafts still require an explicit discard confirmation. No automatic review approval, audit replay or data upload occurs.
- The protection intentionally applies while coordination is open, including an empty draft: this avoids race conditions where a user starts a review mutation immediately before navigating away.

## Regression and acceptance

- Dashboard regression checks host open/close signaling and that image-editor launch remains disabled until protected closure.
- Application integration regression exercises unsent coral-observation text, Home and workspace-tab navigation attempts, preservation of the draft, and explicit close/discard before Home succeeds.
- Existing standalone QC API, saved executable Workflow Builder and idempotent audit-event tests remain required in CI. This is a navigation/UI safeguard, not a new executable scientific node.

## Limits and release hold

Protection is in-memory and cannot restore notes after a hard process crash, forced OS termination or external code that unmounts the entire React application. Durable crash recovery requires a separate privacy-reviewed local persistence design that retains exact UUID semantics. A physical Windows/Tauri installed-GUI test and MSI upgrade/rollback remain required. Independent 1.1/1.6 Alembic revision-0038 reconciliation and representative biological-data acceptance are also unresolved. No claim of release readiness is made.
