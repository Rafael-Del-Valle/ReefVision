# Phase 9 — Project Interoperability

## Scope

Phase 9 introduces a database-independent ReefVision project exchange package. The first release supports complete export and safe inspection. Data import is intentionally preflight-only until stable ID-remapping and conflict rules are implemented.

## Exchange package

- Format name: `reefvision-project-exchange`
- Format version: `1.0`
- Extension: `.reefvision.zip`
- Manifest: `reefvision-exchange-manifest.json`
- Records: deterministic JSON Lines files under `records/`
- Optional original media under `media/`
- Optional model weights under `models/`

## Exported records

- project metadata and label classes
- images, boxes, masks, and image labels
- detection and classification predictions
- classification datasets
- videos and editable tracks
- immutable dataset versions and items
- registered model metadata
- training runs and experiments
- quality-control runs and issues
- review queues and queue items
- active-learning rounds

## Integrity guarantees

- Every record section has a row count and SHA-256 checksum.
- The manifest has a canonical ReefVision checksum stored in the database.
- Archive paths are relative and normalized.
- Export jobs create the archive in managed project storage.
- Original media and model weights are opt-in.
- Model weights remain excluded by default because size and redistribution licenses vary.

## Safe inspection

Inspection performs no database writes. It checks:

- ZIP validity
- unsafe or traversal paths
- file-count and expanded-size limits
- format name and major version
- required manifest
- section file existence
- section checksums
- section row counts
- whether media relinking would be required

## Import boundary

Import is not implemented in this phase. A safe importer still needs:

1. old-to-new ID maps for every project-scoped entity
2. duplicate project and checksum policies
3. class-map reconciliation
4. model and media relinking rules
5. transactional rollback
6. immutable history handling
7. preview of every conflict before commit

The UI therefore exposes Export and Inspect, but not Import.
