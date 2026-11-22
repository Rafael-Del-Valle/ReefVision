# ReefVision 1.6 — safe-integer scientific class reference approval

## Overlap audit and scope

The 1.0–1.5 annotation foundations and isolated 1.6 class manager already have
reviewed class-usage fingerprints, a thirteen-category reference inventory,
explicit researcher confirmation and a backend-authoritative merge operation.
Do **not** add a duplicate class operation, migration, approval stage or Workflow
Builder node for this presentation-side safety guard.

A structurally valid usage response could report individually safe JavaScript
integer counts whose **sum exceeds `Number.MAX_SAFE_INTEGER`**. The class-manager
frontend previously compared rounded sums with equally rounded reported
subtotals and could enable a merge approval although it could not faithfully
represent the total biological references. This is an evidence-integrity issue,
not grounds to silently adjust recorded counts.

## Change

Before enabling merge approval, require finite nonnegative safe integers in all
reported reference totals, and preserve safe-integer arithmetic after every
mutable/immutable count accumulation and their combined total. Reject a
rounded or otherwise unsafe result and require refreshed, independently
trustworthy evidence. The reviewed fingerprint, source/target identity checks,
backend confirmation and existing class-merge preview remain unchanged.
Nothing automatically changes or deletes annotations.

## Regression and acceptance

Two additional React regression cases feed all thirteen correctly named
reference categories with individually safe counts but respectively overflow
(1) the mutable subtotal and (2) the mutable-plus-immutable total. Both must
show the existing incomplete-evidence warning and keep merge disabled with
**no confirmation and no POST**. Existing positive tests check that normal
reviewed zero and nonzero evidence still permits explicitly confirmed merge.

Full exact-head Prettier, TypeScript, Vitest, Playwright, backend CI and
native-Windows preservation checks are required before calling this validated;
CI is not a replacement for a real installed MSI/CAB/GUI test.

## Workflow boundary and release HOLD

The 1.6 saved executable QC Workflow Builder already has typed graph inputs and
outputs, dimensionless prioritization, saved runs, provenance, idempotent retry
behavior and explicit researcher review. This guard applies only to a manual
class-manager merge approval, not to a new analysis node; existing workflow
semantics and original scientific observations are unchanged.

**RELEASE HOLD:** reconcile the incompatible 1.1/1.6 Alembic-0038 lineage
independently, run biological and persisted-workflow acceptance, validate clean
Windows installation, upgrade, rollback and installed GUI, and obtain explicit
researcher approval. No cross-version branch merge, main merge, release, weights
download, paid service or research-asset deletion.
