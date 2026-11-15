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
exchange -> uninstall -> byte-for-byte data-retention validation. When
real upgrade acceptance is explicitly requested, upgrade must precede the
post-upgrade restart. All required PASS timestamps must also remain within
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
