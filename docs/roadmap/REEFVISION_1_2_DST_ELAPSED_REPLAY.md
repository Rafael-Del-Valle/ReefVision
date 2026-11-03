# ReefVision 1.2 — UTC elapsed-time replay integrity (2026-11-02)

**Status:** development-only, not release-ready. Track B / isolated draft PR #74.

The existing standalone `POST /api/v1/ecology/longitudinal-analysis` and
executable, persisted Workflow Builder `ecology_longitudinal_analysis` share
the `LongitudinalChange` result contract. A replayed endpoint previously
subtracted two aware Python datetimes directly. When they share the same
seasonal timezone object, Python wall-clock subtraction ignores a daylight-
saving offset transition. A March 7–9 2026 pair is **47 actual hours**,
not 48; an October 31–November 2 pair is **49 actual hours**, not 48.
A wrong 48-hour denominator changes daily coral-growth or activity rates.

The typed replay validator now converts both endpoint timestamps to UTC
*before* subtraction, consistent with the existing UTC sampling-date checks
and the production domain calculator. Two portable seasonal-offset regression
cases assert correct 47/49-hour durations and reject a forged 48-hour rate.
The existing executable saved Workflow Builder and standalone API acceptance
test also runs a spring-transition, two-organism/tank example, comparing
typed persisted changes, unit coverage, provenance and review designation.
No new node, storage, model weights or migration is required.

This verifies only internal time arithmetic, **not** authenticated biological
sources, calibration, independent tanks/colonies or scientist review.
`caller_supplied_unverified` remains mandatory. Exact-head CI, migrations
and full installed Windows GUI/GPU and representative scientific acceptance
remain release blockers. No merge/tag/publish/install/deploy is authorized.
