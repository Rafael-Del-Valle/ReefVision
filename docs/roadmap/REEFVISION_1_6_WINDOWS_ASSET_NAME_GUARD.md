# ReefVision 1.6 — Windows-portable research asset names

**Scope:** Read-only offline migration-copy verification, not a migration,
export transformation, automatic filename repair or new Workflow Builder
analysis operation. The existing executable saved QC Workflow Builder,
typed outputs, retries, provenance and reviewer approval are unchanged.

The preservation comparison previously rejected case-fold/Unicode
**collisions** but could return `PASS_PRESERVATION_ONLY` when both independent
copies contained an identically named asset that Win32 could not represent.
Copying a biological image, checkpoint or empty study directory to Windows
could then fail or silently target a different path despite equal file hashes.

The verifier now rejects incompatible path components in **either** original
or candidate trees: Win32 device stems (including extensions and superscript
digits), forbidden/control characters, and names ending with a space or dot.
It checks every relative directory and file component before reporting PASS,
including added candidate media. The diagnostic
`asset_windows_incompatible_name` contains no private names or contents.
Original files are not renamed, changed, removed or followed through links.
Normal filenames, multi-dot extensions and non-device COM10/LPT10 names
continue to pass. A PASS is only preservation evidence and never authorizes
an upgrade without explicit researcher approval.

Regression scenarios create independent disposable SQLite copies and
research trees. Linux tests cover ten incompatible paths in baseline and/or
candidate with unchanged private records, plus a valid-name control; Windows
skips only uncreatable invalid-name fixtures while retaining the valid control.
Repository CI, actual MSI/CAB installation, Windows installed-GUI workflow,
1.1/1.6 revision-0038 reconciliation, biological/saved-workflow acceptance and
upgrade/rollback remain release gates.
