# Phase 7 environmental-analysis design

Status: approved implementation design for ReefVision 1.1 Phase 7. This design adds migration `0042`; it does not rewrite existing migrations or replace scientific records, computed metrics, or threshold-event definitions.

## Scientific contract

Numeric environmental samples remain immutable `ScientificRecord` rows. NOAA water-level predictions and observations are separate records with explicit variable identifiers, units, UTC observation times, station identifiers, datum, acquisition source, quality-control state, uncertainty when supplied, and provider provenance. Raw provider payloads and request identity remain in `EnvironmentalCacheEntry`. Predicted values are never presented as observations, and ReefVision does not infer flood/ebb state from water-level height alone.

Composite analyses are persisted separately because lunar phase labels, station-selection evidence, temporal windows, joined rows, and lag configurations are not scalar scientific observations. New immutable `EnvironmentalAnalysisDefinition` and `EnvironmentalAnalysisResult` rows store typed configuration and payload snapshots for:

- `lunar_context`;
- `tidal_context`;
- `event_window`;
- `observation_environment_join`;
- `lagged_comparison`.

Definitions contain a typed kind, human-readable name, configuration JSON, algorithm/calculation version, and canonical SHA-256. Results reference a definition and contain an explicit analysis time, immutable payload, source-record and source-analysis snapshots, QC/uncertainty statements, content SHA-256, and optional workflow run/node lineage. Results are append-only and never silently recalculated in place.

## Time, location, and matching

All persisted times are timezone-aware UTC ISO-8601 values. Biological observation times come from explicit source evidence, primarily image capture timestamps or subject-linked scientific records; computed-result creation timestamps are never treated as observation times.

Environmental joins require an explicit maximum time distance and, when coordinates exist on both sides, an explicit maximum geodesic distance. Depth matching is optional but, when requested, requires compatible depth units and a configured maximum difference. Missing required time, location, or depth evidence fails closed rather than being guessed. Each joined row records the selected environmental record, signed time offset, geodesic distance, depth difference, selection rule, and all rejected/tie-break reasoning needed to reproduce the match.

Lagged comparisons use researcher-specified lags and windows. They return descriptive paired rows and summaries only, preserve the independent observation identifier, and report repeated-use counts when one environmental sample or biological unit appears in multiple pairs. They do not claim statistical independence, significance, or causation.

## Lunar context

The deterministic lunar calculator remains offline-capable and gains persisted single/batch analyses. Its contract records calculation timestamp, phase label, illuminated fraction, lunar age, algorithm identifier/version, reference-frame and precision notes, and reference-test evidence. Eight conventional phases are supported. Tests cover new/full/quarter references, timezone equivalence, and year boundaries with explicit tolerances appropriate to the documented low-precision method.

## NOAA tidal context

The NOAA CO-OPS adapter uses explicit station selection and requests predictions and observed water levels as distinct products. Requests use UTC, metric units, an explicit datum, bounded time ranges, retry-safe error handling, and the existing cache/offline-reuse path. Station identifier, coordinates, station distance from the project/observation location, datum, product, units, provider request parameters, retrieval time, and raw-response hash are retained.

Tidal context analyses select records only within configured time and distance tolerances. Stage labels are limited to evidence supported by the input series: predicted height and nearest predicted high/low context may be reported; rising/falling may be derived only from a documented prediction-series slope and is labelled as predicted. Observed height never becomes predicted stage evidence. Insufficient or conflicting evidence produces `unknown` with a reason.

## Event windows and analyses

Existing `EnvironmentalEventDefinition` threshold behavior remains unchanged. A new `event_window` environmental-analysis definition can reference a legacy threshold definition or an explicit threshold snapshot, with inclusive/exclusive boundary policy and before/after durations. Results snapshot qualifying records and deterministic merged windows. Boundary equality, overlapping windows, empty matches, and UTC normalization are explicit and tested.

Observation-environment joins may reference event-window results or raw scientific-record queries. Lagged comparisons consume persisted join results or explicit immutable join snapshots. Services enforce project ownership for every referenced ID and calculate canonical hashes from remapped payloads.

## API, workflow, CSV, and UI integration

Typed FastAPI endpoints create/list/read definitions, preview or persist analyses, validate currentness, and export evidence CSV. Specialized lunar, tidal, event-window, join, and lag request/response schemas sit above the shared immutable persistence service. Existing lunar calculation and environmental-record endpoints remain backward compatible.

Workflow Builder registers executable typed nodes for lunar context, tidal context, event windows, observation-environment joins, and lagged comparisons. Standalone and workflow execution call the same domain services. Workflow replay is idempotent for one node run and rejects a conflicting second persisted result.

The Environmental Context React workspace adds analysis-kind navigation, timestamp/subject selection, NOAA station/product/datum controls, offline/cache status, persisted-result history, explicit matching tolerances, QC/provenance displays, event-window configuration, joins/lags, and CSV download. UI copy distinguishes observed from predicted data and describes outputs as contextual/descriptive.

## Project exchange

Project exchange gains environmental-analysis definition/result sections. Export includes definitions before results. Import validates schemas, project ownership, canonical hashes, referenced legacy event definitions, source scientific records, source analyses, and workflow lineage. All IDs are safely remapped inside one transaction; canonical hashes are rebuilt after remapping. Missing references, corrupt hashes, duplicate identities, or unsupported kinds abort the import without partial scientific rows.

## Migration and compatibility

Migration `0042` creates only the two environmental-analysis tables and indexes/constraints needed for project queries, kind filtering, and one-result-per-workflow-node replay. Upgrade and downgrade preserve every pre-existing scientific record, cache entry, threshold definition, computed metric, workflow, and project. Legacy projects with no analysis rows behave unchanged. Downgrade removes only `0042` tables.

## Deliberate limits

- NOAA support is limited to CO-OPS stations/products with explicit machine-readable evidence; no station capability is guessed.
- Lunar values are deterministic contextual covariates, not high-precision ephemerides or local moonrise/moonset predictions.
- No causal, inferential, or significance claims are produced.
- Join and lag outputs surface repeated-use/pseudoreplication risk but do not invent an experimental-unit hierarchy.
- Installed-desktop and live-NOAA acceptance remain separate from deterministic mocked-provider and offline-cache regression tests.
