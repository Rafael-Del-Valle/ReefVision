# Scientific Computed Portability Design

## Intent

ReefVision 1.1 project exchange must preserve computed metric definitions/results and persisted environmental-event definitions without weakening the existing import-as-new-project isolation, checksums, scientific provenance, or 1.0 compatibility. This removes the current computed-metric export block and closes the current silent-loss path for event definitions.

## Goals

- Keep exchange format `1.1` as the enriched scientific format; do not add a parallel project store or incompatible format for additive 1.1 records.
- Export/import computed definitions, computed results, and environmental-event definitions with fresh project-scoped IDs.
- Remap declared definition, scientific-record, workflow-run, workflow-node-run, and subject links while leaving literal provider/source provenance unchanged.
- Rebuild computed result input snapshots and hashes from the remapped scientific records so imported results remain reproducible.
- Reject tampered, foreign, unresolved, or internally inconsistent computed inventories before an imported project is committed.
- Preserve format `1.0` import/export for projects without 1.1 scientific state.

## Non-goals

- No new migration, UI surface, formula feature, event aggregation, or release claim.
- No rewriting of migrations `0038`, `0039`, or `0040`.
- No interpretation of environmental associations beyond their existing definitions.

## Constraints

- Original source archives remain immutable import provenance.
- Unknown uncertainty remains unknown; imported results are not recalculated with invented inputs.
- Generic JSON UUID replacement is not used for computed scientific evidence because it could rewrite literal source metadata.
- Failed import remains atomic across database rows and the new project directory.
- Workflow graph/artifact remapping continues through the established exchange machinery.

## Approaches

1. Extend format `1.1` with explicit computed/event sections (selected). This reuses the existing exporter, importer, ID map, scientific remapper, and transaction while allowing evidence-aware remapping and validation.
2. Introduce format `1.2`. This would make a small additive schema unnecessarily incompatible and would duplicate version branching without a semantic need.
3. Export computed CSV only. This loses executable definitions, input links, workflow provenance, and reproducible project state, so it does not satisfy project portability.

## Architecture

`ProjectExchangeV1Service` adds three project-scoped record sections. A focused computed-exchange module validates definition/result hashes and relationships, reconstructs imported result snapshots from explicitly remapped scientific records, and recomputes content hashes. The base importer registers the new models in dependency order and handles computed payloads through the explicit remapper rather than its generic recursive JSON mapper. Finalization runs the production response validators before commit.

Environmental-event definitions contain immutable typed query JSON and no record-specific result rows. They use normal scalar ID/project remapping, retain their definition hash, and are validated through `EnvironmentalContextService` after import. Workflow graphs and artifacts already participate in the shared ID map and checksum refresh.

## Acceptance

- Save scientific inputs, computed definition/result, event definition, and saved workflows; export, import twice, and inspect disjoint IDs with equivalent scientific values and provenance.
- Re-evaluate/recalculate from imported definitions and inputs and obtain the same result.
- Reject modified hashes, missing definitions/inputs, foreign project IDs, mismatched snapshots, and unsupported formula versions without partial rows or directories.
- Existing 1.0 and scientific 1.1 exchange regressions remain green.
- Document the independent 1.6 migration `0038` reconciliation requirement without editing either lineage.
