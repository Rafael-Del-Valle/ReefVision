# ReefVision 1.6 — ephemeral visibility for QC evidence

**Status:** Development increment on isolated `develop/reefvision-1.6`, draft PR #77, coordinated under issue #76. **Not release acceptance.**

## Overlap audit and observed gap

The existing editor already supports persisted per-user/project class visibility, independent box and prediction layer toggles, and a review-queue launch context carrying explicit annotation and prediction UUIDs. The existing QC Workflow Builder node already executes with typed, persisted queue artifacts and a mandatory scientist review gate. These components should not be replaced or duplicated.

Before this change, the review context highlighted its target IDs only **after** rendering filters were applied. If the researcher had hidden that class or the entire layer, the exact object requiring review disappeared from the canvas. Restoring a hidden class manually risked changing the reviewer's preferred visibility environment just to inspect a single QC observation.

## Implementation and scientific boundary

- Explicit `launchContext.highlightAnnotationIds` / `highlightPredictionIds` are temporary, in-memory display exceptions for **those exact IDs only**, not for an entire class or project. A hidden annotation/prediction unrelated to the QC launch remains hidden.
- The same exception applies even if the researcher toggles **Hide boxes** or **Hide predictions** during review. Rendering still uses the existing conservative viewport culler, so evidence outside the viewport is not misrepresented as on-screen.
- The editor displays a status message explaining the narrow override. Removing the review launch context restores the ordinary class/layer controls without a visibility API mutation.
- No annotations, predictions, review events, class preferences, model outputs, source-image bytes, or Workflow Builder artifacts are edited; this is display-only QC navigation. No new Workflow Builder node is appropriate for a transient view state. Saved QC runs and explicit researcher approval remain unchanged.

## Regression and limits

`AnnotationEditor.test.tsx` covers a hidden saved class for both annotations and predictions; a targeted QC-highlighted observation in each layer; unrelated observations of the **same** hidden class that remain invisible; persistence of highlights after global Hide controls; removal of temporary exceptions when the launch context exits; exact cached saved visibility; and no POST/PUT/PATCH/DELETE requests. The test also checks an accessible user-facing notice.

Local Git clone could not resolve github.com in the current execution environment. GitHub-hosted exact-head frontend typecheck/format/Vitest/Playwright and backend CI remain the authoritative regression gates; their results must be inspected independently. No installed Windows GUI test, real-image scientific acceptance, Windows MSI/CAB upgrade or rollback, or independent 1.1/1.6 Alembic 0038 reconciliation is claimed.

**Release: HOLD.** No merge, tag, publication, deployment, hosting, pretrained-model download or user-asset mutation is authorized.
