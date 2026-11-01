# ReefVision 1.6 — Bulk QC page-selection limit

The existing manual bulk QC API permits up to 100 selected review items per request. The review dashboard may display more than 100 eligible items on a page. Before this change, **Select eligible on page (N)** appeared to promise all N items, but silently selected only the first 100. This could lead a researcher to incorrectly believe every visible coral image was triaged.

The UI now discloses the 100-item cap, explicitly labels a truncated selection **100 of N**, and warns that remaining eligible items require a separate batch. It preserves existing server-side limits, original order, explicit reviewer confirmation, idempotent UUID retry, biological evidence snapshots, and researcher-review gates. No scientific predictions or annotations are approved by bulk triage.

Regression: a 105-item page verifies that the warning appears, the selected count is 100, and the outgoing request contains exactly the first 100 IDs rather than silently including or claiming the remaining five. The existing saved `qc_review_queue` Workflow Builder node and its typed/provenance/review-gated execution are unchanged because this is a standalone selection UI correction, not a new workflow operation.

Release remains blocked on exact-head CI, cross-version Alembic revision 0038 reconciliation, representative scientific review, and installed Windows MSI/GUI upgrade/rollback acceptance.

## Manual selection guard — 2026-11-01

The 100-item API cap also applies to individual checkbox selection, not just the bulk **Select eligible on page** button. Once 100 currently eligible rows are selected, additional unchecked boxes are disabled; already selected rows remain enabled so a researcher can deselect an item and replace it with another visible specimen. A functional state-update guard independently prevents a rapid sequence of clicks from exceeding the cap. The request still requires the original explicit human confirmation, remains scoped to the current queue and includes no automatic biological approval.

Frontend regression: a 105-coral queue, 100 selected, the 101st checkbox disabled, replacement after deselection, and an outgoing request containing exactly 100 expected IDs. This is a standalone QC usability safeguard using the existing typed saved `qc_review_queue` Workflow Builder implementation; it adds no analysis node, schema migration or scientific-data mutation. Exact-head frontend CI and Windows installed-GUI validation are required before release.
