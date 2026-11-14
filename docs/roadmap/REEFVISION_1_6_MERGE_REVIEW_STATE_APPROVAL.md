# ReefVision 1.6 — legacy Merge approval binds researcher review state

The existing Class Manager usage review and legacy Merge endpoint already
support an `expected_usage_fingerprint`, which the local UI supplies with
the reviewed reference counts. Previously that fingerprint was computed from
reference IDs only. Changing a prediction from pending to reviewed, changing
a QC issue from open to acknowledged, changing a queue item from pending to
in-progress/completed, or changing its persisted queue owner could leave
the approved fingerprint unchanged while altering which observations Merge
would relabel. This is unacceptable for reviewed coral evidence.

The local fingerprint now includes sorted prediction-review states, QC issue
states and complete biological class memberships, and queue-item review
states, memberships, queue IDs and persisted creator identities. Record
identity and count categories remain unchanged. An old approval token must
be refreshed; the API rejects changed evidence with HTTP 409 *before*
modifying annotations, proposals or QC records. This remains **local
optimistic concurrency**, not a cryptographic researcher signature.

A real saved `project_source -> qc_review_queue` Workflow Builder graph
regression creates dimensionless priority evidence with
`requires_researcher_review`, persists artifacts, changes its review state
under the same item ID, verifies rejection of the prior Merge approval,
restores the review, then successfully merges while preserving the original
workflow-owned biological evidence, artifact checksum and saved-node retry.
A separate existing database-backed class-usage regression checks that
prediction, QC, queue-review and queue-owner changes invalidate approval
without changing record counts.

**Limitations:** older local scripts that omit
`expected_usage_fingerprint` retain their legacy Merge contract; this
enhancement does not make the merge transaction itself an atomic
check-to-write operation across competing SQLite writers. Native Windows
installed-GUI and MSI clean-install/upgrade/rollback, representative
biological datasets, and independent 1.1/1.6 Alembic-0038 reconciliation
remain acceptance requirements. No separate Workflow Builder node,
migration, external service or pretrained model is introduced.
