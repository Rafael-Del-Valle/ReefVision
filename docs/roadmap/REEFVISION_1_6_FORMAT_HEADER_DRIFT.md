# ReefVision 1.6 — SQLite format-header mismatch gate

Status: **read-only diagnostic, release hold**. This work complements existing
Alembic-0038 collision diagnostics. It does not reconcile branches, execute
migrations, authorize upgrades, or modify scientific data.

## Gap

A copied 1.1 scientific database and a 1.6 QC database can have matching
`sqlite_master` DDL fingerprints and identical revision text but different
SQLite `application_id` or `user_version` header fields. These optional
format signals are independent of the Alembic stamp. Previously, a comparison
report exposed only the primary database header, so reviewers could miss
different format declarations in the reference database. Conversely,
`schema_version` is a SQLite schema-change cookie: different values may
reflect ordinary CREATE/DROP history even when the final DDL is equivalent.

## Safe offline use

Run against **two independent, verified, quiescent copies** only:

```sh
python scripts/inspect_sqlite_lineage_16.py copy-16.sqlite \
  --compare-to copy-11.sqlite \
  --fail-on-format-header-drift \
  --fail-on-lineage-collision \
  --fail-on-integrity-error
```

The JSON comparison now exposes `reference_sqlite_header` and
`format_header_differences`: named `application_id` and `user_version`
differences with both integer values. The new opt-in gate exits 2 after
emitting complete evidence if either differs. It does **not** reject a
`schema_version` difference by itself, and the old CLI behavior remains
unchanged unless this flag is given. Header equality is **not** proof of
compatible Alembic histories; the report always requires researcher review.

Disposable regression coverage verifies matching and mismatched format
headers, equal DDL and 0038 stamps, different legitimate schema cookies,
absence of private coral observations in JSON, unchanged bytes for both
databases, and a stable error when `--compare-to` is absent. Existing
scientific/QC workflows, typed outputs, saved runs and researcher approval
gates are untouched: a diagnostic for a local SQLite backup is not a
biological Workflow Builder processing node.

## Remaining hold conditions

Independent reviewed 1.1/1.6 revision-0038 reconciliation; populated
scientific and QC migration/rollback validation; exact-head CI and full
backend/frontend/E2E testing; representative biological and saved executable
workflow acceptance; physical Windows MSI/CAB clean install, upgrade,
rollback and installed-GUI checks; and explicit researcher authorization.
No cross-version merge, stamp, deployment or release is approved.
