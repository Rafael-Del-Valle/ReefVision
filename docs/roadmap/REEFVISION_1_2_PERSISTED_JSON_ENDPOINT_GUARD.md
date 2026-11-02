# ReefVision 1.2 — persisted longitudinal endpoint JSON guard

Status: isolated development increment; draft PR #74; **not release-ready**.
Coordination: issue #76. The existing `docs/roadmap/REEFVISION_1_2.md` remains authoritative and unchanged by this increment.

## Audited baseline

At `8c694b18f673ee602f2405dd6578db73d0b5047e`, 19 GitHub Actions workflows completed: 16 succeeded and three failed on a single Ruff formatting discrepancy at line 112 of `test_ecology_utc_sampling_windows_1_2.py`. The Windows desktop build succeeded, but this is not installed-Windows GUI/GPU acceptance. The existing standalone `POST /api/v1/ecology/longitudinal-analysis` and executable saved `ecology_longitudinal_analysis` Workflow Builder node already share the typed `LongitudinalAnalysisResponse` result, source provenance, persistence and `caller_supplied_unverified` review boundary. No new workflow node is necessary.

## Scientific replay risk and change

Pydantic's default coercion can turn JSON Boolean measurements into floats, numeric strings into measurements, integral floats into observation counts, or Unix-epoch numbers into datetimes. Such representations are not explicit biological observations and could be accepted during persisted result replay if the remaining arithmetic was altered consistently.

The existing `LongitudinalChange` typed result now requires:
- Explicit ISO 8601 calendar timestamp strings or already parsed `datetime` objects for both endpoints; no numeric Unix-time inference.
- JSON numeric values (integer or floating point, but never Boolean or string) for baseline, final, absolute change, percentage when present, elapsed days and change per day.
- A genuine JSON integer for observation count, excluding Boolean and integral float coercion.
- All previously enforced UTC chronology, source distinctness, nonnegative finite endpoints, exact elapsed-time arithmetic, and null percentage for zero baseline.

This is a **schema/replay integrity check**, not verification that any caller's timestamp, coral identity, physical calibration, independent experimental unit or reviewed annotation is authentic. It does not alter existing valid numeric scientific results or migrate old artifacts. Previously saved malformed/coerced artifacts may now fail validation instead of silently acquiring scientific meaning.

## Acceptance evidence and remaining gates

Ten parameterized negative replay cases plus a valid two-organism analysis control exercise the standalone typed response. The existing executable saved Workflow Builder acceptance additionally mutates the **actual persisted result** with an epoch timestamp, a numeric string and a Boolean observation count; all must be rejected while the unmodified result retains typed provenance and the unverified evidence level. The earlier Ruff formatting discrepancy was also corrected.

The repository cannot be cloned in the available local container because `github.com` DNS resolution fails. Consequently full local pytest, Ruff, mypy and installed Windows tests are **not claimed**; inspect exact-head CI before accepting this change. Full 1.2 release gates remain open: source-authenticated calibrated longitudinal observations, verified organism and independent-unit identity, scientist-reviewed human–model comparisons, migration reconciliation with 1.1, full backend/frontend/E2E, MSI/CAB provenance and installed Windows GUI/GPU/scientific acceptance. 1.3 remains separate and not started.

No merge, tag, publication, installation, deployment, model download, user-data deletion, or cross-version integration is authorized.
