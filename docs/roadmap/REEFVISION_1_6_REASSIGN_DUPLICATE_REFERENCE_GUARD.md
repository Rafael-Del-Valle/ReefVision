# ReefVision 1.6 — duplicate reference IDs in class-operation previews

**Development-only; not release accepted.** This increment strengthens the
existing Class Manager's researcher authorization checks without changing the
backend, databases, annotations, or Workflow Builder execution semantics.

## Audited implementation and gap

Reassign and Reassign-and-Delete already use backend-generated operation IDs,
SHA-256 review checksums, explicit researcher confirmation, source/target
identity binding, and typed saved QC Workflow Builder provenance. The UI
requires complete mutable/protected/blocking evidence groups and a count that
matches the number of listed record IDs. However, a defective response such as
`count: 2, record_ids: ["observation-1", "observation-1"]` could satisfy that
check while concealing a second distinct record. A researcher could approve an
operation based on an incomplete scientific reference inventory.

## Bounded change

Each mutable, protected, and blocking evidence group now requires **unique**
record IDs in addition to the existing complete, nonblank, exact-count
contract. Duplicate identifiers make the preview non-executable and show the
incomplete-evidence error. No scientific record is silently reassigned or
relabelled; the backend's immutable evidence checksum remains authoritative.

Six new parameterized React cases cover duplicate IDs in the three groups for
both operation types. Existing positive cases still permit correctly formed
approved previews. A preexisting six-case blocking-evidence fixture was
repaired to include the required empty audit warnings array, aligning the
test with the backend schema rather than weakening the production guard.

This UI-only fail-closed preview validation needs no new scientific Workflow
Builder node; existing executable/saved QC nodes, typed units, run persistence,
provenance, retries, and human approval remain unchanged.

## Acceptance still required

Run exact-head Prettier, TypeScript, Vitest, backend lint/typing/pytest,
Playwright/E2E and production build, migration and real biological saved-QC
regressions, and genuine Windows MSI/CAB install/upgrade/rollback and
installed-GUI validation. Resolve the independent 1.1/1.6 Alembic-0038
collision before integration. No release, merge, deployment or owner approval
is implied.
