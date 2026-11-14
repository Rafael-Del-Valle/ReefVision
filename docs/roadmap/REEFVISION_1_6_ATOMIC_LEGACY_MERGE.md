# ReefVision 1.6 — atomic local approval for legacy class Merge

## Audited gap

The existing Class Manager Merge UI submits reviewed class identities, source
usage counts and a SHA-256 inventory fingerprint. The service checks those
against the current local project, preserves completed review decisions and
saved Workflow Builder QC evidence, and commits changed annotations,
predictions, selected QC references and source archival in one transaction.

Before this increment the first database write followed the approval checks.
A second local SQLite connection could change an observation or review
decision between the fingerprint check and the merge's commit. The approved
evidence was therefore not guaranteed to represent the committed operation.

## Change and invariants

The legacy `ProjectService.merge_class` now issues a no-op `label_classes`
UPDATE on the source class **before any source/target or usage reads**.
SQLite takes its database writer lock at this first statement and holds it
until the existing scientific merge commit. The UPDATE leaves the stored class
`updated_at` revision unchanged. A competing local writer cannot change
biological membership, QC status, target identity or workflow review evidence
between approval validation and the scientific transaction commit.

The endpoint and request schema are unchanged. Missing classes remain
not-found; stale identity or count/fingerprint approvals still return HTTP
409; older scripts omitting optional expected fields retain their previous
contract. Original images, immutable datasets, registered model maps,
historical reviewed observations and saved QC Workflow Builder artifacts are
not altered by the lock. No new migration or duplicate workflow node is
required.

## Regression evidence

`test_reviewed_class_merge_keeps_writer_lock_through_scientific_mutation`
uses a file-backed SQLite test database, one annotated coral image, exact
class identity/count/fingerprint approval, and a second independent SQLAlchemy
connection attempting to edit the target class inside the merge's usage
preflight. The competing writer must fail with a bounded SQLite busy timeout.
The merge must still commit exactly one annotation revision event, archive
the source, retain the approved target meaning and reclassify the active
annotation. The second writer is allowed to proceed after the commit.

Existing standalone Merge tests and a persisted, executable
`project_source → qc_review_queue` Workflow Builder regression separately
check dimensionless QC output, explicit researcher review, saved artifacts,
checksums and replay/retry, and preservation of workflow-owned queue evidence
across merges. This increment does not add a redundant graph node.

## Limitations and release hold

The writer-lock guarantee is specifically for ReefVision's **local SQLite**
configuration. It should not be interpreted as serializable cross-service
locking for a future multi-user PostgreSQL deployment. Native installed
Windows GUI/MSI and upgrade/rollback testing, cross-version Alembic revision
0038 reconciliation, representative biological data acceptance, full
exact-head CI and researcher approval are mandatory before 1.6 can be
called release-ready. No main merge, tag, release, hosted service, model
download or user-asset deletion is authorized by this change.
