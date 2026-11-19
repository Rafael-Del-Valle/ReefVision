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
