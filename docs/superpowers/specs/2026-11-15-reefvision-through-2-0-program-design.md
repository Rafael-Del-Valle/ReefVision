# ReefVision Through 2.0 Program Design

**Status:** Approved execution design derived from the owner-supplied “Build
ReefVision through 2.0” scope and the 2026-11-15 feature-accountability
addendum.

## Intent

Carry the validated ReefVision 1.1–1.3 release line through a verifiable 2.0
candidate without losing scientific evidence, migration history, older project
readability, or ordinary image/video annotation usability. A release is not
complete merely because a broad milestone or test suite passes: every planned
feature has an independently auditable status, entry point, acceptance check,
and evidence record.

## Goals

- Maintain one canonical, versioned feature inventory from 1.1 through 2.0.
- Reconcile each existing draft branch in dependency order without rewriting
  applied migrations or overwriting concurrent work.
- Keep the first-time path visible: create/open project, import, annotate,
  review, and export.
- Put advanced controls in the workspace that owns the task; add a top-level
  workspace only for a durable, distinct activity.
- Preserve standalone and executable saved Workflow Builder parity where the
  operation is appropriate for automation.
- Separate deterministic engineering fixtures, installed desktop evidence,
  physical-hardware evidence, and representative scientific evidence.
- Leave clean, pushed, evidence-linked checkpoints whenever work pauses.

## Non-goals

- Hyperspectral imagery through 2.0.
- Cloud accounts, hosted storage, shared online projects, or real-time cloud
  collaboration.
- Stereo reconstruction.
- A plugin marketplace.
- Treating model output, geometry similarity, or provisional identity evidence
  as reviewed scientific truth.

## Approaches considered

### Markdown-only checklist

Easy to review but difficult to validate mechanically. Required fields and
status-specific blockers can silently disappear, and broad milestone edits can
accidentally close individual features.

### GitHub issue/PR state as the source of truth

Provides live links but is not offline, branch-portable, or reproducible from a
research package. Issue comments also mix superseded and current evidence.

### Canonical JSON plus generated Markdown (selected)

Store stable feature records in JSON and generate a human-readable Markdown
view. A repository validator enforces schema, unique IDs, dependency validity,
status rules, entry points, acceptance checks, and evidence requirements.
GitHub comments link to exact inventory revisions rather than replacing the
inventory. This costs a small generator/validator but makes omissions and
status drift test failures.

## Feature record contract

Every feature record contains:

- stable ID and title;
- target version and source references;
- dependencies by stable feature ID;
- whether it is user-facing;
- the exact place a new user finds it, or an explicit non-UI rationale;
- standalone and Workflow Builder expectations;
- acceptance checks;
- evidence records separated into source, browser, installed Windows,
  physical hardware, and representative research data;
- one status: `verified`, `in_progress`, `blocked`, or
  `explicitly_deferred`;
- an exact missing input for every blocked record;
- a scope decision and reason for every deferred record.

`verified` requires every applicable acceptance check and evidence class.
Synthetic evidence may verify software behavior but cannot satisfy a
representative-data check. A broad release suite cannot mutate child feature
status automatically.

## Version execution model

Work one version at a time:

1. Refresh the validated predecessor, target branch, draft PR, issue #76, and
   exact-head CI.
2. Audit ancestry and migration graphs.
3. Reproduce branch-specific defects before forward-porting fixes.
4. Reconcile the predecessor through explicit merge commits, preserving
   migration IDs and user data.
5. Implement the smallest incomplete feature slice with tests.
6. Test its normal GUI entry path and standalone/workflow parity.
7. Run version-level gates only after its feature entries are individually
   resolved.
8. Push without force and update the draft PR and issue #76.

The 1.4 integration begins from draft #79 and the validated 1.3 head
`f44053a9`. Later version plans are written only after the predecessor has a
clean, reviewed integration head.

`clean, reviewed` does not mean that a blocked scientific check is silently
waived. Work may continue on engineering that does not depend on a missing
external artifact, but the next version is not started and the current version
is not called complete while one of its feature records remains `blocked` or
`in_progress`. Older unresolved feature records also remain release blockers
unless an explicit scope decision defers them.

When sources conflict, the inventory uses this precedence order: the owner's
current explicit scope decision, an approved specification or decision record,
the version roadmap, issue #76, then an unmerged draft PR claim. Lower-priority
sources remain linked as provenance but cannot silently expand or close the
release obligation.

## GUI and discoverability

- Image and video annotation share conventions for classes, overlays, review,
  undo/redo, and source-pixel coordinates.
- 3D opens from a project asset or a 3D task inside the scientific/results
  workspace, not from an unconditional top-level tab.
- Model comparison belongs in Models.
- Reviewer queues belong in Review.
- Environmental links remain contextual to scientific observations.
- Plugin management and experiment registration belong in Models/Research;
  advanced graph editing remains in Workflow Builder.
- Every new user-facing record includes a browser test that starts from the
  normal navigation entry rather than mounting the component directly.

## Scope rulings

### SLEAP

Audit exact distributed components independently. `sleap-io==0.9.2` carries
BSD-3-Clause. The upstream `sleap-nn==0.3.3` tag currently contains a GPLv3
LICENSE while its package metadata declares BSD-3-Clause. That material
inconsistency prevents a verified distribution decision. Under the approved
fail-closed rule, remove active SLEAP-specific provider, runtime, UI,
installer, CI, and SLP-specific supported paths from the release line.
Preserve historical model/run metadata, annotations, tracks, source paths and
provenance with an unavailable-provider state and actionable neutral export
guidance. Native ReefPose remains the standard pose path.

The BSD-3-Clause `sleap-io==0.9.2` library may remain only behind neutral NWB
interchange when the distribution audit proves that path does not register,
run, train, advertise, or import/export the retired SLEAP-specific runtime or
SLP format. Historical SLP-only artifacts remain readable as preserved source
assets and produce an actionable unavailable-provider/export message; they are
not executed.

### Scientific review authority

Until a versioned reviewer-role and adjudication contract is approved, a local
review record is durable evidence of who made a decision, but not external
scientific sign-off. A feature that requires independent review remains
`blocked` with the exact missing reviewer authority, adjudication rule, and
reference evidence. Saved workflows may reference such decisions but may not
upgrade provisional attribution into final approval.

### Deferred and separate features

- Hyperspectral is explicitly deferred beyond 2.0; existing records stay
  readable.
- Cloud collaboration and stereo are outside 2.0.
- 3D organism matching is a spatial-review feature dependent on reviewed
  registration and specimen correspondence.
- Appearance-based ReefPose re-identification across long gaps or recordings
  is a different feature. Existing short-gap tracking does not satisfy it. It
  remains a distinct 2.0 entry and cannot be marked verified without a defined
  model, ambiguity/review behavior, held-out cross-gap/video identities, false
  match/missed match rates, and installed workflow evidence.

## Release-specific detail that must remain visible

- 1.1 projective density and repeated-measures analysis remain individual
  unresolved entries, not children hidden under “scientific foundation.”
- 1.4 biological-condition measurements remain separate from geometric shape
  descriptors; geometry alone cannot verify condition.
- 1.4 anatomical branch length is distinct from an arbitrary surface path. It
  requires declared endpoints/centerline method, scale evidence, independent
  reference measurements, and repeatability thresholds before the anatomical
  claim can be verified.
- 1.5 early plugin foundations remain separate from the full 2.0 plugin SDK.
- 1.6 migration-lineage reconciliation is a data-preservation feature, not
  merely a packaging check.

## Compatibility and data safety

- Never modify original source media.
- Keep canonical coordinates in source pixels.
- Keep predictions/proposals separate from verified annotations.
- Keep dataset versions immutable and group-aware.
- Never edit applied Alembic migrations. Reconcile independent histories with
  new merge/reconciliation revisions and copy-based fingerprint tests.
- ReefVision 1.4 must open and upgrade the validated 1.3 lineage and its own
  draft lineage. It does not promise forward compatibility with databases
  first created by 1.6; the independent 1.6 `0038` lineage is reconciled and
  tested in the 1.6 integration milestone.
- Preserve unknown historical and plugin/provider metadata.
- All timestamps are UTC and all public API identifiers are UUIDs.
- Filesystem mutation stays inside storage services.

## Completion rule

The 2.0 candidate may be called feature-complete only when the inventory
validator passes and every entry is either:

- `verified` with its applicable evidence; or
- `explicitly_deferred` by an approved scope decision.

`in_progress` and `blocked` entries keep the candidate on release hold.
Merging, tagging, and publication remain separately approved actions.
