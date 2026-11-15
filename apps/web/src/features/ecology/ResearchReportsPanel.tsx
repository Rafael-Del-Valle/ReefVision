import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { request } from "../../api/client";
import { getApiBaseUrl } from "../../runtime";
import {
  listStaticComparisons,
  staticLineageLabels,
} from "../video/staticComparisonApi";
import { listEcologyAnalyses } from "./ecologyAnalysisApi";
import { listEventSummaries } from "./EventSummaryPanel";

type SourceKind =
  "ecology" | "event_summary" | "comparison" | "static_comparison";
type FigureKind =
  | "trajectory"
  | "group_summary"
  | "treatment_summary"
  | "sample_coverage"
  | "event_rate"
  | "identity_scatter"
  | "bland_altman";
type Source = { id: string; label: string; figures: FigureKind[] };
const labels: Record<FigureKind, string> = {
  trajectory: "Longitudinal trajectory",
  group_summary: "Independent-unit group summary",
  treatment_summary: "Growth by reviewed treatment",
  sample_coverage: "Sampling coverage and missingness",
  event_rate: "Confirmed biological event rate",
  identity_scatter: "Reference–model identity scatter",
  bland_altman: "Bland–Altman plot",
};

interface Report {
  id: string;
  content_sha256: string;
  stale: boolean;
  snapshot: {
    configuration: { title: string; figure: FigureKind };
    method: string;
    software_version: string;
    source_sha256: string;
    source_evidence: string;
    x_label: string;
    y_label: string;
    uncertainty: string | null;
    exclusions: string[];
    limitations: string[];
    provenance: Record<string, string>;
    series: {
      label: string;
      points: {
        label: string;
        x: number;
        y: number;
        denominator: number | null;
      }[];
    }[];
  };
}

export function ResearchReportsPanel({ projectId }: { projectId: string }) {
  const base = `/projects/${projectId}/research-reports`;
  const cache = useQueryClient();
  const [kind, setKind] = useState<SourceKind>("ecology");
  const [sourceId, selectSource] = useState("");
  const [figure, setFigure] = useState<FigureKind | "">("");
  const [title, setTitle] = useState("");
  const [style, setStyle] = useState("grayscale");
  const [selected, setSelected] = useState("");
  const [offset, setOffset] = useState(0);
  const sources = useQuery({
    queryKey: ["research-report-sources", projectId, kind, offset],
    queryFn: async ({ signal }): Promise<Source[]> => {
      if (kind === "ecology") {
        const data = await listEcologyAnalyses(
          projectId,
          offset / 20 + 1,
          signal,
        );
        return data.items.map((row) => ({
          id: row.id,
          label: `${row.snapshot.result.kind === "growth" ? "Reviewed growth" : "Reviewed abundance"} · ${row.snapshot.reviewed_by} · ${row.id.slice(0, 8)}`,
          figures:
            row.snapshot.result.kind === "growth"
              ? [
                  "trajectory",
                  "group_summary",
                  "treatment_summary",
                  ...(row.snapshot.result.planned_sampling_effort?.length
                    ? (["sample_coverage"] as const)
                    : []),
                ]
              : ["sample_coverage"],
        }));
      }
      if (kind === "event_summary") {
        const data = await request<
          Awaited<ReturnType<typeof listEventSummaries>>
        >(
          `/projects/${projectId}/ecology/event-summaries?limit=20&offset=${offset}`,
          { signal },
        );
        return data.items.map((row) => ({
          id: row.id,
          label: row.snapshot.selection.name,
          figures: ["event_rate"],
        }));
      }
      if (kind === "static_comparison") {
        const data = await listStaticComparisons(
          projectId,
          20,
          offset,
          signal,
          true,
        );
        return data
          .filter((row) => row.status === "succeeded")
          .map((row) => ({
            id: row.id,
            label: [
              row.reference_name,
              row.model_names.join(" / "),
              row.evaluation_status &&
                staticLineageLabels[row.evaluation_status],
            ]
              .filter(Boolean)
              .join(" · "),
            figures: ["identity_scatter", "bland_altman"],
          }));
      }
      const data = await request<
        {
          id: string;
          stale: boolean;
          snapshot: { options: { name: string } };
        }[]
      >(
        `/projects/${projectId}/scientific-comparisons?limit=20&offset=${offset}`,
        { signal },
      );
      return data.map((row) => ({
        id: row.id,
        label: row.snapshot.options.name + (row.stale ? " (historical)" : ""),
        figures: ["identity_scatter", "bland_altman"],
      }));
    },
  });
  const saved = useQuery({
    queryKey: ["research-reports", projectId],
    queryFn: ({ signal }) => request<Report[]>(base, { signal }),
  });
  const selectedReport = useQuery({
    queryKey: ["research-report", projectId, selected],
    queryFn: ({ signal }) => request<Report>(`${base}/${selected}`, { signal }),
    enabled: !!selected,
  });
  const create = useMutation({
    mutationFn: () =>
      request<Report>(base, {
        method: "POST",
        body: JSON.stringify({
          source_kind: kind,
          source_id: sourceId,
          figure,
          title,
          style,
        }),
      }),
    onSuccess: (item) => {
      cache.setQueryData(["research-report", projectId, item.id], item);
      setSelected(item.id);
      void cache.invalidateQueries({
        queryKey: ["research-reports", projectId],
      });
    },
  });
  const options =
    sources.data?.find((item) => item.id === sourceId)?.figures ?? [];
  const report = selectedReport.data;
  const downloads = report && `${getApiBaseUrl()}${base}/${report.id}`;
  return (
    <section
      className="panel-card"
      aria-label="Publication figures and research reports"
    >
      <h3>Research reports</h3>
      <p>
        Build a publication figure from a saved analysis. Each export includes
        the selected method, evidence checksum, and excluded records.
      </p>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          create.mutate();
        }}
      >
        <label>
          Source type
          <select
            value={kind}
            onChange={(event) => {
              setKind(event.target.value as SourceKind);
              setOffset(0);
              selectSource("");
              setFigure("");
            }}
          >
            <option value="ecology">Reviewed ecological analysis</option>
            <option value="event_summary">Reviewed event summary</option>
            <option value="comparison">Held-out human–model comparison</option>
            <option value="static_comparison">
              Static-image human–model comparison
            </option>
          </select>
        </label>
        <label>
          Saved source
          <select
            required
            value={sourceId}
            onChange={(event) => {
              selectSource(event.target.value);
              setFigure(
                sources.data?.find((item) => item.id === event.target.value)
                  ?.figures[0] ?? "",
              );
            }}
          >
            <option value="">Choose a saved source</option>
            {sources.data?.map((item) => (
              <option key={item.id} value={item.id}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
        {offset > 0 && (
          <button
            type="button"
            onClick={() => {
              setOffset(offset - 20);
              selectSource("");
              setFigure("");
            }}
          >
            Previous sources
          </button>
        )}
        {(sources.data?.length ?? 0) === 20 && (
          <button
            type="button"
            onClick={() => {
              setOffset(offset + 20);
              selectSource("");
              setFigure("");
            }}
          >
            More sources
          </button>
        )}
        {sources.isPending && (
          <p role="status">Loading saved source evidence…</p>
        )}
        {sources.data?.length === 0 && (
          <p>
            Save a reviewed result in the corresponding workspace before
            creating a figure.
          </p>
        )}
        <label>
          Figure
          <select
            required
            value={figure}
            onChange={(event) => setFigure(event.target.value as FigureKind)}
          >
            <option value="">Choose a figure</option>
            {options.map((item) => (
              <option key={item} value={item}>
                {labels[item]}
              </option>
            ))}
          </select>
        </label>
        <label>
          Figure title
          <input
            required
            maxLength={120}
            value={title}
            onChange={(event) => setTitle(event.target.value)}
          />
        </label>
        <label>
          Figure style
          <select
            value={style}
            onChange={(event) => setStyle(event.target.value)}
          >
            <option value="grayscale">Grayscale-safe</option>
            <option value="accessible_color">Accessible color</option>
          </select>
        </label>
        <button
          type="submit"
          disabled={!sourceId || !figure || !title.trim() || create.isPending}
        >
          Save research figure
        </button>
      </form>
      <label>
        Saved reports
        <select
          value={selected}
          onChange={(event) => setSelected(event.target.value)}
        >
          <option value="">Choose a saved report</option>
          {saved.data?.map((item) => (
            <option key={item.id} value={item.id}>
              {item.snapshot.configuration.title}
            </option>
          ))}
        </select>
      </label>
      {[sources.error, saved.error, selectedReport.error, create.error]
        .filter(Boolean)
        .map((error, index) => (
          <p role="alert" key={index}>
            {error?.message}
          </p>
        ))}
      {selectedReport.isFetching && (
        <p role="status">Checking source freshness…</p>
      )}
      {report && downloads && (
        <article>
          <h4>{report.snapshot.configuration.title}</h4>
          {report.stale && (
            <p role="alert">
              The source evidence has changed. This figure preserves the
              historical result.
            </p>
          )}
          <p>
            Evidence: {report.snapshot.source_evidence} ·{" "}
            {report.snapshot.uncertainty ?? "Descriptive values"}
          </p>
          <img
            src={`${downloads}/figure.svg`}
            alt={`${report.snapshot.configuration.title}. ${report.snapshot.y_label} by ${report.snapshot.x_label}.`}
            style={{ width: "100%", height: "auto", background: "white" }}
          />
          <div className="button-row">
            <a
              href={`${downloads}/figure.svg`}
              download="reefvision-figure.svg"
            >
              Download SVG
            </a>
            <a href={`${downloads}/table.csv`} download>
              Download CSV
            </a>
            <a href={downloads} download="reefvision-research-methods.json">
              Download methods and provenance
            </a>
          </div>
          <details>
            <summary>Data and method details</summary>
            <p>
              {report.snapshot.method} · ReefVision{" "}
              {report.snapshot.software_version}
            </p>
            <p>
              Source SHA-256 <code>{report.snapshot.source_sha256}</code>
            </p>
            <dl>
              {Object.entries(report.snapshot.provenance).map(
                ([key, value]) => (
                  <div key={key}>
                    <dt>{key}</dt>
                    <dd>{value}</dd>
                  </div>
                ),
              )}
            </dl>
            <ul>
              {[...report.snapshot.exclusions, ...report.snapshot.limitations]
                .slice(0, 50)
                .map((line, index) => (
                  <li key={index}>{line}</li>
                ))}
            </ul>
            <p>The downloads include the complete table and source metadata.</p>
          </details>
        </article>
      )}
    </section>
  );
}
