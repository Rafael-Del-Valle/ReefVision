# ReefVision 1.2 — annotation-to-calibration provenance cardinality

**Status:** isolated development on `develop/reefvision-1.2`, draft PR #74.
Not a verified growth analysis, accepted study design, or release.

## Scientific failure mode

The project-owned ecological registry allows one calibration evidence link
per frozen annotation evidence link. The v0021 persisted-candidate validator
already rejected repeated calibration/metric rows and conflicting metadata
under the same calibration ID, but did not reject a *single annotation
evidence ID* associated with two distinct calibration IDs. A re-signed
Workflow Builder result could therefore claim a second calibration source
that the registry cannot create, distorting the source provenance and
potentially the reported sampling effort.

## Bounded correction

The existing `EcologyMeasurementCandidatesResponse` v0021 source validator
now enforces a one-to-one annotation-evidence-to-calibration-evidence
relationship across all candidate rows. The same frozen calibration may
legitimately yield box width and height; different annotations may use
different calibrations. Older persisted contracts retain historical parsing.
No new workflow node, migration, cloud dependency, or model download is added.

Focused tests cover standalone API and *executed, saved*
`project_source → ecology_measurement_candidates` Workflow Builder
artifacts, including valid box width/height, re-signed forged calibration
links, and a two-date longitudinal series reusing one annotation link.
The predecessor CI formatting errors are corrected separately in the same
draft branch. Full exact-head CI must pass before claiming integration.

## Interpretation and remaining gates

This is **internal provenance consistency**, not calibration accuracy,
authenticated independent experimental units, or scientist-approved
longitudinal growth. The evidence remains `linked_unverified` with
`scientist_review_required`. Source-linked review, representative coral
data, migration reconciliation with 1.1, installed Windows GUI/GPU and
MSI acceptance are still outstanding. No merge, tag, release or deployment.
