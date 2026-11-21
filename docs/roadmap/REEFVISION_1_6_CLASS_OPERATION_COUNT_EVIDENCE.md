# ReefVision 1.6 — class operation reviewed-record count integrity

Track D, 2026-11-20. This change is scoped to the existing manual class
reassign and reassign-and-delete review UI, not an automated model operation.

## Audit and gap

The 1.6 backend `ClassOperationService._group` builds each operation plan
record group with `count=len(record_ids)`, retaining the full identifiers in
its persisted preview plan/checksum. The earlier GUI checked numeric counts
and string IDs separately, but did not check that they agree. A partial or
corrupted API response could therefore present an incorrect number of reviewed
biological observations or conceal a protected record and still enable an
irreversible operation.

## Correction and regression coverage

Every mutable, protected and blocking plan group must now have a nonnegative
safe-integer count exactly equal to the full `record_ids` array length.
Inconsistent evidence displays the recoverable incomplete-plan error,
disables execution and requires fresh explicit preview. The backend remains
authoritative for requester identity, checksum, inventory, and transactions.

The existing React parameter matrix adds inflated mutable record counts and
zero protected counts concealing a nonempty list across both operation types:
four fail-closed regression cases. This change also applies the exact
Prettier formatting corrections identified by CI #44856733232. The new tests
must be confirmed by exact-head CI; independent logic probes are not a
substitute for repository verification.

## Scope and acceptance

No biological assets, SQL migrations, training versions, registered models,
workflow schemas, or standalone/saved Workflow Builder graphs changed.
Existing typed QC operations, units, provenance, reliable retries and
researcher-review gates are preserved. This is a manual GUI authorization
safeguard rather than an additional executable scientific workflow node.

Release HOLD remains until complete exact-head CI, biological and saved
workflow validation, the independently owned 1.1/1.6 Alembic-0038 migration
collision, real Windows MSI/CAB installed-GUI install/upgrade/rollback and
explicit researcher approval are resolved. Versions 1.7 and revised 1.8
are not modified by this increment.
