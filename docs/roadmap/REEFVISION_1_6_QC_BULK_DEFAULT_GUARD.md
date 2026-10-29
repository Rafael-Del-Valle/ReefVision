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
