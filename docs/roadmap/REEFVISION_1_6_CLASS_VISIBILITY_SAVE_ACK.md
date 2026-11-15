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
