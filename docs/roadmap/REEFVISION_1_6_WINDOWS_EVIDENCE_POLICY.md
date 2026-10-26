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
