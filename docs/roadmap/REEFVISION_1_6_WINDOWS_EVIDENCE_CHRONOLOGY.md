# ReefVision 1.6 — installed Windows acceptance chronology integrity

## Audited gap

Track D reviewed draft PR #77, master issue #76, earlier 1.0–1.5
implementations and the existing 1.6 Windows clean-install harness. The
native harness already exercises installed backend connectivity, class
visibility, saved executable QC Workflow Builder graph and replay, explicit
human review, uninstall and retained research assets. Its independent
`validate_windows_acceptance_report.py` required each PASS to carry a
timestamp within the run, but did not establish the **causal order** of
those milestones. A structurally valid, chronologically impossible report
(e.g. uninstall before installation or QC workflow replay before its
creation) could be accepted as installed evidence.

## Change

The verifier now checks milestone dependencies from the actual installed
harness, without inferring a test pass from a filename or synthetic report.
Required gates follow install -> shortcut -> first launch -> connectivity,
restart -> persistence/review -> saved workflow execution/replay -> project
exchange -> uninstall -> byte-for-byte data-retention validation. When a real upgrade is requested, the harness now records two distinct
milestones: `upgrade_install` is a PASS only after MSI installation and
pre-migration research-byte retention (before restarting the installed app),
while final `upgrade` remains NOT RUN until the restarted app executes QC,
replays its saved Workflow Builder graph, exports the project, and verifies
post-migration research-byte retention. Final `upgrade=PASS` must occur after
project exchange and before uninstall. The earlier check incorrectly required
final upgrade PASS before restart, a chronological contradiction with the
native PowerShell harness. Skipped upgrades cannot claim the install stage.
Older reports without `upgrade_install` are not new upgrade-acceptance
evidence; no historical research artifacts are modified. All required PASS timestamps must also remain within
the recorded UTC run window. Equal timestamps are allowed for clock
granularity; local files, research assets, review decisions and database
records remain unchanged.

The verification is deliberately **not** a substitute for native MSI/CAB
installation, GUI interaction, migration lineage reconciliation, real
upgrade/rollback or researcher approval. The build workflow already runs
this standard-library unittest suite on Windows before packaging. No
pretrained weights, cloud services or duplicate Workflow Builder nodes
are added.

## Evidence and acceptance

`scripts/tests/test_validate_windows_acceptance_report.py` adds
parameterized inversions for every declared causal dependency, a positive
realistic chronological report, and explicit real-upgrade/restart ordering.
The verifier also continues checking class visibility, QC coordination and
saved-workflow persistence/replay PASS gates, isolating this work from
1.7/revised 1.8 modalities. Exact-head CI and Windows installed-GUI
acceptance remain required before a version-completion notification.


## Native-harness phase reconciliation (2026-11-14)

The independent verifier and the native installer harness now distinguish the
**pre-restart installer stage** from the **post-replay scientific approval**. The
standard-library tests exercise realistic phase ordering, missing/falsely
skipped installer evidence, and forged before-install/after-uninstall times.
The native PowerShell harness regression checks that the installed-stage PASS
is recorded only after the pre-migration snapshot comparison and the final
upgrade PASS only after the post-migration snapshot. These checks protect the
evidence policy but are not proof that a real MSI upgrade has run. Full
Windows installer, GUI, backward-compatible Alembic lineage and biological
acceptance remain blocked pending independent execution.

## Clean-install versus upgrade approval regression (2026-11-14)

An exact-head CI run for the prior verifier change completed the full backend
suite (**1,888 passed, 32 skipped**) and MSI-provenance tests (**27 passed**),
but exposed one failing installed-evidence test: its expected error was the
*final* upgrade approval failure even though the new pre-migration
`upgrade_install` gate correctly fails first for clean-install-only evidence.
The regression now verifies these two failures separately, so neither the
installer stage nor the later scientific acceptance stage can be mistaken for
the other.

The native harness always sets the same reason for both SKIPPED upgrade gates
(`SkipUpgrade requested` or `previous installer not supplied`). The
independent verifier now rejects conflicting stage reasons even if both gates
say SKIPPED. Tests cover both mismatched directions and the valid no-previous-
installer path. This validates report consistency, **not** a real MSI upgrade,
Windows GUI acceptance, workflow correctness on biological datasets, or
reconciled Alembic lineage.
