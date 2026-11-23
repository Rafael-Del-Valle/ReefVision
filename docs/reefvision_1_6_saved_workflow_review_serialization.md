# ReefVision 1.6 — single-decision review approval (release HOLD)

## Audit and gap

The 1.0–1.5 saved Workflow Builder already persists typed graphs, artifacts,
runs and explicitly paused human-review gates. Track D 1.6 already validates
artifact checksums, the producing node, project provenance and the existence
of biological prediction records. This change does **not** add another node,
change historical data, or permit automatic scientist approval.

Before this change, two API callers using separate SQLite sessions could both
read `waiting_for_review` before either committed, then both attempt consensus
annotation materialization or overwrite the approval attribution. An unrelated
writer could also change a prediction or cancel the workflow after the approval
request's initial read.

## Behavior

- For local SQLite, approval acquires `BEGIN IMMEDIATE` **before the first
  node/run/job/artifact/prediction read**. The writer turn spans evidence
  validation, any authorized consensus materialization and the final commit.
- A second approver re-reads the committed gate state and gets a domain
  conflict, rather than authorizing a second approval. SQLite busy/locked
  contention is a retryable conflict, not a fabricated approval.
- An already-open SQLite read transaction is rejected: the researcher must
  reload rather than approve using a stale snapshot.
- Original image pixels, dataset snapshots, prior annotation history,
  review-required semantics, typed scientific units and saved workflow graphs
  are untouched. No migration or pretrained model is needed.
- This serialization guarantee is specifically for the supported local
  SQLite runtime; validate alternate database backends separately before
  treating them as production-safe.

## Acceptance evidence required

`test_workflow_review_serialization_16.py` exercises competing human
approvals of a real, persisted and executable Workflow Builder graph, tests
that a second reviewer cannot inspect the first reviewer's uncommitted input
snapshot, and verifies no reviewer decision is recorded on a stale read
transaction. Existing standalone review and persisted-graph tests still
exercise input hash/provenance and pending prediction refusals.

Release remains **HOLD** pending full backend/frontend/Windows CI, resolution
of the 1.1/1.6 Alembic-0038 collision, representative biological saved-workflow
science review, genuine Windows MSI/CAB clean installation, upgrade/rollback
and installed-GUI validation, and explicit researcher acceptance. No merge,
tag, release, deployment, paid hosting or asset deletion is authorized.

## 2026-11-23: unique model-prediction evidence (release HOLD)

The review-gate audit found an independent scientific integrity gap in the
already-typed saved input payload: duplicate IDs in `proposal_ids` or
`prediction_ids` were silently collapsed into a set. This could mask
malformed exported prediction evidence and make the saved model-output count
disagree with the actual reviewed observations. After existing string and
nonblank validation, all supported proposal and classification inputs now
reject repeated identifiers **before** any approval or evidence count. This
does not reject a legitimate empty list or require pretrained downloads, and
does not alter older saved graphs or source observations.

Regression coverage includes a *persisted and executable* review workflow with
a rehashed but duplicate-ID input artifact, asserting an HTTP 400 refusal,
the original waiting review/run/job status and no fabricated approval; plus
standalone checks for detection, mask and classification prediction lists.
The existing positive saved-workflow resume/finish test covers compatibility.
No migration or new Workflow Builder node is required because this strengthens
the execution-time validator for existing typed artifacts; explicit human
review remains mandatory. Passing full exact-head CI and real Windows
installed-GUI scientific acceptance must be verified before release.
