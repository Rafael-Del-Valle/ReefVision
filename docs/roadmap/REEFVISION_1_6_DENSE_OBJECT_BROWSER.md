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
