# ReefVision 1.5.0 Report

## Current release state

ReefVision 1.5 is **in progress**. This report records only the early local provider/plugin foundation implemented on the stacked `develop/reefvision-1.5` branch. It does not close the other 1.5 feature-inventory entries, and it does not claim a complete plugin SDK.

## Implemented provider foundation

- Strict discovery of direct `.json` files in `<data_dir>/provider-manifests`.
- Bounded file reads and a closed manifest schema with stable identity, version, capability, and availability fields.
- Failure isolation: invalid UTF-8, JSON, schemas, duplicates, symlinks, directories, built-in ID conflicts, and oversized files remain visible as unavailable records without preventing other manifests from loading.
- No imports, entry-point resolution, package installation, command execution, or model loading.
- Provider-catalog API metadata for source kind, schema version, capabilities, availability, source file and digest, and discovery errors.
- An explicit blocked preflight for local manifests; local records are not accepted by execution routes.
- A tested project path at **Home → open project → Models & AI → Providers**. The workspace exposes discovery evidence and keeps local execution controls disabled.
- A metadata-only `provider_manifest_snapshot` Workflow Builder node. It records manifest metadata and the source digest, can preserve invalid records as unavailable evidence, and refuses a changed digest when one was pinned.

## Safety boundary

The 1.5 foundation is an inspection and provenance layer, not a runtime extension system. A manifest cannot grant code execution authority. Executable plugin loading, lifecycle controls, permissions, compatibility negotiation, and a stable SDK remain tracked separately for 2.0.

## Verification state

Source and browser-path tests cover the implemented slice. The feature inventory remains `in_progress` until an exact-SHA Windows installer is built and the installed application path is exercised. No representative scientific dataset or physical GPU is required for this metadata-only foundation.

## Versioning and migrations

- The application version remains on the 1.4 line while the broader 1.5 release is incomplete.
- This slice adds no database schema changes and no Alembic migration.

## Remaining 1.5 scope

Experimental design, reviewer lab, field capture, model catalog/runtime work, model comparison, reproducibility packaging, and every other 1.5 inventory entry retain their independent status. Passing the provider-foundation gates does not close them.
