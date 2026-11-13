import {
  useMutation,
  useQueries,
  useQuery,
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
  calculateComputedMaskCoverage,
  computedMaskCoverageCsvUrl,
  createComputedMaskCoverageDefinition,
  getComputedMaskCoverageDefinitions,
  getComputedMaskCoverageResults,
  previewComputedMaskCoverage,
  type AggregateGroupingLevel,
  type ComputedMaskCoveragePreview,
  type MaskCoverageRoiPolygon,
  validateComputedMaskCoverageResult,
} from "./computedMetricsApi";

function identifiers(value: string, required: boolean): string[] {
  const items = value
    .split(/[\s,]+/)
    .map((item) => item.trim())
    .filter(Boolean);
  if (required && !items.length) throw new Error("Enter at least one ID.");
  if (new Set(items).size !== items.length)
    throw new Error("IDs must be unique.");
  if (items.length > 500) throw new Error("At most 500 IDs are supported.");
  return items;
}

function percent(value: number | null): string {
  return value === null ? "Unavailable" : `${Number(value.toFixed(6))}%`;
}

function parseRoiPolygons(text: string): MaskCoverageRoiPolygon[] {
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    throw new Error("Enter valid JSON for the saved ROI polygons.");
  }
  if (!Array.isArray(parsed) || parsed.length === 0)
    throw new Error("Enter a JSON list with at least one ROI polygon.");
  return parsed as MaskCoverageRoiPolygon[];
}

function CoverageSummary({ value }: { value: ComputedMaskCoveragePreview }) {
  return (
    <div className="training-content" aria-label="Mask coverage summary">
      <dl className="training-metric-grid">
        <div>
          <dt>Verified masks</dt>
          <dd>{value.mask_count}</dd>
        </div>
        <div>
          <dt>Density numerator masks</dt>
          <dd>{value.density_object_count}</dd>
        </div>
        <div>
          <dt>Summed mask pixels</dt>
          <dd>{value.summed_mask_area_pixels}</dd>
        </div>
        <div>
          <dt>Union pixels</dt>
          <dd>{value.union_area_pixels}</dd>
        </div>
        <div>
          <dt>Overlap pixels</dt>
          <dd>{value.overlap_area_pixels}</dd>
        </div>
        <div>
          <dt>Image coverage</dt>
          <dd>{percent(value.image_coverage_percent)}</dd>
        </div>
        <div>
          <dt>ROI coverage</dt>
          <dd>{percent(value.roi_coverage_percent)}</dd>
        </div>
        {value.calibration_method === "projective_reference_plane" && (
          <div>
            <dt>Reference-plane ROI coverage</dt>
            <dd>{percent(value.roi_coverage_physical_percent ?? null)}</dd>
          </div>
        )}
        <div>
          <dt>Images / independent units</dt>
          <dd>
            {value.image_count} / {value.independent_unit_count}
          </dd>
        </div>
        <div>
          <dt>Physical union area</dt>
          <dd>
            {value.union_area_physical === null || value.physical_unit === null
              ? `Unavailable (${value.physical_unavailable_reason ?? "incompatible calibration"})`
              : `${value.union_area_physical} ${value.physical_unit}²`}
          </dd>
        </div>
        <div>
          <dt>Mask density</dt>
          <dd>
            {value.object_density_per_square_unit === null ||
            value.physical_unit === null
              ? "Unavailable"
              : `${value.object_density_per_square_unit} masks/${value.physical_unit}²`}
          </dd>
        </div>
      </dl>
      <p>
        Summed area can double-count overlap. Union area and coverage never do.
        Image denominator: {value.image_denominator_pixels} px²
        {value.roi_denominator_pixels === null
          ? "."
          : `; ROI denominator: ${value.roi_denominator_pixels} px².`}
      </p>
      {value.roi_contract === "source_image_polygons" && (
        <details>
          <summary>Saved source-image ROI polygons</summary>
          <ul>
            {value.image_snapshot.map((image) => (
              <li key={String(image.image_id)}>
                {String(image.image_id)}{" "}
                <code>{JSON.stringify(image.roi_polygon)}</code>
              </li>
            ))}
          </ul>
        </details>
      )}
      <h4>Union area by class</h4>
      <ul>
        {value.area_by_class.map((item) => (
          <li key={item.label_class_id ?? "unclassified"}>
            {item.label_name}: {item.union_area_pixels} union px² from{" "}
            {item.mask_count} mask(s)
            {item.union_area_physical === null || item.physical_unit === null
              ? ""
              : `; ${item.union_area_physical} ${item.physical_unit}²`}
          </li>
        ))}
      </ul>
      {value.images.length > 0 && (
        <details>
          <summary>Per-image summaries</summary>
          <ul>
            {value.images.map((image) => (
              <li key={image.image_id}>
                Image {image.image_id}: {image.union_area_pixels} union px²;
                image coverage {percent(image.image_coverage_percent)}; ROI
                coverage {percent(image.roi_coverage_percent)}; density
                numerator {image.density_object_count} mask(s)
              </li>
            ))}
          </ul>
        </details>
      )}
      {value.groups.length > 0 && (
        <details>
          <summary>Independent-unit summaries</summary>
          <ul>
            {value.groups.map((group) => (
              <li key={group.unit_key}>
                Unit {group.unit_key}: {group.image_ids.length} image(s),{" "}
                {group.union_area_pixels} union px², image coverage{" "}
                {percent(group.image_coverage_percent)}, ROI coverage{" "}
                {percent(group.roi_coverage_percent)}
              </li>
            ))}
          </ul>
        </details>
      )}
      <p>
        Algorithm: <code>{value.algorithm}</code>; coordinate frame: source
        image pixels.
      </p>
      <p>
        Evidence SHA-256: <code>{value.evidence_sha256}</code>
      </p>
    </div>
  );
}

export function MaskCoveragePanel({ project }: { project: Project }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [groupingLevel, setGroupingLevel] =
    useState<AggregateGroupingLevel>("image");
  const [labelClassIds, setLabelClassIds] = useState("");
  const [roiLabelClassId, setRoiLabelClassId] = useState("");
  const [roiPolygonJson, setRoiPolygonJson] = useState("");
  const [useReferencePlane, setUseReferencePlane] = useState(false);
  const [imageIds, setImageIds] = useState("");
  const [selectedDefinitionId, setSelectedDefinitionId] = useState("");

  const definitionsQuery = useQuery({
    queryKey: ["computed-mask-coverage-definitions", project.id],
    queryFn: ({ signal }) =>
      getComputedMaskCoverageDefinitions(project.id, signal),
  });
  const resultsQuery = useQuery({
    queryKey: ["computed-mask-coverage-results", project.id],
    queryFn: ({ signal }) => getComputedMaskCoverageResults(project.id, signal),
  });
  const definitions = definitionsQuery.data?.items ?? [];
  const results = resultsQuery.data?.items ?? [];
  const activeDefinitionId = selectedDefinitionId || definitions[0]?.id || "";
  const validations = useQueries({
    queries: results.map((result) => ({
      queryKey: ["computed-mask-coverage-validation", project.id, result.id],
      queryFn: ({ signal }: { signal: AbortSignal }) =>
        validateComputedMaskCoverageResult(project.id, result.id, signal),
    })),
  });

  const createMutation = useMutation({
    mutationFn: () =>
      createComputedMaskCoverageDefinition(project.id, {
        name,
        grouping_level: groupingLevel,
        label_class_ids: identifiers(labelClassIds, false),
        roi_label_class_id: roiLabelClassId.trim() || null,
        ...(roiPolygonJson.trim()
          ? { roi_polygons: parseRoiPolygons(roiPolygonJson) }
          : {}),
        ...(useReferencePlane ? { use_reference_plane: true } : {}),
      }),
    onSuccess: async (definition) => {
      setSelectedDefinitionId(definition.id);
      await queryClient.invalidateQueries({
        queryKey: ["computed-mask-coverage-definitions", project.id],
      });
    },
  });
  const previewMutation = useMutation({
    mutationFn: () => {
      if (!activeDefinitionId)
        throw new Error("Save or select a definition first.");
      return previewComputedMaskCoverage(
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
      return calculateComputedMaskCoverage(
        project.id,
        activeDefinitionId,
        identifiers(imageIds, true),
      );
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["computed-mask-coverage-results", project.id],
      });
    },
  });
  const mutationError = previewMutation.error ?? calculateMutation.error;

  return (
    <section
      className="training-content"
      aria-label="Verified mask area and coverage"
    >
      <div className="section-heading">
        <div>
          <p className="eyebrow">Exact source-pixel geometry</p>
          <h3>Verified mask area and coverage</h3>
          <p>
            Compare summed and geometric-union area from verified masks. Use the
            full image, one verified ROI class, or saved per-image polygons as
            the sampling region. Enable reference-plane calibration when the
            image and masks lie on a calibrated plane.
          </p>
        </div>
        <a
          href={computedMaskCoverageCsvUrl(project.id)}
          download="computed-mask-coverage.csv"
        >
          Export mask coverage CSV
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
          <h4>New coverage definition</h4>
          <label>
            Coverage name
            <input
              required
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
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
            Target class IDs
            <textarea
              rows={3}
              value={labelClassIds}
              onChange={(event) => setLabelClassIds(event.target.value)}
            />
          </label>
          <label>
            ROI class ID
            <input
              value={roiLabelClassId}
              disabled={Boolean(roiPolygonJson.trim())}
              onChange={(event) => setRoiLabelClassId(event.target.value)}
              placeholder="Optional verified-mask denominator class"
            />
          </label>
          <label>
            Saved ROI polygons (JSON)
            <textarea
              rows={3}
              value={roiPolygonJson}
              disabled={Boolean(roiLabelClassId.trim())}
              onChange={(event) => setRoiPolygonJson(event.target.value)}
              placeholder='[{"image_id":"…","points":[[0,0],[50,0],[0,50]]}]'
            />
          </label>
          <label>
            <input
              type="checkbox"
              checked={useReferencePlane}
              onChange={(event) => setUseReferencePlane(event.target.checked)}
            />
            Use reference-plane homography for physical values
          </label>
          <button type="submit" disabled={createMutation.isPending}>
            Save coverage definition
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
            Coverage definition
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
            Coverage image IDs
            <textarea
              required
              rows={5}
              value={imageIds}
              onChange={(event) => setImageIds(event.target.value)}
            />
          </label>
          <div className="button-row">
            <button type="button" onClick={() => previewMutation.mutate()}>
              Preview mask coverage
            </button>
            <button type="button" onClick={() => calculateMutation.mutate()}>
              Save immutable coverage
            </button>
          </div>
          {mutationError && (
            <ErrorState
              title="Coverage failed"
              message={mutationError.message}
            />
          )}
        </form>
      </div>

      {previewMutation.data && <CoverageSummary value={previewMutation.data} />}

      <section aria-label="Mask coverage results">
        <h4>Immutable mask coverage results</h4>
        {resultsQuery.isPending ? (
          <LoadingState title="Loading mask coverage results" />
        ) : resultsQuery.error ? (
          <ErrorState
            title="Mask coverage unavailable"
            message={resultsQuery.error.message}
          />
        ) : !results.length ? (
          <EmptyState
            title="No mask coverage results yet"
            description="Preview and save a result."
          />
        ) : (
          <div className="training-card-grid">
            {results.map((result, index) => (
              <article className="panel-card training-content" key={result.id}>
                <h5>{result.definition_name}</h5>
                <p>
                  {validations[index]?.data?.current
                    ? "Evidence current"
                    : validations[index]?.data
                      ? `Evidence stale: ${validations[index].data?.reasons.join(", ")}`
                      : "Checking evidence…"}
                </p>
                <CoverageSummary value={result} />
                <details>
                  <summary>Immutable provenance</summary>
                  <p>
                    Result SHA-256: <code>{result.content_sha256}</code>
                  </p>
                  <pre>{JSON.stringify(result.provenance, null, 2)}</pre>
                </details>
              </article>
            ))}
          </div>
        )}
      </section>
    </section>
  );
}
