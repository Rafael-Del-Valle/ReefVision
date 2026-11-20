import {
  skipToken,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { saveWorkflowGraph } from "../workflow-graphs/workflowGraphApi";
import type { EcologyAnalysis } from "./ecologyAnalysisApi";
import {
  emptyPairedGrowthDraft,
  PairedGrowthFields,
  pairedDesignReady,
  pairedVisitDates,
} from "./PairedGrowthFields";
import {
  calculatePairedContrast,
  downloadPairedReport,
  type PairedGrowthReport,
  type PairedGrowthRequest,
} from "./pairedGrowthContrastApi";

function formatMeasurement(value: number | null, unit: string | null) {
  return value == null
    ? "Unavailable"
    : `${Number(value.toPrecision(6))}${unit ? " " + unit : ""}`;
}

function PairedResults({ report }: { report: PairedGrowthReport }) {
  const interval = report.confidence_interval_95;
  const intervalNotes = {
    available: "Unavailable",
    insufficient_complete_units:
      "At least two complete independent units are required.",
    zero_between_unit_variation: "All included units have the same difference.",
    statistics_runtime_unavailable:
      "The local statistics runtime is unavailable.",
    precision_unavailable:
      "The interval exceeds the supported numerical precision.",
  };
  return (
    <section aria-label="Paired contrast result">
      <h4>Paired contrast result</h4>
      <p>{report.design.estimand}</p>
      <p>
        {report.included_unit_count} of {report.planned_unit_count} planned
        independent units included
      </p>
      <dl>
        <dt>Mean within-unit change</dt>
        <dd>{formatMeasurement(report.mean_difference, report.unit)}</dd>
        <dt>Standard error</dt>
        <dd>{formatMeasurement(report.standard_error, report.unit)}</dd>
        <dt>Degrees of freedom</dt>
        <dd>{report.degrees_of_freedom ?? "Unavailable"}</dd>
        <dt>95% confidence interval</dt>
        <dd>
          {interval
            ? `${formatMeasurement(interval[0], report.unit)} to ${formatMeasurement(interval[1], report.unit)}`
            : intervalNotes[report.interval_status]}
        </dd>
      </dl>
      <table>
        <caption>Independent unit differences</caption>
        <thead>
          <tr>
            <th scope="col">Unit</th>
            <th scope="col">Matched organisms</th>
            <th scope="col">Change</th>
            <th scope="col">Inclusion</th>
          </tr>
        </thead>
        <tbody>
          {report.units.map((row) => (
            <tr key={row.experimental_unit_id}>
              <th scope="row">{row.experimental_unit_id}</th>
              <td>
                {
                  row.organisms.filter(
                    (organism) => organism.difference != null,
                  ).length
                }
              </td>
              <td>{formatMeasurement(row.difference, report.unit)}</td>
              <td>{row.reason || row.status}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <details>
        <summary>Assumptions and source evidence</summary>
        <ul>
          {report.assumptions.map((text) => (
            <li key={text}>{text}</li>
          ))}
        </ul>
        <p>
          Method reference{" "}
          <a href="https://www.itl.nist.gov/div898/handbook/prc/section3/prc311.htm">
            NIST paired observations
          </a>
        </p>
        <p>
          Reviewed analysis <code>{report.analysis_id}</code>
        </p>
        <p>
          Source SHA-256 <code>{report.source_sha256}</code>
        </p>
        <p>
          Report SHA-256 <code>{report.report_sha256}</code>
        </p>
        {report.source_exclusions.map((row) => (
          <p key={`${row.source}:${row.reason}`}>
            {row.source} · {row.reason}
          </p>
        ))}
      </details>
      <button
        type="button"
        onClick={() => downloadPairedReport(report, report.report_sha256)}
      >
        Download paired result JSON
      </button>
    </section>
  );
}

export function PairedGrowthContrast({
  projectId,
  analysis,
}: {
  projectId: string;
  analysis: EcologyAnalysis;
}) {
  const client = useQueryClient();
  const [draft, setDraft] = useState(emptyPairedGrowthDraft);
  const [declaration, setDeclaration] = useState<PairedGrowthRequest | null>(
    null,
  );
  const { selection } = analysis.snapshot;
  const dates = pairedVisitDates(analysis);
  const ready = !analysis.stale && pairedDesignReady(draft);

  const result = useQuery({
    queryKey: ["paired-growth-contrast", projectId, analysis.id, declaration],
    queryFn:
      declaration && !analysis.stale
        ? ({ signal }) =>
            calculatePairedContrast(projectId, analysis.id, declaration, signal)
        : skipToken,
    retry: false,
  });
  const save = useMutation({
    mutationFn: (report: PairedGrowthReport) =>
      saveWorkflowGraph(projectId, {
        graph_id: `paired-growth-${report.report_sha256}`,
        name: `Paired growth · ${report.design.baseline_date} to ${report.design.followup_date} · ${report.design.experimental_unit_type}`.slice(
          0,
          120,
        ),
        nodes: [
          { node_id: "project", node_type: "project_source" },
          {
            node_id: "paired",
            node_type: "paired_growth_contrast",
            parameters: {
              analysis_id: report.analysis_id,
              source_sha256: report.source_sha256,
              ...report.design,
            },
          },
        ],
        edges: [
          {
            edge_id: "project-paired",
            source_node_id: "project",
            source_port_id: "project",
            target_node_id: "paired",
            target_port_id: "project",
          },
        ],
      }),
    onSuccess: () =>
      client.invalidateQueries({ queryKey: ["workflow-graphs", projectId] }),
  });

  function calculate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (ready)
      setDeclaration({
        source_sha256: analysis.content_sha256,
        ...draft,
        experimental_unit_type: draft.experimental_unit_type.trim(),
        estimand: draft.estimand.trim(),
        missingness_policy: "complete_unit",
      });
  }

  if (selection.kind !== "growth") return null;
  const report = declaration && !analysis.stale ? result.data : undefined;
  const saved =
    save.variables &&
    save.variables.report_sha256 === report?.report_sha256 &&
    save.isSuccess;
  return (
    <details>
      <summary>Repeated measures</summary>
      {analysis.stale ? (
        <p>
          Recalculate the stale growth analysis before selecting a paired
          contrast.
        </p>
      ) : dates.length < 2 ? (
        <p>
          Save a growth analysis with a sampling plan that includes two shared
          UTC visit dates for every independent unit.
        </p>
      ) : (
        <form
          aria-label="Declare paired growth contrast"
          onSubmit={calculate}
          onChange={() => setDeclaration(null)}
        >
          <PairedGrowthFields dates={dates} value={draft} onChange={setDraft} />
          <button disabled={!ready || result.isFetching}>
            Calculate paired contrast
          </button>
        </form>
      )}
      {declaration && result.isFetching && (
        <p role="status">Calculating paired contrast…</p>
      )}
      {declaration && result.error && (
        <p role="alert">{result.error.message}</p>
      )}
      {report && (
        <>
          <PairedResults report={report} />
          <button
            type="button"
            onClick={() => save.mutate(report)}
            disabled={save.isPending || Boolean(saved)}
          >
            Save paired workflow
          </button>
          {saved && (
            <p role="status">Saved in Workflow builder as {save.data.name}.</p>
          )}
          {save.isError &&
            save.variables?.report_sha256 === report.report_sha256 && (
              <p role="alert">{save.error.message}</p>
            )}
        </>
      )}
    </details>
  );
}
