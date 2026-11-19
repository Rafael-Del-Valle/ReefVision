# ReefVision 1.6 — verified mask evidence in QC review queues

## Overlap audit and purpose

The earlier dataset-version implementation already freezes verified polygon and
raster masks, including geometry, stored content hashes, measurement metadata,
and biological class provenance. The existing 1.6 QC queue and executable
`project_source → qc_review_queue` / `dataset_version_source → qc_review_queue`
nodes already preserve item priority, pending human review and checksummed
outputs. There is no need for a new mask format, workflow node or migration.

Previously a new QC review-queue item fingerprint recorded verified **box**
annotations and model prediction geometry, but not independent, verified
**mask** annotations. Two coral polygons with the same image, enclosing box,
class and number of objects could therefore receive the same checksum even
when their measured area, branch shape or polygon vertices differed.

## Contract

New queue-item input fingerprints include `verified_mask_annotation_evidence`
for all verified, nondeleted masks. Live project queues reuse the existing
measurement-aware dataset-snapshot service: polygon vertices, source-pixel
bounds, measured area/profile, label, revision, provenance and timestamps are
included, and raster content is SHA-256 hashed from the locally managed mask.
If an expected managed raster is unavailable, snapshot creation fails closed
rather than accepting missing scientific content. The original source image
and mask are read but never changed.

A dataset-version queue instead hashes the **frozen** mask snapshots for the
selected version. New live mask edits cannot rewrite the version's checksum,
recorded biological observations or historical Workflow Builder output.
Mask ordering by stable ID avoids accidental database-return-order drift.

The existing QC scoring formula `review_priority_v1` and the displayed
dimensionless priorities are unchanged; this is stricter **input evidence**
rather than a new biological scoring rule. Previously persisted queues and
reviewer comments, assignments and states are not rewritten or re-scored.
Saved graphs retain typed provenance, deterministic retry/replay validation
and the explicit `requires_researcher_review` gate.

## Regression and limitations

`test_review_queue_mask_evidence_16.py` creates verified coral polygons
with identical bounding extents and counts but differing internal vertices.
It checks project/frozen standalone queues, executable saved project and
version-scoped Workflow Builder runs, historical checksums, scientific
snapshot integrity and pending review decisions.

This change does not count mask-only annotations as box observations in
legacy priority signals; doing so would require a separately versioned
scoring contract and tests. Raster hashing occurs on queue construction, not
on every historical queue replay. Dataset-version raster checksums describe
the original frozen snapshot, not a new on-disk read. A digest does not prove
taxonomic correctness, segmentation accuracy, or researcher approval.

Remaining 1.6 release gates: independent 1.1/1.6 Alembic-0038 lineage
reconciliation, representative biological QC acceptance, crash recovery,
Windows MSI/CAB installation and upgrade/rollback, installed GUI validation
and explicit researcher approval. No merge, tag or release is authorized.

## Frozen 0007 raster provenance follow-up (November 19, 2026)

The original mask-aware producer records a managed raster `mask_path`, a
lowercase 64-character SHA-256 `mask_content_sha256`, a source-image bounding
box and a positive pixel area. The shared read-only frozen-item validator now
rejects fully rehashed raster records with missing/blank paths, missing or
malformed content digests, out-of-image boxes, zero area or an area larger than
the source image. The existing polygon-specific shape/area validation and
historical detection-only `0006` schema are unchanged.

The original `0007` polygon parity fixture was also corrected to match the
actual producer's `polygon_json`, bounding box and `area_pixels` contract:
CI #44517799262 reported **one** failure in that previously unrealistic
positive fixture (2,201 backend tests passed, 32 skipped); frontend and native
Windows preservation passed. The repaired fixture and positive/negative raster
parity scenarios exercise both accepted original data and recomputed-checksum
faults. Database-backed standalone QC and twice-entered saved-graph review
evidence now include raster provenance faults with rollback and pending human
review preserved. Exact-head CI must confirm these tests before acceptance.

The digest is **not** a cryptographic signature. Frozen QC deliberately does
not re-open or delete a user's raster assets: it verifies recorded metadata,
not present-day file availability or byte identity. Original producer-time
managed-file hashing remains the source of that evidence. Taxonomic and
biological correctness still require researcher approval; none of these
metadata guards grants it.
