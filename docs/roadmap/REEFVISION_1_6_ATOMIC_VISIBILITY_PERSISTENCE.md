# ReefVision 1.6 — atomic persisted class-visibility saves

## Gap audited

Class visibility is already implemented for annotations, predictions, QC overlays,
video tracks, and segmentation overlays. Project defaults and per-local-user
preferences are isolated by project, user identity and layer and have durable
SQLite unique constraints (migration 0012). The existing saved, executable
`qc_review_queue` Workflow Builder node handles scientific QC and keeps its
researcher-review gate. This increment does **not** duplicate either capability.

Previously, visibility saves performed a separate SELECT followed by INSERT
on the first write. Two windows or workers could both observe no preference
or project default and one INSERT could fail with a unique-constraint error,
leaving a valid visibility edit unsaved. The existing UNIQUE indexes should
be the arbitration point, not a pre-insert ORM existence check.

## Implementation and scientific limits

Both scope writers now use local SQLite `INSERT .. ON CONFLICT DO UPDATE`
with their existing exact unique keys. The complete, validated class-ID list
is replaced atomically; the row ID and creation timestamp are retained when
updating. The update timestamp is refreshed, and project-default attribution
is replaced with the actual local editor identity. The service reads back the
committed row and fails with an explicit conflict if another editor deleted
the scope immediately after commit.

Independent keys remain separate: project, user, layer for preferences;
project and layer for defaults. Competing writes to the **same** key follow
last-committed-write-wins. This is not conflict-free collaborative editing or
optimistic version locking; it does not merge simultaneous checkbox changes.
Do not use saved class visibility to infer scientific review or detection
confidence, and do not mutate annotation, prediction, calibration, dataset,
or Workflow Builder run records in this code path.

No schema migration is necessary (migration 0012 already enforces both
uniqueness contracts). No network access or cloud synchronization is added.

## Regressions and outstanding evidence

`test_atomic_visibility_upsert_preserves_scopes_after_stale_first_reads`
makes two independent SQLite sessions each read the still-absent preference
and default, then saves through both sessions. It checks one persistent
row per scope, most recent values and default-editor attribution, and a public
API update that reuses the original row IDs. Existing restart, reset and
foreign-project-class rejection tests are retained.

The new regression is deterministic and does not claim to simulate live
two-process contention. Full backend pytest/Ruff/mypy, frontend tests and
Windows installed-GUI acceptance remain required. The independent 1.1/1.6
Alembic revision-0038 conflict is unchanged and remains a release blocker.
