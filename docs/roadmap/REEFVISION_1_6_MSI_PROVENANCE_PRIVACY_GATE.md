# ReefVision 1.6 — offline MSI/CAB provenance privacy boundary

**Track D / draft PR #77 / master issue #76. Development safeguard only; not release approval.**

## Scope audit and gap

ReefVision 1.6 already has class management, class-visibility persistence, QC review and saved executable typed QC Workflow Builder machinery. The existing `scripts/validate_msi_provenance.py` performs a separate read-only MSI/CAB source-commit, cabinet-inventory and SHA-256 preflight before the native Windows installer acceptance harness invokes an installer. A new Workflow Builder node would be inappropriate for this out-of-band packaging gate.

The previous validator echoed a duplicated, attacker-supplied JSON key and some manifest-supplied installer filenames in error messages. If malformed provenance contained a study identifier or a local artifact label, installer logs could reveal it. Initial directory and manifest metadata probes could also propagate `PermissionError`/filesystem exceptions instead of a controlled failed preflight.

## Contract

- Denied directory metadata, manifest metadata, manifest decoding and MSI/CAB file access fail closed with fixed, privacy-safe `BundleValidationError` reasons. No filesystem exception text is included in CLI diagnostics.
- Duplicate JSON keys remain forbidden, but the untrusted key itself is never included in the error.
- Failed artifact digest, missing, empty and unreadable artifact diagnostics do not echo manifest-derived filenames. Valid successful reports may still include the installer and cabinet names as deliberate provenance outputs.
- Verification does not install, extract, rename, delete or repair artifacts. Failure means **HOLD**, not authorization to skip provenance, Media-table inspection, MSI installation, SQLite migration or installed-GUI tests.
- Fault-injection regressions exercise denied metadata in addition to existing denied reads/hashes/inventory/ancestor checks, and test that private manifest keys/artifact labels are absent from error strings and original fixture bytes remain unchanged.

## Limitations / release decision

This verifier is not a cryptographic signature verifier, does not attest Microsoft Authenticode identity, does not provide an atomic defense against malicious filesystem race conditions, and cannot substitute for Windows MSI/CAB installation, clean upgrade/rollback, installed GUI or representative biological and saved-workflow acceptance. Independent reconciliation of the conflicting 1.1/1.6 Alembic-0038 histories and explicit researcher approval remain required. No change here merges, releases or authorizes research-model downloads.
