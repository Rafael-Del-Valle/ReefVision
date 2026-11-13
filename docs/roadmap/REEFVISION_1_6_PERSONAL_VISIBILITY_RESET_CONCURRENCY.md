# ReefVision 1.6 — version-conditional personal visibility reset

A saved class-visibility preference is scoped to a local user, project and layer.
Two windows using the same user identity can edit that preference independently.
Before this change, `Reset My Preferences` issued an unconditional DELETE,
which could erase a newer preference saved by a second window.

## Persistence and API

The optional `expected_updated_at` query parameter on
`DELETE /api/v1/projects/{project_id}/class-visibility/preferences/{layer_type}`
uses an atomic SQLite predicate on project ID, user identity, layer and saved
revision. A stale or already-deleted revision returns HTTP 409 and does not
remove the newer row. Existing local API clients without a revision token retain
their historical behavior. No migration is necessary; the pre-existing unique
scope constraint and timestamp are reused.

## UI and scientific boundary

`Reset My Preferences` is enabled only when the current layer has a saved
personal preference and a loaded timestamp. Its request includes the exact
observed revision. A failed reset invalidates the cached visibility bundle,
so another window's changes are reloaded before a new action. When no project
default exists, `Apply Project Defaults to My Preferences` uses the same
conditional reset for a saved personal preference and does not send a
delete when none was saved. The no-preference/no-default `Apply Project Defaults` action clears the
unsaved session visibility override; the persistent personal reset never
modifies a session override itself. Project defaults, scientific annotations,
predictions, review decisions and saved workflow artifacts are untouched.

This is UI persistence, not a new scientific analysis. The previously shipped
typed, executable `qc_review_queue` Workflow Builder and researcher approval
gates remain the authoritative path for QC work and are not duplicated here.

## Regression and release requirements

`test_class_visibility.py` exercises stale revisions, successful
conditional deletion, deleted/recreated record replay, legacy API callers
and other-layer isolation. `AnnotationEditor.test.tsx` exercises the
exact revision token, cache update, no scientific writes, disabled action
after deletion, and stale-reset refetch/recovery.

These tests must pass the exact-head backend/frontend CI gates. The independent
1.1/1.6 Alembic-0038 conflict, representative biological acceptance, native
Windows MSI/CAB install/upgrade/rollback and installed-GUI validation remain
release blockers. No automatic scientific approval or deletion of research
records is authorized.
