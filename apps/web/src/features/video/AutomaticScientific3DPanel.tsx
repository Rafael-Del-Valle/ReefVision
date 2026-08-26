import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import type { VideoTrackRecord } from "./videoApi";
import {
  createMetricDepth3DJob,
  getMetricDepth3DJob,
  type MetricVideoDepth3DResult,
} from "./videoScienceApi";
import { Scientific3DDepthPreview } from "./Scientific3DDepthPreview";
import { Scientific3DVisualization } from "./Scientific3DVisualization";
import {
  scientific3DGroupFramesCsv,
  scientific3DReportJson,
  scientific3DTrajectoriesCsv,
} from "./scientific3dReport";

interface AutomaticScientific3DPanelProps {
  videoId: string;
  tracks: VideoTrackRecord[];
  cameraReady: boolean;
  classNames: Map<string, string>;
}

function toggleSelection(
  current: string[],
  value: string,
  checked: boolean,
): string[] {
  if (checked) return current.includes(value) ? current : [...current, value];
  return current.filter((item) => item !== value);
}

function downloadText(filename: string, content: string, mediaType: string) {
  const blob = new Blob([content], { type: mediaType });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

function resultFromJob(
  resultJson: Record<string, unknown> | null | undefined,
): MetricVideoDepth3DResult | null {
  if (
    !resultJson ||
    resultJson.schema_version !== "video-metric-depth-3d-job-0001"
  ) {
    return null;
  }
  return resultJson as unknown as MetricVideoDepth3DResult;
}

export function AutomaticScientific3DPanel({
  videoId,
  tracks,
  cameraReady,
  classNames,
}: AutomaticScientific3DPanelProps) {
  const [selectedTrackIds, setSelectedTrackIds] = useState<string[]>([]);
  const [device, setDevice] = useState("auto");
  const [inputSize, setInputSize] = useState(518);
  const [maxResolution, setMaxResolution] = useState(1280);
  const [coreFraction, setCoreFraction] = useState(0.6);
  const [minimumValidFraction, setMinimumValidFraction] = useState(0.25);
  const [maximumFrameGap, setMaximumFrameGap] = useState("");
  const [jobId, setJobId] = useState("");

  useEffect(() => {
    setSelectedTrackIds([]);
    setJobId("");
  }, [videoId]);

  const queueMutation = useMutation({
    mutationFn: () => {
      if (!videoId) throw new Error("Select a video first");
      if (!cameraReady) {
        throw new Error(
          "Save camera intrinsics before automatic Scientific 3D",
        );
      }
      if (selectedTrackIds.length === 0) {
        throw new Error("Select at least one fish/video track");
      }
      const frameGap = maximumFrameGap.trim()
        ? Number.parseInt(maximumFrameGap, 10)
        : null;
      if (frameGap !== null && (!Number.isInteger(frameGap) || frameGap < 1)) {
        throw new Error("Maximum frame gap must be a positive integer");
      }
      return createMetricDepth3DJob(videoId, {
        track_ids: selectedTrackIds,
        device,
        input_size: inputSize,
        max_res: maxResolution,
        core_fraction: coreFraction,
        minimum_valid_fraction: minimumValidFraction,
        maximum_frame_gap: frameGap,
        allow_model_download: false,
        allow_resolution_fallback: true,
      });
    },
    onSuccess: (job) => {
      setJobId(job.id);
    },
  });

  const jobQuery = useQuery({
    queryKey: ["video-metric-depth-3d-job", jobId],
    queryFn: ({ signal }) => getMetricDepth3DJob(jobId, signal),
    enabled: Boolean(jobId),
    refetchInterval: (query) => {
      const job = query.state.data;
      return job &&
        ["queued", "running", "cancel_requested"].includes(job.status)
        ? 1500
        : false;
    },
  });

  const result = useMemo(
    () =>
      jobQuery.data?.status === "succeeded"
        ? resultFromJob(jobQuery.data.result_json)
        : null,
    [jobQuery.data],
  );

  const error =
    queueMutation.error ??
    jobQuery.error ??
    (jobQuery.data?.status === "failed" && jobQuery.data.error_message
      ? new Error(jobQuery.data.error_message)
      : null);

  const safeStem = `reefvision-scientific-3d-${videoId || "video"}`;

  return (
    <section className="panel-card" data-testid="automatic-scientific-3d-panel">
      <p className="eyebrow">Automatic Scientific 3D</p>
      <h4>Video → Depth &amp; 3D</h4>
      <p className="annotation-helper">
        Metric Video Depth Anything Small estimates temporally consistent depth,
        samples robust central regions of each selected fish track, and feeds
        those samples into ReefVision&apos;s existing camera-intrinsics X/Y/Z
        reconstruction.
      </p>

      <div className="annotation-selection-list">
        <div className="annotation-selection-row">
          <strong>Depth validity</strong>
          <span>Model-estimated metric</span>
        </div>
        <div className="annotation-selection-row">
          <strong>Physical measurement claim</strong>
          <span>Disabled — underwater validation required</span>
        </div>
      </div>

      <p className="annotation-helper">
        Water and housing-port refraction, turbidity, attenuation, and model
        domain shift can bias monocular depth. ReefVision therefore preserves
        these outputs as model-estimated metric values until the camera/scene is
        independently validated underwater.
      </p>

      <strong>Tracks to reconstruct</strong>
      {tracks.length === 0 ? (
        <p className="annotation-helper">
          Create or run fish/video tracks before automatic Scientific 3D.
        </p>
      ) : (
        <div className="annotation-selection-list">
          {tracks.map((track) => (
            <label key={track.id} className="annotation-selection-row">
              <input
                type="checkbox"
                checked={selectedTrackIds.includes(track.id)}
                onChange={(event) =>
                  setSelectedTrackIds((current) =>
                    toggleSelection(current, track.id, event.target.checked),
                  )
                }
              />
              <span>
                Track {track.track_number} —{" "}
                {classNames.get(track.label_class_id) ?? "Unknown class"}
              </span>
            </label>
          ))}
        </div>
      )}

      <div className="annotation-editor-inline-actions">
        <button
          type="button"
          className="secondary"
          disabled={tracks.length === 0}
          onClick={() => setSelectedTrackIds(tracks.map((track) => track.id))}
        >
          Select all tracks
        </button>
        <button
          type="button"
          className="secondary"
          disabled={selectedTrackIds.length === 0}
          onClick={() => setSelectedTrackIds([])}
        >
          Clear track selection
        </button>
      </div>

      <div className="annotation-selection-list">
        <label>
          Compute device
          <select
            value={device}
            onChange={(event) => setDevice(event.target.value)}
          >
            <option value="auto">Auto</option>
            <option value="cuda">CUDA</option>
            <option value="cpu">CPU</option>
          </select>
        </label>
        <label>
          Depth model input size
          <select
            value={inputSize}
            onChange={(event) => setInputSize(Number(event.target.value))}
          >
            <option value={518}>518 (highest default quality)</option>
            <option value={448}>448</option>
            <option value={392}>392</option>
            <option value={336}>336 (lowest fallback memory)</option>
          </select>
        </label>
        <label>
          Maximum decoded resolution
          <input
            type="number"
            min={256}
            max={8192}
            step={1}
            value={maxResolution}
            onChange={(event) => setMaxResolution(Number(event.target.value))}
          />
        </label>
        <label>
          Central bbox sampling fraction
          <input
            type="number"
            min={0.05}
            max={1}
            step={0.05}
            value={coreFraction}
            onChange={(event) => setCoreFraction(Number(event.target.value))}
          />
        </label>
        <label>
          Minimum valid depth-pixel fraction
          <input
            type="number"
            min={0}
            max={1}
            step={0.05}
            value={minimumValidFraction}
            onChange={(event) =>
              setMinimumValidFraction(Number(event.target.value))
            }
          />
        </label>
        <label>
          Maximum 3D frame gap (optional)
          <input
            type="number"
            min={1}
            step={1}
            value={maximumFrameGap}
            onChange={(event) => setMaximumFrameGap(event.target.value)}
            placeholder="Leave blank to use all consecutive valid samples"
          />
        </label>
      </div>

      <p className="annotation-helper">
        Install <strong>Metric Video Depth Anything Small</strong> from Models
        &amp; AI before running this analysis. Automatic downloads remain
        disabled during analysis so model provenance cannot change silently.
      </p>

      <button
        type="button"
        disabled={
          !videoId ||
          !cameraReady ||
          selectedTrackIds.length === 0 ||
          queueMutation.isPending
        }
        onClick={() => queueMutation.mutate()}
      >
        {queueMutation.isPending ? "Queuing..." : "Run automatic Depth & 3D"}
      </button>

      {jobQuery.data && (
        <div className="annotation-selection-list">
          <div className="annotation-selection-row">
            <strong>Job</strong>
            <span>{jobQuery.data.id.slice(0, 8)}</span>
          </div>
          <div className="annotation-selection-row">
            <strong>Status</strong>
            <span>{jobQuery.data.status}</span>
          </div>
          <div className="annotation-selection-row">
            <strong>Progress</strong>
            <span>
              {jobQuery.data.progress_current}/{jobQuery.data.progress_total}
            </span>
          </div>
        </div>
      )}

      {result && (
        <>
          <div className="annotation-selection-list">
            <div className="annotation-selection-row">
              <strong>Model</strong>
              <span>Metric Video Depth Anything Small</span>
            </div>
            <div className="annotation-selection-row">
              <strong>Input size used</strong>
              <span>{result.input_size_used}</span>
            </div>
            <div className="annotation-selection-row">
              <strong>Depth samples</strong>
              <span>{result.metric_depth_sample_count.toLocaleString()}</span>
            </div>
            <div className="annotation-selection-row">
              <strong>Analyzed tracks</strong>
              <span>{result.analyzed_track_ids.length}</span>
            </div>
            <div className="annotation-selection-row">
              <strong>Depth stack SHA-256</strong>
              <span>{result.depth_stack_sha256.slice(0, 16)}…</span>
            </div>
          </div>

          {result.analytics.tracks.map((track) => (
            <div key={track.track_id} className="panel-card">
              <strong>
                Track {track.track_number} —{" "}
                {classNames.get(track.label_class_id) ?? "Unknown class"}
              </strong>
              <dl className="metric-list">
                <div>
                  <dt>3D path</dt>
                  <dd>{track.path_length_3d.toFixed(4)} m</dd>
                </div>
                <div>
                  <dt>3D displacement</dt>
                  <dd>{track.displacement_3d.toFixed(4)} m</dd>
                </div>
                <div>
                  <dt>Mean 3D speed</dt>
                  <dd>{track.mean_speed_3d_per_second.toFixed(4)} m/s</dd>
                </div>
                <div>
                  <dt>Maximum 3D speed</dt>
                  <dd>{track.maximum_speed_3d_per_second.toFixed(4)} m/s</dd>
                </div>
                <div>
                  <dt>Mean depth</dt>
                  <dd>{track.mean_depth.toFixed(4)} m</dd>
                </div>
                <div>
                  <dt>Depth range</dt>
                  <dd>
                    {track.minimum_depth.toFixed(4)}–
                    {track.maximum_depth.toFixed(4)} m
                  </dd>
                </div>
              </dl>
            </div>
          ))}

          <Scientific3DDepthPreview
            videoId={videoId}
            jobId={jobId}
            result={result}
          />

          <Scientific3DVisualization result={result} classNames={classNames} />

          <div className="annotation-editor-inline-actions">
            <button
              type="button"
              className="secondary"
              onClick={() =>
                downloadText(
                  `${safeStem}.json`,
                  scientific3DReportJson(result),
                  "application/json",
                )
              }
            >
              Download Scientific 3D JSON
            </button>
            <button
              type="button"
              className="secondary"
              onClick={() =>
                downloadText(
                  `${safeStem}-trajectories.csv`,
                  scientific3DTrajectoriesCsv(result),
                  "text/csv",
                )
              }
            >
              Download trajectory CSV
            </button>
            <button
              type="button"
              className="secondary"
              onClick={() =>
                downloadText(
                  `${safeStem}-group.csv`,
                  scientific3DGroupFramesCsv(result),
                  "text/csv",
                )
              }
            >
              Download group 3D CSV
            </button>
          </div>

          {result.warnings.map((warning) => (
            <p key={warning} className="annotation-helper">
              {warning}
            </p>
          ))}
        </>
      )}

      {error instanceof Error && <p className="form-error">{error.message}</p>}
    </section>
  );
}
