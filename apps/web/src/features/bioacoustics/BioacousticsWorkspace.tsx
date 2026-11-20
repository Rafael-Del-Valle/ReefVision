import {
  useInfiniteQuery,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { saveWorkflowGraph } from "../workflow-graphs/workflowGraphApi";
import { AudioClockForm } from "./AudioClockForm";
import { AudioListening, sourceSeconds } from "./AudioListening";
import {
  audioPage,
  audioPost,
  createAudioRecording,
  downloadAudioReport,
  recordingPath,
  recordingsPath,
  type AudioAlignment,
  type AudioAnchor,
  type AudioAnchorCreate,
  type AudioDecision,
  type AudioProposal,
  type AudioProposalCreate,
  type AudioRecording,
  type AudioReport,
  type AudioReview,
} from "./bioacousticsApi";
import "./bioacoustics.css";

interface Props {
  projectId: string;
  onOpenWorkflow?: () => void;
}

const queryKey = (path: string) => ["bioacoustics", path];

function useAudioList<T>(path: string) {
  const query = useInfiniteQuery({
    queryKey: queryKey(path),
    initialPageParam: 0,
    queryFn: ({ pageParam, signal }) => audioPage<T>(path, pageParam, signal),
    getNextPageParam: (last) => {
      const next = last.offset + last.items.length;
      return last.items.length && next < last.total ? next : undefined;
    },
  });
  return {
    ...query,
    items: query.data?.pages.flatMap((page) => page.items) ?? [],
  };
}

function LoadMore({
  available,
  loading,
  onClick,
  label,
}: {
  available: boolean;
  loading: boolean;
  onClick: () => void;
  label: string;
}) {
  return available ? (
    <button
      type="button"
      className="secondary"
      disabled={loading}
      onClick={onClick}
    >
      {label}
    </button>
  ) : null;
}

function ErrorText({ error }: { error: Error | null }) {
  return error ? <p role="alert">{error.message}</p> : null;
}

function ReviewControls({
  audio,
  proposal,
}: {
  audio: AudioRecording;
  proposal: AudioProposal;
}) {
  const cache = useQueryClient();
  const base = `${recordingPath(audio)}/proposals`;
  const path = `${base}/${proposal.id}/reviews`;
  const history = useAudioList<AudioReview>(path);
  const [decision, setDecision] = useState<AudioDecision | "">("");
  const [reason, setReason] = useState("");
  const review = useMutation({
    mutationFn: (next: AudioDecision) =>
      audioPost<AudioReview>(path, {
        decision: next,
        reason: reason.trim(),
        expected_revision: proposal.review_revision,
      }),
    onSuccess: () => {
      setDecision("");
      setReason("");
      void cache.invalidateQueries({ queryKey: queryKey(base) });
      void cache.invalidateQueries({ queryKey: queryKey(path) });
    },
  });
  function submit(event: FormEvent) {
    event.preventDefault();
    if (decision && reason.trim()) review.mutate(decision);
  }
  return (
    <>
      <p>
        <strong>{proposal.label}</strong> · {proposal.status}
      </p>
      <p>
        Channel {proposal.channel + 1}, samples [{proposal.start_sample},{" "}
        {proposal.end_sample})
      </p>
      <p>
        {sourceSeconds(proposal.start_sample, audio.sample_rate_hz)} to{" "}
        {sourceSeconds(proposal.end_sample, audio.sample_rate_hz)} from the
        original start
      </p>
      {proposal.notes && <p>{proposal.notes}</p>}
      <form className="rv-audio-fields" onSubmit={submit}>
        <label>
          <span>Review decision</span>
          <select
            value={decision}
            onChange={(event) =>
              setDecision(event.target.value as AudioDecision | "")
            }
            required
          >
            <option value="">Choose a decision</option>
            <option value="accepted">Accept</option>
            <option value="dismissed">Dismiss</option>
            <option value="uncertain">Mark uncertain</option>
          </select>
        </label>
        <label className="rv-audio-wide">
          <span>Review reason</span>
          <textarea
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            maxLength={2000}
            required
          />
        </label>
        <button
          type="submit"
          disabled={!decision || !reason.trim() || review.isPending}
        >
          Record decision
        </button>
      </form>
      <ErrorText error={review.error ?? history.error} />
      {history.items.length > 0 && (
        <ol
          className="rv-audio-review-log"
          aria-label="Attributed review history"
        >
          {history.items.map((row) => (
            <li key={row.id}>
              {row.decision} · {row.reviewer} · {row.reason}
            </li>
          ))}
        </ol>
      )}
      <LoadMore
        available={history.hasNextPage}
        loading={history.isFetchingNextPage}
        onClick={() => void history.fetchNextPage()}
        label="Load more review decisions"
      />
    </>
  );
}

function alignmentLabel(alignment: AudioAlignment) {
  if (alignment.status === "withheld")
    return `Withheld. ${alignment.reason ?? "Insufficient evidence"}`;
  const interval =
    alignment.status === "utc"
      ? `${alignment.start_utc} to ${alignment.end_utc}`
      : `Video ${sourceSeconds(alignment.start_video_us ?? 0, 1000000)} to ${sourceSeconds(alignment.end_video_us ?? 0, 1000000)}`;
  return `${interval} ± ${alignment.uncertainty_us} µs`;
}

function ReportView({
  audio,
  report,
  onOpenWorkflow,
}: {
  audio: AudioRecording;
  report: AudioReport;
  onOpenWorkflow?: () => void;
}) {
  const cache = useQueryClient();
  const download = useMutation({
    mutationFn: () => downloadAudioReport(audio, report),
  });
  const workflow = useMutation({
    mutationFn: () =>
      saveWorkflowGraph(audio.project_id, {
        graph_id: `bioacoustics-${report.id}`,
        name: `Bioacoustics · ${audio.original_filename}`,
        nodes: [
          { node_id: "project", node_type: "project_source" },
          {
            node_id: "report",
            node_type: "bioacoustic_report",
            parameters: {
              report_id: report.id,
              report_sha256: report.report_sha256,
            },
          },
        ],
        edges: [
          {
            edge_id: "project-report",
            source_node_id: "project",
            source_port_id: "project",
            target_node_id: "report",
            target_port_id: "project",
          },
        ],
      }),
    onSuccess: () => {
      void cache.invalidateQueries({
        queryKey: ["workflow-graphs", audio.project_id],
      });
    },
  });
  return (
    <div className="rv-audio-panel" aria-label="Frozen report evidence">
      <p className="rv-audio-proof">
        Report SHA-256 <code>{report.report_sha256}</code>
      </p>
      {report.snapshot.anchor && (
        <p>Clock evidence: {report.snapshot.anchor.evidence}</p>
      )}
      {report.snapshot.entries.length === 0 && (
        <p>This report has no source intervals.</p>
      )}
      {report.snapshot.entries.length > 0 && (
        <ul
          className="rv-audio-result-rows"
          aria-label="Reported source intervals"
        >
          {report.snapshot.entries.map(({ proposal, alignment }) => (
            <li key={proposal.id}>
              <strong>{proposal.label}</strong> · {proposal.status} · channel{" "}
              {proposal.channel + 1}, samples [{proposal.start_sample},{" "}
              {proposal.end_sample})<br />
              {alignmentLabel(alignment)}
            </li>
          ))}
        </ul>
      )}
      <div className="rv-audio-actions">
        <button
          type="button"
          className="secondary"
          disabled={download.isPending}
          onClick={() => download.mutate()}
        >
          Download report JSON
        </button>
        <button
          type="button"
          className="secondary"
          disabled={workflow.isPending}
          onClick={() => workflow.mutate()}
        >
          Save bioacoustic workflow
        </button>
        {workflow.isSuccess && onOpenWorkflow && (
          <button type="button" className="secondary" onClick={onOpenWorkflow}>
            Open Workflow Builder
          </button>
        )}
      </div>
      {workflow.isSuccess && (
        <p role="status">Saved workflow for this frozen report.</p>
      )}
      <ErrorText error={download.error ?? workflow.error} />
    </div>
  );
}

function anchorLabel(anchor: AudioAnchor) {
  const clock =
    anchor.kind === "utc"
      ? anchor.utc
      : `video ${sourceSeconds(anchor.video_time_us, 1000000)}`;
  return `Sample ${anchor.sample} to ${clock} ± ${anchor.uncertainty_us} µs`;
}

function RecordingWorkspace({
  audio,
  onOpenWorkflow,
}: {
  audio: AudioRecording;
  onOpenWorkflow?: () => void;
}) {
  const cache = useQueryClient();
  const base = recordingPath(audio);
  const proposals = useAudioList<AudioProposal>(`${base}/proposals`);
  const anchors = useAudioList<AudioAnchor>(`${base}/anchors`);
  const reports = useAudioList<AudioReport>(`${base}/reports`);
  const [proposalId, setProposalId] = useState("");
  const [anchorId, setAnchorId] = useState("");
  const [reportId, setReportId] = useState("");
  const proposal =
    proposals.items.find((item) => item.id === proposalId) ??
    proposals.items[0];
  const report =
    reports.items.find((item) => item.id === reportId) ?? reports.items[0];
  const propose = useMutation({
    mutationFn: (form: AudioProposalCreate) =>
      audioPost<AudioProposal>(`${base}/proposals`, form),
    onSuccess: (saved) => {
      setProposalId(saved.id);
      void cache.invalidateQueries({ queryKey: queryKey(`${base}/proposals`) });
    },
  });
  const createAnchor = useMutation({
    mutationFn: (form: AudioAnchorCreate) =>
      audioPost<AudioAnchor>(`${base}/anchors`, form),
    onSuccess: (saved) => {
      setAnchorId(saved.id);
      void cache.invalidateQueries({ queryKey: queryKey(`${base}/anchors`) });
    },
  });
  const freeze = useMutation({
    mutationFn: () =>
      audioPost<AudioReport>(`${base}/reports`, {
        anchor_id: anchorId || null,
      }),
    onSuccess: (saved) => {
      setReportId(saved.id);
      void cache.invalidateQueries({ queryKey: queryKey(`${base}/reports`) });
    },
  });
  return (
    <article
      className="rv-audio-workspace"
      aria-label="Selected audio recording"
    >
      <div className="panel rv-audio-panel">
        <h3>{audio.original_filename}</h3>
        <p>
          {audio.sample_count.toLocaleString()} samples per channel ·{" "}
          {audio.sample_rate_hz.toLocaleString()} Hz · {audio.bits_per_sample}
          -bit PCM · {audio.channel_count}{" "}
          {audio.channel_count === 1 ? "channel" : "channels"}
        </p>
        <p className="rv-audio-proof">
          Original SHA-256 <code>{audio.sha256}</code>
        </p>
      </div>
      <AudioListening
        audio={audio}
        busy={propose.isPending}
        onPropose={(form) => propose.mutate(form)}
      />
      <section className="panel rv-audio-panel" aria-label="Review proposals">
        <h3>Review proposals</h3>
        <ErrorText error={propose.error ?? proposals.error} />
        {!proposals.isPending && !proposals.items.length && (
          <p>No saved proposals.</p>
        )}
        {proposal && (
          <>
            <label>
              <span>Proposal to review</span>
              <select
                value={proposal.id}
                onChange={(event) => setProposalId(event.target.value)}
              >
                {proposals.items.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.label} · {item.status}
                  </option>
                ))}
              </select>
            </label>
            <ReviewControls
              key={proposal.id}
              audio={audio}
              proposal={proposal}
            />
          </>
        )}
        <LoadMore
          available={proposals.hasNextPage}
          loading={proposals.isFetchingNextPage}
          onClick={() => void proposals.fetchNextPage()}
          label="Load more proposals"
        />
      </section>
      <section className="panel rv-audio-panel" aria-label="Clock alignment">
        <h3>Clock alignment</h3>
        <p>
          Use a shared event with a declared clock and uncertainty. One anchor
          applies an offset. Drift stays unmeasured.
        </p>
        <AudioClockForm
          audio={audio}
          busy={createAnchor.isPending}
          onSave={(form) => createAnchor.mutate(form)}
        />
        {createAnchor.isSuccess && <p role="status">Clock anchor saved.</p>}
        <ErrorText error={createAnchor.error ?? anchors.error} />
      </section>
      <section
        className="panel rv-audio-panel"
        aria-label="Review and export alignment"
      >
        <h3>Review and export alignment</h3>
        <label>
          <span>Anchor for the report</span>
          <select
            value={anchorId}
            onChange={(event) => setAnchorId(event.target.value)}
          >
            <option value="">Unaligned source time</option>
            {anchors.items.map((anchor) => (
              <option key={anchor.id} value={anchor.id}>
                {anchorLabel(anchor)}
              </option>
            ))}
          </select>
        </label>
        <LoadMore
          available={anchors.hasNextPage}
          loading={anchors.isFetchingNextPage}
          onClick={() => void anchors.fetchNextPage()}
          label="Load more clock anchors"
        />
        <button
          type="button"
          disabled={freeze.isPending}
          onClick={() => freeze.mutate()}
        >
          Freeze bioacoustic report
        </button>
        <ErrorText error={freeze.error ?? reports.error} />
        {report && (
          <>
            <label>
              <span>Saved bioacoustic report</span>
              <select
                value={report.id}
                onChange={(event) => setReportId(event.target.value)}
              >
                {reports.items.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.snapshot.anchor
                      ? anchorLabel(item.snapshot.anchor)
                      : "Unaligned source time"}{" "}
                    · {item.report_sha256.slice(0, 10)}
                  </option>
                ))}
              </select>
            </label>
            <ReportView
              key={report.id}
              audio={audio}
              report={report}
              onOpenWorkflow={onOpenWorkflow}
            />
          </>
        )}
        <LoadMore
          available={reports.hasNextPage}
          loading={reports.isFetchingNextPage}
          onClick={() => void reports.fetchNextPage()}
          label="Load more reports"
        />
      </section>
    </article>
  );
}

export function BioacousticsWorkspace(props: Props) {
  return <ProjectAudio key={props.projectId} {...props} />;
}

function ProjectAudio({ projectId, onOpenWorkflow }: Props) {
  const [file, setFile] = useState<File | null>(null);
  const [recordingId, setRecordingId] = useState("");
  const base = recordingsPath(projectId);
  const listings = useAudioList<AudioRecording>(base);
  const cache = useQueryClient();
  const upload = useMutation({
    mutationFn: (source: File) => createAudioRecording(projectId, source),
    onSuccess: (recording) => {
      setRecordingId(recording.id);
      void cache.invalidateQueries({ queryKey: queryKey(base) });
    },
  });
  const selected =
    listings.items.find((item) => item.id === recordingId) ?? listings.items[0];
  function submit(event: FormEvent) {
    event.preventDefault();
    if (file) upload.mutate(file);
  }
  return (
    <section className="rv-audio-workspace" aria-label="Bioacoustics workspace">
      <section
        className="panel rv-audio-panel"
        aria-label="Import and select audio"
      >
        <h3>Import audio</h3>
        <p>
          Use a mono or stereo integer PCM WAV up to 256 MiB. Supported formats
          run from 8 to 96 kHz at 8, 16, 24 or 32 bits.
        </p>
        <form className="rv-audio-fields" onSubmit={submit}>
          <label className="rv-audio-wide">
            <span>Original WAV file</span>
            <input
              type="file"
              accept=".wav,audio/wav,audio/x-wav"
              onChange={(event) =>
                setFile(event.currentTarget.files?.[0] ?? null)
              }
              required
            />
          </label>
          <button type="submit" disabled={!file || upload.isPending}>
            {upload.isPending ? "Importing audio…" : "Import WAV"}
          </button>
        </form>
        <ErrorText error={upload.error ?? listings.error} />
        {selected && (
          <label>
            <span>Audio recording</span>
            <select
              value={selected.id}
              onChange={(event) => setRecordingId(event.target.value)}
            >
              {listings.items.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.original_filename}
                </option>
              ))}
            </select>
          </label>
        )}
        {listings.isPending && <p role="status">Loading project recordings…</p>}
        <LoadMore
          available={listings.hasNextPage}
          loading={listings.isFetchingNextPage}
          onClick={() => void listings.fetchNextPage()}
          label="Load more recordings"
        />
      </section>
      {selected && (
        <RecordingWorkspace
          key={selected.id}
          audio={selected}
          onOpenWorkflow={onOpenWorkflow}
        />
      )}
    </section>
  );
}
