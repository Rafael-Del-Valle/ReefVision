# ReefVision 1.6 — QC review coordination desktop integration

**Development-only, not release accepted.** The existing Review Queue Dashboard now opens a local coordination panel per selected queue item. It uses the persisted append-only event API for comments, assignments and unassignments; shows assignee, history, errors and pagination. Actor labels are explicitly self-reported, not authenticated identities.

The executable `qc_review_queue` Workflow Builder node produces durable queue references, so saved-workflow queues and standalone queues use the same coordination panel. No automatic scientific approval or data verification is introduced. Event UUIDs are generated per action and preserved for retry after an uncertain network result.

This change also repairs the six exact Ruff formatting failures at previous PR head `d4dc3a3`. Validation required at the new head: Ruff, mypy, backend pytest and migration tests, frontend Prettier/TypeScript/Vitest/E2E, saved workflow regression, Windows MSI/CAB and installed-GUI checks. No local repository test execution or installed-GUI validation is claimed.

**Migration integration risk:** isolated 1.1 and 1.6 branches both introduce a migration labeled 0038. Reconcile Alembic revision identifiers and test upgrade paths before combining accepted versions. Do not cherry-pick unrelated unmerged version work.
