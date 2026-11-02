# ReefVision 1.2 — UTC population-stratum replay integrity

**Status:** isolated draft development; not a verified ecological analysis or release.

## Scientific issue

The longitudinal analysis kernel already normalizes acquisition timestamps to UTC,
but the persisted population validator grouped experimental-unit endpoints using
the displayed calendar date. For example, 2026-04-01 08:00 UTC and
2026-03-31 22:00 -10:00 describe the same instant. A coordinated alteration
of the unit timestamp and population baseline date could move a tank into
the March 31 descriptive stratum without changing its observation time.

## Bounded fix

The shared `LongitudinalAnalysisResponse` contract now groups population
strata by UTC-normalized unit endpoint dates, rejects timezone-naive
unit endpoints, and reconciles organism sampling windows by UTC dates.
Both the standalone ecological API and executable saved
`project_source → ecology_longitudinal_analysis` Workflow Builder use this
typed persisted contract. No new node, 1.1 environmental duplicate,
migration, model weight or verified dataset mutation is introduced.

## Focused acceptance

`test_ecology_utc_sampling_windows_1_2.py` checks an equivalent-offset
positive control, a jointly forged timestamp/population-date negative
control, a timezone-naive negative control, and tampering of an actual
executed and persisted Workflow Builder result. This iteration also fixes
three Ruff formatting differences reported by exact predecessor CI
on `dfb9470f`. Exact-head CI must complete before test success is claimed.

## Scientific limitations and release gate

These checks establish internal arithmetic and stratum consistency only.
They do not authenticate animal identity, parent colony, acquisition time,
calibration, independent tanks, or scientific review. Evidence remains
`caller_supplied_unverified`, and image observations are not biological
replicates. Release still requires full CI, representative scientist-reviewed
data, migration reconciliation, and installed Windows MSI/GUI/GPU acceptance.
Preserve draft PR #74 and the existing 1.2 roadmap. Do not merge, tag,
publish, install or deploy without explicit approval.
