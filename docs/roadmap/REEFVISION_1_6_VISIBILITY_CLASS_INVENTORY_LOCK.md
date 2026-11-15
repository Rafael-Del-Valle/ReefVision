# ReefVision 1.6 — atomic class-inventory validation for persisted visibility

## Audited gap

The 1.6 branch already persists layer visibility per local researcher and per
project in SQLite (migration 0012), supports conditional revision/row-identity
saves, and retains typed executable `project_source → qc_review_queue`
Workflow Builder graphs. No new visibility table or workflow node is needed.

Both visibility PUT services previously checked hidden class IDs in one SELECT,
then issued their first write to the preference/default table. Another local
editor could delete a class after that SELECT but before the PUT committed. Since
hidden IDs are stored as JSON rather than foreign keys, the API could confirm a
new preference containing a no-longer-existing biological class and immediately
return a different sanitized value on the next GET.

## Change

`ClassVisibilityService._validated_hidden_class_ids` now acquires the SQLite
writer lock using a revision-preserving no-op UPDATE of the *project* before
reading the class inventory. It retains that transaction through the existing
conditional or legacy visibility save. Concurrent SQLite writers cannot delete
or edit classes during validation and commit; the project timestamp, source
observations, model predictions, dataset versions and Workflow Builder artifacts
are not modified. Unsupported class IDs still return the existing validation
error. Reset semantics, class deletion behavior and API payloads are unchanged.

This is a **local SQLite** serialization contract; it is not a distributed
collaboration mechanism and does not turn visibility into scientific evidence.
The project identity is validated before locking, with existing request-scoped
session rollback for invalid or failed saves.

## Regression and acceptance

`test_visibility_save_locks_class_inventory_until_commit` runs for both
per-user preferences and project defaults using a file-backed SQLite database.
It inserts a class, pauses after validation, attempts to DELETE that exact
class from a separate short-timeout connection and requires SQLite's writer
lock to reject the competing deletion. The original PUT must commit the hidden
ID, the bundle must return the same value, and a subsequent independent writer
must succeed after release of the lock. No test writes user research data.

The existing typed QC Workflow Builder node, immutable saved graph/run outputs,
unit contracts, explicit researcher-review gates and retries are unchanged:
visibility is purely a display preference rather than an analytical node.
Full exact-head CI, scientific acceptance, independent 1.1/1.6 Alembic-0038
reconciliation and Windows MSI/CAB installation/upgrade/rollback/installed-GUI
validation remain release HOLD requirements. No merge, tag or release approved.
