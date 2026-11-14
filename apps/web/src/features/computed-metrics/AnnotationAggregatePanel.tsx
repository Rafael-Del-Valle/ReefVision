import {
  useInfiniteQuery,
  useMutation,
  useQueries,
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
  calculateComputedAggregate,
  computedAggregateCsvUrl,
  createComputedAggregateDefinition,
  getComputedAggregateDefinitions,
  getComputedAggregateResults,
  previewComputedAggregate,
  type AggregateGroupingLevel,
  type AggregateSourceKind,
  type ComputedAggregatePreview,
  validateComputedAggregateResult,
} from "./computedMetricsApi";

function identifiers(value: string, required: boolean): string[] {
  const items = value
    .split(/[\s,]+/)
    .map((item) => item.trim())
    .filter(Boolean);
  if (required && !items.length)
    throw new Error("Enter at least one image ID.");
  if (new Set(items).size !== items.length)
    throw new Error("IDs must be unique.");
  if (items.length > 500) throw new Error("At most 500 IDs are supported.");
  return items;
}

function Summary({ value }: { value: ComputedAggregatePreview }) {
  return (
    <div className="training-content" aria-label="Aggregate preview summary">
      <dl className="training-metric-grid">
        <div>
          <dt>Observations</dt>
          <dd>{value.observation_count}</dd>
        </div>
        <div>
          <dt>Images</dt>
          <dd>{value.image_count}</dd>
        </div>
        <div>
          <dt>Independent units</dt>
          <dd>{value.independent_unit_count}</dd>
        </div>
        <div>
          <dt>Mean per independent unit</dt>
          <dd>{value.mean_per_independent_unit}</dd>
        </div>
      </dl>
      <p>
        Observation count is not the independent-unit sample size. Pending and
        rejected model proposals are never counted.
      </p>
      <h4>Counts by class</h4>
      <ul>
        {value.counts_by_class.map((item) => (
          <li key={item.label_class_id ?? "unclassified"}>
            {item.label_name}: {item.count}
          </li>
        ))}
      </ul>
      <h4>Independent-unit groups</h4>
      <table>
        <thead>
          <tr>
            <th>Unit key</th>
            <th>Images</th>
            <th>Observations</th>
          </tr>
        </thead>
        <tbody>
          {value.groups.map((group) => (
            <tr key={group.unit_key}>
              <td>{group.unit_key}</td>
              <td>{group.image_ids.length}</td>
              <td>{group.observation_count}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p>
        Excluded proposals: {JSON.stringify(value.excluded_proposals_by_status)}
      </p>
      <p>
        Evidence SHA-256: <code>{value.evidence_sha256}</code>
      </p>
    </div>
  );
}

export function AnnotationAggregatePanel({ project }: { project: Project }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [sourceKind, setSourceKind] = useState<AggregateSourceKind>(
    "verified_annotations",
  );
  const [groupingLevel, setGroupingLevel] =
    useState<AggregateGroupingLevel>("image");
  const [labelClassIds, setLabelClassIds] = useState("");
  const [imageIds, setImageIds] = useState("");
  const [selectedDefinitionId, setSelectedDefinitionId] = useState("");

  const definitionsQuery = useInfiniteQuery({
    queryKey: ["computed-aggregate-definitions", project.id],
    initialPageParam: 0,
    queryFn: ({ signal, pageParam }) =>
      getComputedAggregateDefinitions(project.id, signal, pageParam),
    getNextPageParam: (page, _pages, offset) =>
      page.items.length && offset + page.items.length < page.total
        ? offset + page.items.length
        : undefined,
  });
  const resultsQuery = useInfiniteQuery({
    queryKey: ["computed-aggregate-results", project.id],
    initialPageParam: 0,
    queryFn: ({ signal, pageParam }) =>
      getComputedAggregateResults(project.id, signal, pageParam),
    getNextPageParam: (page, _pages, offset) =>
      page.items.length && offset + page.items.length < page.total
        ? offset + page.items.length
        : undefined,
  });
  const definitions =
    definitionsQuery.data?.pages.flatMap((page) => page.items) ?? [];
  const results = resultsQuery.data?.pages.flatMap((page) => page.items) ?? [];
  const activeDefinitionId = selectedDefinitionId || definitions[0]?.id || "";
  const validations = useQueries({
    queries: results.map((result) => ({
      queryKey: ["computed-aggregate-validation", project.id, result.id],
      queryFn: ({ signal }: { signal: AbortSignal }) =>
        validateComputedAggregateResult(project.id, result.id, signal),
    })),
  });

  const createMutation = useMutation({
    mutationFn: () =>
      createComputedAggregateDefinition(project.id, {
        name,
        source_kind: sourceKind,
        grouping_level: groupingLevel,
        label_class_ids: identifiers(labelClassIds, false),
      }),
    onSuccess: async (definition) => {
      setSelectedDefinitionId(definition.id);
      await queryClient.invalidateQueries({
        queryKey: ["computed-aggregate-definitions", project.id],
      });
    },
  });
  const previewMutation = useMutation({
    mutationFn: () => {
      if (!activeDefinitionId)
        throw new Error("Save or select a definition first.");
      return previewComputedAggregate(
        project.id,
        activeDefinitionId,
        identifiers(imageIds, true),
      );
    },
  });
  const calculateMutation = useMutation({
    mutationFn: () => {
      if (!activeDefinitionId)
        throw new Error("Save or select a definition first.");
      return calculateComputedAggregate(
        project.id,
        activeDefinitionId,
        identifiers(imageIds, true),
      );
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["computed-aggregate-results", project.id],
      });
    },
  });

  return (
    <section
      className="training-content"
      aria-label="Reviewed annotation aggregates"
    >
      <div className="section-heading">
        <div>
          <p className="eyebrow">Verified image-derived evidence</p>
          <h3>Reviewed annotation aggregates</h3>
          <p>
            Count canonical boxes or verified masks only on reviewed images.
            Grouping by <code>group_key</code> uses researcher-declared
            replicate identity; ReefVision never infers biological independence.
          </p>
        </div>
        <a
          href={computedAggregateCsvUrl(project.id)}
          download="computed-annotation-aggregates.csv"
        >
          Export aggregate CSV
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
          <h4>New count definition</h4>
          <label>
            Aggregate name
            <input
              required
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          </label>
          <label>
            Verified source
            <select
              value={sourceKind}
              onChange={(event) =>
                setSourceKind(event.target.value as AggregateSourceKind)
              }
            >
              <option value="verified_annotations">Canonical boxes</option>
              <option value="verified_masks">Verified masks</option>
            </select>
          </label>
          <label>
            Independent-unit grouping
            <select
              value={groupingLevel}
              onChange={(event) =>
                setGroupingLevel(event.target.value as AggregateGroupingLevel)
              }
            >
              <option value="image">One unit per image</option>
              <option value="image_group_key">
                One unit per image group_key
              </option>
            </select>
          </label>
          <label>
            Optional class IDs
            <textarea
              rows={3}
              value={labelClassIds}
              onChange={(event) => setLabelClassIds(event.target.value)}
            />
          </label>
          <button type="submit" disabled={createMutation.isPending}>
            Save aggregate definition
          </button>
          {createMutation.error && (
            <ErrorState
              title="Definition failed"
              message={createMutation.error.message}
            />
          )}
        </form>

        <form
          className="panel-card training-content"
          onSubmit={(event) => event.preventDefault()}
        >
          <h4>Preview and calculate</h4>
          <label>
            Aggregate definition
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
            Reviewed image IDs
            <textarea
              required
              rows={5}
              value={imageIds}
              onChange={(event) => setImageIds(event.target.value)}
            />
          </label>
          <div className="button-row">
            <button type="button" onClick={() => previewMutation.mutate()}>
              Preview eligible evidence
            </button>
            <button type="button" onClick={() => calculateMutation.mutate()}>
              Save immutable aggregate
            </button>
          </div>
          {(previewMutation.error || calculateMutation.error) && (
            <ErrorState
              title="Aggregate failed"
              message={
                (previewMutation.error ?? calculateMutation.error)?.message ??
                "Failed"
              }
            />
          )}
        </form>
      </div>

      {previewMutation.data && <Summary value={previewMutation.data} />}

      <section aria-label="Aggregate results">
        <h4>Immutable aggregate results</h4>
        {resultsQuery.isPending ? (
          <LoadingState title="Loading aggregate results" />
        ) : resultsQuery.error ? (
          <ErrorState
            title="Aggregate results unavailable"
            message={resultsQuery.error.message}
          />
        ) : !results.length ? (
          <EmptyState
            title="No aggregate results yet"
            description="Preview and save a result."
          />
        ) : (
          <div className="training-card-grid">
            {results.map((result, index) => {
              const validation = validations[index];
              return (
                <article
                  className="panel-card training-content"
                  key={result.id}
                >
                  <h5>{result.definition_name}</h5>
                  <p>
                    {validation?.data?.current
                      ? "Evidence current"
                      : validation?.data
                        ? `Evidence stale: ${validation.data.reasons.join(", ")}`
                        : "Checking evidence…"}
                  </p>
                  <Summary value={result} />
                  <details>
                    <summary>Immutable provenance</summary>
                    <p>
                      Definition SHA-256:{" "}
                      <code>{result.definition_sha256}</code>
                    </p>
                    <p>
                      Result SHA-256: <code>{result.content_sha256}</code>
                    </p>
                    <p>
                      {result.workflow_run_id
                        ? `Workflow run ${result.workflow_run_id}; node ${result.workflow_node_run_id}`
                        : "Standalone calculation"}
                    </p>
                  </details>
                </article>
              );
            })}
          </div>
        )}
      </section>
    </section>
  );
}
