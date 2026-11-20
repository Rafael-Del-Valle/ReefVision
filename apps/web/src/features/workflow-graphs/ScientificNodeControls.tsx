import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { getDatasetVersions, request, type JobRecord } from "../../api/client";
import {
  listEcologyAnalyses,
  type EcologyAnalysis,
} from "../ecology/ecologyAnalysisApi";
import {
  pairedDesignReady,
  pairedVisitDates,
  PairedGrowthFields,
  type PairedGrowthDraft,
} from "../ecology/PairedGrowthFields";
import type { EventSummary } from "../ecology/EventSummaryPanel";
import type { PoseLink } from "../ecology/poseOrganismLinksApi";
import { ModelSelectionField } from "../models/ReviewedModelRuntime";
import { listStudyDesigns } from "../ecology/studyDesignApi";
import { listResearchProofs } from "../reproducibility/reproducibilityApi";
import {
  AcquisitionQualityControls,
  defaultAcquisitionThresholds,
} from "../quality-control/AcquisitionQuality";
import { listEventRuns } from "../video/biologicalMovementApi";
import type {
  StaticOptions,
  StaticSummary,
} from "../video/staticComparisonApi";

import {
  listProjectSpatialAssets,
  type SpatialSourceAsset,
} from "./workflowGraphApi";

const PAGE = 20;
const scientificNodes = new Set([
  "scientific_comparison",
  "ecology_event_summary",
  "research_publication_figure",
  "image_acquisition_quality",
  "ecology_verified_analysis",
  "paired_growth_contrast",
  "reviewed_study_design",
  "paired_model_comparison",
  "research_reproducibility_package",
  "mesh_surface_preview",
  "point_cloud_preview",
  "mesh_longitudinal_comparison",
  "provider_manifest_snapshot",
  "reviewed_model_runtime",
]);

export const hasScientificNodeControls = (nodeType: string) =>
  scientificNodes.has(nodeType);

type Parameters = Record<string, unknown>;
type Option = {
  id: string;
  label: string;
  unavailable?: boolean;
  digest?: string;
};
const object = (value: unknown): Parameters =>
  value && typeof value === "object" && !Array.isArray(value)
    ? (value as Parameters)
    : {};
const string = (value: unknown) => (typeof value === "string" ? value : "");
const ids = (value: unknown) =>
  Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
const finiteNumber = (value: unknown, fallback: number) =>
  typeof value === "number" && Number.isFinite(value) ? value : fallback;

const registrationErrorBounds = [
  [
    "source_centroid_position_error_bound_m",
    "Earlier centroid error bound (meters)",
  ],
  [
    "target_centroid_position_error_bound_m",
    "Later centroid error bound (meters)",
  ],
  ["registration_alignment_error_bound_m", "Alignment error bound (meters)"],
] as const;

function parseRegistrationMatrix(text: string): unknown {
  if (!text.trim()) return null;
  try {
    const value: unknown = JSON.parse(text);
    if (Array.isArray(value)) return value;
  } catch {
    // Keep invalid text editable while preventing a preview or run.
  }
  return text;
}

function registrationTransformIssue(
  registration: Parameters,
): string | undefined {
  const matrix = registration.source_to_target_transform_m;
  if (
    matrix != null &&
    (!Array.isArray(matrix) ||
      matrix.length !== 4 ||
      matrix.some(
        (row) =>
          !Array.isArray(row) ||
          row.length !== 4 ||
          row.some(
            (value) => typeof value !== "number" || !Number.isFinite(value),
          ),
      ))
  ) {
    return "Enter a 4 × 4 registration matrix with finite numbers.";
  }
  const supplied = registrationErrorBounds
    .map(([field]) => registration[field])
    .filter((value) => value != null);
  if (
    supplied.length &&
    (matrix == null || supplied.length !== registrationErrorBounds.length)
  )
    return "Enter a rigid transform and all three error bounds to calculate a separation interval.";
  if (
    supplied.some((value) => {
      const bound = finiteNumber(value, -1);
      return bound < 0 || bound > 1_000_000;
    })
  ) {
    return "Registration error bounds must be between 0 and 1,000,000 meters.";
  }
}

export function scientificConfigurationIssue(
  nodeType: string,
  parameters: Parameters,
): string | undefined {
  const config = object(parameters.configuration);
  if (
    nodeType === "research_reproducibility_package" &&
    !/^[0-9a-f]{64}$/.test(string(parameters.proof_sha256))
  ) {
    return "Choose a verified research package proof.";
  }
  if (
    nodeType === "paired_model_comparison" &&
    (!string(parameters.comparison_id) ||
      !/^[0-9a-f]{64}$/.test(string(parameters.comparison_sha256)))
  ) {
    return "Choose a completed paired model comparison.";
  }
  if (
    nodeType === "reviewed_model_runtime" &&
    (!string(parameters.selection_id) ||
      !/^[0-9a-f]{64}$/.test(string(parameters.selection_sha256)))
  )
    return "Choose a reviewed project model configuration.";
  if (
    nodeType === "reviewed_study_design" &&
    (!string(parameters.design_revision_id) ||
      !/^[0-9a-f]{64}$/.test(string(parameters.design_sha256)))
  ) {
    return "Choose a frozen study design revision.";
  }
  if (
    nodeType === "paired_growth_contrast" &&
    (!string(parameters.analysis_id) ||
      !/^[0-9a-f]{64}$/.test(string(parameters.source_sha256)) ||
      !pairedDesignReady(pairedDraft(parameters)))
  ) {
    return "Choose a frozen growth analysis and declare its paired visits, independent unit, estimand and missingness policy.";
  }
  if (
    nodeType === "provider_manifest_snapshot" &&
    !string(parameters.record_id)
  )
    return "Choose an inspect-only local provider manifest.";
  if (nodeType === "scientific_comparison") {
    if (
      string(parameters.comparison_id) ||
      string(parameters.static_comparison_id)
    )
      return;
    const staticConfig = object(parameters.static_configuration);
    if (Object.keys(staticConfig).length) {
      if (
        !string(staticConfig.dataset_version_id) ||
        !ids(staticConfig.model_ids).length
      )
        return "Choose a reviewed image dataset and a compatible registered detector.";
      const inference = object(staticConfig.inference);
      if (
        [inference.confidence_threshold, inference.iou_threshold].some(
          (value) =>
            value !== undefined &&
            (typeof value !== "number" ||
              !Number.isFinite(value) ||
              value < 0 ||
              value > 1),
        )
      )
        return "Inference thresholds must be between zero and one.";
      return;
    }
    if (
      !ids(config.source_job_ids).length ||
      !string(config.name).trim() ||
      (config.metric === "measurement" && !string(config.unit).trim())
    )
      return "Choose a completed scoring report and enter the quantity, including its unit for measurements.";
  }
  if (
    nodeType === "ecology_event_summary" &&
    !string(parameters.summary_id) &&
    (!readSessions(config.sessions).length ||
      !string(config.name).trim() ||
      !string(config.reviewer).trim() ||
      string(config.reason).trim().length < 3 ||
      config.confirm !== true)
  )
    return "Choose a saved summary or select sessions and confirm review with a reviewer and reason.";
  if (
    nodeType === "research_publication_figure" &&
    !string(parameters.report_id) &&
    (!string(config.source_id) ||
      !string(config.figure) ||
      !string(config.title).trim())
  )
    return "Choose a saved figure or give the publication source, figure type and title.";
  if (
    nodeType === "ecology_verified_analysis" &&
    !string(parameters.analysis_id)
  )
    return "Choose a reviewed ecological result.";
  if (nodeType === "mesh_longitudinal_comparison") {
    const registration = object(parameters.registration_evidence);
    if (Object.keys(registration).length) {
      const residual = finiteNumber(registration.rms_residual_m, -1);
      const count = finiteNumber(registration.correspondence_count, 0);
      if (
        residual < 0 ||
        residual > 1_000_000 ||
        !Number.isInteger(count) ||
        count < 3 ||
        count > 1_000_000
      )
        return "Enter the measured registration RMS residual and the count of correspondences (at least 3).";
      return registrationTransformIssue(registration);
    }
  }
  if (nodeType === "image_acquisition_quality") {
    const thresholds = {
      ...defaultAcquisitionThresholds,
      ...object(parameters.thresholds),
    };
    if (thresholds.dark_luma_max >= thresholds.bright_luma_min)
      return "Dark luma maximum must be lower than bright luma minimum.";
  }
}
type Result = {
  id: string;
  stale?: boolean;
  stale_reasons?: string[];
  snapshot: Parameters;
};
function SourceSelect({
  label,
  value,
  options,
  onChange,
  empty = "Choose…",
}: {
  label: string;
  value: string;
  options: Option[];
  onChange: (value: string) => void;
  empty?: string;
}) {
  return (
    <label>
      {label}
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        <option value="">{empty}</option>
        {!!value && !options.some((option) => option.id === value) && (
          <option value={value}>
            Saved selection is outside this page or unavailable
          </option>
        )}
        {options.map((option) => (
          <option
            key={option.id}
            value={option.id}
            disabled={option.unavailable}
          >
            {option.label}
            {option.unavailable ? " (unavailable)" : ""}
          </option>
        ))}
      </select>
    </label>
  );
}

function Records({
  queryKey,
  load,
  render,
}: {
  queryKey: (string | number)[];
  load: (offset: number, signal: AbortSignal) => Promise<Option[]>;
  render: (options: Option[]) => React.ReactNode;
}) {
  const [offset, setOffset] = useState(0);
  const records = useQuery({
    queryKey: ["guided-science", ...queryKey, offset],
    queryFn: ({ signal }) => load(offset, signal),
  });
  return (
    <>
      {records.isPending && <p role="status">Loading project evidence…</p>}
      {records.error && <p role="alert">{records.error.message}</p>}
      {render(records.data ?? [])}
      {records.data?.length === 0 && <p>No matching evidence on this page.</p>}
      {(offset > 0 || (records.data?.length ?? 0) >= PAGE) && (
        <div className="button-row">
          <button
            type="button"
            disabled={offset === 0}
            onClick={() => setOffset(offset - PAGE)}
          >
            Previous evidence
          </button>
          <button
            type="button"
            disabled={(records.data?.length ?? 0) < PAGE}
            onClick={() => setOffset(offset + PAGE)}
          >
            More evidence
          </button>
        </div>
      )}
    </>
  );
}

const paged = (path: string, offset: number) =>
  `${path}?${new URLSearchParams({
    limit: String(PAGE),
    offset: String(offset),
  })}`;
const resultLabel = (row: Result, path: string) => {
  const config = object(row.snapshot[path]);
  return {
    id: row.id,
    label: string(config.title ?? config.name) || row.id,
    unavailable: row.stale || !!row.stale_reasons?.length,
  };
};

async function savedOptions(
  base: string,
  kind: string,
  offset: number,
  signal: AbortSignal,
): Promise<Option[]> {
  if (kind === "ecology") {
    const project = base.split("/").at(-1) ?? "";
    const data = await listEcologyAnalyses(project, offset / PAGE + 1, signal);
    return data.items.map((row) => ({
      id: row.id,
      label: `Reviewed ${row.snapshot.result.kind} · ${row.snapshot.reviewed_by} · ${row.id.slice(0, 8)}`,
      unavailable: row.stale,
    }));
  }
  if (kind === "event_summary") {
    const data = await request<{ items: EventSummary[] }>(
      paged(`${base}/ecology/event-summaries`, offset),
      { signal },
    );
    return data.items.map((row) => ({
      id: row.id,
      label: row.snapshot.selection.name,
      unavailable: !!row.stale_reasons.length,
    }));
  }
  if (kind === "static_comparison") {
    const data = await request<StaticSummary[]>(
      paged(`${base}/static-comparisons`, offset),
      { signal },
    );
    return data.map((row) => ({
      id: row.id,
      label: `${row.reference_name} · ${row.model_names.join(", ")}`,
      unavailable: row.status !== "succeeded",
    }));
  }
  const reports = kind === "report";
  const data = await request<Result[]>(
    paged(
      `${base}/${reports ? "research-reports" : "scientific-comparisons"}`,
      offset,
    ),
    { signal },
  );
  return data.map((row) =>
    resultLabel(row, reports ? "configuration" : "options"),
  );
}

function pairedDraft(parameters: Parameters): PairedGrowthDraft {
  return {
    baseline_date: string(parameters.baseline_date),
    followup_date: string(parameters.followup_date),
    experimental_unit_type: string(parameters.experimental_unit_type),
    estimand: string(parameters.estimand),
    missingness_policy:
      parameters.missingness_policy === "complete_unit" ? "complete_unit" : "",
  };
}

function PairedGrowthNodeFields({
  projectId,
  parameters,
  onChange,
}: {
  projectId: string;
  parameters: Parameters;
  onChange: (value: Parameters) => void;
}) {
  const selectedId = string(parameters.analysis_id);
  const source = useQuery({
    queryKey: ["paired-growth-source", projectId, selectedId],
    queryFn: ({ signal }) =>
      request<EcologyAnalysis>(
        `/projects/${encodeURIComponent(projectId)}/ecology/verified-analyses/${encodeURIComponent(selectedId)}`,
        { signal },
      ),
    enabled: !!selectedId,
  });
  const row = source.data;
  const matches =
    row && !row.stale && row.content_sha256 === parameters.source_sha256;
  return (
    <>
      <Records
        queryKey={[projectId, "paired-growth-sources"]}
        load={async (offset, signal) => {
          const data = await listEcologyAnalyses(
            projectId,
            offset / PAGE + 1,
            signal,
          );
          return data.items.map((item) => ({
            id: item.id,
            label: `Reviewed ${item.snapshot.result.kind} · ${item.snapshot.reviewed_by} · ${item.id.slice(0, 8)}`,
            unavailable: item.stale || pairedVisitDates(item).length < 2,
            digest: item.content_sha256,
          }));
        }}
        render={(options) => (
          <SourceSelect
            label="Frozen growth analysis"
            value={selectedId}
            options={options}
            onChange={(id) => {
              const chosen = options.find((option) => option.id === id);
              onChange(
                chosen
                  ? { analysis_id: chosen.id, source_sha256: chosen.digest }
                  : {},
              );
            }}
          />
        )}
      />
      {selectedId && source.error && <p role="alert">{source.error.message}</p>}
      {selectedId && row && !matches && (
        <p role="alert">
          The selected source is stale or its digest has changed. Select a
          current reviewed growth analysis.
        </p>
      )}
      {matches && (
        <PairedGrowthFields
          dates={pairedVisitDates(row)}
          value={pairedDraft(parameters)}
          onChange={(draft) => onChange({ ...parameters, ...draft })}
        />
      )}
    </>
  );
}

function SavedFields({
  base,
  kind,
  label,
  id,
  onChange,
}: {
  base: string;
  kind: string;
  label: string;
  id: string;
  onChange: (id: string) => void;
}) {
  return (
    <Records
      key={kind}
      queryKey={[base, "saved", kind]}
      load={(offset, signal) => savedOptions(base, kind, offset, signal)}
      render={(options) => (
        <SourceSelect
          label={label}
          value={id}
          options={options}
          onChange={onChange}
        />
      )}
    />
  );
}

function AgreementFields({
  config,
  update,
}: {
  config: Parameters;
  update: (delta: Parameters) => void;
}) {
  return (
    <>
      <label>
        ICC formulation
        <select
          value={string(config.icc)}
          onChange={(event) => update({ icc: event.target.value || null })}
        >
          <option value="">Omit ICC</option>
          <option value="A,1">ICC(A,1) · absolute agreement</option>
          <option value="C,1">ICC(C,1) · consistency</option>
        </select>
      </label>
      <label className="toggle-row">
        <input
          type="checkbox"
          checked={config.independent_groups === true}
          onChange={(event) =>
            update({ independent_groups: event.target.checked })
          }
        />
        I verified the independence of the sampling groups
      </label>
      <label className="toggle-row">
        <input
          type="checkbox"
          checked={config.homoscedastic_normal_differences === true}
          onChange={(event) =>
            update({ homoscedastic_normal_differences: event.target.checked })
          }
        />
        I checked the assumptions for classical agreement limits
      </label>
    </>
  );
}

function HeldOutFields({
  base,
  config,
  update,
}: {
  base: string;
  config: Parameters;
  update: (delta: Parameters) => void;
}) {
  const selected = ids(config.source_job_ids);
  const metric = string(config.metric) || "event_count";
  return (
    <>
      <p>
        Use completed scores from the same frozen reference and evaluation
        protocol.
      </p>
      <Records
        queryKey={[base, "held-out-scores"]}
        load={async (offset, signal) =>
          (
            await request<JobRecord[]>(
              paged(`${base}/reefpose-validations`, offset),
              { signal },
            )
          ).map((row) => ({
            id: row.id,
            label: `Score ${row.id.slice(0, 8)} · ${new Date(row.created_at).toLocaleDateString()}`,
            unavailable:
              row.status !== "succeeded" || row.result_json?.split !== "test",
          }))
        }
        render={(options) => (
          <>
            <SourceSelect
              label="Primary held-out report"
              value={selected[0] ?? ""}
              options={options}
              onChange={(id) =>
                update({ source_job_ids: [id, selected[1]].filter(Boolean) })
              }
            />
            <SourceSelect
              label="Second held-out report"
              value={selected[1] ?? ""}
              options={options.filter((row) => row.id !== selected[0])}
              empty="One model only"
              onChange={(id) =>
                update({ source_job_ids: [selected[0], id].filter(Boolean) })
              }
            />
          </>
        )}
      />
      <label>
        Quantity
        <select
          value={metric}
          onChange={(event) =>
            update({ metric: event.target.value, unit: null, name: "" })
          }
        >
          <option value="event_count">Reviewed event count</option>
          <option value="measurement">Continuous measurement</option>
        </select>
      </label>
      <label>
        {metric === "measurement" ? "Measurement definition" : "Event label"}
        <input
          value={string(config.name)}
          maxLength={200}
          onChange={(event) => update({ name: event.target.value })}
        />
      </label>
      {metric === "measurement" && (
        <label>
          Measurement unit
          <input
            value={string(config.unit)}
            maxLength={40}
            onChange={(event) => update({ unit: event.target.value })}
          />
        </label>
      )}
      <AgreementFields config={config} update={update} />
    </>
  );
}

function StaticFields({
  base,
  config,
  update,
}: {
  base: string;
  config: Parameters;
  update: (delta: Parameters) => void;
}) {
  const options = useInfiniteQuery({
    queryKey: ["guided-science", base, "static-options"],
    initialPageParam: 0,
    queryFn: ({ signal, pageParam }) =>
      request<StaticOptions>(
        paged(`${base}/static-comparisons/options`, pageParam),
        { signal },
      ),
    getNextPageParam: (page, previous) =>
      Math.max(page.datasets.length, page.models.length) === PAGE
        ? previous.length * PAGE
        : undefined,
  });
  const data = {
    datasets: options.data?.pages.flatMap((page) => page.datasets) ?? [],
    models: options.data?.pages.flatMap((page) => page.models) ?? [],
  };
  const dataset = data?.datasets.find(
    (row) => row.id === config.dataset_version_id,
  );
  const selected = ids(config.model_ids);
  const classes = ids(config.class_ids);
  const requestedClasses = classes.length
    ? classes
    : (dataset?.classes ?? []).map((row) => row.id);
  const modelOptions = (data?.models ?? []).map((row) => ({
    id: row.id,
    label: row.name,
    unavailable: !requestedClasses.every((id) =>
      row.mapped_class_ids.includes(id),
    ),
  }));
  const inference = object(config.inference);
  return (
    <>
      <p>
        Use an immutable dataset with reviewed boxes. Lineage determines whether
        the comparison qualifies as held out.
      </p>
      {options.isPending && <p role="status">Loading datasets and models…</p>}
      {options.error && <p role="alert">{options.error.message}</p>}
      <SourceSelect
        label="Reviewed reference dataset"
        value={string(config.dataset_version_id)}
        options={(data?.datasets ?? []).map((row) => ({
          id: row.id,
          label: `${row.name} · ${row.reviewed_count} reviewed · ${row.test_reviewed_count} test`,
        }))}
        onChange={(dataset_version_id) =>
          update({ dataset_version_id, class_ids: [], model_ids: [] })
        }
      />
      <label>
        Reference split
        <select
          value={string(config.split) || "test"}
          onChange={(event) => update({ split: event.target.value })}
        >
          <option value="test">Held-out test partition</option>
          <option value="all">All reviewed images</option>
        </select>
      </label>
      <fieldset>
        <legend>Classes to compare</legend>
        <p>Leave classes unchecked to evaluate every frozen class.</p>
        {dataset?.classes.map((row) => (
          <label className="toggle-row" key={row.id}>
            <input
              type="checkbox"
              checked={classes.includes(row.id)}
              onChange={(event) =>
                update({
                  class_ids: event.target.checked
                    ? [...classes, row.id]
                    : classes.filter((id) => id !== row.id),
                  model_ids: [],
                })
              }
            />
            {row.name}
          </label>
        ))}
      </fieldset>
      <SourceSelect
        label="Primary registered detector"
        value={selected[0] ?? ""}
        options={modelOptions}
        onChange={(id) =>
          update({ model_ids: [id, selected[1]].filter(Boolean) })
        }
      />
      <SourceSelect
        label="Second registered detector"
        value={selected[1] ?? ""}
        options={modelOptions.filter((row) => row.id !== selected[0])}
        empty="One detector only"
        onChange={(id) =>
          update({ model_ids: [selected[0], id].filter(Boolean) })
        }
      />
      {options.hasNextPage && (
        <div className="button-row">
          <button
            type="button"
            disabled={options.isFetchingNextPage}
            onClick={() => void options.fetchNextPage()}
          >
            More datasets and models
          </button>
        </div>
      )}
      {(["confidence_threshold", "iou_threshold"] as const).map(
        (key, index) => (
          <label key={key}>
            {index === 0
              ? "Minimum prediction confidence"
              : "Inference overlap threshold (IoU)"}
            <input
              type="number"
              min={0}
              max={1}
              step={0.01}
              value={
                typeof inference[key] === "number"
                  ? inference[key]
                  : index === 0
                    ? 0.25
                    : 0.7
              }
              onChange={(event) =>
                update({
                  inference: {
                    ...inference,
                    [key]: event.target.valueAsNumber,
                  },
                })
              }
            />
          </label>
        ),
      )}
      <label>
        Inference device
        <select
          value={string(inference.device) || "auto"}
          onChange={(event) =>
            update({ inference: { ...inference, device: event.target.value } })
          }
        >
          <option value="auto">Automatic</option>
          <option value="cpu">CPU</option>
          <option value="cuda">CUDA</option>
        </select>
      </label>
      <AgreementFields config={config} update={update} />
    </>
  );
}

type SessionChoice = {
  link_revision_id: string;
  measurement_series_id: string;
  event_run_id: string;
  observed_at: string | null;
};
const readSessions = (value: unknown) =>
  Array.isArray(value)
    ? (value as SessionChoice[]).filter(
        (row) => row && typeof row.link_revision_id === "string",
      )
    : [];

function EventFields({
  base,
  projectId,
  config,
  update,
}: {
  base: string;
  projectId: string;
  config: Parameters;
  update: (delta: Parameters) => void;
}) {
  const [offset, setOffset] = useState(0);
  const links = useQuery({
    queryKey: ["guided-science", base, "pose-links", offset],
    queryFn: ({ signal }) =>
      request<{ items: PoseLink[]; total: number }>(
        paged(`${base}/ecology/pose-links`, offset),
        { signal },
      ),
  });
  const events = useQuery({
    queryKey: ["guided-science", base, "event-runs"],
    queryFn: ({ signal }) => listEventRuns(projectId, signal),
  });
  const sessions = readSessions(config.sessions);
  const updateSession = (link: string, next: SessionChoice | null) =>
    update({
      sessions: [
        ...sessions.filter((row) => row.link_revision_id !== link),
        ...(next ? [next] : []),
      ],
      confirm: false,
    });
  return (
    <>
      <p>
        Select a reviewed organism link and a completed detector that used its
        pinned measurement series. All sessions must share the same protocol.
      </p>
      {[links.error, events.error].filter(Boolean).map((error, index) => (
        <p role="alert" key={index}>
          {error?.message}
        </p>
      ))}
      {(links.isPending || events.isPending) && (
        <p role="status">Loading reviewed pose sessions…</p>
      )}
      {links.data?.items
        .filter((link) => link.status === "current")
        .map((link) => {
          const selected = sessions.find(
            (row) => row.link_revision_id === link.id,
          );
          const combinations = link.source.measurements.flatMap((series) =>
            (events.data ?? [])
              .filter(
                (run) =>
                  run.status === "completed" &&
                  run.measurement_run_id === series.run_id &&
                  Array.isArray(run.configuration_json.cycles) &&
                  run.configuration_json.cycles.some(
                    (value) =>
                      object(value).measurement_series_id === series.id,
                  ),
              )
              .map((run) => ({
                id: `${series.id}/${run.id}`,
                label: `${series.name} · detector ${run.id.slice(0, 8)}`,
              })),
          );
          return (
            <div key={link.id}>
              <SourceSelect
                label={`${link.organism_key} · frames ${link.frame_start} to ${link.frame_end}`}
                options={combinations}
                value={
                  selected
                    ? `${selected.measurement_series_id}/${selected.event_run_id}`
                    : ""
                }
                onChange={(value) => {
                  const [measurement_series_id, event_run_id] =
                    value.split("/");
                  updateSession(
                    link.id,
                    value
                      ? {
                          link_revision_id: link.id,
                          measurement_series_id,
                          event_run_id,
                          observed_at: selected?.observed_at ?? null,
                        }
                      : null,
                  );
                }}
                empty="Omit session"
              />
              {selected && (
                <label>
                  Session time (UTC)
                  <input
                    type="datetime-local"
                    value={selected.observed_at?.slice(0, 16) ?? ""}
                    onChange={(event) =>
                      updateSession(link.id, {
                        ...selected,
                        observed_at: event.target.value
                          ? `${event.target.value}:00Z`
                          : null,
                      })
                    }
                  />
                </label>
              )}
            </div>
          );
        })}
      {(links.data?.total ?? 0) > PAGE && (
        <div className="button-row">
          <button
            type="button"
            disabled={offset === 0}
            onClick={() => setOffset(offset - PAGE)}
          >
            Previous pose links
          </button>
          <button
            type="button"
            disabled={offset + PAGE >= (links.data?.total ?? 0)}
            onClick={() => setOffset(offset + PAGE)}
          >
            More pose links
          </button>
        </div>
      )}
      <p>
        {sessions.length} session{sessions.length === 1 ? "" : "s"} selected.
      </p>
      <label>
        Summary name
        <input
          maxLength={150}
          value={string(config.name)}
          onChange={(event) =>
            update({ name: event.target.value, confirm: false })
          }
        />
      </label>
      <label>
        Reviewer
        <input
          maxLength={100}
          value={string(config.reviewer)}
          onChange={(event) =>
            update({ reviewer: event.target.value, confirm: false })
          }
        />
      </label>
      <label>
        Review reason
        <textarea
          maxLength={500}
          value={string(config.reason)}
          onChange={(event) =>
            update({ reason: event.target.value, confirm: false })
          }
        />
      </label>
      <label className="toggle-row">
        <input
          type="checkbox"
          checked={config.confirm === true}
          disabled={
            !sessions.length ||
            !string(config.name).trim() ||
            !string(config.reviewer).trim() ||
            string(config.reason).trim().length < 3
          }
          onChange={(event) => update({ confirm: event.target.checked })}
        />
        I reviewed these linked sessions and their counting protocol
      </label>
    </>
  );
}

const figureChoices: Record<string, Option[]> = {
  ecology: [
    { id: "trajectory", label: "Longitudinal trajectory" },
    { id: "group_summary", label: "Independent-unit group summary" },
    { id: "treatment_summary", label: "Growth by reviewed treatment" },
    { id: "sample_coverage", label: "Sampling coverage and missingness" },
  ],
  event_summary: [
    { id: "event_rate", label: "Confirmed biological event rate" },
  ],
  comparison: [
    { id: "identity_scatter", label: "Reference–model identity scatter" },
    { id: "bland_altman", label: "Bland–Altman plot" },
  ],
};

function FigureFields({
  base,
  config,
  update,
}: {
  base: string;
  config: Parameters;
  update: (delta: Parameters) => void;
}) {
  const kind = string(config.source_kind) || "ecology";
  return (
    <>
      <p>
        Choose a saved, current source. Each figure retains the exact source
        hash.
      </p>
      <SourceSelect
        label="Figure source type"
        value={kind}
        options={[
          { id: "ecology", label: "Reviewed ecology" },
          { id: "event_summary", label: "Reviewed event summary" },
          { id: "comparison", label: "Held-out pose comparison" },
          { id: "static_comparison", label: "Static-image count comparison" },
        ]}
        onChange={(source_kind) =>
          update({ source_kind, source_id: "", figure: "" })
        }
      />
      <SavedFields
        base={base}
        kind={kind}
        label="Analysis or comparison"
        id={string(config.source_id)}
        onChange={(source_id) => update({ source_id })}
      />
      <SourceSelect
        label="Figure"
        value={string(config.figure)}
        options={
          figureChoices[kind === "static_comparison" ? "comparison" : kind] ??
          []
        }
        onChange={(figure) => update({ figure })}
      />
      <label>
        Figure title
        <input
          value={string(config.title)}
          maxLength={120}
          onChange={(event) => update({ title: event.target.value })}
        />
      </label>
      <label>
        Figure style
        <select
          value={string(config.style) || "grayscale"}
          onChange={(event) => update({ style: event.target.value })}
        >
          <option value="grayscale">Grayscale-safe</option>
          <option value="accessible_color">Accessible color</option>
        </select>
      </label>
    </>
  );
}

function AcquisitionFields({
  projectId,
  parameters,
  onChange,
}: {
  projectId: string;
  parameters: Parameters;
  onChange: (value: Parameters) => void;
}) {
  const datasets = useQuery({
    queryKey: ["dataset-versions", projectId],
    queryFn: ({ signal }) => getDatasetVersions(projectId, signal),
  });
  const thresholds = {
    ...defaultAcquisitionThresholds,
    ...object(parameters.thresholds),
  };
  return (
    <>
      <p>
        Choose a frozen dataset or check source images in the current project.
        Findings are saved for review.
      </p>
      {datasets.error && <p role="alert">{datasets.error.message}</p>}
      <SourceSelect
        label="Acquisition scope"
        value={string(parameters.dataset_version_id)}
        options={(datasets.data ?? []).map((row) => ({
          id: row.id,
          label: row.name,
        }))}
        empty="All project images"
        onChange={(id) =>
          onChange({ ...parameters, dataset_version_id: id || null })
        }
      />
      <AcquisitionQualityControls
        thresholds={thresholds}
        onChange={(value) => onChange({ ...parameters, thresholds: value })}
      />
      {thresholds.dark_luma_max >= thresholds.bright_luma_min && (
        <p role="alert">
          Dark luma maximum must be lower than bright luma minimum.
        </p>
      )}
    </>
  );
}

const operations: Record<
  string,
  { value: string; label: string; kind?: string; defaults?: Parameters }[]
> = {
  scientific_comparison: [
    {
      value: "configuration",
      label: "Calculate a pose agreement report",
      defaults: { source_job_ids: [], metric: "event_count", name: "" },
    },
    {
      value: "comparison_id",
      label: "Replay saved pose agreement",
      kind: "comparison",
    },
    {
      value: "static_configuration",
      label: "Calculate a static-image count comparison",
      defaults: { dataset_version_id: "", model_ids: [], split: "test" },
    },
    {
      value: "static_comparison_id",
      label: "Replay saved static comparison",
      kind: "static_comparison",
    },
  ],
  ecology_event_summary: [
    {
      value: "configuration",
      label: "Calculate a reviewed event summary",
      defaults: {
        name: "",
        reviewer: "",
        reason: "",
        sessions: [],
        confirm: false,
      },
    },
    {
      value: "summary_id",
      label: "Replay a saved event summary",
      kind: "event_summary",
    },
  ],
  research_publication_figure: [
    {
      value: "configuration",
      label: "Create a research figure",
      defaults: {
        source_kind: "ecology",
        source_id: "",
        figure: "",
        title: "",
        style: "grayscale",
      },
    },
    { value: "report_id", label: "Replay a saved figure", kind: "report" },
  ],
};
const savedLabels: Record<string, string> = {
  comparison: "Saved comparison",
  static_comparison: "Saved static comparison",
  event_summary: "Saved event summary",
  report: "Saved research figure",
};

function SpatialTimestamp({
  label,
  value,
  onChange,
}: {
  label: string;
  value: unknown;
  onChange: (value: string | null) => void;
}) {
  return (
    <label>
      {label}
      <input
        placeholder="2026-01-15T14:30:00Z"
        value={string(value)}
        onChange={(event) => onChange(event.currentTarget.value || null)}
      />
    </label>
  );
}

type LocalProviderManifestChoice = {
  provider_id: string;
  display_name: string;
  source_kind: "built_in" | "local_manifest";
  discovery_status: string;
  source_filename: string | null;
  source_sha256: string | null;
};

function ProviderManifestSnapshotFields({
  parameters,
  onChange,
}: {
  parameters: Parameters;
  onChange: (value: Parameters) => void;
}) {
  const manifests = useQuery({
    queryKey: ["workflow-provider-manifests"],
    queryFn: ({ signal }) =>
      request<LocalProviderManifestChoice[]>("/advanced-providers/manifests", {
        signal,
      }),
  });
  const localManifests = (manifests.data ?? []).filter(
    (item) => item.source_kind === "local_manifest",
  );
  const selected = localManifests.find(
    (item) => item.provider_id === string(parameters.record_id),
  );

  return (
    <fieldset>
      <legend>Provider manifest provenance</legend>
      <p>
        This node snapshots metadata only and never executes provider code,
        installs packages, or loads checkpoints.
      </p>
      {manifests.isPending && <p role="status">Loading local manifests…</p>}
      {manifests.error && <p role="alert">{manifests.error.message}</p>}
      <label>
        Local provider manifest
        <select
          value={string(parameters.record_id)}
          onChange={(event) => {
            const manifest = localManifests.find(
              (item) => item.provider_id === event.target.value,
            );
            onChange({
              ...parameters,
              record_id: event.target.value,
              expected_source_sha256: manifest?.source_sha256 ?? null,
            });
          }}
        >
          <option value="">Choose a local manifest</option>
          {localManifests.map((manifest) => (
            <option key={manifest.provider_id} value={manifest.provider_id}>
              {manifest.display_name} · {manifest.discovery_status}
            </option>
          ))}
        </select>
      </label>
      {selected && (
        <p className="annotation-helper">
          {selected.source_filename ?? "Unknown source file"} · SHA-256{" "}
          {selected.source_sha256 ?? "unavailable"}
        </p>
      )}
      {!manifests.isPending && localManifests.length === 0 && (
        <p className="muted-copy">
          No local JSON manifests were found in the ReefVision data directory
          under provider-manifests.
        </p>
      )}
    </fieldset>
  );
}

function SpatialMeasurementFields({
  projectId,
  kind,
  parameters,
  onChange,
}: {
  projectId: string;
  kind: "mesh" | "point_cloud";
  parameters: Parameters;
  onChange: (value: Parameters) => void;
}) {
  const assets = useQuery({
    queryKey: [
      "guided-science",
      `/projects/${projectId}`,
      "spatial-assets",
      kind,
    ],
    queryFn: ({ signal }) => listProjectSpatialAssets(projectId, signal),
    refetchInterval: ({ state }) =>
      state.data?.some((asset) =>
        ["queued", "running", "cancel_requested"].includes(asset.parse_status),
      )
        ? 1000
        : false,
  });
  const update = (delta: Parameters) =>
    onChange({
      ...parameters,
      meters_per_unit: finiteNumber(parameters.meters_per_unit, 1),
      calibration_method: string(parameters.calibration_method) || "other",
      calibration_evidence: string(parameters.calibration_evidence),
      ...delta,
    });
  const isAvailable = (asset: SpatialSourceAsset) =>
    asset.project_id === projectId &&
    asset.parse_status === "succeeded" &&
    asset.parse_summary?.source_kind_resolved === kind &&
    /^[a-f0-9]{64}$/.test(asset.sha256);

  function chooseSource(assetId: string) {
    if (assetId === parameters.asset_id) return;
    const asset = assets.data?.find(
      (item) => item.id === assetId && isAvailable(item),
    );
    if (assetId && !asset) return;
    update({
      asset_id: asset?.id ?? null,
      expected_source_payload_sha256: asset?.sha256 ?? null,
      source_label: null,
      calibration_review: null,
      calibration_review_id: null,
      ply_text: null,
      ...(kind === "mesh"
        ? {
            obj_text: null,
            glb_base64: null,
            vertices: null,
            faces: null,
            surface_path_vertex_pairs: null,
            surface_trace_vertex_paths: null,
            anatomical_branch: null,
          }
        : { points: null, point_index_pairs: null }),
    });
  }
  const uncertainty = parameters.relative_scale_uncertainty;
  return (
    <fieldset>
      <legend>
        {kind === "mesh"
          ? "Guided 3D geometric measurement"
          : "Guided 3D point-cloud measurement"}
      </legend>
      <p>
        Choose an immutable project original. Scale and calibration evidence
        remain provisional until the project review contract verifies them.
      </p>
      {assets.isPending && <p role="status">Loading project 3D originals…</p>}
      {assets.error && <p role="alert">{assets.error.message}</p>}
      <SourceSelect
        label="Project 3D original"
        value={string(parameters.asset_id)}
        options={(assets.data ?? []).map((asset) => ({
          id: asset.id,
          label: `${asset.original_filename} · ${asset.source_format.toUpperCase()} · ${
            asset.parse_status === "succeeded"
              ? "parsed"
              : asset.parse_status.replaceAll("_", " ")
          }`,
          unavailable: !isAvailable(asset),
        }))}
        onChange={chooseSource}
      />
      <label>
        Meters per source unit
        <input
          type="number"
          min={Number.MIN_VALUE}
          step="any"
          value={finiteNumber(parameters.meters_per_unit, 1)}
          onChange={(event) =>
            update({ meters_per_unit: event.target.valueAsNumber })
          }
        />
      </label>
      <label>
        Calibration method
        <select
          value={string(parameters.calibration_method) || "other"}
          onChange={(event) =>
            update({ calibration_method: event.target.value })
          }
        >
          <option value="ruler">Ruler or scale bar</option>
          <option value="photogrammetry_control">Photogrammetry control</option>
          <option value="instrument">Calibrated instrument</option>
          <option value="other">Other / not yet classified</option>
        </select>
      </label>
      <label>
        Calibration evidence
        <textarea
          maxLength={2000}
          value={string(parameters.calibration_evidence)}
          onChange={(event) =>
            update({ calibration_evidence: event.target.value })
          }
        />
      </label>
      <label>
        Relative scale uncertainty (0 to 1)
        <input
          type="number"
          min={0}
          max={1}
          step={0.001}
          value={typeof uncertainty === "number" ? uncertainty : ""}
          onChange={(event) =>
            update({
              relative_scale_uncertainty:
                event.target.value === "" ? null : event.target.valueAsNumber,
            })
          }
        />
      </label>
      {(["specimen_id", "observation_id", "coordinate_frame_id"] as const).map(
        (field) => (
          <label key={field}>
            {
              {
                specimen_id: "Provisional specimen ID",
                observation_id: "Observation ID",
                coordinate_frame_id: "Coordinate frame ID",
              }[field]
            }
            <input
              value={string(parameters[field])}
              onChange={(event) =>
                update({ [field]: event.target.value || null })
              }
            />
          </label>
        ),
      )}
      <SpatialTimestamp
        label="Acquisition timestamp"
        value={parameters.observed_at_utc}
        onChange={(observed_at_utc) => update({ observed_at_utc })}
      />
      <p className="annotation-helper">
        Include Z for UTC or the acquisition time's UTC offset.
      </p>
      {kind === "point_cloud" && (
        <label className="toggle-row">
          <input
            type="checkbox"
            checked={
              parameters.preserve_measured_chord_endpoints_in_preview === true
            }
            onChange={(event) =>
              update({
                preserve_measured_chord_endpoints_in_preview:
                  event.target.checked,
              })
            }
          />
          Preserve measured chord endpoints
        </label>
      )}
      <p className="annotation-helper">
        {kind === "mesh"
          ? "Surface routes are geometric paths, not verified anatomical branch lengths. Configure vertex routes under Advanced parameter JSON only when exact indices are known."
          : "A point cloud reports extents and selected chords; it does not infer surface area, volume, or anatomical branch length."}
      </p>
    </fieldset>
  );
}

function SpatialLongitudinalFields({
  parameters,
  onChange,
}: {
  parameters: Parameters;
  onChange: (value: Parameters) => void;
}) {
  const registration = object(parameters.registration_evidence);
  const correspondence = object(parameters.reidentification_evidence);
  const matrix = registration.source_to_target_transform_m;
  const updateRegistration = (delta: Parameters) =>
    onChange({
      ...parameters,
      registration_evidence: {
        method: "landmark",
        ...registration,
        ...delta,
      },
    });
  const updateCorrespondence = (delta: Parameters) =>
    onChange({
      ...parameters,
      reidentification_evidence: {
        method: "visual_morphology",
        ...correspondence,
        ...delta,
      },
    });
  return (
    <fieldset>
      <legend>Guided longitudinal 3D evidence</legend>
      <p>
        Connect the earlier and later mesh measurements, then record
        registration and organism correspondence separately. Empty review
        decisions remain explicitly unresolved.
      </p>
      <fieldset>
        <legend>Registration review</legend>
        <label>
          Registration source frame
          <input
            value={string(registration.source_frame_id)}
            onChange={(event) =>
              updateRegistration({ source_frame_id: event.target.value })
            }
          />
        </label>
        <label>
          Registration target frame
          <input
            value={string(registration.target_frame_id)}
            onChange={(event) =>
              updateRegistration({ target_frame_id: event.target.value })
            }
          />
        </label>
        <label>
          Registration method
          <select
            value={string(registration.method) || "landmark"}
            onChange={(event) =>
              updateRegistration({ method: event.target.value })
            }
          >
            <option value="landmark">Landmarks</option>
            <option value="icp">Iterative closest point</option>
            <option value="survey_control">Survey control</option>
            <option value="other">Other</option>
          </select>
        </label>
        <label>
          RMS residual (meters)
          <input
            type="number"
            min={0}
            step="any"
            max={1_000_000}
            value={
              typeof registration.rms_residual_m === "number"
                ? registration.rms_residual_m
                : ""
            }
            onChange={(event) =>
              updateRegistration({
                rms_residual_m:
                  event.currentTarget.value === ""
                    ? null
                    : event.currentTarget.valueAsNumber,
              })
            }
          />
        </label>
        <label>
          Correspondence count
          <input
            type="number"
            min={3}
            step={1}
            max={1_000_000}
            value={
              typeof registration.correspondence_count === "number"
                ? registration.correspondence_count
                : ""
            }
            onChange={(event) =>
              updateRegistration({
                correspondence_count:
                  event.currentTarget.value === ""
                    ? null
                    : event.currentTarget.valueAsNumber,
              })
            }
          />
        </label>
        <label>
          Registration evidence note
          <textarea
            maxLength={2000}
            value={string(registration.evidence_note)}
            onChange={(event) =>
              updateRegistration({ evidence_note: event.target.value })
            }
          />
        </label>
        <label>
          Independent registration decision
          <select
            value={string(registration.independent_review_decision)}
            onChange={(event) =>
              updateRegistration({
                independent_review_decision: event.target.value || null,
              })
            }
          >
            <option value="">Unresolved / no independent review</option>
            <option value="supports_alignment">
              Accepted: supports alignment
            </option>
            <option value="disputes_alignment">
              Rejected: disputes alignment
            </option>
            <option value="inconclusive">Disputed / inconclusive</option>
          </select>
        </label>
        <label>
          Registration operator
          <input
            value={string(registration.registration_operator_id)}
            onChange={(event) =>
              updateRegistration({
                registration_operator_id: event.target.value || null,
              })
            }
          />
        </label>
        <label>
          Independent registration reviewer
          <input
            value={string(registration.independent_reviewer_id)}
            onChange={(event) =>
              updateRegistration({
                independent_reviewer_id: event.target.value || null,
              })
            }
          />
        </label>
        <label>
          Independent registration review note
          <textarea
            maxLength={2000}
            value={string(registration.independent_review_note)}
            onChange={(event) =>
              updateRegistration({
                independent_review_note: event.target.value || null,
              })
            }
          />
        </label>
        <SpatialTimestamp
          label="Registration review timestamp"
          value={registration.independent_reviewed_at_utc}
          onChange={(independent_reviewed_at_utc) =>
            updateRegistration({ independent_reviewed_at_utc })
          }
        />
        <details className="advanced-disclosure">
          <summary>Rigid transform and error bounds</summary>
          <p>
            Enter the matrix that maps the earlier calibrated frame into the
            later calibrated frame. Translation and error bounds use meters.
          </p>
          <label>
            Earlier-to-later rigid transform (4 × 4)
            <textarea
              rows={5}
              value={
                typeof matrix === "string"
                  ? matrix
                  : matrix == null
                    ? ""
                    : JSON.stringify(matrix)
              }
              onChange={(event) =>
                updateRegistration({
                  source_to_target_transform_m: parseRegistrationMatrix(
                    event.target.value,
                  ),
                })
              }
              spellCheck={false}
            />
          </label>
          <p>
            Supply all three absolute error bounds for a separation interval.
          </p>
          {registrationErrorBounds.map(([field, label]) => (
            <label key={field}>
              {label}
              <input
                type="number"
                min={0}
                step="any"
                max={1_000_000}
                value={
                  typeof registration[field] === "number"
                    ? registration[field]
                    : ""
                }
                onChange={(event) =>
                  updateRegistration({
                    [field]:
                      event.currentTarget.value === ""
                        ? null
                        : event.currentTarget.valueAsNumber,
                  })
                }
              />
            </label>
          ))}
        </details>
      </fieldset>
      <fieldset>
        <legend>Organism correspondence</legend>
        <label>
          Earlier observation ID
          <input
            value={string(correspondence.before_observation_id)}
            onChange={(event) =>
              updateCorrespondence({
                before_observation_id: event.target.value,
              })
            }
          />
        </label>
        <label>
          Later observation ID
          <input
            value={string(correspondence.after_observation_id)}
            onChange={(event) =>
              updateCorrespondence({ after_observation_id: event.target.value })
            }
          />
        </label>
        <label>
          Matching method
          <select
            value={string(correspondence.method) || "visual_morphology"}
            onChange={(event) =>
              updateCorrespondence({ method: event.target.value })
            }
          >
            <option value="visual_morphology">Visual morphology</option>
            <option value="survey_tag">Survey tag</option>
            <option value="photo_match">Photo match</option>
            <option value="other">Other</option>
          </select>
        </label>
        <label>
          Matching observer
          <input
            value={string(correspondence.observer_id)}
            onChange={(event) =>
              updateCorrespondence({ observer_id: event.target.value })
            }
          />
        </label>
        <label>
          Correspondence evidence note
          <textarea
            maxLength={2000}
            value={string(correspondence.evidence_note)}
            onChange={(event) =>
              updateCorrespondence({ evidence_note: event.target.value })
            }
          />
        </label>
        <label>
          Independent correspondence decision
          <select
            value={string(correspondence.independent_review_decision)}
            onChange={(event) =>
              updateCorrespondence({
                independent_review_decision: event.target.value || null,
              })
            }
          >
            <option value="">Unresolved / no independent review</option>
            <option value="supports_match">Accepted: supports match</option>
            <option value="disputes_match">Rejected: disputes match</option>
            <option value="inconclusive">Disputed / inconclusive</option>
          </select>
        </label>
        <label>
          Independent correspondence reviewer
          <input
            value={string(correspondence.independent_reviewer_id)}
            onChange={(event) =>
              updateCorrespondence({
                independent_reviewer_id: event.target.value || null,
              })
            }
          />
        </label>
        <label>
          Independent correspondence review note
          <textarea
            maxLength={2000}
            value={string(correspondence.independent_review_note)}
            onChange={(event) =>
              updateCorrespondence({
                independent_review_note: event.target.value || null,
              })
            }
          />
        </label>
        <SpatialTimestamp
          label="Correspondence review timestamp"
          value={correspondence.independent_reviewed_at_utc}
          onChange={(independent_reviewed_at_utc) =>
            updateCorrespondence({ independent_reviewed_at_utc })
          }
        />
      </fieldset>
      <p className="annotation-helper">
        Supporting review is durable audit evidence in the saved workflow. It
        does not authenticate reviewer authority or turn geometric change into a
        biological condition claim.
      </p>
    </fieldset>
  );
}

export function ScientificNodeControls({
  nodeType,
  projectId,
  parameters,
  onChange,
}: {
  nodeType: string;
  projectId: string;
  parameters: Parameters;
  onChange: (value: Parameters) => void;
}) {
  const base = `/projects/${projectId}`;
  if (nodeType === "reviewed_model_runtime")
    return (
      <ModelSelectionField
        projectId={projectId}
        value={string(parameters.selection_id)}
        onChange={(selection) =>
          onChange({
            ...parameters,
            selection_id: selection?.id ?? "",
            selection_sha256: selection?.content_sha256 ?? "",
          })
        }
      />
    );
  if (nodeType === "provider_manifest_snapshot")
    return (
      <ProviderManifestSnapshotFields
        parameters={parameters}
        onChange={onChange}
      />
    );
  if (nodeType === "research_reproducibility_package")
    return (
      <Records
        queryKey={[base, "saved", "reproducibility-proofs"]}
        load={async (offset, signal) => {
          const proofs = await listResearchProofs(projectId, signal);
          return proofs.slice(offset, offset + PAGE).map((proof) => ({
            id: proof.proof_sha256,
            label: "Verified proof · " + proof.proof_sha256.slice(0, 12),
          }));
        }}
        render={(options) => (
          <SourceSelect
            label="Pinned proof"
            value={string(parameters.proof_sha256)}
            options={options}
            onChange={(proof_sha256) =>
              onChange({ ...parameters, proof_sha256 })
            }
          />
        )}
      />
    );
  if (nodeType === "paired_model_comparison")
    return (
      <Records
        queryKey={[base, "saved", "paired-model-comparisons"]}
        load={async (offset, signal) => {
          const page = await request<
            {
              id: string;
              task: string;
              status: string;
              content_sha256: string | null;
            }[]
          >(
            base +
              "/paired-model-comparisons?limit=" +
              PAGE +
              "&offset=" +
              offset +
              "&completed_only=true",
            { signal },
          );
          return page.map((item) => ({
            id: item.id,
            label: item.task + " · " + item.id.slice(0, 8),
            digest: item.content_sha256 ?? "",
          }));
        }}
        render={(options) => (
          <SourceSelect
            label="Paired model comparison"
            value={string(parameters.comparison_id)}
            options={options}
            onChange={(id) =>
              onChange({
                ...parameters,
                comparison_id: id,
                comparison_sha256:
                  options.find((item) => item.id === id)?.digest ?? "",
              })
            }
          />
        )}
      />
    );
  if (nodeType === "reviewed_study_design")
    return (
      <Records
        queryKey={[base, "saved", "study-design"]}
        load={async (offset, signal) => {
          const page = await listStudyDesigns(
            projectId,
            offset / PAGE + 1,
            signal,
          );
          return page.items.map((record) => ({
            id: record.id,
            label: `${record.snapshot.declaration.title} · r${record.revision} · ${record.id.slice(0, 8)}`,
            digest: record.content_sha256,
          }));
        }}
        render={(options) => (
          <SourceSelect
            label="Study design revision"
            value={string(parameters.design_revision_id)}
            options={options}
            onChange={(id) =>
              onChange({
                ...parameters,
                design_revision_id: id,
                design_sha256:
                  options.find((item) => item.id === id)?.digest ?? "",
              })
            }
          />
        )}
      />
    );
  if (nodeType === "mesh_surface_preview" || nodeType === "point_cloud_preview")
    return (
      <SpatialMeasurementFields
        projectId={projectId}
        kind={nodeType === "mesh_surface_preview" ? "mesh" : "point_cloud"}
        parameters={parameters}
        onChange={onChange}
      />
    );
  if (nodeType === "mesh_longitudinal_comparison")
    return (
      <SpatialLongitudinalFields parameters={parameters} onChange={onChange} />
    );
  if (nodeType === "image_acquisition_quality")
    return (
      <AcquisitionFields
        projectId={projectId}
        parameters={parameters}
        onChange={onChange}
      />
    );
  if (nodeType === "paired_growth_contrast")
    return (
      <PairedGrowthNodeFields
        projectId={projectId}
        parameters={parameters}
        onChange={onChange}
      />
    );
  if (nodeType === "ecology_verified_analysis")
    return (
      <>
        <p>
          Replay the evidence of a current, explicitly reviewed growth or
          abundance analysis.
        </p>
        <SavedFields
          base={base}
          kind="ecology"
          label="Reviewed ecological analysis"
          id={string(parameters.analysis_id)}
          onChange={(analysis_id) => onChange({ ...parameters, analysis_id })}
        />
      </>
    );
  const choices = operations[nodeType] ?? [];
  const selected = choices.filter((row) =>
    Object.hasOwn(parameters, row.value),
  );
  const operation =
    choices.find(
      (row) =>
        !!string(parameters[row.value]) ||
        Object.keys(object(parameters[row.value])).length > 0,
    ) ?? (selected.length === 1 ? selected[0] : undefined);
  const setMode = (mode: string) => {
    const next = { ...parameters };
    for (const row of choices) delete next[row.value];
    const selection = choices.find((row) => row.value === mode);
    if (selection) next[selection.value] = selection.defaults ?? "";
    onChange(next);
  };
  const config = object(operation && parameters[operation.value]);
  const changeConfig = (delta: Parameters) => {
    if (operation)
      onChange({
        ...parameters,
        [operation.value]: { ...operation.defaults, ...config, ...delta },
      });
  };
  return (
    <fieldset>
      <legend>Guided scientific configuration</legend>
      <SourceSelect
        label="Operation"
        value={operation?.value ?? ""}
        options={choices.map((row) => ({ id: row.value, label: row.label }))}
        onChange={setMode}
      />
      {operation?.kind && (
        <SavedFields
          base={base}
          kind={operation.kind}
          label={savedLabels[operation.kind]}
          id={string(parameters[operation.value])}
          onChange={(id) => onChange({ ...parameters, [operation.value]: id })}
        />
      )}
      {operation?.value === "static_configuration" && (
        <StaticFields base={base} config={config} update={changeConfig} />
      )}
      {operation?.value === "configuration" &&
        nodeType === "scientific_comparison" && (
          <HeldOutFields base={base} config={config} update={changeConfig} />
        )}
      {operation?.value === "configuration" &&
        nodeType === "ecology_event_summary" && (
          <EventFields
            base={base}
            projectId={projectId}
            config={config}
            update={changeConfig}
          />
        )}
      {operation?.value === "configuration" &&
        nodeType === "research_publication_figure" && (
          <FigureFields base={base} config={config} update={changeConfig} />
        )}
    </fieldset>
  );
}
