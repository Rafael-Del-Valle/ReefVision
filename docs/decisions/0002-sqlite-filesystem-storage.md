# ADR 0002: SQLite metadata with filesystem assets

## Status

Accepted.

## Decision

SQLite stores structured metadata and provenance. Images, thumbnails, model
checkpoints, exports, and temporary artifacts remain on the filesystem.

## Consequences

- Filesystem operations must be centralized in a storage layer.
- Managed relative paths are preferred over machine-specific absolute paths.
- Multi-record database changes must use transactions.
