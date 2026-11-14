# ReefVision 1.6 — class-operation approval and protected compatibility provenance

## Gap and scope

The existing Class Manager **Reassign** / **Reassign and Delete** previews bind
researcher approval to source/target biological identities, observation data,
reference record IDs and QC/review state. The original compatibility preview
reported immutable dataset and locally registered model **IDs** but not the
corresponding class-map content or retained artifact checksums. A same-ID
modification to the frozen dataset class map, dataset manifest hash, model class
mapping or local model checksum could therefore reuse an earlier approved plan,
even though the research implications of reassignment had changed.

This is a 1.6 manual class-management integrity gap. It does not duplicate
the existing 1.0–1.5 dataset, model, QC or executable Workflow Builder features.

## Implementation and scientific contract

The plan digest now recomputes, in deterministic record-ID order:

- Relevant frozen dataset versions: exact class map and recorded manifest SHA-256.
- Relevant local model registrations: exact class map and recorded weight SHA-256.

These fields are internal evidence included in the canonical preview digest,
**not** editable client approval fields. If any changes before execution, the
existing stale-preview HTTP 409 path persists a failed, non-mutating operation
and requires the researcher to inspect and approve a fresh preview.
Dataset/version snapshots and registered model artifacts are **never**
rewritten by class reassignment. Existing valid approvals remain supported
except that unexecuted previews generated under the older digest must be
reviewed afresh.

The database-backed HTTP regression covers both distinct operations and four
same-ID provenance changes. It checks stale rejection and preservation of
annotations, predictions, QC issues, review-queue references and the source
class. Existing unchanged-preview success coverage is retained.

## Boundaries and release gates

The digest detects changed *recorded* class maps and hashes, not changes to
external artifact bytes when the database hash is left unchanged. It also does
not provide a write lock against modifications between final recheck and
commit or authenticate a local OS researcher cryptographically. The separate
1.1/1.6 Alembic revision-0038 conflict is unresolved. This increment neither
rewrites published schema nor introduces an analytic node; the already
executable typed QC Workflow Builder nodes, saved graphs/runs, provenance,
retry and human-review contracts must continue to pass their regressions.

**Release status: HOLD** until exact-head backend/frontend/E2E checks, real
scientific saved-workflow replay, independent migration compatibility review,
native Windows MSI/CAB installation/upgrade/rollback and interactive
installed-GUI validation have all passed and researcher approval is recorded.
