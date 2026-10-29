# ReefVision 1.6 — independent-process QC workflow race acceptance

**Scope:** isolated Track D 1.6 development, draft PR #77. This regression
closes a previously untested part of the SQLite queue-identity safety gate:
two independent OS processes executing the same persisted
`project_source -> qc_review_queue` graph against one local database.

## Executable contract

`apps/api/reefvision/tests/test_workflow_queue_multiprocess_16.py` creates
a synthetic project and image through the ordinary API, saves and executes a
real typed workflow, then models an interrupted initial queue creation.
Two separately launched Python processes open independent SQLAlchemy engines,
wait at a filesystem start gate, and attempt the same saved QC node.

The test requires:

- Each successful output to retain the original deterministic queue identity,
  `review_queue_reference` type, dimensionless priority units and explicit
  `requires_researcher_review` state.
- A competing process to either reuse the same queue or fail closed with a
  controlled retry request; no independent replacement queue is permitted.
- Exactly one workflow-owned queue in SQLite after both processes finish,
  followed by a successful saved-node replay with the same identity.
- The imported synthetic image to remain unverified; no prediction is silently
  promoted to a researcher-confirmed biological observation.

The test uses a temporary local database, no cloud services and no downloaded
model weights. It exercises the production QC adapter and actual SQLite
process isolation, not merely an in-memory mocked exception. Existing
standalone queue and saved-workflow tests remain necessary complementary gates.

## Validation and release boundaries

**Pending:** execute this regression in GitHub Actions and on an installed
Windows build. Source inspection and a separate SQLite primary-key reproduction
are not substitutes for passing the full test. Do not claim release readiness
from this test alone.

**Still blocked:** independent 1.1/1.6 Alembic revision-0038 reconciliation;
Windows MSI clean install, upgrade/rollback and interactive GUI; representative
biological-data acceptance; full exact-head lint, typing, backend, frontend,
E2E and migration checks. No other version branch is merged here.

## 2026-10-29 — exact-head CI triage and independent review preservation

CI run 40818779675 on `66e87711` reported two backend Ruff failures:
I001 in the multi-process test import/comment spacing and RUF043 in the
SQLite UNIQUE-constraint regex assertion. Both reported locations were
corrected without changing production queue creation or scientific scoring.

The independent-process regression additionally creates a separate
researcher-owned standalone QC queue, writes a review comment through the
normal event API, and verifies the comment ID, event count, and item identity
after the two saved-workflow writers race. This explicitly tests that
concurrent workflow recovery does not overwrite an unrelated researcher's
review history. It complements the existing single-process lock test.

**Verification boundary:** GitHub blob read-back confirms the changes;
exact-head backend pytest, Ruff, type checks, frontend/E2E, and Windows
installed-GUI acceptance must still be checked in CI. Do not treat a queued
or cancelled CI run as a pass. The cross-version Alembic 0038 conflict,
native MSI upgrade/rollback, and biological acceptance remain HOLD.
