# ReefVision 1.6 — real desktop upgrade and executable QC acceptance

## Purpose

The isolated 1.6 lineage has a real SQLite/Alembic migration path from revision
`0037` to `0041`. A successful migration marker alone does not prove that an
installed desktop can create a persisted Workflow Builder graph, execute the
`qc_review_queue` node, preserve review-required scientific provenance, and
reopen its review history without losing researcher actions.

`apps/api/reefvision/tests/test_desktop_workflow_upgrade_16.py` adds an
end-to-end API-level regression against a disposable on-disk database:

1. Upgrade a real Alembic `0037` database containing a legacy project,
   `Swiftia exserta` class, project visibility default and an explicitly
   saved empty local researcher override.
2. Migrate using the actual desktop startup migration path, import an image,
   plan and save a typed `project_source -> qc_review_queue` graph, and
   execute its queued workflow job.
3. Verify a persisted `review_queue_reference` with dimensionless priority
   scores, `requires_researcher_review` status, and an unchanged scientific
   artifact checksum.
4. Record a manual comment, reviewer assignment and bulk triage start.
   Verify that missing researcher confirmation cannot complete the review
   and that no image annotation is silently approved.
5. Reopen the same database with a new application instance and confirm
   persistence of the workflow run, typed artifact, audit history, reviewer
   assignment, in-progress state, visibility override and original
   unverified image observations. An idempotent comment retry must not
   duplicate reviewer history.
6. Re-enter the persisted QC node twice after restart, using its original
   typed project-source artifact and saved execution parameters. Require the
   same queue ID, scoring checksum, in-progress state, reviewer assignment,
   three audit events and no newly verified annotations. No second queue may
   be created for the original node-run identity.
7. After the real upgrade and restart, persist a deliberately incorrect
   scientific item-evidence digest in the existing queue. Require the
   executable QC adapter to reject the interrupted replay without changing
   the researcher's in-progress state. Restore the original digest, then
   confirm two deterministic successful retries and unchanged audit history.
   The test never recomputes model outputs or silently approves annotations.

This test covers the **standalone manual review APIs** and the **saved
executable Workflow Builder** on the same migrated installation. It is not
a new scientific algorithm or a replacement for existing unit tests.

## Release limitations

The independent 1.1 branch also uses revision `0038` for different
scientific tables. This test intentionally exercises only the isolated 1.6
migration lineage and **does not** reconcile or approve mixing the two
branches. Do not stamp, rewrite or delete user databases to resolve it.

The post-restart replay is an adapter-level retry, not a second queued workflow
job. The existing saved-workflow execution and standalone API are both covered;
no background worker or model download is required. The test still cannot
prove interactive Windows GUI behavior or installation rollback safety.

Exact-head CI, native Windows MSI upgrade/rollback, installed interactive
GUI and real biological-image performance/scientific acceptance remain
mandatory. A passing disposable SQLite regression is not release readiness.
No pretrained model downloads, external services, user-asset deletion or
automatic scientific approval are involved.

## Ambiguous saved-QC ownership safeguard

A persisted `qc_review_queue` node must have **at most one** review queue
with its exact `workflow:<run-id>:<node-id>` creator identity in the same
project. The adapter now reads up to two matching queues before retrying:
if two exist, it rejects replay rather than selecting an arbitrary historical
snapshot. It neither deletes a queue nor rewrites researcher decisions.

`apps/api/reefvision/tests/test_workflow_duplicate_queue_16.py` exercises
a real saved executable graph and an initial successful retry, records a
researcher comment, injects a second queue with the same owner into a
disposable test database, and requires a controlled validation rejection.
The regression verifies preservation of both queues, the original comment,
the review-required artifact and unverified image annotations.

This is a **replay safety check**, not a database uniqueness migration or
proof of atomic queue creation under concurrent workers. A separate reviewed
transaction/uniqueness design would be needed to prevent all races without
breaking historical duplicate records. The 1.1/1.6 revision-0038 collision
and native Windows installed-GUI/installer acceptance remain blockers.
