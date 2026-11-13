# ReefVision 1.6 — installed-Windows evidence policy

**Status:** draft Track D implementation; **not** release acceptance. See [master issue #76](https://github.com/Rafael-Del-Valle/ReefVision/issues/76) and draft PR #77.

The disposable Windows clean-install harness records each required check as a
structured `PASS` entry containing a human-readable detail and a UTC timestamp.
The independent verifier in `scripts/validate_windows_acceptance_report.py`
now rejects a required `PASS` when either field is missing, blank, malformed,
or when the check timestamp falls outside the report's UTC start/completion
window. This also applies to an explicitly approved optional live-model check
that reports `PASS`, and to a real MSI upgrade when upgrade acceptance is
requested. `SKIPPED` is not silently promoted to `PASS`.

The change is backward-compatible with reports produced by the current
`New-ReefVisionEvidenceResult` helper in
`scripts/lib/windows-clean-acceptance.ps1`, which already records details
and `timestamp_utc` for successful checks. Older reports without these
fields cannot be used as **new release evidence**; their underlying assets
and historical logs are not changed or deleted.

Regression coverage in
`scripts/tests/test_validate_windows_acceptance_report.py` checks missing
or blank details, absent or malformed timestamps, events before/after the
run, non-UTC timestamps, approved optional checks, and upgrade checks. Run:

```sh
python -m unittest discover -s scripts/tests -p test_validate_windows_acceptance_report.py -v
```

The verifier checks **internal consistency, not authenticity**: a JSON report
is not a cryptographic attestation of actual desktop interaction. MSI SHA-256,
packaged API and database checks, real upgrade/rollback, and interactive
installed-GUI scientific acceptance remain separate gates. No merge, tag,
release, deployment, pretrained-model download, or user-data mutation is
authorized by this policy.

## Disposable path alias and device-namespace rejection (2026-10-29)

The report verifier requires both `acceptance_root` and
`isolated_data_root` to use ordinary absolute local drive paths. UNC shares,
Windows extended/device namespace paths, NTFS alternate-data-stream
components, reserved device names (including names with extensions), trailing
spaces/dots and control characters cannot substantiate the marker-gated
disposable data boundary. This is an additional read-only report-evidence
check; it does not modify or clean any research directory.

Standalone negative-path regressions cover those aliases, while the existing
valid local-drive and case-insensitive Windows path tests remain. The native
PowerShell harness must still independently verify filesystem ancestry and
reparse points. A structurally valid report is **not** evidence that an MSI
upgrade, rollback or installed interactive GUI was executed. Exact-head CI,
native Windows acceptance, cross-version Alembic reconciliation and biological
validation remain release blockers.

## Uninstall scientific-file retention (2026-11-13)

The installed Windows harness previously marked `data_retention=PASS` merely
because the isolated data **directory** still existed after `msiexec /x`.
Uninstall could have erased `reefvision.db` or imported coral imagery while
leaving a log directory behind, creating false-positive release evidence.

The disposable acceptance now takes an SHA-256/length snapshot of the SQLite
database and stable scientific files (imported imagery, data exports and
metadata) **after closing the installed desktop**, then compares it against
a fresh post-uninstall snapshot. Missing or modified project files fail the
acceptance before `data_retention` becomes `PASS`. Volatile logs, runtime
state and model caches are excluded to avoid conflating nonresearch cleanup
with biological-data loss. The harness requires at least a database and one
other persisted research file, and checks for directory reparse points before
reading. Hashes remain in-memory; research contents are not uploaded.

Native Windows regression fixtures verify unchanged data, deliberately
altered image bytes, removed imagery, missing SQLite and changed log content.

### All stable scientific asset formats (2026-11-13)

The original snapshot used a fixed extension allowlist. It overlooked imported
field videos (`.mp4`), camera/telemetry subtitles (`.srt`), user-trained
checkpoints (`.onnx`), extensionless research records and unknown plugin
output formats. Uninstall could have deleted those files while the retained
SQLite, PNG and JSON passed the gate.

The snapshot now checks **every regular file inside the isolated data root**
except files beneath explicitly volatile *top-level* directories
(`cache`, `logs`, `runtime`, `tmp`, `temp`). It preserves the existing
reparse-point checks, case-insensitive relative-path keys and SHA-256/byte-size
comparison. There is no science-file extension allowlist to become outdated.
New disposable PowerShell regressions assert both byte mutation and deletion
of representative video, telemetry, local-model, arbitrary-extension and
extensionless files, while changing logs, cache and runtime state remains
permissible. A trained checkpoint under `models/` is treated as a persistent
research asset, *not* excluded as a cache.

This tests byte retention for a **disposable** installed profile, not the
accuracy of media/model decoding, real-user profile coverage, files outside
the isolated root, model provenance, MSI rollback, or interactive-GUI/scientific
acceptance. Hashes and file contents are not uploaded. Release remains HOLD.

A failed post-uninstall research-retention check also suppresses automatic
cleanup of the disposable run directory, even when `msiexec /x` itself
succeeded. The generated profile remains available for failure diagnosis;
a genuinely successful acceptance may still remove its marker-owned profile.


## MSI upgrade scientific-asset retention (2026-11-13)

An earlier upgrade gate verified the Windows product registration, packaged
API version, migrated schema, project ID and one existing annotation. Those
checks could still pass if an MSI upgrade removed other original research
assets—such as field video, telemetry, researcher-trained checkpoints or plugin
outputs—while leaving the database and test annotation intact.

For an explicitly supplied, independently verified previous MSI, the disposable
Windows acceptance now captures the full stable-file SHA-256/byte-length
inventory **after the old desktop closes, before the new MSI runs**. It repeats
the inventory **immediately after MSI installation but before restarting the
new app**, and requires *every* pre-upgrade file, including SQLite, to be
unchanged. A second comparison **after the new desktop has migrated the
database and completed installed QC/Workflow Builder replay** requires every
pre-upgrade non-SQLite asset to remain byte-for-byte unchanged. Only
`reefvision.db` and its `-wal`/`-shm` sidecars may change during the latter
comparison, because authorized schema migrations and append-only review
events modify SQLite. A real SQLite file and at least one other stable asset
are still mandatory in the captured snapshots.

This adds an upgrade guard rather than another Workflow Builder node. It
preserves existing typed `qc_review_queue` execution, saved workflow results,
researcher approval and evidence boundaries. A passing upgrade report is not
recorded until the final stable-asset check succeeds, and failed acceptance
preserves its disposable data for investigation.

PowerShell regression fixtures test a changed SQLite file rejected in
pre-migration mode, accepted in explicit post-migration mode, and a damaged
image rejected in both modes. Static harness-order assertions require the
three samples to straddle MSI installation, installed QC replay and uninstall.

**Limitations:** This requires a disposable Windows environment and a previous
MSI honoring isolated acceptance; this change alone is neither a successful
native MSI upgrade nor proof of migration correctness, rollback or interactive
GUI behavior. Cross-version Alembic-0038 reconciliation, exact-head CI,
representative biology and full installed-GUI acceptance remain release
blockers. No research file content or pretrained weights are uploaded.
