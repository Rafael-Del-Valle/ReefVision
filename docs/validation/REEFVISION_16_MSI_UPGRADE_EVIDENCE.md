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
