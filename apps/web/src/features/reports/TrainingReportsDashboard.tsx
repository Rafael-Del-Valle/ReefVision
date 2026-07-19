import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import type { Project } from "../../api/client";
import {
  createTrainingReport,
  listReportTrainingRuns,
  trainingReportDownloadUrl,
  type TrainingReportPayload,
  type TrainingReportResult,
} from "./api";

interface PerClassMetric {
  scope: string;
  class_id: number;
  class_name: string;
  precision: number | null;
  recall: number | null;
  f1: number | null;
  map50: number | null;
  map50_95: number | null;
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object"
    ? (value as Record<string, unknown>)
    : {};
}

function asRows(runManifest: Record<string, unknown>): PerClassMetric[] {
  const validation = asRecord(runManifest.ultralytics_validation);
  const summary = asRecord(validation.summary);
  const scopes = Array.isArray(summary.scopes) ? summary.scopes : [];
  const rows: PerClassMetric[] = [];
  scopes.forEach((scopeValue) => {
    const scope = asRecord(scopeValue);
    const scopeName = typeof scope.scope === "string" ? scope.scope : "model";
    const perClass = Array.isArray(scope.per_class) ? scope.per_class : [];
    perClass.forEach((rowValue) => {
      const row = asRecord(rowValue);
      rows.push({
        scope: scopeName,
        class_id: typeof row.class_id === "number" ? row.class_id : rows.length,
        class_name:
          typeof row.class_name === "string"
            ? row.class_name
            : `Class ${rows.length}`,
        precision: typeof row.precision === "number" ? row.precision : null,
        recall: typeof row.recall === "number" ? row.recall : null,
        f1: typeof row.f1 === "number" ? row.f1 : null,
        map50: typeof row.map50 === "number" ? row.map50 : null,
        map50_95: typeof row.map50_95 === "number" ? row.map50_95 : null,
      });
    });
  });
  return rows;
}

function metric(value: number | null): string {
  return value === null ? "—" : value.toFixed(4);
}

const fonts = [
  "system",
  "sans-serif",
  "serif",
  "monospace",
  "Arial",
  "Aptos",
  "Calibri",
  "Georgia",
  "Helvetica",
  "Times New Roman",
];

export function TrainingReportsDashboard({ project }: { project: Project }) {
  const [selectedRunId, setSelectedRunId] = useState("");
  const [title, setTitle] = useState("");
  const [subtitle, setSubtitle] = useState("");
  const [fontFamily, setFontFamily] = useState("system");
  const [baseFontSize, setBaseFontSize] = useState(10.5);
  const [headingFontSize, setHeadingFontSize] = useState(18);
  const [tableFontSize, setTableFontSize] = useState(9);
  const [figureFontSize, setFigureFontSize] = useState(9);
  const [includeHistory, setIncludeHistory] = useState(true);
  const [includePerClass, setIncludePerClass] = useState(true);
  const [includeConfusion, setIncludeConfusion] = useState(true);
  const [includePlots, setIncludePlots] = useState(true);
  const [includeTuning, setIncludeTuning] = useState(true);
  const [includeProvenance, setIncludeProvenance] = useState(true);
  const [lastReport, setLastReport] = useState<TrainingReportResult | null>(null);

  const runs = useQuery({
    queryKey: ["training_report_runs", project.id],
    queryFn: ({ signal }) => listReportTrainingRuns(project.id, signal),
    refetchInterval: 3000,
  });
  const completedRuns = useMemo(
    () =>
      (runs.data ?? []).filter(
        (run) => run.status === "completed" || run.status === "succeeded",
      ),
    [runs.data],
  );
  const selectedRun =
    completedRuns.find((run) => run.id === selectedRunId) ?? null;
  const perClassRows = useMemo(
    () => asRows(selectedRun?.artifact_manifest_json ?? {}),
    [selectedRun?.artifact_manifest_json],
  );
  const tuning = asRecord(selectedRun?.artifact_manifest_json.tuning);

  useEffect(() => {
    if (!selectedRunId && completedRuns.length > 0) {
      setSelectedRunId(completedRuns[0].id);
    }
  }, [completedRuns, selectedRunId]);

  const reportMutation = useMutation({
    mutationFn: () => {
      if (!selectedRun) throw new Error("Choose a completed training run");
      const payload: TrainingReportPayload = {
        title: title.trim() || undefined,
        subtitle: subtitle.trim() || undefined,
        font_family: fontFamily,
        base_font_size_pt: baseFontSize,
        heading_font_size_pt: headingFontSize,
        table_font_size_pt: tableFontSize,
        figure_label_font_size_pt: figureFontSize,
        include_training_history: includeHistory,
        include_per_class_metrics: includePerClass,
        include_confusion_matrix: includeConfusion,
        include_ultralytics_plots: includePlots,
        include_tuning_analysis: includeTuning,
        include_provenance: includeProvenance,
      };
      return createTrainingReport(selectedRun.id, payload);
    },
    onSuccess: setLastReport,
  });

  return (
    <section className="dashboard-panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Model development</p>
          <h3>Training reports</h3>
          <span>
            CoralNet-style class metrics, Ultralytics plots, tuning analysis, and
            configurable report typography.
          </span>
        </div>
        <span>{completedRuns.length} completed runs</span>
      </div>

      <div className="dashboard-layout">
        <div className="dashboard-sidebar">
          <article className="dashboard-card">
            <h4>Report source</h4>
            <label>
              Completed run
              <select
                value={selectedRunId}
                onChange={(event) => {
                  setSelectedRunId(event.target.value);
                  setLastReport(null);
                }}
              >
                <option value="">Choose a run</option>
                {completedRuns.map((run) => (
                  <option key={run.id} value={run.id}>
                    {run.run_name} · {run.task}
                  </option>
                ))}
              </select>
            </label>
            {runs.isPending && <p>Loading runs...</p>}
            {runs.error && <p className="form-error">{runs.error.message}</p>}
            {selectedRun && (
              <div className="annotation-selection-list">
                <div className="annotation-selection-row">
                  <strong>Architecture</strong>
                  <span>{selectedRun.architecture}</span>
                </div>
                <div className="annotation-selection-row">
                  <strong>Provider</strong>
                  <span>{selectedRun.provider_id}</span>
                </div>
                <div className="annotation-selection-row">
                  <strong>Class rows</strong>
                  <span>{perClassRows.length}</span>
                </div>
                <div className="annotation-selection-row">
                  <strong>Tuning trials</strong>
                  <span>
                    {typeof tuning.trial_count === "number"
                      ? tuning.trial_count
                      : "None"}
                  </span>
                </div>
              </div>
            )}
          </article>

          <article className="dashboard-card">
            <h4>Typography</h4>
            <label>
              Font family
              <select
                aria-label="Report font family"
                value={fontFamily}
                onChange={(event) => setFontFamily(event.target.value)}
              >
                {fonts.map((font) => (
                  <option key={font} value={font}>
                    {font}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Body font: {baseFontSize} pt
              <input
                type="range"
                min="7"
                max="24"
                step="0.5"
                value={baseFontSize}
                onChange={(event) => setBaseFontSize(Number(event.target.value))}
              />
            </label>
            <label>
              Heading font: {headingFontSize} pt
              <input
                type="range"
                min="10"
                max="48"
                step="1"
                value={headingFontSize}
                onChange={(event) =>
                  setHeadingFontSize(Number(event.target.value))
                }
              />
            </label>
            <label>
              Table font: {tableFontSize} pt
              <input
                type="range"
                min="6"
                max="20"
                step="0.5"
                value={tableFontSize}
                onChange={(event) => setTableFontSize(Number(event.target.value))}
              />
            </label>
            <label>
              Figure labels: {figureFontSize} pt
              <input
                type="range"
                min="6"
                max="20"
                step="0.5"
                value={figureFontSize}
                onChange={(event) => setFigureFontSize(Number(event.target.value))}
              />
            </label>
          </article>
        </div>

        <div className="dashboard-main">
          <article className="dashboard-card">
            <h4>Report content</h4>
            <label>
              Title
              <input
                value={title}
                placeholder={selectedRun ? `${selectedRun.run_name} training report` : ""}
                onChange={(event) => setTitle(event.target.value)}
              />
            </label>
            <label>
              Subtitle
              <input
                value={subtitle}
                placeholder={project.name}
                onChange={(event) => setSubtitle(event.target.value)}
              />
            </label>
            <div className="version-status-grid">
              {[
                ["Training history", includeHistory, setIncludeHistory],
                ["Per-class metrics", includePerClass, setIncludePerClass],
                ["Confusion matrix", includeConfusion, setIncludeConfusion],
                ["Ultralytics plots", includePlots, setIncludePlots],
                ["Tuning analysis", includeTuning, setIncludeTuning],
                ["Provenance", includeProvenance, setIncludeProvenance],
              ].map(([label, checked, setter]) => (
                <label key={String(label)} className="toggle-row">
                  <input
                    type="checkbox"
                    checked={Boolean(checked)}
                    onChange={(event) =>
                      (setter as (value: boolean) => void)(event.target.checked)
                    }
                  />
                  {String(label)}
                </label>
              ))}
            </div>
            <button
              type="button"
              disabled={!selectedRun || reportMutation.isPending}
              onClick={() => reportMutation.mutate()}
            >
              {reportMutation.isPending ? "Generating..." : "Generate HTML report"}
            </button>
            {reportMutation.error && (
              <p className="form-error">{reportMutation.error.message}</p>
            )}
            {lastReport && (
              <div className="editor-message">
                <strong>{lastReport.title}</strong>
                <p>{lastReport.included_sections.join(" · ")}</p>
                <a
                  href={trainingReportDownloadUrl(lastReport)}
                  target="_blank"
                  rel="noreferrer"
                >
                  Open generated report
                </a>
                {lastReport.warnings.map((warning) => (
                  <p key={warning}>{warning}</p>
                ))}
              </div>
            )}
          </article>

          <article className="dashboard-card">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Ultralytics validation</p>
                <h4>Per-class precision, recall, and F1</h4>
              </div>
              <span>{perClassRows.length} rows</span>
            </div>
            {perClassRows.length === 0 ? (
              <p>
                Complete a new detection or segmentation run to generate the
                explicit class-wise validation artifact.
              </p>
            ) : (
              <div style={{ overflowX: "auto" }}>
                <table>
                  <thead>
                    <tr>
                      <th>Scope</th>
                      <th>Class</th>
                      <th>Precision</th>
                      <th>Recall</th>
                      <th>F1</th>
                      <th>mAP50</th>
                      <th>mAP50–95</th>
                    </tr>
                  </thead>
                  <tbody>
                    {perClassRows.map((row) => (
                      <tr key={`${row.scope}-${row.class_id}`}>
                        <td>{row.scope}</td>
                        <td>{row.class_name}</td>
                        <td>{metric(row.precision)}</td>
                        <td>{metric(row.recall)}</td>
                        <td>{metric(row.f1)}</td>
                        <td>{metric(row.map50)}</td>
                        <td>{metric(row.map50_95)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </article>

          {Object.keys(tuning).length > 0 && (
            <article className="dashboard-card">
              <h4>Hyperparameter tuning</h4>
              <p>
                Best fitness: {typeof tuning.best_fitness === "number"
                  ? tuning.best_fitness.toFixed(5)
                  : "Unavailable"}
              </p>
              <pre>{JSON.stringify(tuning.best_parameters ?? {}, null, 2)}</pre>
            </article>
          )}
        </div>
      </div>
    </section>
  );
}
