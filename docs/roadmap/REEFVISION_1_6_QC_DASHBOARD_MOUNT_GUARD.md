# ReefVision 1.6 — QC dashboard coordination lifetime guard

## Audited gap

The coordination component already retains unsent notes, reviewer-assignment drafts and uncertain idempotency UUIDs in item-keyed in-memory maps. Its A → B → A regression tests exercise **a reused component instance**. The production `ReviewQueueDashboard`, however, supplied `key={`${selectedQueueId}:${coordinationItemId}`}`, forcing React to unmount the panel every time the researcher opened another item. This discarded those maps despite the component-level safeguards.

## Bounded fix

- Reuse the mounted coordination panel across item navigation within the selected queue; the panel's existing queue/item/epoch keys keep drafts and retries isolated.
- While coordination is open, disable changing queue scope, dataset version, selected historical queue, and queue regeneration/generation. Explain the guard in the dashboard. The researcher must close coordination using the panel's existing explicit discard and uncertain-event controls before switching queues.
- Preserve original scientific annotations, queue items, audit-event records, UUIDs and existing API/database contracts. No automatic review completion or biological verification is introduced.
- Do not add another Workflow Builder node: the existing typed executable `qc_review_queue` node, saved graphs/runs, provenance, idempotent server retries and researcher-review gates are unchanged. This is a frontend lifetime fix, not an analysis transform.

## Regression and limitations

The dashboard component test now exercises two items in one queue, verifies that an unsent draft for A survives opening B and returning to A, and verifies queue/scope mutation controls are disabled while coordination is open. The real coordination panel's separate tests cover item-keyed notes, assignment drafts, uncertain UUID retries and explicit close confirmation.

This guard does **not** provide durable recovery after application termination, a full page reload or navigation to another project/workspace outside the dashboard. Such recovery requires a separately reviewed local retention/privacy policy and persisted request registry; do not claim it here. Installed Windows GUI and MSI upgrade/rollback still require native acceptance. The independent 1.1/1.6 Alembic 0038 lineage conflict remains unresolved.

**Release status: HOLD** pending exact-head frontend/backend CI, migration integration, native Windows validation and representative biological-data acceptance.
