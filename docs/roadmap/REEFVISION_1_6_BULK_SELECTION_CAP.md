# ReefVision 1.6 — Bulk QC page-selection limit

The existing manual bulk QC API permits up to 100 selected review items per request. The review dashboard may display more than 100 eligible items on a page. Before this change, **Select eligible on page (N)** appeared to promise all N items, but silently selected only the first 100. This could lead a researcher to incorrectly believe every visible coral image was triaged.

The UI now discloses the 100-item cap, explicitly labels a truncated selection **100 of N**, and warns that remaining eligible items require a separate batch. It preserves existing server-side limits, original order, explicit reviewer confirmation, idempotent UUID retry, biological evidence snapshots, and researcher-review gates. No scientific predictions or annotations are approved by bulk triage.

Regression: a 105-item page verifies that the warning appears, the selected count is 100, and the outgoing request contains exactly the first 100 IDs rather than silently including or claiming the remaining five. The existing saved `qc_review_queue` Workflow Builder node and its typed/provenance/review-gated execution are unchanged because this is a standalone selection UI correction, not a new workflow operation.

Release remains blocked on exact-head CI, cross-version Alembic revision 0038 reconciliation, representative scientific review, and installed Windows MSI/GUI upgrade/rollback acceptance.
