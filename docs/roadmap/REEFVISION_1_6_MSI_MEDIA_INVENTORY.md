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
