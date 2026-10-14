# ReefVision 1.0.2 annotation usability design

**Status:** Approved implementation brief derived from the maintainer's ReefVision 1.0.2 master prompt.

## Goal

Make routine annotation faster and more reliable while preserving source-image geometry, review state, provenance, immutable datasets, held-out evaluation boundaries, and the existing local-model architecture.

## Scope

This release builds on commit `70da46deceebe56ecc1c58240e950c08ae581360`. It keeps the existing gallery and annotation workspaces and adds a shared, deterministic image-selection model, viewer navigation, temporary pan controls, annotation clipboard operations, discoverable shortcuts, and evidence for release review.

The historical product specification's initial no-segmentation non-goal is superseded by the shipped 1.0.1 polygon, raster-mask, SAM-proposal, and refinement workflows. This release preserves those contracts and does not introduce a second editor, a new annotation schema, or a database migration.

## Design

### Project entry and active-image ownership

The gallery owns the browsable project image sequence. A small local preference record stores the last selected image and page for each project. On project change, selection is reset synchronously, then restored only after the matching project page has loaded. If the stored image is absent, the first eligible loaded image becomes active. Empty and failed queries remain explicit states.

The selected image ID is the identity boundary for image and annotation queries. Query keys include that ID and request cancellation is honored so a late response cannot replace a newer image's state. Gallery thumbnails, the main preview, and editor launch all consume the same active ID. An explicit active-image callback replaces observation of query-cache internals where possible.

Broken image assets display an inline recovery state with retry rather than leaving a blank viewer. The original source file is never changed.

### Navigation

A pure navigation helper resolves previous, next, first, and last actions from page metadata. It supports large paginated galleries without loading every record. Boundary navigation requests only the adjacent or terminal page. Wrapping is a persisted, project-independent preference and defaults to disabled.

Left Arrow, Right Arrow, Home, and End act only while the gallery or editor viewer has focus. Shortcut guards reject editable controls, dialogs, menus, and controls that consume the same key. Escape cancels the active transient interaction. A keydown produces at most one navigation request. Selected thumbnails are scrolled into view after selection changes.

### View transforms

Existing source-to-screen transforms remain authoritative. Alt plus left drag and middle drag temporarily enter pan mode without changing the selected tool or annotation document. Wheel zoom remains centered on the pointer and clamped to the existing safe zoom range. Fit, Actual Size, and Reset commands all change viewport state only. Pointer cancellation, window blur, and pointer release outside the viewer terminate the transient interaction.

Transform tests compare source-image points and annotation geometry before and after arbitrary pan and zoom sequences, including image edges. SAM prompts, polygon hit-testing, raster painting, and box drawing continue to convert through source-image coordinates.

### Annotation clipboard and history

An in-memory annotation clipboard stores geometry and allowed scientific metadata. Copy never writes data. Paste and Duplicate generate fresh IDs, offset geometry in source pixels, clamp the translation without distorting shape, and create one normal undoable editor transaction. Operations reject incompatible image dimensions or geometry kinds instead of rescaling.

New copies retain class and source geometry type but clear verification, review, prediction, evaluation, and audit identity fields. Evaluation-only predictions are never accepted through clipboard commands. Polygon and compatible raster selections use their current workspace history mechanisms. Repeated paste chooses the next bounded offset; if no nonzero safe translation exists, the operation is disabled.

Ctrl+C, Ctrl+V, Ctrl+D, Ctrl+Z, Ctrl+Shift+Z, Ctrl+Y, Delete, and Escape share the same focus guard. Existing Shift+1, Shift+2, plain number keys, SAM box prompts, and review shortcuts retain their meanings.

### Responsiveness and accessibility

Navigation helpers and clipboard transforms are pure and linear in the selected annotations. Viewer pointer handlers use refs for transient drag state and avoid document commits during pan. Active selection is cleared when its annotation or image disappears. Controls expose names, shortcut tooltips, keyboard focus, and a shortcuts reference dialog.

Performance evidence uses checked-in reproducible benchmark scenarios and measured results from the final commit. Reports separate deterministic computation timings from interactive desktop observations and do not claim unavailable hardware measurements.

### Versioning and release evidence

All live version sources move from 1.0.1 to 1.0.2 while historical 1.0.0 and 1.0.1 release records remain unchanged. Release notes document upgrade compatibility, internal clipboard limits, operating-system conflicts, test evidence, packaging output, and outstanding physical desktop checks.

The implementation is developed on `feat/reefvision-1.0.2-annotation-usability`. A new tracking issue and draft pull request may be created. PR #44 remains draft and unchanged. No release, tag, merge, public asset replacement, or installation on the maintainer's computer is authorized.

## Acceptance strategy

Each behavior begins with a failing focused test. The final gate includes frontend formatting, TypeScript, all Vitest tests, production build, Playwright workflows, backend Ruff and formatting checks, mypy, complete pytest, migration upgrade/downgrade validation, version consistency, exact-head Windows packaging, package inspection, and all feasible desktop smoke checks. Any unavailable interactive or hardware-only check remains explicitly outstanding.
