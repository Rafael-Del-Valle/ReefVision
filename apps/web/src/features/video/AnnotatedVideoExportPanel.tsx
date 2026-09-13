import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { cancelJob } from "../../api/client";
import {
  annotatedVideoExportContentUrl,
  createAnnotatedVideoExport,
  getAnnotatedVideoExports,
  type AnnotatedVideoOverlayOptions,
  type AnnotatedVideoPreset,
  type VideoTrackingRun,
} from "./videoApi";

const PRESET_DEFAULTS: Record<
  AnnotatedVideoPreset,
  AnnotatedVideoOverlayOptions
> = {
  clean_tracking: {
    boxes: true,
    track_ids: true,
    class_labels: true,
    confidence: true,
    trails: false,
    frame_time: false,
    counters: false,
  },
  full_review: {
    boxes: true,
    track_ids: true,
    class_labels: true,
    confidence: true,
    trails: true,
    frame_time: true,
    counters: true,
  },
};

const OVERLAY_LABELS: Array<[keyof AnnotatedVideoOverlayOptions, string]> = [
  ["boxes", "Bounding boxes"],
  ["track_ids", "Track IDs"],
  ["class_labels", "Class labels"],
  ["confidence", "Confidence"],
  ["trails", "Trajectory trails"],
  ["frame_time", "Frame / timestamp"],
  ["counters", "Review counters"],
];

function resultString(
  result: Record<string, unknown> | null,
  key: string,
): string | null {
  const value = result?.[key];
  return typeof value === "string" ? value : null;
}

function requestString(request: Record<string, unknown>, key: string): string {
  const value = request[key];
  return typeof value === "string" ? value : "—";
}

export function AnnotatedVideoExportPanel({
  videoId,
  trackingRuns,
}: {
  videoId: string | null;
  trackingRuns: VideoTrackingRun[];
}) {
  const queryClient = useQueryClient();
  const succeededRuns = useMemo(
    () => trackingRuns.filter((run) => run.status === "succeeded"),
    [trackingRuns],
  );
  const [sourceTrackingJobId, setSourceTrackingJobId] = useState("");
  const [preset, setPreset] = useState<AnnotatedVideoPreset>("clean_tracking");
  const [overlays, setOverlays] = useState<AnnotatedVideoOverlayOptions>(
    PRESET_DEFAULTS.clean_tracking,
  );
  const [trailLength, setTrailLength] = useState(60);

  useEffect(() => {
    if (
      sourceTrackingJobId &&
      succeededRuns.some((run) => run.job_id === sourceTrackingJobId)
    ) {
      return;
    }
    setSourceTrackingJobId(succeededRuns[0]?.job_id ?? "");
  }, [sourceTrackingJobId, succeededRuns]);

  const exportsQuery = useQuery({
    queryKey: ["annotated-video-exports", videoId],
    queryFn: ({ signal }) =>
      getAnnotatedVideoExports(videoId as string, signal),
    enabled: Boolean(videoId),
    refetchInterval: 1000,
  });

  const createMutation = useMutation({
    mutationFn: () =>
      createAnnotatedVideoExport(videoId as string, {
        source_tracking_job_id: sourceTrackingJobId,
        preset,
        overlays,
        trail_length: trailLength,
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["annotated-video-exports", videoId],
      });
    },
  });

  const cancelMutation = useMutation({
    mutationFn: (jobId: string) => cancelJob(jobId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["annotated-video-exports", videoId],
      });
    },
  });

  const error =
    createMutation.error ?? cancelMutation.error ?? exportsQuery.error;

  return (
    <section className="management-card">
      <p className="eyebrow">Annotated video export</p>
      <h3>Tracking review MP4</h3>
      <p className="annotation-helper">
        Render stored tracking observations into a new MP4 without rerunning the
        detector. Boxes appear only where ReefVision stored an observation.
        Source audio is not copied in this exporter.
      </p>

      <label>
        Tracking run
        <select
          value={sourceTrackingJobId}
          onChange={(event) => setSourceTrackingJobId(event.target.value)}
        >
          {succeededRuns.length === 0 && (
            <option value="">No succeeded tracking runs</option>
          )}
          {succeededRuns.map((run) => (
            <option key={run.job_id} value={run.job_id}>
              {run.job_id.slice(0, 8)} · {run.tracker} · {run.track_count}{" "}
              tracks
            </option>
          ))}
        </select>
      </label>

      <label>
        Preset
        <select
          value={preset}
          onChange={(event) => {
            const next =
              event.target.value === "full_review"
                ? "full_review"
                : "clean_tracking";
            setPreset(next);
            setOverlays({ ...PRESET_DEFAULTS[next] });
          }}
        >
          <option value="clean_tracking">Clean Tracking</option>
          <option value="full_review">Full Review</option>
        </select>
      </label>

      <div className="annotation-selection-list">
        {OVERLAY_LABELS.map(([field, label]) => (
          <label key={field} className="annotation-selection-row">
            <input
              type="checkbox"
              checked={overlays[field]}
              onChange={(event) =>
                setOverlays((current) => ({
                  ...current,
                  [field]: event.target.checked,
                }))
              }
            />
            <span>{label}</span>
          </label>
        ))}
      </div>

      <label>
        Trail length (observations)
        <input
          type="number"
          min={2}
          max={1000}
          step={1}
          disabled={!overlays.trails}
          value={trailLength}
          onChange={(event) =>
            setTrailLength(
              Math.max(2, Math.min(1000, Number(event.target.value))),
            )
          }
        />
      </label>

      <button
        type="button"
        disabled={!videoId || !sourceTrackingJobId || createMutation.isPending}
        onClick={() => createMutation.mutate()}
      >
        {createMutation.isPending
          ? "Queuing export..."
          : preset === "clean_tracking"
            ? "Export Clean Tracking MP4"
            : "Export Full Review MP4"}
      </button>

      {(exportsQuery.data ?? []).length > 0 && (
        <div style={{ overflowX: "auto" }}>
          <table>
            <thead>
              <tr>
                <th>Export</th>
                <th>Preset</th>
                <th>Status</th>
                <th>Progress</th>
                <th>Source run</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {(exportsQuery.data ?? []).map((job) => {
                const total = job.progress_total || 0;
                const current = job.progress_current || 0;
                const percent = total > 0 ? (current / total) * 100 : 0;
                const filename = resultString(job.result_json, "filename");
                const active =
                  job.status === "queued" ||
                  job.status === "running" ||
                  job.status === "cancel_requested";

                return (
                  <tr key={job.id}>
                    <td>{job.id.slice(0, 8)}</td>
                    <td>
                      {requestString(job.request_json, "preset") ===
                      "full_review"
                        ? "Full Review"
                        : "Clean Tracking"}
                    </td>
                    <td>{job.status}</td>
                    <td>
                      {current.toLocaleString()} / {total.toLocaleString()} (
                      {percent.toFixed(1)}%)
                    </td>
                    <td>
                      {requestString(
                        job.request_json,
                        "source_tracking_job_id",
                      ).slice(0, 8)}
                    </td>
                    <td>
                      <div className="annotation-editor-inline-actions">
                        {active && job.status !== "cancel_requested" && (
                          <button
                            type="button"
                            className="danger-ghost"
                            disabled={cancelMutation.isPending}
                            onClick={() => cancelMutation.mutate(job.id)}
                          >
                            Cancel
                          </button>
                        )}
                        {job.status === "succeeded" && filename && (
                          <a
                            className="secondary"
                            href={annotatedVideoExportContentUrl(job.id)}
                            download={filename}
                          >
                            Download MP4
                          </a>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {error instanceof Error && <p className="form-error">{error.message}</p>}
    </section>
  );
}
