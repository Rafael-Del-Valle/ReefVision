import { useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import {
  audioVideos,
  type AudioAnchorCreate,
  type AudioRecording,
} from "./bioacousticsApi";

export function AudioClockForm({
  audio,
  busy,
  onSave,
}: {
  audio: AudioRecording;
  busy: boolean;
  onSave: (anchor: AudioAnchorCreate) => void;
}) {
  const [kind, setKind] = useState<"utc" | "video">("utc");
  const [sample, setSample] = useState("0");
  const [uncertainty, setUncertainty] = useState("");
  const [evidence, setEvidence] = useState("");
  const [utc, setUtc] = useState("");
  const [videoId, setVideoId] = useState("");
  const [seconds, setSeconds] = useState("");
  const videos = useQuery({
    queryKey: ["audio-anchor-videos", audio.project_id],
    queryFn: ({ signal }) => audioVideos(audio.project_id, signal),
    enabled: kind === "video",
  });
  const video = videos.data?.find((candidate) => candidate.id === videoId);
  const source = Number(sample);
  const error = Number(uncertainty);
  const validBase =
    sample !== "" &&
    uncertainty !== "" &&
    Number.isSafeInteger(source) &&
    source >= 0 &&
    source < audio.sample_count &&
    Number.isSafeInteger(error) &&
    error >= 0 &&
    error <= 86400000000 &&
    !!evidence.trim();
  const videoSeconds = Number(seconds);
  const validClock =
    kind === "utc"
      ? /(?:Z|[+-]\d{2}:\d{2})$/.test(utc.trim())
      : !!video &&
        !!seconds &&
        Number.isFinite(videoSeconds) &&
        videoSeconds >= 0 &&
        videoSeconds <= video.duration_seconds;

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!validBase || !validClock) return;
    const common = {
      sample: source,
      source_sha256: audio.sha256,
      uncertainty_us: error,
      evidence: evidence.trim(),
    };
    if (kind === "utc") onSave({ ...common, kind, utc: utc.trim() });
    else if (video)
      onSave({
        ...common,
        kind,
        video_id: video.id,
        video_sha256: video.sha256,
        video_time_us: Math.round(videoSeconds * 1_000_000),
      });
  }

  return (
    <form className="rv-audio-fields" onSubmit={submit}>
      <label>
        <span>Clock reference</span>
        <select
          value={kind}
          onChange={(event) =>
            setKind(event.target.value === "video" ? "video" : "utc")
          }
        >
          <option value="utc">Explicit UTC or offset</option>
          <option value="video">Project video timeline</option>
        </select>
      </label>
      <label>
        <span>Anchor sample</span>
        <input
          type="number"
          min={0}
          max={audio.sample_count - 1}
          step={1}
          value={sample}
          onChange={(event) => setSample(event.target.value)}
          required
        />
      </label>
      {kind === "utc" ? (
        <label className="rv-audio-wide">
          <span>Anchor timestamp with offset</span>
          <input
            type="text"
            placeholder="2026-04-17T11:30:00-04:00"
            value={utc}
            onChange={(event) => setUtc(event.target.value)}
            required
          />
        </label>
      ) : (
        <>
          <label>
            <span>Reference video</span>
            <select
              value={videoId}
              onChange={(event) => setVideoId(event.target.value)}
              required
            >
              <option value="">Choose a project video</option>
              {videos.data?.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.original_filename}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>Video time (seconds)</span>
            <input
              type="number"
              min={0}
              max={video?.duration_seconds}
              step="0.000001"
              value={seconds}
              onChange={(event) => setSeconds(event.target.value)}
              required
            />
          </label>
          {videos.error && (
            <p className="rv-audio-wide" role="alert">
              {videos.error.message}
            </p>
          )}
        </>
      )}
      <label>
        <span>Uncertainty (microseconds)</span>
        <input
          min={0}
          max={86400000000}
          step={1}
          inputMode="numeric"
          type="number"
          value={uncertainty}
          onChange={(event) => setUncertainty(event.target.value)}
          required
        />
      </label>
      <label className="rv-audio-wide">
        <span>Clock evidence</span>
        <textarea
          maxLength={2000}
          value={evidence}
          onChange={(event) => setEvidence(event.target.value)}
          required
        />
      </label>
      <button type="submit" disabled={!validBase || !validClock || busy}>
        Save clock anchor
      </button>
    </form>
  );
}
