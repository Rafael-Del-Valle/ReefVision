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
