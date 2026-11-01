# ReefVision 1.6 — QC annotation-evidence fingerprint

## Scientific gap and correction

The prior review-queue `input_checksum` recorded the number of verified
annotations on an image, but not their identities, classes, bounding-box
coordinates, or source provenance. Moving a coral-polyp annotation without
changing its count could therefore yield the same item input checksum.
This is an evidence-integrity issue even when the calculated priority score
happens to remain unchanged.

Newly generated standalone and saved-workflow `qc_review_queue` snapshots
now include a stable, ID-sorted list of each current annotation's ID, class,
source-pixel `[x_min, y_min, x_max, y_max]` box, revision, source type,
source model/prediction references, and annotation provenance in the existing
item input checksum. The data are hashed locally using the existing canonical
JSON SHA-256 utility; no coordinates or research images are uploaded.

## Backward compatibility and review boundaries

No migration or change to historical queue rows is made. Older saved
workflow runs keep their original checksums, review states, and evidence
digests, and remain subject to their existing saved-snapshot integrity
checks. A fresh run produces a new immutable queue input fingerprint.
This change does **not** automatically verify, reject, or approve a
biological observation; researcher review is still required.

This addresses verified bounding-box annotation evidence only. Prediction
geometry, image pixel-content changes, and full image annotation-revision
provenance require separate audit and tests; the fingerprint is not a
replacement for dataset-version integrity or experimental-unit metadata.

## Regression and release gate

`test_review_queue_annotation_evidence_16.py` exercises the standalone
queue API and executable, saved `project_source -> qc_review_queue`
Workflow Builder graph before and after a same-count annotation geometry
edit. It asserts that the fresh checksum changes, the historical saved
queue remains intact, its original snapshot still validates, and all
workflow outputs retain dimensionless priority units and the explicit
researcher-review gate.

Release remains blocked on exact-head backend/frontend CI, independent
1.1/1.6 Alembic revision-0038 reconciliation, representative coral-image
acceptance, durable recovery, and native Windows MSI/CAB and installed-GUI
upgrade/rollback validation.
