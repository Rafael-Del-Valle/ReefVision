# ReefVision 1.6 — researcher-confirmed project default visibility reset

## Pre-existing functionality and gap

ReefVision already stores separate per-user class-visibility preferences and
project defaults for annotation, prediction, segmentation, QC, and video layers.
The backend already exposes a scoped DELETE for project defaults, and the
frontend mutation API already supports this action. The editor exposed
**Reset My Preferences** but no equivalent way to remove a saved project
default. Changing a project-wide default to an empty hidden-class list was
not equivalent to deleting the default: it still retained a saved scope,
editor attribution, and a different precedence state.

## GUI behavior

A **Reset Project Default** action is now available only after the current
project's visibility bundle loads and the selected layer actually has a saved
project default. A native confirmation describes project-wide consequences,
including that users without saved personal preferences or session
overrides will see all classes in that layer. Declining does not send a request. Accepting calls the existing
scoped DELETE, clears only the selected project/layer default in the local
cache on success, and disables the action when the default no longer exists.

Users' own saved preferences and their session overrides remain intact and
continue to take precedence. Other layers are unchanged. No annotations,
predictions, masks, scientific QC dispositions, dataset snapshots, or
Workflow Builder runs are modified. An HTTP failure follows the existing
visibility mutation error path and does not optimistically remove defaults.

## Regression and scientific boundaries

The AnnotationEditor component regression exercises an initially saved
personal preference alongside project defaults for two layers, cancellation,
positive confirmation, exactly one DELETE, preserved personal and
other-layer settings, absent annotation write requests, and disabled reset
after success. A separate regression simulates a failed first DELETE, checks
that the default is retained, and requires another explicit confirmation
before the second attempt can complete. A pre-load regression includes the new action among controls
that cannot mutate the wrong project before identity is known.

This is a UI/API completion of existing visibility functionality, not a new
analysis or a biological event, so no duplicate Workflow Builder node is
introduced. Existing executable `qc_review_queue` Workflow Builder support,
provenance, saved runs, retries and researcher-review gates remain unchanged.

Release remains **HOLD** until exact-head CI and end-to-end tests, independent
1.1/1.6 Alembic revision-0038 reconciliation, native Windows installed-GUI
and MSI upgrade/rollback checks, and representative scientific validation.

## Concurrent editor reset safety (2026-11-13)

The researcher-confirmed **Reset Project Default** now submits the saved
`updated_at` revision. A single conditional SQLite DELETE protects a newer
project/layer default from another editor's concurrent upsert. An outdated,
already deleted or recreated record returns HTTP 409 rather than removing newer
settings. The GUI refetches the authoritative visibility bundle and requires
a fresh confirmation before attempting another reset; missing revision
metadata disables project-default reset. Saved user preferences, other layers,
annotations, QC decisions and workflow artifacts remain unchanged.

For existing local API clients the revision query parameter is optional:
legacy unconditional DELETE remains available but is *not* concurrency safe.
The GUI uses the guarded path. Backend and frontend regressions cover stale
and current revisions, delete/recreate replay, preserved preferences, the
query-string revision and conflict refresh. Full exact-head CI and native
Windows installed-GUI/MSI upgrade tests remain acceptance gates.
