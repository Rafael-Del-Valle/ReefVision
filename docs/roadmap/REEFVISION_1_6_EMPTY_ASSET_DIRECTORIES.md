# ReefVision 1.6 — preserve empty research folders across migration copies

**Status:** Read-only offline migration acceptance improvement; **release HOLD**.

## Audited gap

The existing 1.6 offline preservation preflight hashes each research file,
validates non-symlink copies, detects concurrent mutation, and compares every
original relative file path. It also records directory metadata so changes
during the scan fail closed. However, the baseline-versus-candidate comparison
only included files. A directory containing no files, such as a curated
unscored study collection or a planned field-observation folder, could be
removed during an upgrade without affecting any file hashes. The tool could
therefore report `PASS_PRESERVATION_ONLY` despite lost research organization.

## Implementation

The asset-copy comparison now includes the original relative directory
inventory, omitting the already-required root `.`. Each original directory
must remain at its relative path; candidate additions are permitted. The
public diagnostic reports only counts of baseline, candidate, missing and
added directories, not private directory names or observation contents.
Missing original directories result in `research_directories_missing` and
`HOLD` even if every scientific file byte and every SQLite record matches.
Both asset roots remain read-only and independent, with symlink and
mutation-during-scan safeguards unchanged.

Three disposable-SQLite/API CLI cases cover an exact directory copy plus an
added collection, a missing original empty leaf, and a missing original empty
subtree. They assert status, exact missing counts, privacy, unchanged database
bytes, unchanged original media, and explicit researcher approval. The
existing full-copy positive regression now asserts the directory counts.

## Workflow Builder and release boundary

This is an out-of-band desktop migration-copy safeguard, not a new scientific
analysis capability; no duplicate workflow node, user approval, reviewer event
or saved graph was introduced. The existing executable typed `qc_review_queue`
Workflow Builder, immutable evidence, retries and human review remain intact.
No 1.7 or revised 1.8 work, cross-version merge, Alembic revision rewrite,
deployment, downloaded model weights or research asset deletion occurred.

Still required: independently reconcile the 1.1/1.6 Alembic-0038 collision;
full exact-head lint, type, backend, frontend and E2E; representative biology
and saved-workflow acceptance; real Windows MSI/CAB clean install, upgrade,
rollback and installed-GUI validation; and explicit owner approval. A passing
offline preflight does **not** authorize an upgrade.
