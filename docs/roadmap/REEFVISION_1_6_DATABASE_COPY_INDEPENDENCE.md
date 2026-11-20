# ReefVision 1.6 — independent offline database-copy preflight

**Status:** Isolated Track D 1.6 scientific migration-copy guard; **release HOLD**.

## Gap confirmed before implementation

The existing row-preservation verifier already compares original/candidate SQLite
scientific and QC evidence, schema contracts, saved Workflow Builder records,
external research assets, and WAL/SHM sidecar presence. It checks whether the two
resolved input paths identify the *same* database, but previously called
`Path.resolve()` before checking their lexical parents. A symlink or Windows
junction could therefore point a supposedly disposable backup at an external
research database. Distinct SQLite paths can also be hardlinks to a third,
unscanned file, permitting changes through an undisclosed alias even when both
verified copies currently have identical records.

## Guard and evidence

Before opening either database, inspect every lexical path component for symlinks
and Windows reparse points/junctions. Reject noncanonical `..` traversal,
nonregular files, and input databases whose hardlink count is not exactly one.
All errors are fail-closed, path-free diagnostics. These checks do not modify
research rows, external assets, migration stamps, or reviewer events.

Five new subprocess regression executions cover baseline/candidate symlinked
parents, baseline/candidate hidden third-party hardlinks, direct file symlinks,
and explicit noncanonical paths. They assert exit code 2, `HOLD`, redacted
JSON, unchanged biological/QC/Workflow Builder SQLite data bytes, and no
automatic approval. Existing independently copied database cases remain
positive controls. Symbolic-link/hardlink tests skip only when the host cannot
create the corresponding filesystem link.

This is a preflight defense, **not a transactional snapshot or proof that a live
SQLite file cannot change during inspection**. The existing sidecar checks and
researcher-reviewed offline migration-copy procedure remain mandatory. The
independent 1.1/1.6 Alembic-0038 histories still require reconciliation on
disposable copies. Real biological saved-workflow validation, complete CI,
Windows MSI/CAB clean installation, upgrade/rollback, installed GUI, and
explicit researcher approval remain release blockers.

This diagnostic is outside the scientific Workflow Builder; no duplicate node
is needed. Existing typed executable standalone and saved QC workflows, units,
immutable provenance, retries and human-review gates remain unchanged.
Versions 1.7 and revised 1.8 are untouched.
