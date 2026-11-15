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

## Consistent visibility GET snapshots (2026-11-15)

Class-visibility GET must also be consistent under concurrent local edits.
SQLite's legacy deferred SELECT behavior can otherwise produce a response
whose class inventory and personal hidden-class settings were read before an
independent editor's commit, but whose shared project defaults were read
*after* that commit. This is display state, not biological observation data,
but inconsistent local layer visibility can still mislead a researcher.

`ClassVisibilityService.get_bundle` now starts an explicit SQLite read
transaction before its first project/class/scope query, unless the caller
already has an active DBAPI transaction. Existing transactions remain owned
by their caller. No write lock, schema migration, model change, cloud
communication, or data mutation is introduced. On SQLite WAL databases an
independent writer can commit while a bundle is read; the bundle retains its
original coherent snapshot, and a subsequent GET observes the new state.

`test_visibility_bundle_uses_one_snapshot_across_concurrent_scope_updates`
forces a separate writer to commit a new project default between personal
preference and project-default reads on a real SQLite WAL database. It checks
the first GET returns the earlier defaults, the later GET sees the new
defaults, and neither GET modifies research records. The test is deterministic
database-level evidence, not an installed-Windows GUI or multiprocessing
benchmark. Existing saved, typed executable QC Workflow Builder nodes and
researcher-approval gates are unchanged; per-editor visibility is deliberately
not injected into scientific workflow results.
