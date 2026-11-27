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


## Verified mask eligibility under re-signed snapshots (November 19, 2026)

The existing 1.0–1.5 mask-aware dataset-version producer includes only
`status == "verified"` masks and rejects unsupported geometry kinds. The 1.6
shared frozen-item QC validator previously checked mask identities, counts and
checksums but could admit a fully rehashed historical mask that had been
changed to an unreviewed draft, had lost its review status or carried an unknown
geometry kind. Such a record must not be counted as scientifically reviewed
segmentation evidence simply because a local database writer updated the
manifest checksum.

The read-only validator now enforces the original producer's verified-mask
status, nonempty class identity and `polygon`/`raster_mask` geometry kinds.
Seven fully re-signed synthetic cases and three disposable, database-backed
mask-study cases exercise corrupt evidence rejection. The database cases test
standalone QC, saved executable typed Workflow Builder manifest-binding
rejection, dimensionless output, deterministic rollback/replay and unchanged
pending human-review records. No live masks, class labels, original files,
models or database migrations are changed; no new overlapping workflow node
or implicit researcher approval is introduced.

The previous exact-head CI #44499316065 failed a Ruff-only formatting check
in the bounding-box helper before backend pytest. This iteration also applies
that exact formatting correction; the new head still requires full CI,
scientific review, independent Alembic-0038 resolution and genuine installed
Windows MSI/GUI upgrade and rollback acceptance.


## Frozen polygon source-pixel scientific consistency (2026-11-19)

Audited the existing editor's polygon contract and the frozen `0007`
producer before changing the shared QC guard. Previously, the validator
checked verification state, geometry kind, class census and mask identity,
but an actor capable of recomputing both unkeyed SHA-256 checksums could
replace a polygon with coordinates outside its source image, an incorrect
bounding box, or an inconsistent reported area. The shared read-only QC
validator now checks finite numeric polygon points inside the original
pixel dimensions, three distinct vertices, nonduplicated adjacent points,
matching stored bounding extrema, and the original editor's shoelace
area/rounded pixel-area relationship. Historical `0006` and `0007`
raster-mask records are not reinterpreted as polygons.

Five new rehashed mask regressions extend the existing real database
standalone and saved `dataset_version_source → qc_review_queue`
tests, including rollback, deterministic replay, provenance binding
and pending human-review evidence. These checks are scientific
consistency checks, not authenticated signatures or a full polygon
topology/self-intersection proof. No live annotations or researcher
decisions are modified. Full exact-head CI and actual Windows installer
and installed-GUI acceptance remain release holds.


## Frozen taxonomic identity binding (2026-11-19, Track D)

The original 0006 and 0007 dataset producers store a project-class
dictionary in both `DatasetVersion.class_map_json` and the checksummed
manifest's `class_map`, and include `label_class_id`, `class_index`, and
`class_name` in every frozen detection and verified mask observation.
Previous read-only QC validated class counts keyed by ID but did not check
the identity/index/name tuple against the original dictionary. A fully
recomputed item and manifest SHA-256 could therefore call a Swiftia
observation another taxon without changing counts or observed geometry.

Standalone dataset-version QC and the existing saved executable typed
`project_source -> dataset_version_source -> qc_review_queue` path now
share a fail-closed guard that checks the frozen dictionary equals the
version record, rejects duplicate or malformed class IDs, and requires
every detection/mask class tuple to match that dictionary. Live class
renaming is deliberately **not** consulted. Tests cover original 0006,
mask-free 0007 and mask-bearing 0007, fully rehashed aliases and indices,
unknown identities and conflicting class-map entries, plus database-backed
standalone and saved-workflow rejection/replay with pending human-review
evidence preserved. No new node, migration, model download, mutation of
original observations, or automatic researcher approval is introduced.

This is internal scientific consistency, **not** an authenticated signature:
an actor able to rewrite the version row, dictionary, entire manifest and
its SHA-256 together could forge a mutually consistent new identity.
Independent dataset custody and audit attestation remain necessary. Exact-head
CI, independent 1.1/1.6 migration-lineage reconciliation, representative
biological research validation, Windows MSI/CAB installed-GUI clean
installation/upgrade/rollback and explicit researcher approval still gate
release.


## Frozen image review eligibility and selected-status lineage (2026-11-19, Track D)

The original 0006 detection-only and 0007 mask-aware snapshot producers select images
by explicit `eligible_annotation_statuses`, persist the exact selection in the
`DatasetVersion` record and `manifest.split_config`, and freeze each source
image's status in its item payload. Previously, a locally rehashed frozen item
could report an excluded or otherwise unselected annotation status while
retaining consistent image and observation counts. The shared read-only QC
validator now requires a nonempty, unique, producer-supported eligible-status
selection identical to the manifest configuration, with every frozen image's
status included in that selection. This is **selection provenance**, not a
requirement that all images be reviewed: an investigator may explicitly select
other producer-supported statuses in the dataset-version request.

The same validator protects standalone version QC and the existing executable
saved `project_source → dataset_version_source → qc_review_queue` Workflow
Builder path. Synthetic two-schema, mask-aware rehashed cases test excluded,
unknown, duplicated and contradictory selections; database-backed saved-graph
and standalone regressions test rejection, persisted provenance, deterministic
replay, rollback and unchanged human-review state. No duplicate node, new
migration, automatic approval, asset mutation or pretrained-model access is
introduced. SHA-256 is an **unkeyed consistency checksum**, not a cryptographic
attestation of a study's original researcher decisions. Exact-head CI, real
Windows clean install/upgrade/rollback and independently reconciled Alembic
lineage remain release gates.

## 2026-11-26 — Exact integer biological census

Python mapping equality treats JSON booleans and integral floats as equal to integer counts. The existing frozen QC manifest validator now requires positive integer entries in both detection and mask class censuses (an empty census is valid), and exact integer summary counts for images, detections and, for schema 0007, masks. The detection-only schema 0006 remains supported. This is a shared scientific validation boundary for standalone creation, manual regeneration and saved typed QC workflows; no duplicate node or migration. Priority remains dimensionless and explicitly requires researcher review.

Five additional database-backed regression configurations re-sign a frozen study with boolean/float taxon counts or malformed summary counts, test standalone refusal and manual regeneration refusal, saved-workflow refusal and rollback to the original queue. Twelve isolated SQLite JSON census checks and six summary-type probes passed; full repository tests and final exact-head CI are unverified (local GitHub DNS prevents checkout; Ruff unavailable). These probes do not establish biological or installed Windows acceptance.

Release HOLD: independent 1.1/1.6 Alembic-0038 reconciliation, complete CI, representative scientific and saved-workflow acceptance, genuine Windows MSI/CAB installed GUI clean installation/upgrade/rollback and explicit researcher approval. No cross-version merging, release, deployment, weights or user-asset changes.

## 2026-11-26 — Typed manifest-copy identity

A frozen row and its separately checksummed manifest copy must contain the
same JSON types, not merely compare equal as Python mappings. For example,
a copied split-reuse flag of `0`, a taxonomic index of `0.0`, or a copied
biological count of `true` can otherwise compare equal to valid original
values. The shared validator now compares canonical JSON bytes for recorded
split settings, the frozen class dictionary and each per-image payload
(including its existing snapshot digest). Neither schema 0006 nor 0007
changes; no migration, duplicate workflow node, model download or data repair
is introduced. These checks do not authenticate research against an actor
who can rewrite all independent records and checksums.

Eight schema-parity regression configurations exercise both historical
formats, and four database-backed configurations check standalone creation,
manual regeneration, saved typed QC workflow refusal, rollback and original
queue recovery with dimensionless scores and required researcher review.
Seven adversarial and six unchanged independent SQLite JSON round-trip
comparison probes passed. Repository tests, Ruff and exact-head CI are not
confirmed; local checkout cannot resolve github.com. Integrated Alembic
lineage, representative biology, genuine Windows MSI/GUI acceptance and
explicit researcher approval remain release HOLD gates.


## 2026-11-26 — Biological group and achieved-ratio domain validation

Frozen group keys now obey the original split producer's nonblank rule.
An unknown group is represented by null, not a shared whitespace label.
Achieved image fractions must also lie in the closed interval [0, 1]
before the existing census tolerance is applied. This rejects tiny negative
or above-one values that previously passed the tolerance and very large JSON
integers before float conversion could raise an unhandled OverflowError.
No group is inferred or repaired, and no original research data is changed.

The existing shared validator protects standalone frozen QC, manual
regeneration and saved typed Workflow Builder retries. Sixteen historical
schema-parity configurations and three additional database-backed regression
configurations cover rejection, null/known-group compatibility, rollback
and required researcher review. Seventeen isolated SQLite JSON probes passed;
repository tests and exact-head CI remain unconfirmed, as local GitHub
checkout cannot resolve github.com and Ruff is unavailable. Independent
Alembic lineage reconciliation, representative scientific acceptance, genuine
installed Windows MSI/GUI validation and researcher approval remain HOLD.


## 2026-11-26 — Requested split protocol semantics

The original split producer normalizes explicitly requested train/validation/test
weights to a unit sum and resolves random splitting to group_random whenever
at least one eligible image has a biological group. The frozen QC validator
now checks these semantics independently of the manifest/row copy comparison.
Unknown methods, impossible requested/resolved pairs, missing ratio keys,
non-numeric or out-of-range weights and non-unit sums are rejected. Null
requested ratios retain the original implicit/default protocol. The achieved
ratio census remains separate: an exact requested allocation is not promised
when groups, explicit assignments or inherited assignments constrain splitting.

The shared read-only validator is used by standalone QC, regeneration and
saved typed QC Workflow Builder execution. Added 32 original-schema cases
and two database-backed corruption/recovery configurations. Thirteen isolated
SQLite JSON round-trip ratio probes passed; these are not repository tests.
No data repair, split reassignment or researcher approval is inferred.
Exact-head repository CI, independent migration reconciliation, representative
biology and actual installed-Windows MSI/GUI qualification remain release
HOLD gates.


## 2026-11-26 — Parent reuse provenance

The original dataset producer requires a selected parent before inheriting
split assignments. Re-signed version and manifest flags alone cannot establish
that provenance: frozen QC now rejects a missing, blank, self-referencing or
manifest-disagreeing parent ID whenever parent assignments were reused.
This check does not independently authenticate the entire ancestry or prove
that the inherited assignments match the parent; the existing producer lineage
validation remains separate. Independent datasets retain their original
behavior.

Fourteen original-schema cases and one database-backed standalone,
regeneration and saved-workflow corruption/recovery case extend the existing
typed QC gate without altering original observations or researcher decisions.
Twelve isolated SQLite JSON/row parent-reuse probes passed. Repository tests
and exact-head CI are unconfirmed; full biological, migration and installed
Windows GUI qualification remain release HOLD.


## 2026-11-26 — Parent identity without inherited splits

Both original 0006/0007 producers explicitly record the selected parent ID
(or null for an independent dataset). Frozen QC now binds that field to the
version record even if split reuse is disabled. Missing metadata, divergent
parent IDs and blank or self-referencing parents fail closed rather than
letting a locally rehashed snapshot fabricate independent study provenance.
This does not authenticate the whole ancestry or prove that a parent exists.

Sixteen historical-schema cases and one database-backed standalone,
regeneration and persisted workflow regression extend the previous gate.
Twelve isolated SQLite JSON parent-metadata probes passed; full repository
tests and exact-head CI remain unverified. No research data or decisions are
rewritten; existing typed QC outputs and human review gates remain intact.
