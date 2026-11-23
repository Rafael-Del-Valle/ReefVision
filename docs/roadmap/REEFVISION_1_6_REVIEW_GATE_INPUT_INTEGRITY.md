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

## Verified API failure contract and pause preservation (23 November 2026)

The exact-head backend CI for the original regression reported **2,394 passing,
32 skipped and nine failures**. All nine new corruption cases correctly refused
approval with HTTP **400** and an explicit domain-validation reason; the tests
incorrectly expected HTTP 422, which applies to FastAPI request-shape
validation, not the application's `ValidationError`. The scoped correction
asserts the actual nine individual refusal reasons, retained review-node
`waiting_for_review` state, no approval record, and the parent job remaining
`waiting_for_review`. This does not weaken any scientific input check, convert
a refusal to approval, or change the production API contract. The original
consensus-review positive path is still covered separately.

Do not claim the updated tests pass until exact-head CI completes. Genuine
Windows installer/GUI, representative biological acceptance, Alembic-0038
cross-version reconciliation and explicit researcher approval remain open.

## Rehashed saved-graph typed-port enforcement (23 November 2026)

A saved review's SHA-256 and the persisted graph edge are necessary, but an
altered graph can be recomputed with matching hashes. The previous edge check
confirmed source node/output labels and only required a nonempty target port:
it did not verify those labels against the executable node registry. A
consensus artifact could also have its data type switched to another
review-gate-accepted type even though its original producer cannot emit it.

At approval, the existing pause gate now resolves the node types through the
same installed Workflow Builder registry used for executable graph planning.
The exact source output and target input ports must exist and **both** must
accept the original artifact's stored scientific data type. Unknown or
incompatible port claims fail closed without reassigning or deleting media,
observations, original review records or predictions. The check applies
equally to detection, segmentation, classification, pose and pose Active
Learning review nodes, including earlier registered pose extensions. The
Workflow Builder graph, persisted run, units, retry behavior and human approval
requirement remain unchanged; no duplicate workflow nodes or migration.

Three additional parameterized persisted-graph regressions rehash forged
source/target edges or substitute a producer-incompatible data type, assert
the direct service and HTTP approval both reject them, and preserve the
waiting run, review node, original parent job and unrecorded approval. The
preexisting successful consensus review regression is the positive control.

Full new-head CI, biological domain checks, the independent 1.1/1.6
Alembic-0038 reconciliation and installed Windows MSI/CAB GUI/upgrade/rollback
remain release blockers pending independent proof and researcher signoff.
