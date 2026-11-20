import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  originalAudioUrl,
  waveform,
  type AudioProposalCreate,
  type AudioRecording,
  type Waveform,
} from "./bioacousticsApi";

const width = 1024;
const height = 180;

export function sourceSeconds(sample: number, sampleRate: number) {
  return `${(sample / sampleRate).toFixed(6)} s`;
}

function AudioWaveform({
  data,
  start,
  end,
}: {
  data: Waveform;
  start: number;
  end: number;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const context = canvas.current?.getContext("2d");
    if (!context) return;
    const paint = (color: string) => {
      context.strokeStyle = color;
      context.beginPath();
    };
    context.clearRect(0, 0, width, height);
    context.fillStyle = "rgba(45, 164, 168, 0.18)";
    const first = (width * start) / data.sample_count;
    const last = (width * end) / data.sample_count;
    if (Number.isFinite(first) && Number.isFinite(last) && last > first) {
      context.fillRect(first, 0, last - first, height);
    }
    paint("rgba(92, 140, 150, 0.55)");
    context.moveTo(0, height / 2);
    context.lineTo(width, height / 2);
    context.stroke();
    paint("#0b8387");
    for (const peak of data.peaks) {
      const x =
        (width * (peak.start_sample + peak.end_sample)) /
        (2 * data.sample_count);
      context.moveTo(x, ((1 - peak.maximum) * height) / 2);
      context.lineTo(x, ((1 - peak.minimum) * height) / 2);
    }
    context.stroke();
  }, [data, start, end]);
  return (
    <canvas
      ref={canvas}
      className="rv-audio-waveform"
      width={width}
      height={height}
      role="img"
      aria-label={`Source waveform for channel ${data.channel + 1}`}
    />
  );
}

export function AudioListening({
  audio,
  busy,
  onPropose,
}: {
  audio: AudioRecording;
  busy: boolean;
  onPropose: (proposal: AudioProposalCreate) => void;
}) {
  const player = useRef<HTMLAudioElement>(null);
  const [channel, setChannel] = useState(0);
  const [start, setStart] = useState("0");
  const [end, setEnd] = useState(String(audio.sample_count));
  const [label, setLabel] = useState("");
  const [notes, setNotes] = useState("");
  const [playerError, setPlayerError] = useState(false);
  const peaks = useQuery({
    queryKey: [
      "audio-waveform",
      audio.project_id,
      audio.id,
      channel,
      audio.sha256,
    ],
    queryFn: ({ signal }) => waveform(audio, channel, signal),
  });
  const first = Number(start);
  const last = Number(end);
  const valid =
    start !== "" &&
    end !== "" &&
    Number.isSafeInteger(first) &&
    Number.isSafeInteger(last) &&
    first >= 0 &&
    first < last &&
    last <= audio.sample_count;

  function submit(event: FormEvent) {
    event.preventDefault();
    if (valid && label.trim())
      onPropose({
        start_sample: first,
        end_sample: last,
        channel,
        label: label.trim(),
        notes: notes.trim() || undefined,
        source_sha256: audio.sha256,
      });
  }

  return (
    <section
      className="panel rv-audio-panel"
      aria-label="Listen and propose intervals"
    >
      <h3>Listen and propose intervals</h3>
      <label>
        <span>Waveform channel</span>
        <select
          value={channel}
          onChange={(event) => setChannel(Number(event.target.value))}
        >
          {Array.from({ length: audio.channel_count }, (_, index) => (
            <option key={index} value={index}>
              Channel {index + 1}
            </option>
          ))}
        </select>
      </label>
      {peaks.isPending && <p role="status">Loading source waveform…</p>}
      {peaks.error && <p role="alert">{peaks.error.message}</p>}
      {peaks.data && peaks.data.source_sha256 === audio.sha256 && (
        <AudioWaveform data={peaks.data} start={first} end={last} />
      )}
      <div className="rv-audio-transport">
        <audio
          aria-label="Original audio playback"
          ref={player}
          controls
          preload="metadata"
          src={originalAudioUrl(audio)}
          onError={() => setPlayerError(true)}
        />
        <button
          type="button"
          className="secondary"
          disabled={playerError}
          onClick={() =>
            void player.current?.play().catch(() => setPlayerError(true))
          }
        >
          Play original audio
        </button>
        <button
          type="button"
          className="secondary"
          disabled={!valid || playerError}
          onClick={() => {
            if (player.current)
              player.current.currentTime = first / audio.sample_rate_hz;
          }}
        >
          Seek to interval start
        </button>
      </div>
      {playerError && (
        <p role="alert">
          The original could not be played. The source must be available and
          verified.
        </p>
      )}
      <form onSubmit={submit} className="rv-audio-fields">
        <label>
          <span>Start sample</span>
          <input
            type="number"
            min={0}
            max={audio.sample_count - 1}
            step={1}
            required
            value={start}
            onChange={(event) => setStart(event.target.value)}
          />
        </label>
        <label>
          <span>End sample (exclusive)</span>
          <input
            type="number"
            min={1}
            max={audio.sample_count}
            step={1}
            required
            value={end}
            onChange={(event) => setEnd(event.target.value)}
          />
        </label>
        <p className="rv-audio-wide">
          {valid
            ? `${sourceSeconds(first, audio.sample_rate_hz)} to ${sourceSeconds(last, audio.sample_rate_hz)} from the original start`
            : "Select a nonempty interval inside the recording."}
        </p>
        <label className="rv-audio-wide">
          <span>Proposed label</span>
          <input
            required
            value={label}
            maxLength={200}
            onChange={(event) => setLabel(event.target.value)}
          />
        </label>
        <label className="rv-audio-wide">
          <span>Proposal notes (optional)</span>
          <textarea
            value={notes}
            maxLength={2000}
            onChange={(event) => setNotes(event.target.value)}
          />
        </label>
        <button type="submit" disabled={!valid || !label.trim() || busy}>
          Add proposal
        </button>
      </form>
    </section>
  );
}
