# ReefVision 1.6 — rare-class evidence consistency in saved QC replay

## Audited gap

The existing v3 review-queue generator computes `rare_class_presence` only
from annotations with class IDs. The persisted saved-workflow validator
already checked canonical class references and numeric scoring consistency,
but accepted a re-signed snapshot that listed **zero annotated classes** and
nevertheless claimed positive rare-class priority. That would invent biological
class evidence without an underlying annotated taxon.

## Change

For v3 queue replay, reject positive `rare_class_presence` when the
persisted item has no annotated class IDs. This is a consistency check on
immutable evidence, not taxonomic identification or verification. Keep the
historical v2/unversioned replay contract unchanged. Reviewer comments,
assignments, completion state and scientific source files remain untouched.
No new workflow node, database migration or model download is needed.

## Regression and validation boundary

The synthetic v3 integrity regression re-signs the item-evidence digest after
fabricating rare-class evidence, verifies rejection and preserves in-progress
researcher state. A separate API regression creates a reviewed image with no
annotations, freezes it as a dataset version, then compares standalone QC
with an executable saved `project_source → dataset_version_source →
qc_review_queue` graph. It checks zero rare-class signal, unchanged scores,
dimensionless priority and pending human review.

These tests require backend pytest and exact-head CI before they can be
claimed passing. Release acceptance additionally requires cross-version
Alembic lineage, representative biological-data validation and installed
Windows MSI/GUI upgrade and rollback. A rare-class priority score is not a
verified biological observation.
