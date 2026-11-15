# ReefVision 1.6 — staged QC migration inventory (read-only)

**Status: HOLD.** This diagnostic must never authorize an upgrade, issue an
Alembic stamp, change a research record, or imply installed-Windows acceptance.
Track D remains isolated on `develop/reefvision-1.6` and draft PR #77.

## Audited overlap and genuine gap

1.1 independently uses numeric revisions 0038–0042 for scientific, computed
metric, and environmental tables. 1.6 instead creates
`review_queue_item_events` in revision 0038, expands review-event type
constraints in 0039–0040, and creates `review_queue_bulk_requests` only
in revision 0041. The previous read-only inventory treated both QC tables as
a single all-or-none family. It therefore falsely labeled healthy 1.6
0038, 0039 and 0040 databases `incomplete_qc_schema_family`, even though
those revisions legitimately lack the 0041 registry.

## Correction and scientific safety

The inspector now diagnoses migration stages independently. A 1.6 QC 0039
or 0040 database with review events and no bulk registry has no false
incomplete-family warning. Revision 0038 **still** reports the real
cross-branch collision; it cannot be considered an authorized upgrade.
A bulk registry without its 0038 review-event predecessor, a 0041 bulk
table under an earlier QC revision stamp, a 0041 QC database missing
the bulk registry, and 0037-stamped review events are reported explicitly.
Other scientific-family and SQLite-integrity warnings remain unchanged.

Registered CLI regressions exercise four legitimate QC stage states and five
interrupted/contradictory states, retaining reviewer and biological sentinel
rows and comparing the complete SQLite bytes after two inspections each.
They assert typed JSON warning names, fail-closed strict exit, classification
and `upgrade_authorized: false` even for valid stage inventories.
No unmerged 1.1–1.5 branch is blended into this work. Existing
`project_source -> qc_review_queue` executable Workflow Builder, persisted
graphs/runs, typed dimensions, provenance, explicit researcher-review gates
and retries are preserved; this is inspector safety, **not** a workflow node.

## Outstanding release gate

Reconcile the 1.1/1.6 revision-number collision by an independently reviewed,
data-preserving unified DAG. Confirm full backend/frontend/lint/type/E2E and
representative saved-workflow/scientific data acceptance, actual native
Windows MSI/CAB install, upgrade/rollback, installed GUI and explicit
researcher approval. Do not merge, tag, release, deploy, download unapproved
models or delete research assets.
