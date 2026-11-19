# ReefVision 1.6 — checksummed per-image frozen dataset QC evidence

## Gap and scope audit

The existing 1.0–1.5 immutable dataset-version service saves a per-image
`snapshot_sha256` and a checksummed manifest containing the original image, split,
class-count and annotation coordinates. The 1.6 standalone QC service and
executable saved `dataset_version_source → qc_review_queue` adapter already
checked manifest hashes, total counts, typed artifact provenance, unitless
priority scores, retry identity and mandatory researcher review. They did not
compare the actual per-image database record against the checksummed original.
Thus an amended coral bounding box (or a recomputed per-image digest) could be
treated as original frozen evidence while every aggregate count still matched.

## Implementation

A shared read-only `validate_frozen_dataset_manifest` guard now reconstructs
the historical per-image detection payload, verifies its original SHA-256, and
compares the entire record with the unchanged checksummed manifest entry. It rejects
duplicate/missing membership, mismatched labels, splits, filenames, class counts,
bounding boxes, and unexpected mask-bearing schemas that lack a checksummed mask
contract. It runs before **standalone queue creation** and before **saved
Workflow Builder queue creation or retry**. No data is repaired, migrated,
deleted, re-checksummed, or implicitly approved.

The new parametrized regression starts a real Swiftia study, creates standalone
and saved typed QC evidence, tampers with six different immutable per-image
fields, verifies both routes reject the alteration, rolls back each disposable
transaction, then replays the original node without changing pending reviewer
state or prior QC queue evidence. The saved artifact retains its
`dimensionless` priority score unit and `requires_researcher_review` gate.

## Boundaries

No new node is needed: existing saved graphs, provenance, retries and review
gates execute the shared check. Future mask-bearing dataset manifest formats
must define their own checksummed scientific contract before QC; silently accepting
an uncommitted mask snapshot is unsafe. Local model inference remains offline;
there are no pretrained downloads or external services.

The independent 1.1/1.6 revision-0038 collision, representative biological
acceptance, native installed-GUI performance and true Windows MSI/CAB
clean-install/upgrade/rollback remain release holds. Passing API regressions
does not approve those gates or permit a merge/release.

The manifest and per-item values are **SHA-256 checksums, not authenticated
cryptographic signatures**. This guards against a corrupt or individually
re-signed row while the original manifest remains intact; an actor who can
rewrite and rehash every database record must be addressed by independent
backups or external attestations. No authenticity guarantee is claimed.


## Schema-parity correction (CI #44460632911)

Full backend CI uncovered 50 failures because the first check assumed the historical
detection-only `0006` item format, while the installed dataset API already writes
`0007` mask-aware manifests even when a study contains no masks. The API uses
`MeasurementAwareDatasetVersionService`, inheriting mask-aware snapshot creation.
This was an overstrict validator, not evidence that the original data were altered.

The shared guard now checks the **original recorded version** against the
manifest schema, accepting only the existing `0006` detection and `0007`
mask/measurement contracts. For `0007`, the original snapshot hash and
manifest must match all polygon/raster mask evidence, per-class counts, mask
counts, and any saved measurement metadata. A `0006` snapshot cannot silently
gain mask evidence; a changed or unknown schema fails closed. No live
scientific data, generated dataset version, or reviewer decision is modified.

New standalone format-parity tests cover legacy detection, current mask-free
and mask-bearing manifests, original scientific measurements and altered/
re-signed mask geometry, measurement values, counts and schema downgrade.
The existing real API and saved Workflow Builder regressions exercise both
routes; full exact-head CI and real installed Windows acceptance are required
before lifting the release hold.

## Independent detection census and diagnostic ordering (CI #44467738435)

After schema-parity repairs, the comprehensive backend job passed 2,152 tests
but exposed six previously written lineage assertions that expected the old
producer diagnostic after tampered frozen rows. The stricter manifest guard
correctly rejects those records first. Regression expectations now distinguish
direct frozen-row integrity errors from forged upstream producer-binding errors,
without relaxing either fail-closed path.

A separate census check also reconstructs the count and per-class distribution
from the original frozen annotation records for both supported manifest schemas.
A local actor cannot make contradictory detection counts valid merely by
recomputing an item's SHA-256 and the encompassing manifest SHA-256. Synthetic
tests re-sign both layers while preserving old completed QC evidence, then
require standalone and persisted typed Workflow Builder QC to reject both a
forged annotation total and forged taxonomic class counts. The original review
queue is replayed after a transaction rollback, and no reviewer action is
implicitly approved.

Checksums still cannot provide authenticity against a database writer who
rewrites *all* logically consistent evidence: independent read-only backups
or authenticated external provenance would be required for that threat model.
The Windows-installed GUI, real MSI upgrade/rollback, 1.1/1.6 Alembic lineage
reconciliation and researcher approval remain outstanding release gates.

## Re-signed observation identities and saved retry ordering (November 19, 2026)

The independent frozen-item QC validator now also rejects missing, empty or
reused detection annotation IDs, including identities reused across frozen
images. Project annotation IDs are unique record identifiers: duplicating one
can falsely inflate a coral observation count even when the annotation census,
class totals, item checksum and enclosing manifest checksum all agree. Existing
`0006` and `0007` snapshot formats use this same read-only check. No new
migration or Workflow Builder node is needed.

The database-backed regression now also re-signs duplicated and empty IDs,
checks standalone dataset QC refusal, and verifies the saved typed QC workflow
rejects altered source data while preserving its completed human-review queue.
For a completely re-signed version, the saved workflow first notices that its
original dataset-source manifest digest is stale; this deliberate, earlier
provenance failure is *not* the downstream frozen-item error. A transaction
rollback restores the original evidence for a deterministic saved-node replay.
The checksum still does not authenticate a wholly fabricated internally
consistent research dataset; that requires independent evidence custody.

The unresolved 1.1/1.6 Alembic-0038 collision, complete exact-head CI,
representative scientific acceptance, physical MSI clean install and
upgrade/rollback with installed GUI, and explicit researcher approval keep the
release on HOLD.


## Mask identity integrity for 0007 saved studies (November 19, 2026)

The existing original 0007 producer assigns each verified polygon/raster mask
a globally unique database `MaskAnnotation.id`, but the frozen QC validator
previously verified mask counts and class totals without checking the mask
identity field. A duplicated or absent ID could represent two masks as one
biological observation even when the item and manifest SHA-256 values were
both recomputed. The 0006 detection-only format has no mask identity field.

The same read-only shared validator now requires a nonempty string ID for
each 0007 mask and rejects reuse within or across frozen images. Detection
and mask identifiers retain their separate database namespaces. Synthetic
tests check fully rehashed missing, empty and duplicated IDs and cross-image
identity reuse. A real mask-bearing coral study regression checks standalone
QC rejection, saved typed Workflow Builder provenance refusal, rollback,
unchanged pending review evidence, and idempotent saved-node replay. This
does not add an overlapping node or migration, does not rewrite originals
and does not claim hash-only authenticity. All other release holds apply.


## Re-signed detection geometry validity (November 19, 2026)

The original annotation editor validates **source-pixel** boxes against the
image dimensions: all four coordinates must be finite numbers, nonnegative,
inside the image bounds, and define strictly positive width and height. Frozen
QC previously checked the boxes against the original checksummed manifest,
but did not independently enforce those geometric constraints when a local
writer recomputed both manifest and item digests. This could let impossible
coral observations (negative coordinates, zero-area boxes, outside-image
regions, infinities or nonnumeric values) enter a re-signed study.

Both historical detection-only `0006` and existing mask-aware `0007`
versions now apply the original editor's source-pixel bounds inside the
shared **read-only** frozen-item validator. The same validator protects
standalone QC and saved typed `dataset_version_source → qc_review_queue`
Workflow Builder runs. It does not alter original annotations, generate new
workflow nodes, download pretrained weights, or approve research.

Synthetic schema-parity tests rehash the entire invalid box and manifest for
each original schema. Database-backed saved-graph regressions also verify
standalone refusal, rejection at the saved source-provenance gate, rollback,
deterministic retry, dimensionless priority units and preserved pending human
review. Checksums remain unauthenticated; independent dataset custody, the
Alembic-0038 collision, real installed Windows GUI/MSI upgrade/rollback,
and explicit researcher approval still block release.
