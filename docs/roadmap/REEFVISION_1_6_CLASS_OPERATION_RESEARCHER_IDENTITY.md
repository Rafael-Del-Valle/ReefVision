# ReefVision 1.6 — class-operation preview identity binding

## Audited gap and scope

Class Manager's saved Reassign and Reassign and Delete previews already persist the initiating local user identity, exact reference IDs and a reviewed plan checksum. However, execution accepted a matching operation ID and checksum from a *different* local identity. That let another researcher execute someone else's approval if they had access to the same local project and API. Earlier 1.0–1.5 branch implementations lack this execution-time identity guard. The 1.6 class-merge and data-inventory safety controls remain unchanged.

## Implementation

Both execution endpoints now compare the currently resolved stable local-user identity to the immutable `requested_by_identity` captured on preview. On mismatch, the API returns HTTP 409 before recalculating or applying the plan, changing the operation status, moving biological annotations, modifying prediction/QC/review references or physically deleting a class. The original reviewer may still execute a valid preview. A new researcher or a deliberately reset local identity must create and explicitly approve a new preview. No new model downloads, network activity or schema migration are introduced.

This is an **offline approval-consistency guard**, not cryptographic user authentication, tenant isolation or protection against someone with filesystem access editing the local identity file. Genuine multi-user authorization must be designed separately, rather than treating this local identity as an adversarial security boundary.

## Verification and release boundaries

A parameterized real-database HTTP regression covers both Reassign and Reassign and Delete. It makes a preview under researcher A, attempts to execute the valid ID/checksum under researcher B, checks HTTP 409 and no changes to annotations, predictions, QC, review queues, class identity, operation lifecycle or append-only reassignment events, then allows A to execute the original approval and verifies event attribution. Full CI, real scientific dataset/workflow acceptance, and Windows installer/GUI validation are separate gates.

The change is a human approval constraint on existing class metadata operations, not a new analysis/model/measurement capability, so it does not add a duplicate Workflow Builder node. Existing typed executable QC workflows, saved graphs/runs, provenance and researcher review gates remain intact. Earlier versions are not merged into this branch. Pending Alembic-0038 cross-version reconciliation and Windows MSI/CAB upgrade/rollback remain release blockers.
