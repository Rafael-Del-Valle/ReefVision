# ReefVision 1.6 — annotation pointer-release integrity

## Scope audit

The existing 1.0–1.5 annotation editor already supports drawing, moving,
resizing, cancellation, stable annotation identities, and source-pixel
coordinate restoration. Track D 1.6 recently added initiating-pointer
isolation and pan/wheel continuity. This change addresses a different gap:
the final `pointerup` location could be lost when no preceding `pointermove`
was dispatched, or when that move had not yet reached React state.

## Behavior

For a drawing, moving, or resizing gesture, only the initiating pointer can
finish the gesture. The final source-image coordinate comes from that
pointer's release event and the current viewport transform rather than the
last rendered drag preview. A box dragged and released without an
intermediate movement event can therefore be committed. A release with
nonfinite coordinates or invalid viewport scale/offset is cancelled instead
of committing nonfinite biological geometry.

The source-image document, identifiers, labels, masks, saved classifications,
QC decisions, and persisted workflow runs are not rewritten by this display
interaction. Pan gestures retain their prior behavior, including secondary
pointer isolation and wheel-zoom continuity. No database migration or
duplicate scientific Workflow Builder node is warranted: existing typed QC
and dataset workflows continue operating on explicitly saved annotations
with their existing units, provenance, retries, and human review gates.

## Regression coverage

`apps/web/src/features/annotation-editor/AnnotationEditor.test.tsx`
includes a real React interaction with no `pointermove` between pointer
down and pointer up, an unrelated pointer release, and a nonfinite release
that must not create another annotation. Existing pan, selection, drawing,
and persisted-workflow coverage must also remain green.

## Acceptance limits

CI lint/type/Vitest/Playwright/build and installed Windows GUI validation
must pass at the exact branch head before accepting this change. This
code-level test does not substitute for real mouse, touch, or pen testing.
Track D 1.6 retains its independent Alembic-0038 reconciliation,
representative biological-data checks, and installed Windows MSI/CAB
clean-install/upgrade/rollback release hold. Do not merge, tag, release,
download unapproved weights, or modify source research assets.
