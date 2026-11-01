# ReefVision 1.6 — QC biological grouping evidence

A project image can be reassigned from one nonempty experimental group (for
example, coral tank A) to another without changing its object counts, class
distribution, QC priority score, or the binary missing-group signal. Earlier
new-queue fingerprints did not distinguish those two experimental contexts.

Newly generated review-queue item fingerprints now include the evaluated
image's `group_key`, `width_px`, and `height_px`, alongside its stored
source-image SHA-256 and previously captured annotation, prediction and
scoring evidence. For dataset-version contexts, these image-level fields and the missing-group
priority signal come from the frozen image-item snapshot, not a later live
reassignment. Dataset-version review queues now reuse the existing immutable dataset-version
QC context builder: frozen annotation IDs/classes/geometry, annotation status,
image grouping/dimensions and source checksums are used for scoring and evidence.
Unreviewed predictions added to the live project after snapshot creation are
**not** silently attributed to the frozen version. Project-scoped queues still
use live annotations and predictions. This fixes a former mixed-context defect
where version-level image metadata was frozen but annotation counts and
coordinates were drawn from the mutable project.

The additional regression edits the same coral annotation after dataset
versioning, then checks unchanged version-scoped fingerprints and priority,
changed project-scoped evidence, fresh executable saved project workflows,
and historical workflow snapshot integrity with review still pending.

**Scientific limit:** dataset-version QC ranking is snapshot-scoped, not a
re-evaluation of later project inference; the latest QC issue run may have its
own historical provenance and should be evaluated independently. The existing
Workflow Builder `qc_review_queue` node takes a project reference and is
unchanged; this iteration does not claim a new dataset-version workflow port.
The fields are not treated as proof that a coral was verified or that a
particular tank is an independent statistical replicate.

The regressions exercise standalone queue creation and executable saved
`project_source → qc_review_queue` graphs before and after a tank reassignment,
and verify that dataset-version queue image metadata remains frozen while a
project-scoped queue tracks live group changes.
It verifies distinct fresh evidence checksums despite identical priorities,
historical saved-queue integrity, dimensionless priority units and the
researcher-review gate. No existing saved queue is rewritten and no migration
or new Workflow Builder node is introduced.

Limits: the source SHA-256 is stored metadata, not a fresh read of image
bytes; no inference or biological ground truth is asserted. Windows installed
GUI, real tank-data acceptance, and cross-version migration reconciliation
remain separate release gates.
