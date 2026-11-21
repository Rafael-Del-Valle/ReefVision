# ReefVision 1.6 — invocation-bound Windows acceptance evidence

The **Track D 1.6** `scripts/phase11c-acceptance.ps1 -TrackD16` wrapper now generates a random 12-character lowercase hexadecimal acceptance token and passes it to the existing disposable clean-install harness with `-EvidenceToken`. The child writes its report only under `.artifacts/windows-clean-acceptance-<token>/report.json` and refuses an already-existing evidence or run directory. Its report also records `evidence_run_token`. The wrapper requires the exact token, the actual disposable acceptance root supplied to the child, and the canonical full `<acceptance-root>/reefvision-clean-<token>/data` path before independent installed-science verification. A matching last-directory name at a different root is not accepted.

This removes a false-attribution race: two simultaneous clean-install jobs may each produce a valid new report, but only the report tied to the *current* parent invocation can be evaluated. A missing, stale or mismatched report fails closed. An unrelated concurrent run does not spuriously cause rejection. Historical Phase 11C mode retains its prior unique-new-directory selector, and direct clean-install runs without `-EvidenceToken` retain their generated-token behavior. `-PlanOnly` remains a non-installing dry run and does not imply a release-ready installed-GUI result.

**Regressions:** `scripts/test-phase11c-report-selection.ps1` exercises native Windows PowerShell token shape, canonical case/path normalization, rejection of different-root and same-basename substituted data paths, legacy report selection and exact-head checks. `apps/api/reefvision/tests/test_phase11c_acceptance_contract.py` checks wrapper/child token handoff and fail-closed report binding. CI runs the native PowerShell script in the Windows research-preservation job. The existing installed-science validator still requires class visibility, QC review and executable persisted/replayed typed Workflow Builder evidence with scientific provenance and explicit researcher review.

**Release status: HOLD.** This is an evidence-attribution improvement, **not** a genuine installed Windows MSI/CAB acceptance result. Independent 1.1/1.6 Alembic-0038 reconciliation, complete exact-head backend/frontend/E2E/Windows CI, representative biological saved-workflow checks, real MSI clean installation/upgrade/rollback, installed GUI and explicit researcher approval remain outstanding. No 1.7/revised-1.8 changes, merge, tag, release, hosting, model-weight download or research-asset deletion are authorized.

## Fully qualified local-drive evidence paths (2026-11-21)

The 1.6 wrapper now refuses Windows drive-relative (`C:folder`),
current-drive-rooted (`\\folder`), UNC and extended-device evidence roots
**before** calling `GetFullPath`. On Windows, `Path.IsPathRooted` can return
true for a path that is not fully qualified; expanding it against the
process's working directory could otherwise make an incomplete report path
appear to match the invocation's disposable root. The expected root supplied
to the child, returned acceptance root and returned isolated data root all
require ordinary fully qualified local-drive paths. Case differences and
forward-slash separators remain supported.

Native PowerShell regressions reject five unsafe path forms independently
at all three validation positions and accept a standard forward-slash path.
The independent Python verifier remains the final installed-science gate.
No user data, schema, model, or Workflow Builder node is changed.

## Independent installed-science token binding (2026-11-21)

The standalone Python installed-Windows verifier now checks the report
`evidence_run_token` against its exact `reefvision-clean-<token>/data`
directory, even when called without the PowerShell wrapper. For Track D 1.6,
the wrapper supplies `--expected-evidence-token`, binding the independent
class-visibility, QC and saved executable Workflow Builder PASS decision to
the invocation that actually launched the disposable MSI test. Missing,
malformed, replayed and substituted tokens fail closed. Historical direct
install reports with no invocation token remain supported without this
explicit option.

Python regression cases cover matching, missing, invalid/case-changed and
different-run tokens plus the parent-to-verifier CLI contract. This is an
evidence integrity improvement, not proof of a completed MSI installation;
full exact-head CI, cross-track 0038 reconciliation, representative biology,
installed-GUI upgrade/rollback, and researcher approval remain outstanding.
