# ReefVision 1.6 — QC bulk registry server-default preflight

The 0041 migration declares all required bulk-review request fields without
server defaults. SQLite can satisfy a NOT NULL field with a default even if the
caller omitted the reviewer, project, queue, action, timestamp or request UUID.
Such a forged or partially altered schema would produce misleading provenance
in manual QC and saved Workflow Builder runs.

The read-only desktop migration guard now refuses any revision-0041 bulk
registry that supplies server defaults on required fields, while permitting
the optional human reason to remain nullable. This is schema validation, not
a repair, stamp, downgrade or change to researcher data.

Regression: `test_migration_bulk_defaults_16.py` exercises all seven required
fields plus a valid control, twice per schema, checking that the revision,
scientific observation, reviewer event and full table definitions remain
unchanged. The existing standalone and executable saved Workflow Builder QC
tests continue to cover actual review operations.

**Acceptance remains HOLD.** CI must pass on the exact new head; the independent
1.1/1.6 Alembic 0038 collision is unresolved. Windows MSI upgrade/rollback,
installed-GUI and representative biological-data acceptance remain required.

## Review-event attribution defaults (2026-10-29)

The same read-only 1.6 desktop guard now checks the 0038–0041
`review_queue_item_events` lineage for unexpected SQLite server defaults on
seven nonoptional audit identity/attribution fields: event ID, queue ID, item
ID, project ID, idempotency request ID, actor, and event timestamp. The actual
0038 migration does not define defaults for any of these fields. An altered
schema could otherwise invent a researcher or timestamp when a caller omits
one, even with an intact event-type CHECK and request-identity UNIQUE.

`test_migration_event_attribution_defaults_16.py` covers the 0038 and 0041
stamps, all seven forged defaults, and valid controls. Each case repeats the
preflight and checks unchanged coral observation, reviewer-event rows, Alembic
stamp, and complete SQLite table definitions. The Windows desktop packaging
preflight includes this regression. Independent SQLAlchemy/SQLite inspection
confirmed that all seven defaults are discoverable and the control is clean;
this is **not** an integrated ReefVision test pass.

This does not resolve the 1.1/1.6 duplicate revision IDs, certify real
researcher identity, or authorize an automated migration repair. Exact-head
CI, native Windows upgrade/rollback, installed-GUI and representative
biological-data acceptance remain **HOLD**. No review decisions or saved
Workflow Builder outputs are rewritten.
