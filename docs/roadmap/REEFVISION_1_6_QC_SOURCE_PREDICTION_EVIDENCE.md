# ReefVision 1.6 — source-image and prediction evidence in QC fingerprints

## Gap and implementation

A QC review queue previously hashed verified annotation geometry but only
the **IDs** of unverified model predictions. A pending coral-polyp proposal
could move or change class/confidence/provenance while retaining its ID and
the same number of detections. The review priority could remain unchanged,
leaving the old and new evidence with identical per-item input checksums.

Fresh standalone and saved-workflow `qc_review_queue` snapshots now bind
the per-item input checksum to:

- the imported image's stored SHA-256 digest;
- a prediction-ID-sorted list of prediction IDs, model/class identifiers,
  predicted label/index, confidence, source-pixel box coordinates,
  review status, edited flag, accepted-annotation link, and provenance;
- the previously implemented annotation evidence, QC issue identifiers,
  weights and scoring inputs.

This is a **fingerprint of local research evidence**, not a claim that a
model prediction is a verified biological observation. It does not change
review priority calculations, annotate images, or approve predictions.

## Limits and compatibility

The image SHA-256 value is the digest recorded at import, **not** a fresh
read of the underlying image bytes at queue creation. Out-of-band disk
tampering without updating stored metadata requires separate storage
integrity checks. This increment does not hash polygon/mask payloads or
the full model checkpoint file; those require explicit follow-up coverage.

Existing queue records, scoring rules, reviewer decisions, saved workflow
artifacts, migration lineage and immutable historical evidence are not
rewritten. Newly generated queues use the expanded input checksum. The
existing `review_queue_reference` output remains typed, its priority score
remains dimensionless, and explicit researcher review remains mandatory.

## Regression and release hold

`test_review_queue_prediction_evidence_16.py` seeds a synthetic local
model registration and unverified prediction **without downloading or
creating weights**, then exercises both the standalone queue API and an
executable saved `project_source -> qc_review_queue` Workflow Builder
graph. Moving the prediction box while holding the detection count, model
ID and priority score fixed must change the new checksum. The old saved
queue must still pass its integrity validation and remain pending review.

Native Windows MSI upgrade/rollback and installed-GUI checks, representative
biological-data acceptance, durable QC crash recovery and independent
reconciliation of the 1.1/1.6 Alembic 0038 collision remain release gates.
No automated scientific verification or cloud upload is introduced.
