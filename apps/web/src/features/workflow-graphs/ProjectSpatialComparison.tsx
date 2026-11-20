import { useRef, useState } from "react";

import { request } from "../../api/client";
import {
  ScientificNodeControls,
  scientificConfigurationIssue,
} from "./ScientificNodeControls";
import {
  saveWorkflowGraph,
  type MeshPreviewCalibration,
  type SpatialSourceAsset,
  type WorkflowGraphRecord,
} from "./workflowGraphApi";

type Parameters = Record<string, unknown>;
type Review = {
  registration_evidence?: Parameters;
  reidentification_evidence?: Parameters;
};
type Pair = { before: Parameters; after: Parameters };

interface ComparisonResult {
  before_surface_area_m2: number;
  after_surface_area_m2: number;
  delta_surface_area_m2: number | null;
  delta_surface_area_scale_interval_m2: [number, number] | null;
  registered_surface_centroid_separation_m: number | null;
  registered_surface_centroid_separation_caller_bound_interval_m:
    [number, number] | null;
  qc_warnings: string[];
}

function comparisonGraph(id: string, pair: Pair, review: Review) {
  const slots = ["before", "after"] as const;
  return {
    graph_id: id,
    name: `3D comparison · ${pair.before.observation_id} to ${pair.after.observation_id}`.slice(
      0,
      200,
    ),
    nodes: [
      {
        node_id: "project",
        node_type: "project_source",
        position: { x: 40, y: 120 },
      },
      ...slots.map((slot, index) => ({
        node_id: slot,
        node_type: "mesh_surface_preview",
        parameters: pair[slot],
        position: { x: 340, y: 50 + index * 200 },
      })),
      {
        node_id: "compare",
        node_type: "mesh_longitudinal_comparison",
        parameters: review,
        position: { x: 680, y: 120 },
      },
    ],
    edges: slots.flatMap((slot) => [
      {
        edge_id: `project-${slot}`,
        source_node_id: "project",
        source_port_id: "project",
        target_node_id: slot,
        target_port_id: "project",
      },
      {
        edge_id: `${slot}-compare`,
        source_node_id: slot,
        source_port_id: "measurement",
        target_node_id: "compare",
        target_port_id: slot,
      },
    ]),
  };
}

function bindReview(
  projectId: string,
  { before, after }: Pair,
  review: Review,
): Review {
  const bound: Review = {};
  if (review.registration_evidence) {
    bound.registration_evidence = {
      project_id: projectId,
      source_frame_id: before.coordinate_frame_id,
      target_frame_id: after.coordinate_frame_id,
      source_observation_id: before.observation_id,
      target_observation_id: after.observation_id,
      source_specimen_id: before.specimen_id,
      target_specimen_id: after.specimen_id,
      source_observed_at_utc: before.observed_at_utc,
      target_observed_at_utc: after.observed_at_utc,
      source_spatial_source_asset_id: before.asset_id,
      target_spatial_source_asset_id: after.asset_id,
      source_payload_sha256: before.expected_source_payload_sha256,
      target_payload_sha256: after.expected_source_payload_sha256,
      source_meters_per_mesh_unit: before.meters_per_unit,
      target_meters_per_mesh_unit: after.meters_per_unit,
      source_calibration_method: before.calibration_method,
      target_calibration_method: after.calibration_method,
      source_calibration_evidence: before.calibration_evidence,
      target_calibration_evidence: after.calibration_evidence,
      ...review.registration_evidence,
    };
    if (
      before.relative_scale_uncertainty != null &&
      after.relative_scale_uncertainty != null
    ) {
      bound.registration_evidence.source_relative_scale_uncertainty =
        before.relative_scale_uncertainty;
      bound.registration_evidence.target_relative_scale_uncertainty =
        after.relative_scale_uncertainty;
    }
  }
  if (review.reidentification_evidence) {
    bound.reidentification_evidence = {
      project_id: projectId,
      specimen_id: before.specimen_id,
      before_observation_id: before.observation_id,
      after_observation_id: after.observation_id,
      before_observed_at_utc: before.observed_at_utc,
      after_observed_at_utc: after.observed_at_utc,
      before_spatial_source_asset_id: before.asset_id,
      after_spatial_source_asset_id: after.asset_id,
      before_source_payload_sha256: before.expected_source_payload_sha256,
      after_source_payload_sha256: after.expected_source_payload_sha256,
      ...review.reidentification_evidence,
    };
  }
  return bound;
}

interface ProjectSpatialComparisonProps {
  projectId: string;
  asset: SpatialSourceAsset;
  calibration?: MeshPreviewCalibration;
  onSaved?: () => void;
}

export function ProjectSpatialComparison(props: ProjectSpatialComparisonProps) {
  const [open, setOpen] = useState(false);
  if (!open)
    return (
      <button type="button" onClick={() => setOpen(true)}>
        Compare two acquisitions
      </button>
    );
  return <ComparisonForm {...props} />;
}

function ComparisonForm({
  projectId,
  asset,
  calibration,
  onSaved,
}: ProjectSpatialComparisonProps) {
  const [id] = useState(() => crypto.randomUUID());
  const [pair, setPair] = useState<Pair>(() => ({
    before: {
      asset_id: asset.id,
      expected_source_payload_sha256: asset.sha256,
      ...calibration,
    },
    after: {},
  }));
  const [review, setReview] = useState<Review>({});
  const [result, setResult] = useState<ComparisonResult | null>(null);
  const [saved, setSaved] = useState<WorkflowGraphRecord | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const version = useRef(0);

  function invalidate() {
    version.current += 1;
    setResult(null);
    setSaved(null);
    setError("");
  }

  function updateObservation(slot: keyof Pair, parameters: Parameters) {
    invalidate();
    setPair({ ...pair, [slot]: parameters });
    setReview({});
  }

  const issue =
    !pair.before.asset_id || !pair.after.asset_id
      ? "Choose both project originals."
      : scientificConfigurationIssue("mesh_longitudinal_comparison", review);

  async function preview() {
    if (issue) return;
    invalidate();
    const requested = version.current;
    setBusy(true);
    try {
      const value = await request<ComparisonResult>(
        `/projects/${projectId}/spatial/mesh-longitudinal-comparison`,
        {
          method: "POST",
          body: JSON.stringify({ ...pair, ...review }),
        },
      );
      if (requested === version.current) setResult(value);
    } catch (reason) {
      if (requested === version.current)
        setError(
          reason instanceof Error ? reason.message : "Comparison failed.",
        );
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    if (!result || saved) return;
    setBusy(true);
    setError("");
    try {
      const record = await saveWorkflowGraph(
        projectId,
        comparisonGraph(id, pair, review),
      );
      setSaved(record);
      onSaved?.();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Unable to save the comparison workflow.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <section
      className="panel-card"
      aria-label="Two-acquisition mesh comparison"
    >
      <h5>Compare two acquisitions</h5>
      <p>
        Choose the original and calibration for each survey. Changing either
        acquisition clears its pair review.
      </p>
      <fieldset disabled={busy}>
        {(["before", "after"] as const).map((slot) => (
          <fieldset key={slot}>
            <legend>
              {slot === "before" ? "Earlier acquisition" : "Later acquisition"}
            </legend>
            <ScientificNodeControls
              nodeType="mesh_surface_preview"
              projectId={projectId}
              parameters={pair[slot]}
              onChange={(parameters) => updateObservation(slot, parameters)}
            />
          </fieldset>
        ))}
        <ScientificNodeControls
          nodeType="mesh_longitudinal_comparison"
          projectId={projectId}
          parameters={review}
          onChange={(parameters) => {
            invalidate();
            setReview(bindReview(projectId, pair, parameters));
          }}
        />
        {(review.registration_evidence || review.reidentification_evidence) && (
          <button
            type="button"
            className="secondary"
            onClick={() => {
              invalidate();
              setReview({});
            }}
          >
            Clear pair review
          </button>
        )}
      </fieldset>
      {issue && <p>{issue}</p>}
      <div className="button-row">
        <button
          type="button"
          disabled={busy || !!issue}
          onClick={() => void preview()}
        >
          Preview comparison
        </button>
        <button
          type="button"
          disabled={busy || !result || !!saved}
          onClick={() => void save()}
        >
          Save comparison workflow
        </button>
      </div>
      {error && (
        <p role="alert" className="form-error">
          {error}
        </p>
      )}
      {result && (
        <section aria-label="Provisional surface comparison">
          <h5>Provisional surface area</h5>
          <dl>
            <dt>Earlier area</dt>
            <dd>{result.before_surface_area_m2} m²</dd>
            <dt>Later area</dt>
            <dd>{result.after_surface_area_m2} m²</dd>
            <dt>Geometric change</dt>
            <dd>
              {result.delta_surface_area_m2 == null
                ? "Withheld"
                : `${result.delta_surface_area_m2} m²`}
            </dd>
            <dt>Scale uncertainty interval</dt>
            <dd>
              {result.delta_surface_area_scale_interval_m2
                ? `${result.delta_surface_area_scale_interval_m2.join(" to ")} m²`
                : "Unavailable"}
            </dd>
            {result.registered_surface_centroid_separation_m != null && (
              <>
                <dt>Registered surface centroid separation</dt>
                <dd>{result.registered_surface_centroid_separation_m} m</dd>
                <dt>Caller-declared separation bounds</dt>
                <dd>
                  {result.registered_surface_centroid_separation_caller_bound_interval_m
                    ? `${result.registered_surface_centroid_separation_caller_bound_interval_m.join(" to ")} m`
                    : "Unavailable"}
                </dd>
              </>
            )}
          </dl>
          {result.registered_surface_centroid_separation_m != null && (
            <p>
              Surface centroid separation is a provisional alignment diagnostic.
            </p>
          )}
          <details>
            <summary>Measurement qualifications</summary>
            <ul>
              {result.qc_warnings.map((warning) => (
                <li key={warning}>{warning.replaceAll("_", " ")}</li>
              ))}
            </ul>
          </details>
        </section>
      )}
      {saved && (
        <p role="status">
          Saved {saved.name}, revision {saved.revision}. Open it in Saved
          revisions to run and export.
        </p>
      )}
    </section>
  );
}
