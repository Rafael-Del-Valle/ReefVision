# ReefVision 1.6 — installed Windows QC exact-UUID retry acceptance

## Audited gap

The existing disposable Windows MSI acceptance harness already tests class visibility persistence, QC comment and assignment audit events, bulk review transitions, an executable saved `qc_review_queue` Workflow Builder graph, typed output provenance, restart persistence, and saved-graph replay. Those are not new features in this increment.

However, the previous bulk-QC smoke requests omitted `client_request_id`. A repeated *unkeyed* request can produce `changed_count = 0` simply because the item is already in the desired state. That does **not** demonstrate the durable exact-request identity needed for a lost HTTP response, a competing review action, or a packaged desktop restart.

## Hardened installed acceptance contract

On disposable test media, `scripts/acceptance-windows-clean-install.ps1` now:

1. Allocates a distinct stable UUID for each bulk skip, return, start, and explicitly confirmed complete action, and reuses the original serialized body for retries.
2. Checks immediate skip/completion retries produce no additional transition. The original QC event history still must contain exactly one of each six expected event types.
3. After completion, replays the **original start UUID** and requires `changed_count = 0`, an unchanged `completed` state and completion timestamp, and `requires_researcher_review = true`.
4. Stops and restarts the actually installed desktop and packaged API, then replays the **original completion and start UUIDs** against the restarted loopback endpoint. Both must remain no-ops and preserve the scientist-review gate, completion timestamp, audit history, queue scope, and unchanged source annotation.
5. Retains the existing installed saved-Workflow-Builder plan, run, artifact-integrity and after-restart replay checks. No standalone-only substitution or duplicate Workflow Builder node was added.

`scripts/test-windows-clean-install-harness.ps1` prevents a later refactor from silently removing keyed requests, stale-start replay, post-restart replay, or review-gate assertions. This is an acceptance-evidence improvement, not a database migration or a change to biological observations.

## Validation and limitations

The Windows build workflow runs the static PowerShell harness safeguards **before** packaging, then exercises the installed MSI in a separate disposable Windows runner. The new assertions only earn evidence once that exact-head workflow succeeds. A source guard or a successful build alone cannot prove installed GUI usability or upgrade/rollback behavior.

The full version 1.6 release remains **HOLD**, pending current-head backend/frontend/E2E and Windows acceptance evidence, reconciliation of the independent 1.1/1.6 Alembic revision-0038 collision, representative scientific review, actual GUI interaction, and native MSI upgrade/rollback. Never use a real researcher installation or research data for this harness, and never acquire unapproved pretrained models.

See [master issue #76](https://github.com/Rafael-Del-Valle/ReefVision/issues/76) and [draft PR #77](https://github.com/Rafael-Del-Valle/ReefVision/pull/77).
