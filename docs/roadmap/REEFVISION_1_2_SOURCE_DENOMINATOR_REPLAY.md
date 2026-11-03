# ReefVision 1.2 — persisted longitudinal source-denominator replay (2026-11-02)

**Status:** Development only. Draft PR #74 on `develop/reefvision-1.2`; coordination issue #76. This is not an accepted release or a verified biological study.

## Audited baseline

The preceding branch head `41b5e323be023f05b3bd362e716dd0d0075ac360` completed 19 PR-triggered Actions: 16 successful, three failed at Ruff formatting in `schemas/longitudinal_monitoring.py`. The exact Ruff diagnostic called for collapsing the `math.isclose` expression in the organism endpoint replay validator. The existing standalone exploratory endpoint and executable saved `project_source → ecology_longitudinal_analysis` Workflow Builder already share the typed `LongitudinalAnalysisResponse` result and unverified scientific provenance; no new node or 1.1 environmental integration is necessary.

## Scientific integrity increment

Correct the exact formatter failure and reject internally inconsistent saved longitudinal outputs. Reconcile `observation_count` with the unique nonblank source IDs in `analysis_provenance`; `evaluated_series_count` with the number of organism/metric changes; and completed-series observation totals plus one observation per incomplete series with the total. Reject duplicate completed organism/metric keys, missing or fabricated baseline/final source IDs, and reuse of one endpoint source across biological series. The same response schema is used for standalone results and persisted executable Workflow Builder artifacts.

These checks do **not** authenticate the caller's source records, calibration, animal/colony identity, independence of tanks or colonies, or correctness of the SHA-256 input fingerprint against raw observations that are not retained in the response. They are internal replay guards, not evidence promotion. Preserve `caller_supplied_unverified`, existing review gates, local/offline execution, and historical branch isolation. No migration or new model checkpoint is introduced.

## Acceptance and release gates

A valid three-observation fixture with one completed organism series and one singleton remains readable. Parameterized tampering tests cover forged source totals, missing/duplicate/blank/extra source IDs, series counts, completed observation counts, missing endpoint provenance, duplicate organism/metric series, and reused endpoint sources. An existing executed saved Workflow Builder test checks persisted typed provenance and rejects a forged source identifier. These are regression requirements; do not claim test success until exact-head CI completes.

Remaining: full exact-head Ruff/mypy/backend/frontend/E2E and Windows Actions; source-authenticated calibrated longitudinal observations; verified independent experimental units and scientific comparison review; 1.1 Alembic reconciliation; physical installed Windows MSI/GUI/GPU acceptance. **1.2 NOT RELEASE-READY; 1.3 not started.**
