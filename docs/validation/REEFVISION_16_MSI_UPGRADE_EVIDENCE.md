# ReefVision 1.6 — two-installer Windows upgrade evidence

The disposable Windows acceptance harness now records a SHA-256 digest for the
**previous** MSI when a real upgrade is requested. The report validator requires
that digest, the previous MSI path and a strictly lower previous ProductVersion
before accepting `--expected-upgrade passed`.

When invoked by the installed-Windows acceptance workflow with `--installer`,
validation checks the actual bytes and paths of **both** the target and previous
MSI. Missing, substituted, identical or modified previous installers fail
closed. Clean-install-only runs still report upgrade `SKIPPED` and do not
require a previous MSI. Existing reports without a previous digest are not
sufficient to claim upgrade acceptance; rerun on an isolated Windows machine.

Regression coverage uses disposable synthetic MSI bytes only to verify the
evidence contract. It does **not** establish a successful Windows installation,
upgrade, rollback, interactive GUI, or scientific-data preservation. Those
remain separate release blockers, along with the 1.1/1.6 Alembic 0038
collision and representative biological-data acceptance. No actual research
assets, pretrained weights, or user installations are modified.

## 2026-10-29 — bind PASS evidence to the disposable data root

The installed-Windows report validator now requires `acceptance_root` and
`isolated_data_root` to be absolute Windows paths. The latter must be the
exact `reefvision-clean-<12 hex characters>/data` child of the former,
with Windows case-insensitive comparisons. It rejects path traversal, a
drive-root acceptance directory, missing fields, foreign drives, sibling
prefix lookalikes, malformed run identifiers, and normal application-data
paths substituted as the isolated root. This prevents an apparently green
report from omitting or misidentifying the disposable research-data boundary.

The Windows acceptance harness still owns the **actual filesystem** safety
checks (including junctions/reparse points and protection of normal user
data). The report validator checks claimed evidence structure only; it cannot
prove the real machine's isolation without the harness. CI runs the standalone
Python contract regressions using:

```sh
python -m unittest discover -s scripts/tests -p test_validate_windows_acceptance_report.py -v
```

A green synthetic report test is **not** evidence of a real installed GUI,
MSI upgrade/rollback, data retention or reconciliation of Alembic 0038.
