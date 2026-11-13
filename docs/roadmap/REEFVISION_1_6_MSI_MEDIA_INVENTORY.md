# ReefVision 1.6 — MSI Media/CAB inventory evidence

**Development only; native Windows installation/GUI acceptance remains pending.**

Existing 1.6 packaging checked that MSI-declared CABs existed and hashed every
physical CAB. An undeclared CAB left from an earlier split-media build could
therefore be hashed into a new manifest and pass the hash-only verifier.

The Windows build script now compares its entire physical CAB inventory against
the MSI's authoritative Windows Installer **Media** table, refusing unsafe,
duplicate, missing, empty or extra CABs before release provenance is produced.
The manifest carries a separate `media_cabinets` list from that table; the
read-only Python provenance validator independently cross-checks the declared
list against hashed payload records. It never repairs or deletes user data.
An old manifest without Media evidence is not suitable as *new* release proof.

Offline regressions cover missing, unsafe, duplicate and mismatched inventory,
including a fully hashed stale CAB. Run
`python -m pytest scripts/tests/test_validate_msi_provenance.py -q`.

This packaging safeguard does not alter QC decisions, user-created model assets,
or the existing typed executable `qc_review_queue` Workflow Builder node.
1.1/1.6 Alembic 0038 reconciliation, actual Windows MSI/CAB install/upgrade,
installed GUI, and representative scientific saved-workflow tests remain open.

## Independent Windows artifact handoff (2026-11-13)

The build job hashes the MSI/CAB set and binds its manifest to the checked-out
commit. The disposable **second Windows runner** previously verified the MSI
Media table but did not re-run `validate_msi_provenance.py` after downloading
the artifact. A previously valid, altered, or misrouted artifact could therefore
reach the install step without a second-runner check of the claimed source
commit, Media inventory, and file digests.

The Windows clean-install job now explicitly provisions Python 3.12 and,
**before querying Media or invoking msiexec**, independently validates the
downloaded MSI, every external CAB, manifest flags, exact version, and exact
`git rev-parse HEAD` commit for that workflow checkout. A missing manifest,
foreign-commit bundle, extra/empty/linked CAB, or mismatched digest fails
closed without modifying any installer payload or research data. Both build
and acceptance jobs use the same GitHub workflow source checkout; a later
PR branch update must trigger its own new workflow run.

Regression coverage exercises a correctly hashed foreign-commit bundle and
asserts that the independent guard is mandatory and ordered before installation
in `.github/workflows/build-desktop.yml`. Run the existing provenance tests
with `python -m pytest scripts/tests/test_validate_msi_provenance.py -q`.

This proves consistency with the CI checkout, **not** binary authenticity,
cryptographic code-signing, a real GUI session, field hardware, or a supported
old-to-new upgrade/rollback. The 1.1/1.6 Alembic collision and those release
gates remain unresolved. No unapproved pretrained checkpoints, scientific
verification decisions, or user research assets are affected.
