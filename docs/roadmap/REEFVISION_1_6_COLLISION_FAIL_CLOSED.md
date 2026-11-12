# Lineage collision gate: uncertain evidence fails closed (1.6)

The read-only SQLite inspector's `--fail-on-lineage-collision` gate now exits 2 when independent databases have unequal schema fingerprints **or** their validated Alembic revision markers do not match. Previously a missing/malformed/different revision could cause a false success because the collision predicate only checked equal valid stamps. A successful gate still requires researcher review and is not evidence of equivalent migration history.

This stricter optional gate does not change the default inspection behavior, does not alter databases, and does not automatically reconcile the independent 1.1/1.6 revision-0038 histories. `--fail-on-noncanonical-stamp` remains separately opt-in for legacy tables without PK/NOT NULL constraints.

Regression: `test_collision_gate_fails_closed_on_uncertain_revision_evidence` covers equal revisions/equal schemas, equal revisions/divergent schemas, unequal revisions/equal schemas, and absent reference revision. It checks JSON review status, confidential record exclusion and byte preservation. Full exact-head CI and Windows installed-GUI validation are required before release.
