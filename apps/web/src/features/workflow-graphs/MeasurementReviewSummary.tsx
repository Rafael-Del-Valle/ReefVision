import type { WorkflowArtifact, WorkflowNodeRun } from "./workflowGraphApi";

export function measurementReviewInput(
  node: WorkflowNodeRun,
  artifacts: WorkflowArtifact[],
) {
  const inputs = artifacts.filter(
    (artifact) =>
      artifact.data_type === "scientific_record_collection" &&
      node.input_artifact_ids_json.includes(artifact.id),
  );
  return inputs.length === 1 ? inputs[0] : undefined;
}

export function MeasurementReviewSummary({
  artifact,
}: {
  artifact?: WorkflowArtifact;
}) {
  if (!artifact)
    return <p role="alert">The saved measurement to review is unavailable.</p>;

  const { quantity, value, unit, qc, plugin } = artifact.payload_json;
  const source =
    plugin && typeof plugin === "object" && !Array.isArray(plugin)
      ? (plugin as Record<string, unknown>)
      : undefined;

  return (
    <section
      aria-label="Measurement to review"
      className="workflow-provenance-summary"
    >
      <h6>Measurement to review</h6>
      {typeof quantity === "string" &&
      typeof value === "number" &&
      Number.isFinite(value) &&
      typeof unit === "string" ? (
        <dl>
          <div>
            <dt>Quantity</dt>
            <dd>{quantity}</dd>
          </div>
          <div>
            <dt>Value</dt>
            <dd>
              {value} {unit}
            </dd>
          </div>
          {typeof source?.image_sha256 === "string" && (
            <div>
              <dt>Original image SHA-256</dt>
              <dd>
                <code>{source.image_sha256}</code>
              </dd>
            </div>
          )}
          {typeof source?.package_sha256 === "string" && (
            <div>
              <dt>Plugin package SHA-256</dt>
              <dd>
                <code>{source.package_sha256}</code>
              </dd>
            </div>
          )}
        </dl>
      ) : (
        <p>
          Open the saved scientific record collection in Artifacts to inspect
          its contents.
        </p>
      )}
      <p>Resuming acknowledges this evidence for the current run.</p>
      {qc === "unassessed" && <p>Scientific QC remains unassessed.</p>}
    </section>
  );
}
