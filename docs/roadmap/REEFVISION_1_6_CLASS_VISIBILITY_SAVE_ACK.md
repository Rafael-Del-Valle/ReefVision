# 1.6 class-visibility save acknowledgement (offline/local editors)

Personal and shared-project class visibility are already persisted independently and
the editor uses revision/record-ID compare-and-save. The original API saved a
visibility scope, committed, **then** re-read its record for the PUT response.
A second local editor could commit between those operations, causing the first
PUT to report the second editor's hidden classes, author identity or revision as
its own save result. That is a misleading acknowledgement, even if both SQL
transactions are individually correct.

Both 1.6 save paths now materialize their exact record ID, revision and saved
hidden-class state **before** releasing the SQLite writer lock; the HTTP
response is returned only after that transaction successfully commits. The
current editor receives the state of its own successful transaction. A later
editor's newer state is visible in the next GET, as expected. A subsequent
conditional PUT using the first response's revision then rejects the stale
write with HTTP 409 instead of replacing the newer revision.

The database-backed regression covers personal and project-default scopes,
both revision-checked and backwards-compatible legacy PUTs, and interleaves
a second independent writer's commit immediately after the first transaction
commits, before the first HTTP response is assembled. It verifies the returned
revision, the later GET, second editor attribution and stale CAS rejection.

No historical preferences or classes are rewritten, no new migration or
Workflow Builder node is introduced, and no annotation or model review is
automatically approved. This is a local user-interface persistence contract,
not an analysis/measurement workflow capability; existing typed persisted
executable QC workflows remain unaffected.

**Acceptance limits:** database-backed tests and CI are not substitutes for
installed Windows multi-editor GUI tests. Other 1.6 release holds remain:
independent 1.1/1.6 migration-history reconciliation, representative research
data and saved-workflow validation, MSI/CAB install/upgrade/rollback and
installed-GUI validation, and explicit researcher approval.

## Convenience-action identity parity (2026-11-16)

The editor's ordinary **Save as My Preference**, **Save as Project Default**
and explicit reset actions already sent both the observed UTC revision and the
persistent record ID. Three convenience paths did not: copying the current
visibility into project defaults, applying a saved default to personal
preferences, and applying an absent project default (deleting a saved personal
preference). Their timestamp-only precondition could match a distinct,
recreated record with the same timestamp, defeating the existing database
record-ID anti-ABA protection.

All three paths now pass the originating scope's `expected_record_id` along
with `expected_updated_at`. No locally hidden class is silently promoted to
a verified biological observation. The UI still surfaces HTTP 409 and reloads
authoritative visibility state if another editor has replaced the record.

Three parameterized component regression cases exercise the actual controls,
including both the conditional PUT and conditional DELETE HTTP paths, verify
the record ID is transmitted, and require failed conditional requests to
refetch instead of falsely acknowledging a successful update. The backend's
existing database-backed identity/revision tests remain in force. No data
migration, model download, new Workflow Builder node, or scientific asset
change is needed for these display-only preferences. Release remains HOLD
pending native Windows GUI/installer, cross-version migration, representative
science and complete exact-head CI checks.
