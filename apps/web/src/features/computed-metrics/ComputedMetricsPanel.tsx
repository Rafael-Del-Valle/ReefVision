import {
  useInfiniteQuery,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import { useState } from "react";

import type { Project } from "../../api/client";
import {
  EmptyState,
  ErrorState,
  LoadingState,
} from "../../components/ui/AsyncState";
import {
  calculateComputedMetric,
  computedMetricCsvUrl,
  createComputedMetricDefinition,
  getComputedMetricDefinitions,
  getComputedMetricResults,
  type ComputedMetricDefinitionCreate,
  type MetricDimension,
} from "./computedMetricsApi";

const DIMENSIONS = new Set<MetricDimension>([
  "dimensionless",
  "length",
  "area",
  "time",
  "speed",
  "temperature",
  "practical_salinity",
  "mass_salinity",
  "count",
  "count_density",
  "count_rate",
  "angle",
  "pixel_length",
  "pixel_area",
]);

function parseLines(value: string, kind: "dimension" | "record") {
  const entries = value
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const separator = line.indexOf(":");
      if (separator < 1 || !line.slice(separator + 1).trim()) {
        throw new Error(`Each ${kind} line must use symbol: value.`);
      }
      return [
        line.slice(0, separator).trim(),
        line.slice(separator + 1).trim(),
      ] as const;
    });
  if (!entries.length) throw new Error(`Enter at least one ${kind} line.`);
  if (new Set(entries.map(([symbol]) => symbol)).size !== entries.length) {
    throw new Error("Input symbols must be unique.");
  }
  return entries;
}

function utc(value: string) {
  return new Date(value)
    .toISOString()
    .replace("T", " ")
    .replace(".000Z", " UTC");
}

export function ComputedMetricsPanel({ project }: { project: Project }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [expression, setExpression] = useState("");
  const [inputSpecs, setInputSpecs] = useState("value: dimensionless");
  const [outputUnit, setOutputUnit] = useState("1");
  const [selectedDefinitionId, setSelectedDefinitionId] = useState("");
  const [bindings, setBindings] = useState("");

  const definitionsQuery = useInfiniteQuery({
    queryKey: ["computed-metric-definitions", project.id],
    initialPageParam: 0,
    queryFn: ({ signal, pageParam }) =>
      getComputedMetricDefinitions(project.id, signal, pageParam),
    getNextPageParam: (lastPage, _pages, offset) =>
      lastPage.items.length && offset + lastPage.items.length < lastPage.total
        ? offset + lastPage.items.length
        : undefined,
  });
  const resultsQuery = useInfiniteQuery({
    queryKey: ["computed-metric-results", project.id],
    initialPageParam: 0,
    queryFn: ({ signal, pageParam }) =>
      getComputedMetricResults(project.id, signal, pageParam),
    getNextPageParam: (lastPage, _pages, offset) =>
      lastPage.items.length && offset + lastPage.items.length < lastPage.total
        ? offset + lastPage.items.length
        : undefined,
  });
  const definitions =
    definitionsQuery.data?.pages.flatMap((page) => page.items) ?? [];
  const results = resultsQuery.data?.pages.flatMap((page) => page.items) ?? [];
  const definitionsTotal = definitionsQuery.data?.pages[0]?.total ?? 0;
  const resultsTotal = resultsQuery.data?.pages[0]?.total ?? 0;
  const activeDefinitionId = selectedDefinitionId || definitions[0]?.id || "";

  const createMutation = useMutation({
    mutationFn: () => {
      const inputs = parseLines(inputSpecs, "dimension").map(
        ([symbol, dimension]) => {
          if (!DIMENSIONS.has(dimension as MetricDimension)) {
            throw new Error(`Unsupported input dimension: ${dimension}`);
          }
          return { symbol, dimension: dimension as MetricDimension };
        },
      );
      const payload: ComputedMetricDefinitionCreate = {
        name,
        expression,
        inputs,
        output_unit: outputUnit,
      };
      return createComputedMetricDefinition(project.id, payload);
    },
    onSuccess: async (definition) => {
      setSelectedDefinitionId(definition.id);
      await queryClient.invalidateQueries({
        queryKey: ["computed-metric-definitions", project.id],
      });
    },
  });
  const calculateMutation = useMutation({
    mutationFn: () => {
      if (!activeDefinitionId)
        throw new Error("Save or select a metric definition first.");
      const inputs = Object.fromEntries(parseLines(bindings, "record"));
      return calculateComputedMetric(project.id, activeDefinitionId, inputs);
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["computed-metric-results", project.id],
      });
    },
  });

  return (
    <section
      className="feature-workspace"
      aria-label="Computed Metrics workspace"
    >
      <div className="section-heading">
        <div>
          <p className="eyebrow">Project scientific calculations</p>
          <h2>Computed Metrics</h2>
          <p>
            Define safe unit-aware expressions and calculate them from explicit
            scientific record IDs. Definitions and results are immutable,
            checksummed provenance snapshots.
          </p>
        </div>
        <a
          href={computedMetricCsvUrl(project.id)}
          download="computed-metrics.csv"
        >
          Export results as CSV
        </a>
      </div>

      <div className="training-card-grid">
        <form
          className="panel-card training-content"
          onSubmit={(event) => {
            event.preventDefault();
            createMutation.mutate();
          }}
        >
          <h3>New immutable definition</h3>
          <label>
            Metric name
            <input
              required
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          </label>
          <label>
            Expression
            <input
              required
              placeholder="fish / area"
              value={expression}
              onChange={(event) => setExpression(event.target.value)}
            />
          </label>
          <label>
            Input symbols and dimensions
            <textarea
              required
              rows={4}
              value={inputSpecs}
              onChange={(event) => setInputSpecs(event.target.value)}
            />
          </label>
          <p className="form-help">
            One per line: symbol: dimension. Example: fish: count
          </p>
          <label>
            Output unit
            <input
              required
              value={outputUnit}
              onChange={(event) => setOutputUnit(event.target.value)}
            />
          </label>
          <button type="submit" disabled={createMutation.isPending}>
            {createMutation.isPending ? "Saving…" : "Save immutable definition"}
          </button>
          {createMutation.error && (
            <ErrorState
              title="Definition failed"
              message={createMutation.error.message}
            />
          )}
          {createMutation.isSuccess && <p role="status">Definition saved.</p>}
        </form>

        <form
          className="panel-card training-content"
          onSubmit={(event) => {
            event.preventDefault();
            calculateMutation.mutate();
          }}
        >
          <h3>Calculate from records</h3>
          <label>
            Metric definition
            <select
              value={activeDefinitionId}
              onChange={(event) => setSelectedDefinitionId(event.target.value)}
            >
              {!definitions.length && (
                <option value="">No definitions available</option>
              )}
              {definitions.map((definition) => (
                <option key={definition.id} value={definition.id}>
                  {definition.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Input symbols and record IDs
            <textarea
              required
              rows={5}
              placeholder="fish: record UUID"
              value={bindings}
              onChange={(event) => setBindings(event.target.value)}
            />
          </label>
          <p className="form-help">
            Inputs must have the same exact subject and observation time.
            Verified annotations and unverified predictions cannot be mixed.
            Without a subject, inputs need matching location, depth, dataset,
            and source context. Use distinct records and a common standard
            uncertainty kind; bounds and temperature arithmetic are unsupported.
          </p>
          <button
            type="submit"
            disabled={!activeDefinitionId || calculateMutation.isPending}
          >
            {calculateMutation.isPending ? "Calculating…" : "Calculate metric"}
          </button>
          {calculateMutation.error && (
            <ErrorState
              title="Calculation failed"
              message={calculateMutation.error.message}
            />
          )}
        </form>
      </div>

      <section className="training-content" aria-label="Metric definitions">
        <h3>Metric definitions</h3>
        <p>
          Showing {definitions.length} of {definitionsTotal} definitions
        </p>
        {definitionsQuery.isPending ? (
          <LoadingState title="Loading metric definitions" />
        ) : definitionsQuery.error ? (
          <ErrorState
            title="Metric definitions unavailable"
            message={definitionsQuery.error.message}
            onRetry={() => definitionsQuery.refetch()}
          />
        ) : !definitions.length ? (
          <EmptyState
            title="No metric definitions yet"
            description="Save a definition to begin."
          />
        ) : (
          <div className="training-card-grid">
            {definitions.map((definition) => (
              <article className="panel-card" key={definition.id}>
                <h4>{definition.name}</h4>
                <p>
                  <code>{definition.expression}</code> →{" "}
                  {definition.output_unit}
                </p>
                <p>
                  Inputs:{" "}
                  {definition.inputs
                    .map((item) => `${item.symbol}: ${item.dimension}`)
                    .join(", ")}
                </p>
                <details>
                  <summary>Immutable formula provenance</summary>
                  <p>
                    Formula version: <code>{definition.formula_version}</code>
                  </p>
                  <p>
                    Definition SHA-256:{" "}
                    <code>{definition.definition_sha256}</code>
                  </p>
                </details>
              </article>
            ))}
          </div>
        )}
        {definitionsQuery.hasNextPage && (
          <button
            type="button"
            disabled={definitionsQuery.isFetchingNextPage}
            onClick={() => definitionsQuery.fetchNextPage()}
          >
            Load more definitions
          </button>
        )}
      </section>

      <section className="training-content" aria-label="Computed results">
        <h3>Computed results</h3>
        <p>
          Showing {results.length} of {resultsTotal} results
        </p>
        {resultsQuery.isPending ? (
          <LoadingState title="Loading computed results" />
        ) : resultsQuery.error ? (
          <ErrorState
            title="Computed results unavailable"
            message={resultsQuery.error.message}
            onRetry={() => resultsQuery.refetch()}
          />
        ) : !results.length ? (
          <EmptyState
            title="No computed results yet"
            description="Calculate a saved definition."
          />
        ) : (
          <div className="training-card-grid">
            {results.map((result) => (
              <article
                className="panel-card training-content"
                key={result.id}
                aria-label={`Computed result ${result.definition_name}`}
              >
                <h4>{result.definition_name}</h4>
                <p className="metric-value">
                  {result.value} {result.unit}
                  {result.uncertainty === null
                    ? " (uncertainty unavailable)"
                    : ` ± ${result.uncertainty}`}
                </p>
                <p>
                  Normalized: {result.normalized_value} {result.normalized_unit}
                </p>
                <p>Observed: {utc(result.observed_at)}</p>
                <p>
                  {result.workflow_run_id
                    ? `Workflow run ${result.workflow_run_id}; node ${result.workflow_node_run_id}`
                    : "Standalone calculation"}
                </p>
                <details open>
                  <summary>Formula, inputs, and provenance</summary>
                  <p>
                    <code>{result.expression}</code>
                  </p>
                  <p>
                    Formula version: <code>{result.formula_version}</code>
                  </p>
                  <p>
                    Definition SHA-256: <code>{result.definition_sha256}</code>
                  </p>
                  <p>
                    Result SHA-256: <code>{result.content_sha256}</code>
                  </p>
                  <dl>
                    {Object.entries(result.input_record_ids).map(
                      ([symbol, id]) => (
                        <div key={symbol}>
                          <dt>{symbol}</dt>
                          <dd>
                            <code>{id}</code>
                          </dd>
                        </div>
                      ),
                    )}
                  </dl>
                  <pre>{JSON.stringify(result.provenance, null, 2)}</pre>
                </details>
              </article>
            ))}
          </div>
        )}
        {resultsQuery.hasNextPage && (
          <button
            type="button"
            disabled={resultsQuery.isFetchingNextPage}
            onClick={() => resultsQuery.fetchNextPage()}
          >
            Load more results
          </button>
        )}
      </section>
    </section>
  );
}
