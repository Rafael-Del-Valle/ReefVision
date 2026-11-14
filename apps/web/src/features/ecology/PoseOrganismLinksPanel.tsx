import {
  useMutation,
  useQueries,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { ErrorState, LoadingState } from "../../components/ui/AsyncState";
import {
  listBiologicalEvents,
  listEventRuns,
  listMeasurementRuns,
  listMeasurementSeries,
} from "../video/biologicalMovementApi";
import {
  getPoseIdentityIdentities,
  getPoseIdentityObservations,
  listPoseIdentityRuns,
} from "../video/poseIdentityTrackingApi";
import { getVideos } from "../video/videoApi";
import type { PoseEvidenceNavigation } from "../video/videoWorkspaceBridge";
import {
  getPoseOrganismLinkHistory,
  listPoseOrganismLinks,
  savePoseOrganismLink,
  unlinkPoseOrganism,
  type PoseLink,
  type Review,
} from "./poseOrganismLinksApi";

export type { PoseEvidenceNavigation } from "../video/videoWorkspaceBridge";

type OpenEvidence = (evidence: PoseEvidenceNavigation) => void;
type FormSource = {
  projectId: string;
  organismRevisionId: string;
  link?: PoseLink;
};

function review(form: FormData): Review {
  return {
    confirm: true,
    reviewer: String(form.get("reviewer") ?? "").trim(),
    reason: String(form.get("reason") ?? "").trim(),
  };
}

function ReviewFields({ action }: { action: string }) {
  return (
    <>
      <label>
        Reviewer
        <input name="reviewer" required maxLength={100} />
      </label>
      <label>
        Reason
        <input name="reason" required minLength={3} maxLength={500} />
      </label>
      <label>
        <input type="checkbox" required name="confirm" />
        {action}
      </label>
    </>
  );
}

function failMessage(error: unknown) {
  return error instanceof Error
    ? error.message
    : "The evidence could not be loaded.";
}

function LinkForm({
  projectId,
  organismRevisionId,
  link,
  onSaved,
}: FormSource & { onSaved: () => void }) {
  const [runId, setRunId] = useState(link?.association_run_id ?? "");
  const [animalId, setAnimalId] = useState(link?.animal_identity_id ?? "");
  const [start, setStart] = useState(link ? String(link.frame_start) : "");
  const [end, setEnd] = useState(link ? String(link.frame_end) : "");
  const videos = useQuery({
    queryKey: ["project-videos", projectId],
    queryFn: ({ signal }) => getVideos(projectId, signal),
  });
  const runs = useQuery({
    queryKey: ["pose-identity-runs", projectId],
    queryFn: ({ signal }) => listPoseIdentityRuns(projectId, signal),
  });
  const completed = (runs.data ?? []).filter(
    (run) => run.status === "completed",
  );
  const run = completed.find((item) => item.id === runId);
  const identities = useQuery({
    queryKey: ["pose-identity-identities", runId],
    queryFn: ({ signal }) => getPoseIdentityIdentities(runId, signal),
    enabled: !!run,
  });
  const observations = useQuery({
    queryKey: ["pose-identity-observations", runId],
    queryFn: ({ signal }) => getPoseIdentityObservations(runId, signal),
    enabled: !!run,
  });
  const active = (identities.data ?? []).filter(
    (item) => item.lifecycle_state === "active",
  );
  const animal = active.find((item) => item.id === animalId);
  const scope = (observations.data ?? []).filter(
    (item) =>
      item.animal_identity_id === animalId &&
      item.frame_index >= Number(start) &&
      item.frame_index <= Number(end),
  );
  const reviewed = scope.filter((item) =>
    ["scientist_verified", "scientist_confirmed"].includes(
      item.verification_state,
    ),
  );
  const ready =
    !!run &&
    !!animal &&
    start !== "" &&
    end !== "" &&
    reviewed.length > 0 &&
    reviewed.length === scope.length;

  const measurementRuns = useQuery({
    queryKey: ["pose-measurement-runs", projectId],
    queryFn: ({ signal }) => listMeasurementRuns(projectId, signal),
    enabled: ready,
  });
  const matchingMeasurements = (measurementRuns.data ?? []).filter(
    (item) =>
      item.source_identity_run_id === runId &&
      item.source_identity_run_revision === run?.revision &&
      item.status === "completed" &&
      item.verification_state === "scientific",
  );
  const measurementSeries = useQueries({
    queries: matchingMeasurements.map((item) => ({
      queryKey: ["pose-measurement-series", item.id],
      queryFn: ({ signal }: { signal: AbortSignal }) =>
        listMeasurementSeries(item.id, signal),
    })),
  });
  const series = measurementSeries
    .flatMap((query) => query.data ?? [])
    .filter((item) => item.animal_identity_id === animalId);
  const eventRuns = useQuery({
    queryKey: ["pose-event-runs", projectId],
    queryFn: ({ signal }) => listEventRuns(projectId, signal),
    enabled: ready,
  });
  const matchingEvents = (eventRuns.data ?? []).filter(
    (item) =>
      item.status === "completed" &&
      matchingMeasurements.some(
        (measurement) => measurement.id === item.measurement_run_id,
      ),
  );
  const eventRevisions = useQueries({
    queries: matchingEvents.map((item) => ({
      queryKey: ["pose-biological-events", item.id],
      queryFn: ({ signal }: { signal: AbortSignal }) =>
        listBiologicalEvents(item.id, false, signal),
    })),
  });
  const events = eventRevisions
    .flatMap((query) => query.data ?? [])
    .filter(
      (item) =>
        item.animal_identity_id === animalId &&
        item.review_state === "confirmed" &&
        item.start_frame >= Number(start) &&
        item.end_frame !== null &&
        item.end_frame <= Number(end),
    );
  const mutation = useMutation({
    mutationFn: (form: FormData) => {
      if (!run || !animal || !ready || !form.has("confirm")) {
        throw new Error(
          "Select reviewed evidence and explicitly confirm the link.",
        );
      }
      return savePoseOrganismLink(
        projectId,
        {
          ...review(form),
          organism_revision_id: organismRevisionId,
          association_run_id: run.id,
          animal_identity_id: animal.id,
          expected_identity_run_revision: run.revision,
          expected_pose_schema_sha256: run.pose_schema_content_hash,
          frame_start: Number(start),
          frame_end: Number(end),
          measurement_series_ids: form.getAll("measurement").map(String),
          event_revision_ids: form.getAll("event").map(String),
        },
        link,
      );
    },
    onSuccess: onSaved,
  });
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    mutation.mutate(new FormData(event.currentTarget));
  }
  if (runs.isPending || videos.isPending)
    return <LoadingState title="Loading source recordings" />;
  const error = runs.error ?? videos.error;
  if (error)
    return (
      <ErrorState
        title="Source recordings unavailable"
        message={failMessage(error)}
        onRetry={() => {
          void runs.refetch();
          void videos.refetch();
        }}
      />
    );
  if (!completed.length)
    return (
      <p>
        Complete and review an identity association run in Video &amp; tracking
        to link pose evidence.
      </p>
    );
  return (
    <form
      className="panel-card"
      onSubmit={submit}
      aria-label={link ? "Correct pose link" : "Link reviewed pose"}
    >
      <label>
        Reviewed identity run
        <select
          value={runId}
          onChange={(event) => {
            setRunId(event.target.value);
            setAnimalId("");
            setStart("");
            setEnd("");
          }}
          required
        >
          <option value="">Select a recording and run</option>
          {completed.map((item) => (
            <option key={item.id} value={item.id}>
              {videos.data?.find((video) => video.id === item.video_id)
                ?.original_filename ?? item.video_id}{" "}
              · revision {item.revision} · {item.id.slice(0, 8)}
            </option>
          ))}
        </select>
      </label>
      <label>
        Animal identity
        <select
          value={animalId}
          disabled={!run}
          required
          onChange={(event) => {
            const picked = active.find(
              (item) => item.id === event.target.value,
            );
            setAnimalId(event.target.value);
            setStart(picked ? String(picked.first_frame) : "");
            setEnd(
              picked ? String(picked.last_frame ?? picked.first_frame) : "",
            );
          }}
        >
          <option value="">Select an animal</option>
          {active.map((item) => (
            <option key={item.id} value={item.id}>
              {item.display_name ?? item.stable_identity_key}
            </option>
          ))}
        </select>
      </label>
      <label>
        First frame
        <input
          type="number"
          min={0}
          step={1}
          required
          value={start}
          onChange={(event) => setStart(event.target.value)}
        />
      </label>
      <label>
        Last frame
        <input
          type="number"
          min={Number(start)}
          step={1}
          required
          value={end}
          onChange={(event) => setEnd(event.target.value)}
        />
      </label>
      {animal && (
        <p className="annotation-helper">
          {reviewed.length} reviewed observations in the interval
          {scope.length !== reviewed.length &&
            " · Review unresolved observations before linking"}
          {ready &&
            Number(end) - Number(start) + 1 > reviewed.length &&
            " · Frames without reviewed observations remain gaps"}
        </p>
      )}
      {(identities.error ?? observations.error) && (
        <p role="alert">
          {failMessage(identities.error ?? observations.error)}
        </p>
      )}
      {ready && (series.length > 0 || events.length > 0) && (
        <details key={`${runId}/${animalId}/${start}/${end}`}>
          <summary>Attach reviewed measurements and events</summary>
          {series.map((item) => (
            <label key={item.id}>
              <input
                name="measurement"
                type="checkbox"
                value={item.id}
                defaultChecked={link?.source.measurements.some(
                  (row) => row.id === item.id,
                )}
              />
              {item.display_name}
            </label>
          ))}
          {events.map((item) => (
            <label key={item.id}>
              <input
                name="event"
                type="checkbox"
                value={item.id}
                defaultChecked={link?.source.events.some(
                  (row) => row.id === item.id,
                )}
              />
              Confirmed event · frames {item.start_frame}–{item.end_frame}
            </label>
          ))}
        </details>
      )}
      <ReviewFields action="I confirm this organism identity for the selected pose evidence" />
      <button type="submit" disabled={!ready || mutation.isPending}>
        {link ? "Save link correction" : "Confirm pose link"}
      </button>
      {mutation.error && <p role="alert">{mutation.error.message}</p>}
    </form>
  );
}

function EvidenceButtons({
  link,
  onOpen,
}: {
  link: PoseLink;
  onOpen: OpenEvidence;
}) {
  const selected = link.source.observations[0];
  const source = {
    videoId: link.source.video_id,
    frameIndex: selected.frame_index,
    sourceTrackId: selected.source_video_track_id,
    identityRunId: link.association_run_id,
    animalIdentityId: link.animal_identity_id,
  };
  return (
    <div className="inline-actions">
      <button type="button" onClick={() => onOpen(source)}>
        Open pose evidence
      </button>
      {link.source.measurements.map((item) => (
        <button
          key={item.id}
          type="button"
          onClick={() =>
            onOpen({
              ...source,
              measurementRunId: item.run_id,
              measurementSeriesId: item.id,
            })
          }
        >
          Open {item.name}
        </button>
      ))}
      {link.source.events.map((item) => (
        <button
          key={item.id}
          type="button"
          onClick={() =>
            onOpen({
              ...source,
              frameIndex: item.start_frame,
              measurementRunId: link.source.measurements.find(
                (measurement) => measurement.id === item.measurement_series_id,
              )?.run_id,
              measurementSeriesId: item.measurement_series_id,
              eventRunId: item.run_id,
              eventRevisionId: item.id,
            })
          }
        >
          Open event at frame {item.start_frame}
        </button>
      ))}
    </div>
  );
}

function LinkCard({
  projectId,
  organismRevisionId,
  link,
  onOpen,
  invalidate,
}: FormSource & {
  link: PoseLink;
  onOpen?: OpenEvidence;
  invalidate: () => Promise<void>;
}) {
  const [edit, setEdit] = useState<"correct" | "unlink" | null>(null);
  const [showHistory, setShowHistory] = useState(false);
  const history = useQuery({
    queryKey: ["ecology-pose-link-history", projectId, link.link_id],
    queryFn: ({ signal }) =>
      getPoseOrganismLinkHistory(projectId, link.link_id, signal),
    enabled: showHistory,
  });
  function saved() {
    setEdit(null);
    void invalidate();
  }
  const remove = useMutation({
    mutationFn: (form: FormData) => {
      if (!form.has("confirm"))
        throw new Error("Confirm unlinking before saving.");
      return unlinkPoseOrganism(projectId, link, review(form));
    },
    onSuccess: saved,
  });
  return (
    <article className="panel-card">
      <h4>
        Frames {link.frame_start}–{link.frame_end}
      </h4>
      <p>
        {link.status === "current"
          ? "Confirmed link"
          : link.status === "stale"
            ? "Stale evidence"
            : link.status === "superseded"
              ? "Superseded link"
              : "Unlinked"}
      </p>
      {link.stale_reason && (
        <p role="status">
          {link.stale_reason}. Review and correct this link before using its
          evidence.
        </p>
      )}
      {onOpen && <EvidenceButtons link={link} onOpen={onOpen} />}
      {(link.status === "current" || link.status === "stale") && (
        <div className="inline-actions">
          <button
            type="button"
            aria-expanded={edit === "correct"}
            onClick={() => setEdit(edit === "correct" ? null : "correct")}
          >
            Correct link
          </button>
          <button
            type="button"
            aria-expanded={edit === "unlink"}
            onClick={() => setEdit(edit === "unlink" ? null : "unlink")}
          >
            Unlink
          </button>
        </div>
      )}
      {edit === "correct" && (
        <LinkForm
          projectId={projectId}
          organismRevisionId={organismRevisionId}
          link={link}
          onSaved={saved}
        />
      )}
      {edit === "unlink" && (
        <form
          aria-label="Unlink reviewed pose"
          onSubmit={(event) => {
            event.preventDefault();
            remove.mutate(new FormData(event.currentTarget));
          }}
        >
          <ReviewFields action="I confirm removing this link" />
          <button type="submit" disabled={remove.isPending}>
            Confirm unlink
          </button>
          {remove.error && <p role="alert">{remove.error.message}</p>}
        </form>
      )}
      <details onToggle={(event) => setShowHistory(event.currentTarget.open)}>
        <summary>Link history and provenance</summary>
        {history.isPending && <p>Loading revisions…</p>}
        {history.isError && <p role="alert">{history.error.message}</p>}
        <ol>
          {history.data?.map((item) => (
            <li key={item.id}>
              r{item.revision} · {item.action} · {item.reviewer} ·{" "}
              {new Date(item.created_at).toLocaleString()}
              <p>{item.reason}</p>
              <code>{item.source_sha256}</code>
            </li>
          ))}
        </ol>
      </details>
    </article>
  );
}

export function PoseOrganismLinksPanel({
  projectId,
  organismKey,
  organismRevisionId,
  onOpenPoseEvidence,
}: {
  projectId: string;
  organismKey: string;
  organismRevisionId: string;
  onOpenPoseEvidence?: OpenEvidence;
}) {
  const queryClient = useQueryClient();
  const [offset, setOffset] = useState(0);
  const [showForm, setShowForm] = useState(false);
  const queryKey = ["ecology-pose-links", projectId, organismKey];
  const links = useQuery({
    queryKey: [...queryKey, offset],
    queryFn: ({ signal }) =>
      listPoseOrganismLinks(projectId, organismKey, offset, signal),
  });
  async function invalidate() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey }),
      queryClient.invalidateQueries({
        queryKey: ["ecology-pose-link-history", projectId],
      }),
    ]);
  }
  return (
    <section className="management-card" aria-label="Reviewed pose links">
      <h3>Reviewed pose links</h3>
      <button
        type="button"
        aria-expanded={showForm}
        onClick={() => setShowForm(!showForm)}
      >
        Link reviewed pose
      </button>
      {showForm && (
        <LinkForm
          projectId={projectId}
          organismRevisionId={organismRevisionId}
          onSaved={() => {
            setShowForm(false);
            setOffset(0);
            void invalidate();
          }}
        />
      )}
      {links.isPending && <LoadingState title="Loading reviewed pose links" />}
      {links.isError && (
        <ErrorState
          title="Reviewed pose links unavailable"
          message={links.error.message}
          onRetry={() => void links.refetch()}
        />
      )}
      {links.data?.total === 0 && <p>No reviewed links for this organism.</p>}
      {links.data?.items.map((item) => (
        <LinkCard
          key={item.link_id}
          projectId={projectId}
          organismRevisionId={organismRevisionId}
          link={item}
          onOpen={onOpenPoseEvidence}
          invalidate={invalidate}
        />
      ))}
      {links.data && links.data.total > links.data.limit && (
        <div className="inline-actions">
          <button
            type="button"
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - links.data.limit))}
          >
            Previous links
          </button>
          <button
            type="button"
            disabled={offset + links.data.limit >= links.data.total}
            onClick={() => setOffset(offset + links.data.limit)}
          >
            Next links
          </button>
        </div>
      )}
    </section>
  );
}
