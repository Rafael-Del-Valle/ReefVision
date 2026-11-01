# ReefVision 1.6 — preserve QC coordination during asynchronous queue refresh

## Audited scope and actual gap

Track D's existing 1.6 implementation already includes class visibility, researcher QC comments and assignments, guarded close/discard controls, and an executable typed `qc_review_queue` Workflow Builder node with saved runs, provenance, idempotent retry and explicit researcher-review requirements. This is an interface-lifecycle correction, **not** a second QC workflow node or a migration.

The dashboard previously reset `coordinationItemId` whenever the derived active queue changed. A background queue-list refetch could temporarily omit the selected queue, causing the open coordination component to unmount and discard unsent biological notes or the original idempotency UUID for an uncertain audit event. The queue-history button for the **currently selected queue** also remained enabled while coordination was open and its click handler unmounted the panel.

## Fix

- Pin the original queue ID when the researcher opens coordination. Preserve the same coordination component and its original queue identity even when a refreshed list temporarily omits that queue. Host queue selection remains pinned while the panel is open.
- Disable **all** queue-history buttons during coordination, including the already-selected queue, with an event-handler guard as defense in depth.
- If a refresh omits the pinned queue, display an explicit warning and disable opening coordination on a different queue. A subsequent list refresh restores the normal queue display without clearing drafts.
- Only the existing guarded panel close (or an explicit project transition outside this component) clears the pinned queue. No automatic approval, event replay, model download, network transmission or research-asset mutation occurs.

## Pending generation and regeneration race (2026-11-01)

A researcher can begin generating or regenerating a queue and then open
coordination while that API request is still pending. The existing mutation
success callback checked only the original project/dataset navigation scope.
It could therefore select the newly generated queue after coordination opened,
changing the host's selected queue even though a biological note or uncertain
audit UUID remained protected on the original queue. Disabling new Generate
clicks during coordination does not protect already-running requests.

Both queue-generation success callbacks now consult the current protected
coordination/bulk state before selecting a returned queue. The server-created
queue still exists and the originating queue list is invalidated normally;
researchers may select the new queue only after safely closing the protected
review work. The original source queue and draft remain in memory. Two
parameterized dashboard regressions resolve pending generation and
regeneration after a coral observation is drafted and verify unchanged host
selection and draft contents. The CI-reported Prettier indentation issue in
the missing-queue warning was also corrected.

This guard does not claim durability across process crashes, nor does it
change reviewer decisions, annotations, or executable saved Workflow Builder
artifacts. No new workflow node or migration is warranted for UI lifecycle
coordination.

## Regression and release gates

Dashboard regressions check that reselecting the same queue cannot discard a draft; that replacing the list with another queue preserves a coral observation, original host queue identity and the open panel; and that restoring the list leaves the draft unchanged. Existing standalone QC event tests and saved executable Workflow Builder regression suites remain mandatory; this UI-only change does not alter typed graph execution.

This is in-memory protection, **not** durable crash recovery. Native Windows installed-GUI/MSI upgrade and rollback, representative biological-data acceptance, complete exact-head CI, and independent 1.1/1.6 Alembic revision-0038 reconciliation remain required. Version 1.6 is **not release-ready**.

## Explicit queue selection during an in-flight mutation (2026-11-01)

The previous protected-coordination guard did not cover an unprotected
researcher manually selecting a different historical queue while a generation
or regeneration request was pending. The late response would replace that
intentional selection, potentially shifting the ranked biological observations
under inspection. The dashboard now records a monotonically increasing
selection revision on explicit queue-history clicks and captures that revision
with each queue-generation request. The response may auto-select its new queue
only when project/dataset navigation, the captured selection revision, and
current QC protection state all still permit it. Regardless of selection, the
server-created queue remains in history after normal query invalidation.

Two parameterized React regressions cover generate and regenerate, with a
manual queue switch before resolution. They require the manually chosen queue
to remain selected and prohibit fetching the newly generated queue. The
previous exact-head frontend CI failure was a Prettier-only assertion layout
difference in the pending-coordination regression; that exact layout was also
corrected. No standalone QC API, typed saved Workflow Builder execution,
scientific review gate, database migration or user asset was changed.

The new regressions still require exact-head CI confirmation. This UI safeguard
does not guarantee cross-process crash recovery or constitute installed Windows
GUI acceptance. Release remains **HOLD**.

## Deterministic asynchronous regression preconditions (2026-11-01)

The exact-head frontend CI at `51bb299e` reported three failures in the
scope-isolation suite (all other 611 frontend tests passed; backend CI passed).
The missing-queue fixture could be overwritten by its initial in-flight
history request, and a pending generation fixture could attempt to open
coordination before the ranked-item query had rendered the control. The
regeneration fixture additionally assumed the last global React Query mutation
would already report `success` even while its async history invalidation was
still settling. These were test synchronization/observation gaps, not evidence
that a reviewer action had been accepted or that a saved scientific workflow
had executed.

The regression now waits for initial queue-history fetch completion before
injecting the missing-list response, waits for the actual coordination control
before starting the delayed queue mutation, and checks that history refetch
began after mutation resolution instead of depending on a global mutation-cache
ordering. The original assertions protecting unsent biological observations,
queue identity and refusal to fetch a different queue remain in place. These
changes do **not** weaken researcher approval, retry UUID or provenance checks.

This is a frontend regression repair only. Exact-head Vitest, TypeScript,
formatting, full E2E, installed-Windows GUI and MSI upgrade/rollback must still
pass independently. No claim of release readiness or crash-durable draft
recovery follows from these test changes.

## Follow-up: exercise real queue-history refresh and avoid global mutation-cache races (2026-11-01)

[CI 41307538412](https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/41307538412) at `c94c16eb` passed the backend job but failed the frontend Vitest job: 610 tests passed and four scope-isolation tests failed. The missing-queue warning assertion observed the original cached queue after a synthetic cache write, the pending-regenerate scenario attempted to open coordination during a transient item-list render, and the manual-selection cases waited on a global mutation-cache status that remained pending while the success callback awaited history invalidation.

The updated regressions now simulate an actual `getReviewQueues` refetch for the omitted/restored historical queue, wait for the researcher-facing warning and coordination control, and observe a new history request as evidence that the delayed mutation's success callback executed. The tests still require the original queue and unsent coral note to survive, and prohibit selecting/fetching the new queue after a researcher manually selects another. This does not change the QC API, scientific review gate, typed executable saved `qc_review_queue` Workflow Builder, migrations, or user data.

**Verification status:** the edited test blob is committed on the isolated 1.6 branch; full exact-head frontend/backend CI is required before calling these repairs successful. Local npm/Vitest/Playwright execution remains unavailable because GitHub DNS resolution prevents a checkout. Native Windows installed-GUI, MSI upgrade/rollback, representative biological-data acceptance, durable crash recovery, and the independent 1.1/1.6 Alembic 0038 collision remain release blockers. **Release HOLD.**

## Follow-up: isolate one-shot mutation mocks (2026-11-01)

[Exact-head CI 41312338952](https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/41312338952) passed backend but failed 3 of 614 frontend tests (611 passed). The remaining failures were confined to delayed QC queue-generation/regeneration scope tests. A deterministic fixture defect was identified: each parameterized test installed **both** `createReviewQueue.mockReturnValueOnce(pending)` and `regenerateReviewQueue.mockReturnValueOnce(pending)`, although only one operation was invoked. Vitest's `vi.clearAllMocks()` clears call history **without discarding unused one-shot mock implementations**. Consequently, the next parameterized test could receive the prior test's already-resolved queue, unexpectedly replacing the selected queue and causing subsequent coordination/history assertions to fail.

The suite now uses `vi.resetAllMocks()` before reinstating explicit per-test API defaults, and each parameterized scenario installs a pending response **only** on the operation under test. This prevents a stale generated queue from leaking into the next scientific-review scenario. Existing assertions continue to require preservation of the researcher's explicit historical queue selection, unsent coral notes, and prohibition on fetching the newly generated queue during protected review. This is test-fixture isolation, not a change to reviewer decisions, immutable evidence, production APIs, migrations or the executable saved `qc_review_queue` Workflow Builder node.

**Acceptance:** exact-head TypeScript/format/Vitest/E2E and backend checks remain necessary; a committed fixture repair is not itself evidence that the regressions pass. Windows MSI upgrade/rollback, installed-GUI, representative biological-data acceptance, crash-durable recovery and independent 1.1/1.6 Alembic 0038 reconciliation remain blocked. **Release HOLD.**

## Follow-up: missing-queue warning for protected bulk QC (2026-11-01)

The previous history-refresh warning appeared only when single-item
coordination was pinned. An unresolved **bulk** QC request already pinned its
queue and prevented navigation, but a background queue-list response that
temporarily omitted that queue left no explanation for the disabled controls.
This could prompt a researcher to discard or retry an uncertain review action
without first recognizing the history-list inconsistency.

The dashboard now uses the shared protected queue identity for the warning,
covering both coordination drafts and unresolved bulk review requests. The
warning explicitly states that protected QC work remains on its original
queue; it does not claim that a missing history entry is deleted. A regression
exercises a real queue-history refetch that omits the queue, confirms the
original host selection and bulk retry controls remain available, then
restores the listing and confirms the warning clears **without** clearing
the protected request. The researcher still resolves the request explicitly.

No biological annotations, reviewer decisions, audit events, API payloads,
database migrations, or saved executable `qc_review_queue` Workflow Builder
graphs/runs were changed. Existing typed provenance, idempotent retry, and
human-review gates remain authoritative. This is an in-memory UI safeguard,
not durable crash recovery or proof of installed-Windows acceptance.

**Release HOLD:** exact-head frontend/backend CI, independent 1.1/1.6
Alembic revision-0038 reconciliation, Windows MSI upgrade/rollback and
installed-GUI, representative biological-data acceptance and durable crash
recovery remain required.
