# ReefVision 1.6 — finite-confidence QC queue boundary

## Existing overlap and gap

ReefVision already has locally registered models, separately verified annotations,
scored quality-control review queues and an executable, persistent
`project_source → qc_review_queue` Workflow Builder graph. Priority-weight
validation already rejects nonfinite and overflowing *requested weights*.
However, an imported or otherwise altered **model prediction confidence**
could be negative, exceed one, or be infinite in the local database.

Such values are not calibrated probabilities and may produce misleading
priority scores, invalid normalized signals or nonportable serialized evidence.
This change is a narrow validation of **unverified source data**, not a new
scoring algorithm or an assertion that any prediction is biologically correct.

## Contract and release boundaries

For a **new** live QC review queue, every scoped prediction confidence must be
a finite numeric value within the inclusive unit interval [0, 1], regardless
of current review state or whether the optional confidence-selection threshold
would include it. The service fails closed with a privacy-safe domain error
**before** inserting the queue or creating persisted workflow review artifacts.
No model weights are downloaded; original images, verified annotations, old
queues and manually recorded review decisions remain unchanged.

The existing saved Workflow Builder node uses the same validation. When the
input is corrupted its run must fail without producing a
`review_queue_reference` artifact. After the local prediction evidence is
corrected, a new saved run can produce the same typed, checksummed output with
dimensionless priority and `requires_researcher_review` gating. Previously
persisted queues remain intact. Dataset-version QC continues to use frozen
snapshots and does not import live pending prediction evidence.

## Verification and limitations

`test_review_queue_prediction_confidence_integrity_16.py` covers four
invalid locally stored values in standalone API calls plus a saved executable
workflow failure/recovery and historic queue integrity. Synthetic model
metadata are used; there is no actual model inference or biological accuracy
claim. This closes a corrupt-input risk without modifying the existing
`review_priority_v1` scoring formula or adding an incompatible migration.

Full CI, representative biology and real native Windows MSI/CAB clean-install,
upgrade/rollback and installed-GUI validation remain release gates, as does
independent reconciliation of the 1.1/1.6 Alembic-0038 histories and explicit
researcher approval.
