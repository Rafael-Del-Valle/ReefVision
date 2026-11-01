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
reassignment. The existing QC queue continues to evaluate annotations and
predictions from live project context; that broader version-snapshot parity
requires separate scientific acceptance and must not be inferred here.
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
