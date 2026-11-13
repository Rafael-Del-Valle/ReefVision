# ReefVision 1.6 — version-conditional class visibility saves

## Audit and gap

ReefVision already supports per-user/per-project class-visibility persistence,
atomic SQLite upserts, and optimistic revision protection for reset/delete.
The editor's **save** action nevertheless used an unconditional PUT, so an older
window could overwrite a newer visibility change made to the same saved scope.
Neither a reset-only guard nor a unique database index prevents that lost update.

## API and storage contract

The existing PUT body now accepts optional `expected_updated_at`:

- **Field omitted:** retained legacy local-client behavior, an atomic upsert.
- **Field explicitly null:** create the scope only if it is still absent.
- **Field a timestamp:** update only when the project's/user's/layer's saved
  record still has precisely that timestamp.

SQLite's unique scope index and `INSERT ... ON CONFLICT DO NOTHING` make
first-write conflicts atomic. An `UPDATE ... WHERE updated_at = ?` protects
later saves. Both report HTTP 409 on a missing, newer, deleted or recreated
revision. The saved classes and actor attribution remain unchanged on conflict;
the requester must reload authoritative settings and explicitly save again.
The editor always includes its observed revision, including null for a confirmed
absent scope; legacy API integrations without the field stay compatible.

This is distinct from an idempotency key: repeating a successful conditional
save with the same old token returns a conflict, not a second write. The GUI
refreshes the authoritative visibility bundle after any failed save or reset.
No stale merge or automatic re-application is performed.

## Scientific and Workflow Builder boundary

Visibility preferences affect display only, never underlying annotations,
predictions, immutable dataset versions, QC decisions or model results. No
migration or new scientific Workflow Builder node is necessary. Existing typed,
saved and executable `qc_review_queue` workflows, provenance and explicit
researcher-review gates are unchanged. This does not replace the independent
1.1/1.6 Alembic-0038 reconciliation requirement.

## Regression and acceptance

Backend `test_class_visibility.py` covers create-once collisions, stale
updates, post-delete stale writes, read-back isolation and legacy PUTs for both
personal and project-default scopes. `AnnotationEditor.test.tsx` checks
explicit null on first save and conflict-triggered refresh of the newer
personal preference without modifying scientific data.

Exact-head CI lint/type/backend/frontend/E2E and Windows installed-MSI/GUI
testing are required before claiming acceptance. This change does not constitute
a verified release; the native installer upgrade/rollback, representative
biological-data tests and cross-version migration issues remain release blockers.

## Monotonic revisions under clock rollback

The 1.6 conditional save path derives a new microsecond-precision timestamp
strictly greater than the observed saved timestamp, even if the workstation's
wall clock stops or moves backwards. Both personal and project-default scopes
share this guard. Without it, a successful save could reuse the old timestamp
and a second stale editor could overwrite or remove the new visibility settings
despite its optimistic-concurrency check. An aware or naive SQLite timestamp is
normalized to UTC before calculating the next revision. Client request/response
formats, existing tables and legacy unversioned PUT compatibility are unchanged.

The guard applies to **conditional** saves only; historical unconditional PUTs
remain supported for older local integrations, and revisions are not a globally
ordered time-series clock. A monotonic visibility timestamp should never be
used as biological observation time, camera timing or scientific event evidence.
This is a display-preference consistency fix, not a research Workflow Builder
feature. The existing typed and persisted QC review workflow remains unchanged.

The parameterized API regression in `test_class_visibility.py` forces the
clock one day backwards for consecutive conditional saves of both visibility
scopes, verifies strictly advancing revision tokens, rejects stale save/reset,
and confirms the latest settings remain intact. Full repository CI and native
Windows installed-GUI/installer validation are still required for acceptance.

## Row identity protects against delete/recreate ABA

Each saved scope also exposes optional `record_id` (its existing UUID primary
key). A client may supply `expected_record_id` alongside a timestamp on PUT
or DELETE to atomically protect against a deleted/recreated scope with an
identical timestamp. A stale row ID yields HTTP 409 without mutation. Older
timestamp-only API clients remain compatible, but lack this ABA protection.
These are display preference tokens, not biological event timestamps or
organism identities. No migration or duplicate Workflow Builder node is added.

## Legacy unconditional saves must invalidate modern editor tokens

Older offline clients may omit `expected_updated_at` and continue to perform
unconditional PUTs. Their SQLite `ON CONFLICT DO UPDATE` previously used the
wall clock directly, which could regress or repeat the saved timestamp if a
workstation clock froze or moved backward. A modern editor holding the earlier
revision could then overwrite that intervening legacy save.

The 1.6 SQLite upsert now computes a strictly increasing microsecond revision
**inside the atomic conflict update from the database's current row**, not
from an unprotected preliminary read. It carries `.999999` into the next
second. The existing row UUID and creation time remain stable; two older
clients still have last-committed-writer behavior, but a version-aware client
cannot silently reuse its stale timestamp after an older client writes.

Parameterized API regressions cover both personal and project defaults,
a frozen/backdated clock, repeated legacy saves, the microsecond rollover,
preserved record identity, and stale conditional saves/resets returning 409.
These changes affect display preferences only; no new Workflow Builder node,
scientific observation mutation, model download or migration is involved.
Full repository CI and native Windows installed-MSI/GUI checks remain required.
