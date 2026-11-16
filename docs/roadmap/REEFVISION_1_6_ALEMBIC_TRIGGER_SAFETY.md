# ReefVision 1.6: reject executable Alembic stamp triggers before desktop upgrades

**Scope:** read-only SQLite safety check, not a migration or new workflow node.

ReefVision 1.6 and the independent 1.1 branch currently assign distinct migrations
the same Alembic revision `0038`. The existing desktop guard rejects conflicting
schema history; it must also reject any unreviewed SQLite trigger attached to
`alembic_version`. When Alembic inserts, updates or deletes its revision marker,
such a trigger could run SQL against preserved research observations or reviewer
history even when the version table's columns and revision string appear valid.

The desktop's `assert_compatible_revision_0038` now checks the SQLite catalog
*before* any Alembic write, including on the already-at-head path, and refuses
stamp-table triggers without executing or dropping them. The standalone read-only
`inspect-alembic-lineage.py` reports only a trigger count and the warning
`alembic_version_triggers_require_review`, never executable SQL, trigger names,
biological notes or row contents. Strict CLI mode exits with status 2. Unrelated
research-table triggers are not mistaken for stamp triggers.

Regression fixtures exercise INSERT, UPDATE and DELETE triggers capable of
deleting a sentinel research observation, an otherwise valid historical
revision, strict and informational inspector output, unmodified file bytes,
a trigger-free QC 0039 control and an unrelated research-table trigger.
All fixtures are disposable; no user SQLite file or version stamp is modified.

**Remaining release blockers:** the independent 1.1/1.6 0038 collision requires a
reviewed, data-preserving reconciliation, complete exact-head CI and scientific
workflow acceptance, genuine Windows MSI/CAB installation/upgrade/rollback,
installed-GUI testing and explicit researcher approval. This check does not
authorize an upgrade, replace immutable backup verification, or imply 1.6
release readiness. It is intentionally not an executable Workflow Builder node
because it checks local desktop startup safety rather than scientific analysis.
