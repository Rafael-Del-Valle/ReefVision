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

This test covers the **standalone manual review APIs** and the **saved
executable Workflow Builder** on the same migrated installation. It is not
a new scientific algorithm or a replacement for existing unit tests.

## Release limitations

The independent 1.1 branch also uses revision `0038` for different
scientific tables. This test intentionally exercises only the isolated 1.6
migration lineage and **does not** reconcile or approve mixing the two
branches. Do not stamp, rewrite or delete user databases to resolve it.

Exact-head CI, native Windows MSI upgrade/rollback, installed interactive
GUI and real biological-image performance/scientific acceptance remain
mandatory. A passing disposable SQLite regression is not release readiness.
No pretrained model downloads, external services, user-asset deletion or
automatic scientific approval are involved.
