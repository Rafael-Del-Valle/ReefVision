# ReefVision 1.6 — saved Workflow Builder review input integrity

The existing 1.0–1.5 review gates pause and resume executable local graphs. This
1.6 increment does **not** introduce a duplicate node, change scientific units,
or alter prediction records. It closes a missing-evidence approval path.

A researcher may approve a saved review gate only when its one typed input is
still bound to the same workflow run, exists, matches its original SHA-256
payload digest, carries no foreign project identifier (while accepting historical null hints), and is present in the
successful producer's persisted output list. For live prediction artifacts,
every referenced proposal/classification row must still exist in the same
project; absence is **not** equivalent to a reviewed prediction. Pending rows
continue to block approval. A rejected request leaves the workflow paused.

This is an integrity gate, not proof that a locally recomputed checksum is
cryptographically authoritative. Researchers must retain original data,
workflow graph revisions, input artifacts and audit logs. No data are repaired
or deleted automatically. The preexisting successful consensus-review
regression remains the positive path; new parameterized saved-graph tests
cover lost, duplicated, modified, wrong-type, foreign-project, detached
producer and absent-prediction inputs.

**Acceptance:** run backend Ruff, mypy and pytest, frontend lint/type/Vitest/
Playwright, persisted-workflow replay and native Windows installed-GUI
tests. Verify representative biological images before release, reconcile the
separate 1.1/1.6 Alembic-0038 histories, and obtain explicit researcher
approval. No release is authorized by this scoped change alone.
