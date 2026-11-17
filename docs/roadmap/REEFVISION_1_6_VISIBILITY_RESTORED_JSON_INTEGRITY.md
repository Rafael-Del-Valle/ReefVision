# ReefVision 1.6 — restored class-visibility JSON integrity

Status: development safeguard, **not** a release acceptance or user-data repair. Coordinates with draft PR #77 and issue #76.

## Audit and gap

The 1.6 branch already implements per-local-user and project-default layer visibility, persisted settings, optimistic revision checks, SQLite class-inventory locking and UI save acknowledgements. These are UI display preferences rather than a scientific compute node, so no duplicate Workflow Builder node is warranted. Existing typed, executable, saved QC workflows and human review gates remain unchanged.

SQLite JSON columns do not constrain the deserialized shape to `list[str]`. A restored or externally modified value such as `null`, a mapping, a nested array, a number, or malformed JSON text could raise an unhandled Python/SQLAlchemy exception while building an editor bundle. A legacy unconditional PUT could silently overwrite the original bad evidence before a researcher recognized the problem.

## Safeguard

The service validates each stored list before display and before mutation, while holding the existing local SQLite writer turn for saves. SQLAlchemy JSON decoding failures and wrong JSON shapes yield a controlled HTTP 409 with a generic restore-from-verified-backup instruction. The faulty serialized content is neither exposed in HTTP errors nor rewritten. Only a separately reviewed restoration or explicit user recovery may change corrupted settings.

Legacy lists containing repeated IDs or IDs of already deleted classes retain their previous compatibility behavior: display deduplicates/filter-joins against this project's current class inventory, without modifying the stored record. Other projects remain isolated. No biological annotations, original media, model weights, saved graphs, run provenance, migrations or reviewer approvals are modified.

## Verification matrix and release hold

Disposable SQLite API regressions cover seven bad JSON encodings in **both** personal and project-default settings (14 cases), reject reads and unconditional writes atomically, preserve original storage bytes, verify a separate project still loads, restore the fixture and verify valid settings, plus two backward-compatibility cases. Prior persisted-visibility, class-inventory concurrency and optimistic-lock tests remain relevant.

Repository CI (Ruff, mypy, pytest, frontend/E2E) and installed Windows GUI still need exact-head verification. Migration collision across independent 1.1/1.6 Alembic revision 0038, representative biological/scientific saved-workflow acceptance, MSI/CAB clean install/upgrade/rollback and explicit researcher approval remain release blockers. Do not merge, tag, publish, deploy or download pretrained weights.
