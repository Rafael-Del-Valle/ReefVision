# ReefVision 1.6 — preserve existing pose and behavior evidence during offline upgrades

**Scope:** read-only research-data preservation preflight on isolated
`develop/reefvision-1.6`. This is a gap audit across earlier ReefVision
features, not a new pose model or a duplicate Workflow Builder node.

## Why this matters

The existing 1.6 migration-copy verifier already protected class visibility,
review queues, saved executable Workflow Builder records, original media and
other scientific source tables. Its explicitly bounded inventory did **not**
cover 19 preexisting SQLAlchemy tables for pose identity, animal behavior and
skeleton measurements. An offline upgrade could alter a reviewed landmark,
identity correction, pose training dataset or behavior bout while otherwise
preserving QC and Workflow Builder rows, incorrectly returning a
`PASS_PRESERVATION_ONLY` result.

This increment extends the same read-only table/column, DDL and row-fingerprint
checks to all 19 existing tables for pose landmark schemas, schema bindings,
tracked observations, association and correction records, pose training and
active learning, skeleton revision graphs, ethograms, behavior states/bouts,
and locally registered behavior classifiers and predictions.

## Acceptance and boundaries

The parameterized regression fixture creates 19 disposable tables containing
nonpublic-looking biological evidence. It changes one table at a time and
requires **HOLD** in all 19 cases, while preserving both database files
byte-for-byte. A removed landmark-observation table also causes HOLD;
an additive column with unchanged old values still yields only
`PASS_PRESERVATION_ONLY`, not installation authorization. Public reports
contain static table categories, counts and digests, never observation values.

Run `python -m pytest scripts/tests/test_verify_research_row_preservation_16.py -v`;
the exact-head Linux Ruff/pytest and native Windows jobs already execute this
file in `.github/workflows/ci.yml`. Independent end-to-end native Windows
installer/installed GUI, representative biological datasets, complete 1.6
scope, saved-workflow retries and approval gates still require acceptance.

**Important:** The read-only check does not reconcile the conflicting 1.1 and
1.6 Alembic-0038 lineages, does not migrate data, does not prove *all* possible
SQLite tables are protected, and does not perform model training or download
weights. The existing executable saved pose/QC Workflow Builder, typed units,
provenance, reliable retries and manual researcher review remain unchanged.
No main merge, tag, release, installation or asset deletion is authorized.
