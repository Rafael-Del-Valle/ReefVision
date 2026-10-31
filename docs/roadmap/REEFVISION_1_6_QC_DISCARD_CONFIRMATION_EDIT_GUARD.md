# ReefVision 1.6 — QC draft-discard confirmation edit guard

**Status:** implemented on isolated 1.6 development branch; release HOLD.

## Audited gap

The coordination panel already required explicit confirmation before closing
with unsent reviewer notes or assignment drafts, and blocked close during an
unresolved audit-event request. However, the confirmation remained visible
after the researcher edited the note, assignment or self-reported reviewer
label. Clicking the previously approved discard button could therefore
silently discard new biological context that had not existed when the
researcher first confirmed.

## Change

Every edit to the local coordination draft invalidates the pending discard
confirmation. This includes actor/reviewer-label edits and edit-then-revert
sequences. The researcher must choose **Close coordination** again to view a
fresh warning and explicitly discard the current unsent draft. Navigation
between items continues to scope confirmations to the original queue/item;
existing unresolved-event locks and idempotent UUID retries are preserved.
No scientific annotation is approved, promoted or modified by this UI change.

## Regressions and acceptance

- React component tests cover changes to the note, assignment and reviewer
  label after the initial discard warning, plus edit-then-revert.
- Each case requires the warning to disappear without calling the close
  callback or writing a review event. A new explicit close action is required.
- Standalone QC APIs and the existing executable, typed, persisted Workflow
  Builder QC queue/review nodes, provenance, dimensionless priority scores and
  researcher-review gates are unaffected; no new scientific node or database
  migration is appropriate for this local UI safety correction.

**Validation still required:** exact-head frontend formatting, TypeScript,
Vitest, backend, E2E and saved-workflow CI; native Windows installed-GUI/MSI
upgrade and rollback; representative biological data; and independent
1.1/1.6 Alembic revision-0038 reconciliation. This does not provide durable
recovery after a browser reload, application crash or workstation shutdown.
No auto-merge, release, deployment, pretrained download or research-asset
mutation is authorized.
