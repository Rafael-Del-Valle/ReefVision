import { useState } from "react";
import { saveWorkflowGraph } from "../workflow-graphs/workflowGraphApi";
import {
  agreementExportUrl,
  displayError,
  values,
  valueLabels,
  type LabDecision,
  type LabReport,
} from "./reviewerLabApi";

export function AgreementReport({
  projectId,
  reportId,
  report,
  onOpenWorkflow,
}: {
  projectId: string;
  reportId: string;
  report: LabReport;
  onOpenWorkflow: () => void;
}) {
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const result = report.agreement;
  const roleNames = new Map(
    report.role_revisions.map((item) => [item.id, item]),
  );
  const describe = (item: LabDecision): string => {
    const owner = roleNames.get(item.role_revision_id);
    return (
      valueLabels[item.value] +
      " · " +
      item.reason +
      (owner
        ? " · " + owner.name + " (role revision " + owner.revision + ")"
        : "")
    );
  };

  async function save() {
    setSaving(true);
    setError("");
    try {
      await saveWorkflowGraph(projectId, {
        graph_id: "reviewer-agreement-" + reportId,
        name: "Reviewer agreement · " + report.plan.title,
        nodes: [
          {
            node_id: "project",
            node_type: "project_source",
            name: "Project",
            parameters: {},
          },
          {
            node_id: "agreement",
            node_type: "reviewer_lab_agreement_report",
            name: "Reviewer Lab agreement",
            parameters: { report_id: reportId },
          },
        ],
        edges: [
          {
            edge_id: "project-agreement",
            source_node_id: "project",
            source_port_id: "project",
            target_node_id: "agreement",
            target_port_id: "project",
          },
        ],
      });
      setSaved(true);
    } catch (reason) {
      setError(displayError(reason));
    } finally {
      setSaving(false);
    }
  }

  return (
    <section aria-label="Sealed reviewer agreement" className="panel-card">
      <h3>{report.plan.title} agreement</h3>
      <p>{report.plan.criterion}</p>
      <p>
        Local role attribution. Independent scientific authority requires
        external verification.
      </p>
      <dl>
        <dt>Paired reviews</dt>
        <dd>
          {result.paired_subjects} of {result.planned_subjects} planned sources
        </dd>
        <dt>Observed agreement</dt>
        <dd>
          {result.agreements} of {result.paired_subjects} pairs (
          {Math.round(result.observed_agreement * 100)}%)
        </dd>
        <dt>Disagreement</dt>
        <dd>
          {result.disagreements} pairs, {result.adjudicated_disagreements}{" "}
          adjudicated
        </dd>
        <dt>Cohen’s kappa</dt>
        <dd>
          {result.cohens_kappa === null
            ? "Undefined for these category marginals"
            : result.cohens_kappa.toFixed(3)}
        </dd>
        <dt>Report SHA-256</dt>
        <dd>
          <code className="reviewer-lab-digest">{report.content_sha256}</code>
        </dd>
      </dl>
      <details>
        <summary>Agreement table and decisions</summary>
        <table>
          <caption>Independent decisions before adjudication</caption>
          <thead>
            <tr>
              <th scope="col">First reviewer</th>
              {values.map((item) => (
                <th key={item} scope="col">
                  Second reviewer · {valueLabels[item]}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {values.map((first) => (
              <tr key={first}>
                <th scope="row">{valueLabels[first]}</th>
                {values.map((second) => (
                  <td key={second}>{result.matrix[first][second]}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        <ul>
          {report.subjects.map((item) => (
            <li key={item.source.id}>
              <strong>{item.source.filename}</strong>
              <ul>
                <li>{describe(item.first)}</li>
                <li>{describe(item.second)}</li>
                {item.resolution && (
                  <li>Adjudication · {describe(item.resolution)}</li>
                )}
              </ul>
            </li>
          ))}
        </ul>
      </details>
      <div className="button-row">
        <a href={agreementExportUrl(projectId, reportId)} download>
          Download agreement JSON
        </a>
        <button
          type="button"
          disabled={saving || saved}
          onClick={() => void save()}
        >
          Save agreement workflow
        </button>
        {saved && (
          <button type="button" onClick={onOpenWorkflow}>
            Open Workflow Builder
          </button>
        )}
      </div>
      {saved && <p role="status">Agreement workflow saved.</p>}
      {error && <p role="alert">{error}</p>}
    </section>
  );
}
