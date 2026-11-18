# ReefVision 1.6 — protected scientific column collation preservation

Status: **read-only migration-copy diagnostic; release HOLD**. No migration
revision was altered or applied, and no installed database is modified.

## Gap and risk

SQLite `PRAGMA table_xinfo` does not expose the declared column collation.
A rebuilt scientific table can retain identical saved measurements and column
types while changing `label TEXT COLLATE NOCASE` to `COLLATE BINARY`. New
label lookups and uniqueness decisions may then interpret differently cased
taxonomic or sample identifiers differently. Existing row hashes and
type/nullability checks cannot detect this difference.

## Safeguard

The protected-table verifier now parses existing column declarations from
stored SQLite DDL and compares *effective column-level* collation for every
original column. Implicit and explicit `BINARY` compare equal; quoted/unquoted
case spelling of the same collation is normalized. Nested collation operators
inside CHECK expressions and generated formulas are not mistaken for the
column's declared collation. Added columns remain allowed, while changed
original collation reports `changed_column_collation_contract` and HOLD.
Unparseable original declarations fail closed rather than authorizing an
upgrade. Reports do not disclose private SQL or biological records.

The previously existing generated-column formula contract uses the shared
DDL-declaration parser. Current formula, trigger, CHECK, index, foreign-key,
row-integrity and research-asset safeguards remain in place.

## Regression and acceptance boundary

Disposable SQLite tests compare equal existing coral-label observations under
NOCASE/BINARY/RTRIM divergence, valid explicit default, quoted case spelling,
unchanged declarations and nested CHECK usage. Each diagnostic requires manual
researcher approval and never grants `upgrade_authorized` or edits the
before/after database copies.

This preflight is **not** a runtime scientific Workflow Builder node. The
existing typed and persisted executable QC nodes, scientific provenance,
review gates and saved-workflow regressions are preserved without duplicate
implementation.

Remaining release conditions: fully green exact-head backend/frontend/E2E
and Windows checks; independent 1.1/1.6 Alembic-0038 reconciliation;
representative biological and saved-workflow acceptance; genuine Windows
MSI/CAB install, upgrade, rollback and installed-GUI checks; and explicit
researcher authorization. No deployment, tag, release or merge is allowed.
