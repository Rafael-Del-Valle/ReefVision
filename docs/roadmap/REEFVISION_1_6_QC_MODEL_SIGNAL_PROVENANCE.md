# ReefVision 1.6 — model-derived QC evidence requires model references

## Scope audit and scientific gap

Version 1.6 already has class visibility, human QC coordination, standalone
review queues and an executable, persisted `qc_review_queue` Workflow Builder
node (including frozen dataset-version inputs and researcher-review gates).
This change strengthens that existing shared replay validator; it does not
duplicate the review subsystem or import work from unmerged 1.0–1.5 branches.

The v3 generator derives `model_ids_json` from the image's model predictions.
A re-signed saved queue could previously remove **all** model IDs while
retaining nonzero confidence deficits, pending prediction counts, rejection
rates or edited-acceptance rates. Such an artifact would report model evidence
without any referenced model. A matching checksum alone does not establish
scientific provenance.

## Contract

For **v3** saved queues only, when the frozen model-ID list is empty, the
following five prediction-derived raw signals must all be zero:
`low_mean_confidence`, `low_min_confidence`, `pending_proposals`,
`rejection_rate` and `edited_acceptance_rate`. Human-only images may still
have nonzero model-versus-human **count disagreement** when annotated objects
exist, so that separate signal is not forced to zero. Other provenance,
normalization, scoring, digest, queue ownership and explicit human-review
requirements are unchanged.

This check uses **persisted immutable evidence only**. It does not inspect
later live predictions, infer model accuracy, validate a species, alter
researcher decisions or rewrite historical v2/unversioned queues. Model IDs
are references, not proof that detections are correct or biologically verified.

## Regression and acceptance boundary

- A coherent, synthetic human-annotation-only v3 snapshot passes replay.
  Five independent re-signed, unweighted signal mutations fail despite
  otherwise valid score, summary and digest, while preserving an in-progress
  review decision.
- Standalone frozen-dataset QC and executable saved
  `project_source → dataset_version_source → qc_review_queue` are compared
  for an image with no annotations or predictions. Both must retain empty
  model IDs, zero prediction-derived signals, equal scientific fingerprints,
  dimensionless scores and mandatory pending researcher review.
- The preceding exact-head CI failed only at a single Ruff formatting
  difference in the frozen-dataset test; that exact line was corrected.

This remains **development / RELEASE HOLD** until new-head Ruff, mypy,
pytest, frontend/E2E and migrations pass, cross-version Alembic 0038 lineage
is reconciled independently, representative biological data are accepted,
and native Windows MSI upgrade/rollback and installed-GUI checks are run.
No merge, release, pretrained-weight download, cloud hosting or user-data
mutation is authorized by these synthetic checks.
