import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState, type FormEvent } from "react";

import { saveWorkflowGraph } from "../workflow-graphs/workflowGraphApi";
import {
  listEcologyAnalyses,
  type EcologyAnalysis,
} from "./ecologyAnalysisApi";
import type { Identity, Metric } from "./ecologyApi";
import { getRegistry } from "./ecologyApi";
import {
  bindStudyDesign,
  getStudyDesign,
  listStudyDesigns,
  saveStudyDesign,
  studyDesignExport,
  studyDesignKey,
  type StudyDesignCreate,
  type StudyDesignDeclaration,
  type StudyDesignRecord,
  type StudyDesignSource,
} from "./studyDesignApi";

const metricLabels = {
  box_width: "Calibrated box width",
  box_height: "Calibrated box height",
  mask_projected_area: "Calibrated projected mask area",
} satisfies Record<Metric, string>;

function sourcePin(analysis: EcologyAnalysis): StudyDesignSource {
  return {
    growth_analysis_id: analysis.id,
    growth_source_sha256: analysis.content_sha256,
  };
}

async function growthSources(projectId: string, signal: AbortSignal) {
  const sources: EcologyAnalysis[] = [];
  for (let page = 1; ; page++) {
    const result = await listEcologyAnalyses(projectId, page, signal);
    sources.push(...result.items);
    if (sources.length >= result.total || result.items.length === 0) break;
  }
  return sources.filter(
    ({ stale, snapshot: { selection } }) =>
      !stale &&
      selection.kind === "growth" &&
      Boolean(selection.sampling_plan?.length),
  );
}

function GrowthSourceChoice({
  sources,
  value,
  onChange,
  required = false,
}: {
  sources: EcologyAnalysis[];
  value: string;
  onChange: (value: string) => void;
  required?: boolean;
}) {
  const labelId = useId();
  return (
    <label>
      <span id={labelId}>Reviewed growth evidence</span>
      <select
        aria-labelledby={labelId}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        required={required}
      >
        <option value="">Choose a saved analysis with a sampling plan</option>
        {sources.map((analysis) => (
          <option value={analysis.id} key={analysis.id}>
            {analysis.snapshot.reviewed_by} · {analysis.created_at.slice(0, 10)}{" "}
            · {analysis.id.slice(0, 8)}
          </option>
        ))}
      </select>
    </label>
  );
}

function DesignForm({
  identities,
  sources,
  parent,
  saving,
  onSave,
  onCancel,
}: {
  identities: Identity[];
  sources: EcologyAnalysis[];
  parent: StudyDesignRecord | null;
  saving: boolean;
  onSave: (payload: StudyDesignCreate) => void;
  onCancel: () => void;
}) {
  const previous = parent?.snapshot.declaration;
  const timingLabel = useId();
  const [timing, setTiming] = useState<StudyDesignDeclaration["timing"]>(
    previous?.timing ?? "prospective",
  );
  const [sourceId, setSourceId] = useState(parent?.growth_analysis_id ?? "");
  const [unitType, setUnitType] = useState(
    previous?.contrast.experimental_unit_type ?? "",
  );
  const [keys, setKeys] = useState(previous?.organism_keys ?? []);
  const source = sources.find((item) => item.id === sourceId);
  const selection = source?.snapshot.selection;
  const sourceKeys =
    selection?.kind === "growth"
      ? (selection.sampling_plan?.flatMap((unit) => unit.organism_keys) ?? [])
      : [];
  const enrolled = timing === "prospective" ? keys : sourceKeys;
  const roster = identities.filter((row) =>
    enrolled.includes(row.organism_key),
  );
  const treatmentCodes = Array.from(
    new Set(
      roster.flatMap(({ study_assignment }) =>
        study_assignment?.treatment_code
          ? [study_assignment.treatment_code]
          : [],
      ),
    ),
  ).sort();
  const eligible = identities.filter(
    (row) =>
      row.study_assignment &&
      row.experimental_unit_type?.toLowerCase() ===
        unitType.trim().toLowerCase(),
  );

  function selectSource(id: string) {
    setSourceId(id);
    const selected = sources.find((item) => item.id === id)?.snapshot.selection;
    if (selected?.kind !== "growth") return;
    const first = selected.sampling_plan?.[0]?.organism_keys[0];
    const registered = identities.find((row) => row.organism_key === first);
    if (registered?.experimental_unit_type)
      setUnitType(registered.experimental_unit_type);
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!enrolled.length || (timing === "retrospective" && !source)) return;
    const form = new FormData(event.currentTarget);
    const value = (name: string) => String(form.get(name) ?? "").trim();
    if (
      form.get("confirmed") !== "on" ||
      value("missingness") !== "complete_unit" ||
      value("method") !== "paired_growth_contrast"
    )
      return;
    const payload: StudyDesignCreate = {
      declaration: {
        title: value("title"),
        timing,
        reviewed_by: value("reviewer"),
        review_note: value("review"),
        confirm_review: true,
        contrast: {
          baseline_date: value("baseline"),
          followup_date: value("followup"),
          experimental_unit_type: unitType.trim(),
          estimand: value("estimand"),
          missingness_policy: "complete_unit",
        },
        metric:
          selection?.kind === "growth" && timing === "retrospective"
            ? selection.metric
            : (value("metric") as Metric),
        method: "paired_growth_contrast",
        nesting: "parent_colony_within_unit",
        exclusion_policy: value(
          "exclusion-policy",
        ) as StudyDesignDeclaration["exclusion_policy"],
        exclusion_rule: value("exclusion-rule"),
        organism_keys: enrolled,
        treatments: treatmentCodes.map((code) => ({
          code,
          label: value(`treatment-${code}`),
        })),
      },
      ...(source && timing === "retrospective" ? sourcePin(source) : {}),
      ...(parent
        ? {
            supersedes_revision_id: parent.id,
            supersedes_sha256: parent.content_sha256,
          }
        : {}),
    };
    onSave(payload);
  }

  return (
    <form
      className="management-card"
      onSubmit={submit}
      aria-label={parent ? "Revise study design" : "Declare study design"}
    >
      <h4>{parent ? `Revise ${previous?.title}` : "Declare a study design"}</h4>
      <label>
        <span id={timingLabel}>Timing</span>
        <select
          aria-labelledby={timingLabel}
          value={timing}
          onChange={(event) => setTiming(event.target.value as typeof timing)}
        >
          <option value="prospective">
            Prospective · freeze before baseline
          </option>
          <option value="retrospective">
            Retrospective · use existing growth evidence
          </option>
        </select>
      </label>
      {timing === "retrospective" && (
        <GrowthSourceChoice
          sources={sources}
          value={sourceId}
          onChange={selectSource}
          required
        />
      )}
      <label>
        Study title{" "}
        <input
          name="title"
          required
          maxLength={150}
          defaultValue={previous?.title}
        />
      </label>
      <label>
        Independent experimental unit type
        <input
          value={unitType}
          required
          maxLength={150}
          onChange={(event) => {
            setUnitType(event.target.value);
            setKeys([]);
          }}
        />
      </label>
      {timing === "prospective" ? (
        <fieldset>
          <legend>Enroll organisms with reviewed assignments</legend>
          {!eligible.length && (
            <p>
              Review assignments in the organism registry for this unit type.
            </p>
          )}
          {eligible.map((row) => (
            <label key={row.id}>
              <input
                type="checkbox"
                checked={keys.includes(row.organism_key)}
                onChange={(event) =>
                  setKeys(
                    event.target.checked
                      ? [...keys, row.organism_key]
                      : keys.filter((key) => key !== row.organism_key),
                  )
                }
              />
              {row.organism_key} · {row.experimental_unit_id}
            </label>
          ))}
        </fieldset>
      ) : (
        source && (
          <p>
            {enrolled.length} enrolled organisms in the reviewed growth plan.{" "}
            {enrolled.filter(
              (key) =>
                !roster.some(
                  (row) => row.organism_key === key && row.study_assignment,
                ),
            ).length > 0
              ? "Review missing organism assignments in the registry before freezing."
              : "Review the frozen roster below."}
          </p>
        )
      )}
      {roster.length > 0 && (
        <details open>
          <summary>Enrolled assignments and nesting</summary>
          <ul>
            {roster.map((row) => (
              <li key={row.id}>
                {row.organism_key} · {row.experimental_unit_type}{" "}
                {row.experimental_unit_id}
                {row.parent_colony_key &&
                  ` · parent colony ${row.parent_colony_key}`}
                {row.study_assignment?.treatment_code &&
                  ` · treatment ${row.study_assignment.treatment_code}`}
                {row.study_assignment?.site_code &&
                  ` · site ${row.study_assignment.site_code}`}
                {row.study_assignment?.tank_code &&
                  ` · tank ${row.study_assignment.tank_code}`}
                {row.study_assignment?.sampling_unit_id &&
                  ` · sampling unit ${row.study_assignment.sampling_unit_id}`}
              </li>
            ))}
          </ul>
        </details>
      )}
      {treatmentCodes.map((code) => (
        <label key={code}>
          Treatment label for {code}
          <input
            name={`treatment-${code}`}
            required
            maxLength={150}
            defaultValue={
              previous?.treatments.find((row) => row.code === code)?.label
            }
          />
        </label>
      ))}
      <label>
        Baseline UTC date{" "}
        <input
          name="baseline"
          type="date"
          required
          defaultValue={previous?.contrast.baseline_date}
        />
      </label>
      <label>
        Follow-up UTC date{" "}
        <input
          name="followup"
          type="date"
          required
          defaultValue={previous?.contrast.followup_date}
        />
      </label>
      {timing === "retrospective" && selection?.kind === "growth" ? (
        <p>Measurement · {metricLabels[selection.metric]}</p>
      ) : (
        <label>
          Measurement metric
          <select name="metric" defaultValue={previous?.metric ?? "box_width"}>
            {Object.entries(metricLabels).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
      )}
      <label>
        Analysis method
        <select name="method" required defaultValue={previous?.method ?? ""}>
          <option value="">Choose an analysis method</option>
          <option value="paired_growth_contrast">
            Two-visit paired growth contrast
          </option>
        </select>
      </label>
      <p>
        The paired contrast weights complete independent units equally and pools
        the declared treatments.
      </p>
      <p>
        Nesting · Average matched organisms within each parent colony, then
        average colonies or unparented organisms within the declared unit.
      </p>
      <label>
        Missing observations policy
        <select
          name="missingness"
          required
          defaultValue={previous?.contrast.missingness_policy ?? ""}
        >
          <option value="">Choose a missing observations policy</option>
          <option value="complete_unit">
            Exclude incomplete units and retain their reasons
          </option>
        </select>
      </label>
      <label>
        Estimand{" "}
        <textarea
          name="estimand"
          required
          minLength={3}
          maxLength={1500}
          defaultValue={previous?.contrast.estimand}
        />
      </label>
      <label>
        Source exclusion policy
        <select
          name="exclusion-policy"
          defaultValue={
            previous?.exclusion_policy ?? "reviewed_source_exclusions"
          }
        >
          <option value="reviewed_source_exclusions">
            Keep recorded reviewed exclusions
          </option>
          <option value="no_source_exclusions">
            Require evidence without excluded sources
          </option>
        </select>
      </label>
      <label>
        Exclusion rule{" "}
        <textarea
          name="exclusion-rule"
          required
          minLength={3}
          maxLength={1500}
          defaultValue={previous?.exclusion_rule}
        />
      </label>
      <label>
        Study reviewer{" "}
        <input
          name="reviewer"
          required
          maxLength={100}
          defaultValue={previous?.reviewed_by}
        />
      </label>
      <label>
        Review note{" "}
        <textarea
          name="review"
          required
          minLength={3}
          maxLength={1500}
          defaultValue={previous?.review_note}
        />
      </label>
      <label>
        <input type="checkbox" name="confirmed" required /> I reviewed this
        design
      </label>
      <button type="submit" disabled={saving || !enrolled.length}>
        Freeze study design
      </button>
      {parent && (
        <button type="button" className="secondary" onClick={onCancel}>
          Cancel revision
        </button>
      )}
    </form>
  );
}

function DesignReceipt({
  record,
  sources,
  saving,
  onBind,
  onRevise,
  onSaveGraph,
}: {
  record: StudyDesignRecord;
  sources: EcologyAnalysis[];
  saving: boolean;
  onBind: (source: StudyDesignSource) => void;
  onRevise: () => void;
  onSaveGraph: () => void;
}) {
  const [sourceId, setSourceId] = useState("");
  const { snapshot } = record;
  const { declaration, binding } = snapshot;
  const paired = binding?.paired_report;
  const source = sources.find((item) => item.id === sourceId);
  return (
    <article className="management-card">
      <h4>
        {declaration.title} · Revision {record.revision}
      </h4>
      <p>
        {declaration.timing === "prospective"
          ? "Prospectively declared"
          : "Retrospective use of existing evidence"}{" "}
        · {snapshot.declared_at}
      </p>
      <dl>
        <div>
          <dt>Study design ID</dt>
          <dd>
            <code>{snapshot.design_id}</code>
          </dd>
        </div>
        <div>
          <dt>Original revision ID</dt>
          <dd>
            <code>{snapshot.revision_id}</code>
          </dd>
        </div>
        {record.id !== snapshot.revision_id && (
          <div>
            <dt>Revision in this project</dt>
            <dd>
              <code>{record.id}</code>
            </dd>
          </div>
        )}
        <div>
          <dt>Design SHA-256</dt>
          <dd>
            <code>{record.content_sha256}</code>
          </dd>
        </div>
        <div>
          <dt>Reviewed by</dt>
          <dd>
            {declaration.reviewed_by} · {declaration.review_note}
          </dd>
        </div>
        <div>
          <dt>Visits</dt>
          <dd>
            {declaration.contrast.baseline_date} and{" "}
            {declaration.contrast.followup_date} UTC
          </dd>
        </div>
        <div>
          <dt>Estimand</dt>
          <dd>{declaration.contrast.estimand}</dd>
        </div>
        <div>
          <dt>Source exclusions</dt>
          <dd>{declaration.exclusion_rule}</dd>
        </div>
      </dl>
      <details>
        <summary>Frozen roster and treatments</summary>
        <ul>
          {snapshot.roster.map((row) => (
            <li key={row.identity_id}>
              {row.organism_key} · {row.experimental_unit_type}{" "}
              {row.experimental_unit_id} · identity revision{" "}
              {row.identity_revision}
              {row.parent_colony_key &&
                ` · parent colony ${row.parent_colony_key}`}
              {row.assignment.treatment_code &&
                ` · ${declaration.treatments.find((item) => item.code === row.assignment.treatment_code)?.label} (${row.assignment.treatment_code})`}
              {row.assignment.site_code &&
                ` · site ${row.assignment.site_code}`}
              {row.assignment.tank_code &&
                ` · tank ${row.assignment.tank_code}`}
              {row.assignment.sampling_unit_id &&
                ` · sampling unit ${row.assignment.sampling_unit_id}`}
              {` · reviewed by ${row.assignment.reviewer}`}
            </li>
          ))}
        </ul>
      </details>
      {paired && binding ? (
        <>
          <p>
            {paired.included_unit_count} of {paired.planned_unit_count} planned
            independent units included
          </p>
          <p>
            Mean paired change ·{" "}
            {paired.mean_difference == null
              ? "Unavailable"
              : `${Number(paired.mean_difference.toPrecision(6))} ${paired.unit ?? ""}`}
          </p>
          <details>
            <summary>Bound evidence and analysis assumptions</summary>
            <dl>
              <div>
                <dt>Original growth analysis ID</dt>
                <dd>
                  <code>{binding.analysis_id}</code>
                </dd>
              </div>
              <div>
                <dt>Growth source SHA-256</dt>
                <dd>
                  <code>{binding.source_sha256}</code>
                </dd>
              </div>
              <div>
                <dt>Paired report SHA-256</dt>
                <dd>
                  <code>{paired.report_sha256}</code>
                </dd>
              </div>
            </dl>
            <ul>
              {paired.assumptions.map((assumption) => (
                <li key={assumption}>{assumption}</li>
              ))}
            </ul>
            <ul>
              {paired.units.map((unit) => (
                <li key={unit.experimental_unit_id}>
                  {unit.experimental_unit_id} ·{" "}
                  {unit.reason?.replaceAll("_", " ") ?? unit.status}
                </li>
              ))}
            </ul>
          </details>
        </>
      ) : (
        <>
          <p>
            Prospective plan awaiting reviewed growth evidence. Replay of this
            revision returns the declaration and its roster.
          </p>
          <GrowthSourceChoice
            sources={sources}
            value={sourceId}
            onChange={setSourceId}
          />
          <button
            type="button"
            disabled={saving || !source}
            onClick={() => source && onBind(sourcePin(source))}
          >
            Bind evidence in a new revision
          </button>
        </>
      )}
      <div className="button-row">
        <a href={studyDesignExport(record.project_id, record.id)}>
          Download frozen study JSON
        </a>
        <button type="button" className="secondary" onClick={onRevise}>
          Start a new study revision
        </button>
        <button
          type="button"
          className="secondary"
          disabled={saving}
          onClick={onSaveGraph}
        >
          Save study workflow
        </button>
      </div>
    </article>
  );
}

export function StudyDesignWorkspace({ projectId }: { projectId: string }) {
  const registry = useQuery({
    queryKey: ["ecology-registry", projectId],
    queryFn: ({ signal }) => getRegistry(projectId, signal),
  });
  if (registry.error) return <p role="alert">{registry.error.message}</p>;
  if (!registry.data) return <p>Loading the project roster…</p>;
  return (
    <StudyDesignPanel
      projectId={projectId}
      identities={registry.data.identities}
    />
  );
}

export function StudyDesignPanel({
  projectId,
  identities,
}: {
  projectId: string;
  identities: Identity[];
}) {
  const client = useQueryClient();
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState("");
  const [parent, setParent] = useState<StudyDesignRecord | null>(null);
  const list = useQuery({
    queryKey: [...studyDesignKey(projectId), "page", page],
    queryFn: ({ signal }) => listStudyDesigns(projectId, page, signal),
  });
  const evidence = useQuery({
    queryKey: ["study-growth-sources", projectId],
    queryFn: ({ signal }) => growthSources(projectId, signal),
  });
  const detail = useQuery({
    queryKey: [...studyDesignKey(projectId), selected],
    queryFn: ({ signal }) => getStudyDesign(projectId, selected, signal),
    enabled: Boolean(selected),
  });
  async function afterFreeze(record: StudyDesignRecord) {
    setPage(1);
    setSelected(record.id);
    setParent(null);
    await client.invalidateQueries({ queryKey: studyDesignKey(projectId) });
  }
  const freeze = useMutation({
    mutationFn: (payload: StudyDesignCreate) =>
      saveStudyDesign(projectId, payload),
    onSuccess: afterFreeze,
  });
  const bind = useMutation({
    mutationFn: ({
      record,
      source,
    }: {
      record: StudyDesignRecord;
      source: StudyDesignSource;
    }) =>
      bindStudyDesign(projectId, record.id, {
        ...source,
        design_sha256: record.content_sha256,
      }),
    onSuccess: afterFreeze,
  });
  const workflow = useMutation({
    mutationFn: (record: StudyDesignRecord) =>
      saveWorkflowGraph(projectId, {
        graph_id: `study-design-${record.id}`,
        name: `Study design · ${record.snapshot.declaration.title} · r${record.revision}`.slice(
          0,
          120,
        ),
        nodes: [
          { node_id: "project", node_type: "project_source" },
          {
            node_id: "study",
            node_type: "reviewed_study_design",
            parameters: {
              design_revision_id: record.id,
              design_sha256: record.content_sha256,
            },
          },
        ],
        edges: [
          {
            edge_id: "project-study",
            source_node_id: "project",
            source_port_id: "project",
            target_node_id: "study",
            target_port_id: "project",
          },
        ],
      }),
    onSuccess: () =>
      client.invalidateQueries({ queryKey: ["workflow-graphs", projectId] }),
  });

  function open(id: string) {
    setSelected(id);
    bind.reset();
    workflow.reset();
  }
  const error = [
    list.error,
    evidence.error,
    detail.error,
    freeze.error,
    bind.error,
    workflow.error,
  ].filter((item) => item != null);

  return (
    <section aria-label="Study design">
      <h3>Study design</h3>
      <p>
        Freeze reviewed assignments, repeated visits and the analysis plan.
        Check the independence and field assumptions with your study team.
      </p>
      {error.map((item, index) => (
        <p key={index} role="alert">
          {item.message}
        </p>
      ))}
      <DesignForm
        key={parent?.id ?? "new"}
        identities={identities}
        sources={evidence.data ?? []}
        parent={parent}
        saving={freeze.isPending}
        onSave={freeze.mutate}
        onCancel={() => setParent(null)}
      />
      <h4>Frozen study revisions</h4>
      {list.isPending && <p role="status">Loading study revisions…</p>}
      {list.data && list.data.total === 0 && (
        <p>No frozen study designs yet.</p>
      )}
      <ul>
        {list.data?.items.map((record) => (
          <li key={record.id}>
            {record.snapshot.declaration.title} · Revision {record.revision}
            <button
              className="secondary"
              type="button"
              aria-label={`Open ${record.snapshot.declaration.title} revision ${record.revision}`}
              aria-current={record.id === selected ? "true" : undefined}
              onClick={() => open(record.id)}
            >
              Open
            </button>
          </li>
        ))}
      </ul>
      {list.data && list.data.total > 20 && (
        <div className="button-row">
          <button
            type="button"
            disabled={page === 1}
            onClick={() => setPage(page - 1)}
          >
            Previous
          </button>
          <span>Page {page}</span>
          <button
            type="button"
            disabled={page * 20 >= list.data.total}
            onClick={() => setPage(page + 1)}
          >
            Next
          </button>
        </div>
      )}
      {detail.data && (
        <DesignReceipt
          key={detail.data.id}
          record={detail.data}
          sources={evidence.data ?? []}
          saving={bind.isPending || workflow.isPending}
          onRevise={() => setParent(detail.data)}
          onBind={(source) => bind.mutate({ record: detail.data, source })}
          onSaveGraph={() => workflow.mutate(detail.data)}
        />
      )}
      {workflow.isSuccess && (
        <p role="status">
          Study workflow saved. Open Workflow builder to replay this revision.
        </p>
      )}
    </section>
  );
}
