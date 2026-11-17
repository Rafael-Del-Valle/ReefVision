# ReefVision 1.6 — QC diagnostic provenance in review queues

## Existing overlap and precise gap

ReefVision already supports independent quality-control runs, explainable
priorities, issue triage, immutable review histories and executable saved
Workflow Builder graphs. Existing input fingerprints bind source image bytes
(by stored SHA-256), bounding-box and verified mask geometry, predictions,
biological group assignments, issue identifiers, and numeric scoring signals.

The remaining gap was the **finding's diagnostic content**. A source QC
issue could retain its ID and severity while its rule version, explanation,
measured value, or threshold changed. A subsequent queue could then produce
the same score **and** item input checksum, making distinct scientific
interpretations appear identical.

New 1.6 queues additionally hash a deterministic, issue-ID-sorted set of
QC issue facts: source rule identity/version and fingerprint, severity and
status, title and explanation, related annotation/prediction/class IDs,
measurements, thresholds and resolution metadata. This evidence is included
only inside the canonical SHA-256 input construction. It is not copied into
the user-facing queue-item API or workflow artifact.

## Science, privacy, interoperability and backward compatibility

This modification does not recalculate priority scores, change the QC
ruleset, accept model predictions, alter human review decisions or mutate
prior QC findings. A finding is diagnostic evidence, **not confirmed
biological ground truth**. A mutable issue's content is captured at
**new queue creation**; saved queue retries always compare their persisted
immutable input checksum and typed workflow provenance.

Both standalone queue generation and executable saved graphs call the same
ReviewQueueService. The graph continues to produce a checksummed
review_queue_reference with dimensionless priority and an explicit
requires_researcher_review gate. Historical queues retain their existing
fingerprints; no database migration or content rewrite is performed.

An issue's descriptive text may contain sensitive research details. Only
its digest contributes to the queue-item fingerprint. Do not expose raw
diagnostic text in workflow artifacts, logs or telemetry.

## Regression and remaining release gates

The disposable API + saved-workflow test
test_review_queue_qc_finding_evidence_16.py creates a biological annotation
overlap, executes source QC, creates standalone and persisted executable
QC queues, alters a finding's diagnostic details without changing its
severity or priority, then verifies that only **new** fingerprints change.
The historical workflow queue must remain pending and integrity-valid.

This test does not replace native Windows installation/upgrade and rollback,
physical installed-GUI checks, real biological-data review, crash recovery,
full CI, or independent reconciliation of the 1.1/1.6 Alembic-0038
collision. Release remains blocked pending those checks and explicit
researcher approval.
