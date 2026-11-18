# ReefVision 1.6 — preserve scientific and reviewer trigger contracts

Status: **read-only migration-copy verification; release HOLD**. This change is not
a migration, a grant of approval, a restoration of conflicting Alembic lineages,
or a substitute for an installed-Windows acceptance test.

## Audited gap

Earlier 1.6 checks retained all original protected-table values, column rules,
CHECK constraints, unique-index semantics, foreign-key policies, reviewer
append chronology and research assets. They did **not** retain SQLite triggers.
An upgrade could drop a BEFORE UPDATE/DELETE guard, change a trigger's WHEN
condition or replace RAISE(ABORT) with a no-op while existing scientific and QC
records remained identical. Future observations or reviewer events could then
be changed in ways forbidden by the original database contract.

## Preservation rule

For each preexisting table in the explicitly enumerated protected-table set,
retain **every originally installed trigger by name and normalized SQL token
contract**. The comparison includes the timing, event, target, WHEN predicate
and complete body. Only insignificant whitespace, SQL comments and unquoted
keyword case are normalized. New triggers may be added. Missing, renamed,
rebound or changed original triggers return `changed_trigger_contract` and
`HOLD`; no private trigger SQL or observation values appear in the JSON
report. Conservative false-positive holds require researcher inspection,
never automated rewriting.

The check does not claim to inventory triggers on unprotected tables or prove
that arbitrary newly added triggers are harmless. It remains subordinate to
the unresolved 1.1/1.6 revision-0038 reconciliation and preserved pre/post
row, index, FK, CHECK and asset evidence.

## Regression and acceptance

The registered `scripts/tests/test_verify_research_row_preservation_16.py`
suite includes scientific records and reviewer QC events, each with controls
for exact preservation, insignificant formatting and additive guards, and
negative cases for missing triggers, changed events, narrowed WHEN gates and
inert actions. The tests compare read-only report outcomes and unchanged
database bytes, verify report privacy, and require human approval in every
case. A passing preservation-only report must **never** authorize upgrade.

Existing executable Workflow Builder `qc_review_queue` nodes, saved graph and
run provenance, typed dimensionless outputs, reliable retries and researcher
review gates are unchanged. This **offline installation/migration integrity
verifier** is not a scientific Workflow Builder analysis node; duplicating QC
runtime behavior would introduce unsafe competing state.

Release remains on hold pending full exact-head CI, independent Alembic-0038
lineage reconciliation and copied-database migration/recovery matrix,
representative biological and saved-workflow scientific acceptance, actual
Windows MSI/CAB clean install/upgrade/rollback and installed GUI validation,
and explicit researcher approval. No merge, tag, release, deployment, model
download or research asset mutation is authorized.
