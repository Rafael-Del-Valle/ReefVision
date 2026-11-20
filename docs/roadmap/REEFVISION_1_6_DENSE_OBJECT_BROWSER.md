# ReefVision 1.6 — bounded dense-object browser

**Scope:** Display-only image-editor object selection. Existing viewport
culling already bounds visible SVG overlays but the side-panel object browser
still constructed one React option per saved box and mask, even on images with
tens of thousands of objects. This caused a separate, unbounded UI workload.

The browser now initially renders the first **200** matching objects and
offers explicit 200-object increments. Filtered ordering is stable: boxes
followed by masks, with accessible 1-based positions and the total count.
Currently selected matching objects remain represented even when outside the
initial window; their original list positions are not renumbered. Changing the
image, project, or class-name filter resets the display window. A filter with
zero matches is distinguished from an empty scientific document.

**Scientific guarantees:** The limit is applied only after filtering, only
to sidebar option rendering; it does not discard, hide, truncate, rewrite,
reindex, or serialize any scientific annotations or mask data. Canvas viewport
culling, selected IDs, undo/redo, QC review, counts, provenance, source
images, and saved/executable Workflow Builder graphs are unchanged. This is
a UI performance improvement rather than a new scientific workflow node.

**Validation:** `denseObjectList.test.ts` covers a 20,000-object input,
selected objects beyond the window, mask boundary paging, ordering,
malformed limits and data preservation. Frontend type, Vitest, Playwright and
installed Windows GUI with representative large images still require
independent acceptance on the exact commit; passing unit tests alone is
not evidence of full release readiness.

## End-to-end acceptance contract

The former 1,500-annotation Playwright scenario assumed all objects were
simultaneously mounted as sidebar options. That assertion fails with the
intentional bounded renderer (exact-head CI #43529559660: received 200,
expected 1,500), and restoring the unbounded DOM would regress usability.
The scenario now tests the intended observable contract instead: 200 initial
options with ARIA count 1,500, two explicit 200-object reveals, selection of
object 600, reset to a 200-row filtered window, selected-object inclusion
outside that window with correct original filtered position and count, and
retention when the filter is removed. This exercises the built app in
Chromium rather than relying exclusively on the pure windowing helper.
No annotation, calibration or saved research record is modified by the
windowing operation. Exact-head Playwright and installed Windows acceptance
must still pass before considering the version release-ready.

## Bounded selection lookup

Rendering now reads the first visible prefix directly rather than scanning all
saved boxes and masks on every selection change. Distant selected records are
found by scanning only the appropriate suffix, stopping when the last selected
ID has been found. Original ordering and accessible positions are preserved.
This is display-only: annotations, mask pixels, measurements, QC and Workflow
Builder run artifacts remain intact. Proxy-instrumented regressions verify a
20,000-box document reads only its first 200 entries for an in-window selection,
and a distant selected box does not trigger unrelated mask traversal. Native
Windows GUI and full workflow acceptance remain separately required.

## Very large multi-object selections

A range selection of 20,000 saved boxes previously bypassed the 200-row
display window by pinning all 20,000 selected objects into the DOM. The browser
now pins at most **200 additional selected boxes** and **200 additional selected
masks** outside the ordinary display window, prioritizing the last IDs of each
selection type and displaying the pinned results in their original source
order. The ordinary **Show 200 more objects** control can reveal earlier
selected entries. Nothing alters the actual selected-ID sets, scientific
records, serialization, QC review or Workflow Builder provenance. Small
selections (200 or fewer off-window per type) retain the existing immediate
access behavior.

Pure regressions cover 20,000 selected boxes, mixed large box/mask selections,
and sparse distant selections. Browser E2E, exact-head repository CI, and
installed Windows performance on real dense data remain release gates.

## Direct position navigation without unbounded DOM growth

The incremental **Show 200 more objects** control alone required dozens of
clicks to reach a distant, unselected observation in a 20,000-object image.
Researchers can now enter a **1-based filtered object position** and jump
directly to the corresponding 200-object page without mounting the skipped
rows. Positions are in the same deterministic order (all boxes followed by
masks), and the helper retains each row's original `aria-posinset` and
`aria-setsize` metadata. The existing initial prefix/reveal behavior remains
the default; jumping and returning to the first page are explicit UI actions.

At most 200 selected boxes and 200 selected masks outside the target window
remain pinned, including selections *before* a jumped-to page. Invalid,
out-of-range, non-integer or unsafe input cannot trigger a jump; changing
image, project or class filter resets the page. No scientific record, selected
ID, human QC decision, calibration, source image or Workflow Builder run is
modified. This is editor navigation, not a new analysis or model operation,
so a duplicate workflow node would be inappropriate.

Unit tests cover 20,000 observations with bounded indexed reads, cross-type
box/mask page boundaries, out-of-window selected observations, and invalid
offsets. The built-app Playwright scenario exercises a 1,500-object jump to
the final page, asserts 101 mounted rows (100 page rows plus one previously
selected pinned row), correct full-document accessible positions, invalid
input rejection and return-to-first-page behavior. Full exact-head CI and
installed Windows GUI usability still require independent verification.

## Constant-size off-window selection pinning (Track D)

Previously the display window was bounded but each invocation still copied
*every* selected annotation and mask ID into temporary sets and filtered
arrays before taking the latest 200. This duplicated large multi-selection
buffers and delayed sidebar updates on dense ecological images. Pin discovery
now traverses each selected-ID list **backwards only until 200 off-window
entries per type are found**. It retains only IDs already mounted in the
visible window plus those 200 candidates, without allocating a selection-sized
temporary lookup. Repeated IDs preserve the previous last-200-entry behavior.

A proxy-instrumented 50,000-object regression requires only **200 indexed
selection reads** when the latest 200 are outside the current window; a
separate test verifies duplicate-tail semantics. These are UI-only changes:
full selected-ID arrays, annotation/mask data, QC decisions, class visibility,
scientific outputs and saved executable Workflow Builder graphs remain
unaltered. Exact-head TypeScript/Vitest/Playwright, native Windows
installed-GUI profiling on real dense media, and researcher approval remain
release requirements; this is not a new scientific Workflow Builder node.

## Pointer-identity isolation for dense image pan gestures (Track D)

Alt+drag and middle-button panning now track the initiating pointer ID. Additional
pen/touch pointers cannot replace the drag origin, move the viewport, or end a
different pointer's active drag. The active pointer's release/cancel and a
window blur still clear the gesture. This is display-only: original image
pixels, annotation/mask coordinates, selected IDs, class visibility, QC review
decisions, and saved executable Workflow Builder graph/run provenance are never
altered. No new workflow node or database migration is required.

Two frontend regressions exercise interleaved pointer-down/move/up/cancel,
source-geometry preservation, and blur cancellation. Browser E2E on dense
representative media and installed Windows pen/touch usability remain required
for 1.6 acceptance.

## Preserving live zoom during active pan (Track D)

The image editor previously anchored pointer movement to the viewport transform
at pointer-down. When a researcher turned the mouse wheel while holding an
Alt/middle-button pan, the next move restored the stale starting scale and
undid the zoom. Panning now consumes pointer movement increments against the
**latest** transform, so wheel zoom remains in effect and subsequent movement
continues from the most recent pointer position. Secondary pointers cannot
move or terminate a different pointer's drag; fit/reset still ends the gesture.

This is a display-only interaction fix. Original image pixels, annotation and
mask coordinates, reviewer decisions, class visibility, scientific measurements,
and executable saved Workflow Builder runs/provenance are unchanged. The React
regression verifies pan → wheel zoom → pan continuity, zoom retention, reset
cancellation and preserved overlay geometry. Exact-head frontend/Playwright and
real Windows installed-GUI acceptance remain independently required.

## Bounded group translation of dense annotations (Track D)

The inherited 1.0–1.5 multi-selection geometry used
`Math.max(...annotations.map(...))` and `Math.min(...annotations.map(...))`
to constrain an entire selected group within source-image bounds. At dense
selection sizes (200,000 objects in the Node/V8 reproduction), spreading an
array into function arguments raises `RangeError: Maximum call stack size
exceeded` before the researcher can move those selected objects.

The editor now computes the exact same four group bounds in one streaming
pass, with no argument spread or four full temporary arrays. Empty selections
return an empty result. All selected boxes still move together, stay within
the source-image, preserve ID and class identities, and leave original
annotation objects untouched. The existing undo/redo and save paths are
unchanged. No sample counts, QC decisions, models, source images, datasets,
or persisted Workflow Builder inputs/outputs/provenance are modified. Since
this is an editor-only geometric interaction, no scientific workflow node
or migration is introduced.

`geometry.test.ts` now includes a **200,000-annotation** bounded group
translation, extreme image-edge constraints, object immutability and an
empty-selection case. Exact-head frontend/Vitest/Playwright and installed
Windows GUI acceptance remain required; an independent Node/V8 reproduction
is not a substitute for repository CI.

## Fail-closed group translation for malformed imported geometry (Track D)

Imported or restored annotations can contain nonfinite, inverted or off-image
coordinates despite the normal editor's input checks. Previously one such
selected box made the group movement limit `NaN`, so dragging the selection
produced nonfinite coordinates for otherwise valid biological observations.
The display and commit paths both use the same translation helper.

Group translation now refuses the entire move and returns the original
selection unchanged when any selected box has invalid bounds, when the image
size is not positive/finite or when pointer displacement is nonfinite.
It never discards or repairs an imported scientific observation, reassigns a
class, or silently moves only the healthy subset. Valid groups retain the
existing bounded collective movement and 200,000-object streaming behavior.
The UI still needs explicit invalid-selection feedback in a future usability
pass; refusing corruption is not the same as explaining the blocked gesture.

Three Vitest regressions cover five corrupt imported geometries, a late
invalid member of a 20,000-coral group, invalid image dimensions and pointer
deltas, source-record identity and the existing valid 200,000-object case.
This is an annotation-editor integrity guard, not a new biological analysis:
existing typed standalone and saved executable Workflow Builder QC, immutable
provenance, human approval and retries are unaffected. Exact-head CI,
representative source data, installed Windows GUI and MSI upgrade/rollback
remain independent 1.6 release gates.

## Fail-closed single-object resizing with imported geometry (Track D)

The earlier editor safety check protected **group translation**, but resizing a
single historical box still accepted nonfinite pointer coordinates or malformed
source bounds, potentially writing `NaN`/inverted annotation geometry. The
shared preview/commit resize helper now refuses corrupt imported boxes, invalid
image sizes, nonfinite pointers, and impossible minimum dimensions. It preserves
the original scientific observation and its identity without silently repairing
or deleting geometry. A subsequent valid drag still uses the existing clamped
source-pixel resize contract; the source record remains immutable. These checks
also refuse degenerate boxes below the requested minimum size.

Three Vitest regressions cover corrupted imported geometry, impossible event or
canvas input, and valid recovery after an invalid attempt. The preceding
[exact-head CI #44676388267](https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/44676388267)
failed frontend Prettier before TypeScript/Vitest; its precise formatting
diagnostic in `geometry.test.ts` is also corrected in this increment.

This is editor state/geometry integrity, not an analysis node. The existing
standalone and saved typed QC Workflow Builder operations, provenance, retries,
review gates, and source datasets remain unchanged. Full exact-head CI and
installed-Windows dense-image/resize usability plus MSI upgrade/rollback remain
required independent acceptance evidence.

## Isolating manual annotation gestures by initiating pointer (Track D)

The full editor previously processed global pointer events without verifying the
initiating pointer. An unrelated touch/pen contact could move or prematurely
commit a coral box, group selection, resize or pan. Every drawing, moving,
resizing and panning interaction now carries its originating pointer ID;
unrelated moves/releases/cancellations cannot affect it and other pointer-down
events cannot replace it. Window blur still cancels any gesture. Class IDs,
original observation geometry, saved scientific records, QC review decisions,
and executable Workflow Builder provenance remain unchanged. Two React tests
cover mixed-pointer pan and box-creation lifecycles. This is a UI event-integrity
fix, not a new scientific Workflow Builder node or schema migration.

[Previous exact-head CI #44682654483](https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/44682654483)
passed backend and Windows preservation but failed frontend Prettier before
TypeScript/Vitest. Its exact single-file formatter diff is corrected here.
Full new-head frontend/E2E, real installed Windows pen/touch and MSI upgrade/
rollback, representative biology and owner approval are still required.

## Full-editor pan and wheel continuity (Track D)

The full annotation editor used to calculate each pointer-move displacement
against the viewport transform captured when panning started. If a researcher
zoomed while keeping an Alt/middle/pan-tool drag active, the next pointer move
restored that stale scale and offset, making dense coral overlays jump. The
editor now applies incremental displacement to the latest zoomed viewport and
tracks the active pointer's previous client position. A secondary pointer still
cannot move or complete that gesture. The existing class-visibility, QC and
saved typed Workflow Builder paths are unchanged: this is purely a rendering
interaction, not a scientific transform or a new analysis node.

A React regression checks pan → wheel zoom → continued pan, zoom persistence,
secondary-pointer isolation, cancellation at pointer release and unchanged
source-pixel annotation geometry. The preceding exact-head frontend CI
identified Prettier differences in the two pointer-identity tests; the same
increment formats those tests. Acceptance still requires full exact-head
frontend/backend/E2E CI and genuine installed-Windows pen/touch/mouse testing.
