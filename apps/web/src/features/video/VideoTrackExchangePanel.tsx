import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import type { Project } from "../../api/client";
import { getVideos } from "./videoApi";
import {
  importVideoTracks,
  videoTrackExportUrl,
  type VideoTrackExchangeFormat,
} from "./videoTrackExchangeApi";

interface VideoTrackExchangePanelProps {
  project: Project;
}

const formatLabels: Record<VideoTrackExchangeFormat, string> = {
  reefvision_json: "ReefVision JSON (lossless)",
  reefvision_csv: "ReefVision CSV (0-based observations)",
  mot_csv: "MOTChallenge text (1-based frame/coordinates)",
};

export function VideoTrackExchangePanel({ project }: VideoTrackExchangePanelProps) {
  const queryClient = useQueryClient();
  const [videoId, setVideoId] = useState("");
  const [format, setFormat] = useState<VideoTrackExchangeFormat>("reefvision_json");
  const [importFile, setImportFile] = useState<File | null>(null);
  const [motLabelClassId, setMotLabelClassId] = useState(
    project.label_classes[0]?.id ?? "",
  );

  const videosQuery = useQuery({
    queryKey: ["videos", project.id],
    queryFn: ({ signal }) => getVideos(project.id, signal),
  });

  useEffect(() => {
    if (!videoId && videosQuery.data?.[0]) {
      setVideoId(videosQuery.data[0].id);
    }
  }, [videoId, videosQuery.data]);

  useEffect(() => {
    setImportFile(null);
  }, [videoId, format]);

  const importMutation = useMutation({
    mutationFn: () => {
      if (!videoId) throw new Error("Select a video first");
      if (!importFile) throw new Error("Choose a track file first");
      if (format === "mot_csv" && !motLabelClassId) {
        throw new Error("Choose the ReefVision class to apply to imported MOT tracks");
      }
      return importVideoTracks(
        videoId,
        format,
        importFile,
        format === "mot_csv" ? motLabelClassId : undefined,
      );
    },
    onSuccess: async () => {
      setImportFile(null);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["video-tracks", videoId] }),
        queryClient.invalidateQueries({ queryKey: ["video-tracking-runs", videoId] }),
      ]);
    },
  });

  return (
    <section className="management-card" data-testid="video-track-exchange-panel">
      <p className="eyebrow">Interoperability</p>
      <h3>Track interchange</h3>
      <p className="annotation-helper">
        ReefVision JSON preserves classes, interpolation, status, keyframes, and
        provenance metadata. CSV stores persisted 0-based observations. MOT uses
        1-based frame and left/top coordinates and does not carry ReefVision classes.
      </p>
      <label>
        Video
        <select value={videoId} onChange={(event) => setVideoId(event.target.value)}>
          {(videosQuery.data ?? []).map((video) => (
            <option key={video.id} value={video.id}>
              {video.original_filename}
            </option>
          ))}
        </select>
      </label>
      {videosQuery.isError && (
        <p className="form-error">{videosQuery.error.message}</p>
      )}
      <label>
        Format
        <select
          value={format}
          onChange={(event) => setFormat(event.target.value as VideoTrackExchangeFormat)}
        >
          {(Object.keys(formatLabels) as VideoTrackExchangeFormat[]).map((value) => (
            <option key={value} value={value}>
              {formatLabels[value]}
            </option>
          ))}
        </select>
      </label>
      <a
        href={videoId ? videoTrackExportUrl(videoId, format) : undefined}
        download
        aria-disabled={!videoId}
        onClick={(event) => {
          if (!videoId) event.preventDefault();
        }}
      >
        Export active tracks
      </a>
      <hr />
      <label>
        Import track file
        <input
          type="file"
          accept={
            format === "reefvision_json"
              ? ".json,application/json"
              : ".csv,.txt,text/plain,text/csv"
          }
          onChange={(event) => setImportFile(event.target.files?.[0] ?? null)}
        />
      </label>
      {format === "mot_csv" && (
        <label>
          Class for imported MOT tracks
          <select
            value={motLabelClassId}
            onChange={(event) => setMotLabelClassId(event.target.value)}
          >
            {project.label_classes.map((labelClass) => (
              <option key={labelClass.id} value={labelClass.id}>
                {labelClass.name}
              </option>
            ))}
          </select>
        </label>
      )}
      <button
        type="button"
        disabled={!videoId || !importFile || importMutation.isPending}
        onClick={() => importMutation.mutate()}
      >
        {importMutation.isPending ? "Importing..." : "Import as new tracks"}
      </button>
      {importMutation.data && (
        <div className="annotation-selection-list">
          <div className="annotation-selection-row">
            <strong>Imported tracks</strong>
            <span>{importMutation.data.track_count}</span>
          </div>
          <div className="annotation-selection-row">
            <strong>Observations</strong>
            <span>{importMutation.data.observation_count}</span>
          </div>
          {importMutation.data.warnings.map((warning) => (
            <p key={warning} className="annotation-helper">
              {warning}
            </p>
          ))}
        </div>
      )}
      {importMutation.error instanceof Error && (
        <p className="form-error">{importMutation.error.message}</p>
      )}
    </section>
  );
}
