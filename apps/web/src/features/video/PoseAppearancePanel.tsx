import { useEffect, useState } from "react";
import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { getJob, getModels, request, type JobRecord } from "../../api/client";
import { getApiBaseUrl } from "../../runtime";
import { saveWorkflowGraph } from "../workflow-graphs/workflowGraphApi";

interface Observation {
  id: string;
  video_id: string;
  filename: string;
  identity_name: string;
  frame_index: number;
  revision: number;
}
interface Summary {
  id: string;
  name: string;
  content_sha256: string;
}
interface Rates {
  false_links: number;
  impostor_pairs: number;
  missed_links: number;
  genuine_pairs: number;
  false_match_rate: number | null;
  missed_match_rate: number | null;
}
interface Study extends Summary {
  resolution: string;
  decisions: {
    id: string;
    role_slot: string;
    reason: string;
    outcome: string;
    reviewer: { name: string };
  }[];
  snapshot: {
    inputs: {
      model: { name: string; sha256: string };
      crops: {
        key: string;
        filename: string;
        frame: number;
        identity_name?: string;
      }[];
      reference: { data_kind: string } | null;
    };
    result: {
      method: string;
      device: string;
      minimum_similarity: number;
      threshold_source: string;
      ranking: {
        state: string;
        selected: string | null;
        margin: number | null;
        candidates: [string, number][];
      };
      evaluation: {
        heldout: {
          counts: Rates;
          scored_animals: number;
          scored_recording_groups: number;
          decisions: Record<string, number>;
          prespecified_targets?: Record<
            string,
            { limit: number; within_limit: boolean | null }
          >;
        };
      } | null;
    };
  };
}
interface Reference extends Summary {
  manifest: { recordings: { annotations: { rater_id: string }[] }[] };
}

function AppearanceWorkspace({
  projectId,
  videoId,
}: {
  projectId: string;
  videoId: string;
}) {
  const scope = "/projects/" + encodeURIComponent(projectId);
  const base = scope + "/pose-appearance";
  const cache = useQueryClient();
  const [model, setModel] = useState("");
  const [probe, setProbe] = useState("");
  const [gallery, setGallery] = useState<string[]>([]);
  const [name, setName] = useState("Cross-recording appearance");
  const [device, setDevice] = useState("auto");
  const [gap, setGap] = useState("10");
  const [threshold, setThreshold] = useState("0.85");
  const [margin, setMargin] = useState("0.05");
  const [falseRate, setFalseRate] = useState("0.05");
  const [heldoutFalse, setHeldoutFalse] = useState("");
  const [heldoutMissed, setHeldoutMissed] = useState("");
  const [referenceId, setReferenceId] = useState("");
  const [rater, setRater] = useState("");
  const [studyId, setStudyId] = useState("");
  const [jobId, setJobId] = useState("");
  const [roleKey, setRoleKey] = useState("");
  const [decision, setDecision] = useState("uncertain");
  const [candidate, setCandidate] = useState("");
  const [reason, setReason] = useState("");
  const observations = useInfiniteQuery({
    queryKey: ["appearance-observations", projectId],
    initialPageParam: 0,
    queryFn: ({ pageParam, signal }) =>
      request<Observation[]>(
        base + "/observations?limit=100&offset=" + pageParam,
        { signal },
      ),
    getNextPageParam: (last, pages) =>
      last.length === 100 ? pages.length * 100 : undefined,
  });
  const options = observations.data?.pages.flat() ?? [];
  const models = useQuery({
    queryKey: ["appearance-models", projectId],
    queryFn: ({ signal }) => getModels(projectId, undefined, signal),
  });
  const studies = useQuery({
    queryKey: ["appearance-studies", projectId],
    queryFn: ({ signal }) => request<Summary[]>(base + "/studies", { signal }),
  });
  const refs = useQuery({
    queryKey: ["appearance-references", projectId],
    queryFn: ({ signal }) =>
      request<Summary[]>(scope + "/reefpose-references", { signal }),
  });
  const reference = useQuery({
    queryKey: ["appearance-reference", referenceId],
    enabled: !!referenceId,
    queryFn: ({ signal }) =>
      request<Reference>(scope + "/reefpose-references/" + referenceId, {
        signal,
      }),
  });
  const study = useQuery({
    queryKey: ["appearance-study", projectId, studyId],
    enabled: !!studyId,
    queryFn: ({ signal }) =>
      request<Study>(base + "/studies/" + studyId, { signal }),
  });
  const job = useQuery({
    queryKey: ["appearance-job", jobId],
    enabled: !!jobId,
    queryFn: ({ signal }) => getJob(jobId, signal),
    refetchInterval: (q) =>
      ["queued", "running", "cancel_requested"].includes(
        q.state.data?.status ?? "queued",
      )
        ? 600
        : false,
  });
  const queue = useMutation({
    mutationFn: (replay: boolean) =>
      request<JobRecord>(
        base + "/studies" + (replay ? "/" + studyId + "/replay" : ""),
        {
          method: "POST",
          body: JSON.stringify(
            replay
              ? {
                  operation_id: crypto.randomUUID(),
                  study_sha256: study.data?.content_sha256,
                }
              : {
                  operation_id: crypto.randomUUID(),
                  name,
                  model_id: model,
                  query_observation_id: probe,
                  gallery_observation_ids: gallery,
                  device,
                  minimum_gap_seconds: Number(gap),
                  minimum_similarity: Number(threshold),
                  minimum_margin: Number(margin),
                  reference_id: referenceId || null,
                  reference_rater: rater || null,
                  maximum_development_false_rate: Number(falseRate),
                  maximum_heldout_false_rate:
                    referenceId && heldoutFalse !== ""
                      ? Number(heldoutFalse)
                      : null,
                  maximum_heldout_missed_rate:
                    referenceId && heldoutMissed !== ""
                      ? Number(heldoutMissed)
                      : null,
                },
          ),
        },
      ),
    onSuccess: (value) => setJobId(value.id),
  });
  useEffect(() => {
    const id = job.data?.result_json?.study_id;
    if (job.data?.status === "succeeded" && typeof id === "string") {
      setStudyId(id);
      void cache.invalidateQueries({
        queryKey: ["appearance-studies", projectId],
      });
    }
  }, [job.data, cache, projectId]);
  const save = useMutation({
    mutationFn: () =>
      request<Study>(base + "/studies/" + studyId + "/reviews", {
        method: "POST",
        headers: { Authorization: "Bearer " + roleKey },
        body: JSON.stringify({
          operation_id: crypto.randomUUID(),
          study_sha256: study.data?.content_sha256,
          outcome: decision,
          candidate_observation_id: candidate || null,
          reason,
        }),
      }),
    onSuccess: () => {
      setRoleKey("");
      setReason("");
      void cache.invalidateQueries({
        queryKey: ["appearance-study", projectId, studyId],
      });
    },
  });
  const graph = useMutation({
    mutationFn: (s: Study) =>
      saveWorkflowGraph(projectId, {
        graph_id: "appearance-" + s.id,
        name: "Replay " + s.name,
        nodes: [
          { node_id: "project", node_type: "project_source" },
          {
            node_id: "appearance",
            node_type: "reefpose_appearance_replay",
            parameters: { study_id: s.id, study_sha256: s.content_sha256 },
          },
        ],
        edges: [
          {
            edge_id: "project-appearance",
            source_node_id: "project",
            source_port_id: "project",
            target_node_id: "appearance",
            target_port_id: "project",
          },
        ],
      }),
  });
  const busy =
    queue.isPending ||
    ["queued", "running", "cancel_requested"].includes(job.data?.status ?? "");
  const label = (o: Observation) =>
    o.filename +
    " · frame " +
    o.frame_index +
    " · " +
    o.identity_name +
    " · " +
    o.id.slice(0, 8);
  const detail = study.data;
  const results = detail?.snapshot.result;
  const counts = results?.evaluation?.heldout.counts;
  const errors = [
    observations.error,
    models.error,
    studies.error,
    refs.error,
    reference.error,
    study.error,
    queue.error,
    save.error,
    graph.error,
    job.error,
  ].filter(Boolean);
  return (
    <section aria-label="Appearance comparison">
      <label>
        Study name{" "}
        <input value={name} onChange={(e) => setName(e.target.value)} />
      </label>
      <label>
        Trained native checkpoint{" "}
        <select value={model} onChange={(e) => setModel(e.target.value)}>
          <option value="">Select checkpoint</option>
          {models.data
            ?.filter(
              (item) =>
                item.provider_name === "reefpose" && item.task === "pose",
            )
            .map((item) => (
              <option key={item.id} value={item.id}>
                {item.display_name}
              </option>
            ))}
        </select>
      </label>
      <label>
        Reviewed probe from this recording{" "}
        <select
          value={probe}
          onChange={(e) => {
            setProbe(e.target.value);
            setGallery(gallery.filter((id) => id !== e.target.value));
          }}
        >
          <option value="">Select probe</option>
          {options
            .filter((o) => o.video_id === videoId)
            .map((o) => (
              <option key={o.id} value={o.id}>
                {label(o)}
              </option>
            ))}
        </select>
      </label>
      <label>
        Reviewed gallery observations{" "}
        <select
          multiple
          value={gallery}
          onChange={(e) =>
            setGallery(
              Array.from(e.currentTarget.selectedOptions, (o) => o.value),
            )
          }
        >
          {options
            .filter((o) => o.id !== probe)
            .map((o) => (
              <option key={o.id} value={o.id}>
                {label(o)}
              </option>
            ))}
        </select>
      </label>
      {observations.hasNextPage && (
        <button type="button" onClick={() => void observations.fetchNextPage()}>
          Load more reviewed observations
        </button>
      )}
      <label>
        Minimum same-recording gap (seconds){" "}
        <input
          type="number"
          min="0.001"
          step="any"
          value={gap}
          onChange={(e) => setGap(e.target.value)}
        />
      </label>
      <label>
        Minimum winning margin{" "}
        <input
          type="number"
          min="0"
          max="2"
          step="any"
          value={margin}
          onChange={(e) => setMargin(e.target.value)}
        />
      </label>
      <label>
        Frozen independent reference{" "}
        <select
          value={referenceId}
          onChange={(e) => {
            setReferenceId(e.target.value);
            setRater("");
          }}
        >
          <option value="">Use a researcher-specified threshold</option>
          {refs.data?.map((ref) => (
            <option key={ref.id} value={ref.id}>
              {ref.name}
            </option>
          ))}
        </select>
      </label>
      {referenceId ? (
        <>
          <label>
            Reference rater{" "}
            <select value={rater} onChange={(e) => setRater(e.target.value)}>
              <option value="">Select rater</option>
              {reference.data?.manifest.recordings[0]?.annotations.map((a) => (
                <option key={a.rater_id}>{a.rater_id}</option>
              ))}
            </select>
          </label>
          <label>
            Maximum development false-match rate{" "}
            <input
              type="number"
              min="0"
              max="1"
              step="any"
              value={falseRate}
              onChange={(e) => setFalseRate(e.target.value)}
            />
          </label>
          <label>
            Prespecified held-out false-match limit (optional)
            <input
              type="number"
              min="0"
              max="1"
              step="any"
              value={heldoutFalse}
              onChange={(e) => setHeldoutFalse(e.target.value)}
            />
          </label>
          <label>
            Prespecified held-out missed-match limit (optional)
            <input
              type="number"
              min="0"
              max="1"
              step="any"
              value={heldoutMissed}
              onChange={(e) => setHeldoutMissed(e.target.value)}
            />
          </label>
        </>
      ) : (
        <label>
          Minimum cosine similarity{" "}
          <input
            type="number"
            min="-1"
            max="1"
            step="any"
            value={threshold}
            onChange={(e) => setThreshold(e.target.value)}
          />
        </label>
      )}
      <label>
        Appearance device{" "}
        <select value={device} onChange={(e) => setDevice(e.target.value)}>
          <option value="auto">Automatic</option>
          <option value="cpu">CPU</option>
          <option value="cuda">CUDA</option>
        </select>
      </label>
      <button
        type="button"
        disabled={
          busy ||
          !name.trim() ||
          !model ||
          !probe ||
          !gallery.length ||
          (!!referenceId && !rater)
        }
        onClick={() => queue.mutate(false)}
      >
        Compare reviewed appearances
      </button>
      {job.data && (
        <p role="status">
          Appearance job {job.data.status}
          {job.data.error_message ? " · " + job.data.error_message : ""}
        </p>
      )}
      <label>
        Saved appearance study{" "}
        <select
          value={studyId}
          onChange={(e) => {
            setStudyId(e.target.value);
            setCandidate("");
            setReason("");
          }}
        >
          <option value="">Choose study</option>
          {studies.data?.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
      </label>
      {detail && results && (
        <article aria-label="Appearance result">
          <h5>{detail.name}</h5>
          <p>
            Model proposal: {results.ranking.state} · Review:{" "}
            {detail.resolution}
          </p>
          <p>
            {detail.snapshot.inputs.model.name} · {results.device} · cosine
            threshold {results.minimum_similarity.toFixed(5)} (
            {results.threshold_source})
          </p>
          {detail.snapshot.inputs.crops.map((o, i) => (
            <figure key={o.key}>
              <img
                width={104}
                loading="lazy"
                src={
                  getApiBaseUrl() +
                  base +
                  "/studies/" +
                  detail.id +
                  "/crops/" +
                  o.key
                }
                alt={
                  (i ? "Gallery" : "Probe") +
                  " crop, " +
                  o.filename +
                  ", frame " +
                  o.frame
                }
              />
              <figcaption>
                {i ? "Gallery " + i : "Probe"} · {o.identity_name ?? o.key} ·{" "}
                {o.filename} · frame {o.frame}
                {results.ranking.selected === o.key && " · proposed match"}
                {i
                  ? " · similarity " +
                    results.ranking.candidates
                      .find(([key]) => key === o.key)?.[1]
                      .toFixed(5)
                  : ""}
              </figcaption>
            </figure>
          ))}
          {counts && results.evaluation && (
            <p>
              Held-out {detail.snapshot.inputs.reference?.data_kind} reference ·{" "}
              {results.evaluation.heldout.scored_animals} animals ·{" "}
              {results.evaluation.heldout.scored_recording_groups} recording
              groups. False matches {counts.false_links}/{counts.impostor_pairs}{" "}
              ({counts.false_match_rate?.toFixed(3) ?? "undefined"}). Missed
              matches {counts.missed_links}/{counts.genuine_pairs} (
              {counts.missed_match_rate?.toFixed(3) ?? "undefined"}).
            </p>
          )}
          {Object.entries(
            results.evaluation?.heldout.prespecified_targets ?? {},
          ).map(([metric, target]) => (
            <p key={metric}>
              {metric === "false_match_rate" ? "False-match" : "Missed-match"}{" "}
              limit {target.limit}.{" "}
              {target.within_limit === null
                ? "No eligible denominator."
                : target.within_limit
                  ? "Within the prespecified limit."
                  : "Exceeds the prespecified limit."}
            </p>
          ))}
          <label>
            Reviewer Lab role key{" "}
            <input
              type="password"
              autoComplete="off"
              value={roleKey}
              onChange={(e) => setRoleKey(e.target.value)}
            />
          </label>
          <label>
            Reviewed gallery candidate{" "}
            <select
              value={candidate}
              onChange={(e) => setCandidate(e.target.value)}
            >
              <option value="">Unresolved</option>
              {detail.snapshot.inputs.crops.slice(1).map((o, i) => (
                <option key={o.key} value={o.key}>
                  Gallery {i + 1} · {o.identity_name ?? o.key} · {o.filename} ·
                  frame {o.frame}
                </option>
              ))}
            </select>
          </label>
          <label>
            Identity judgement{" "}
            <select
              value={decision}
              onChange={(e) => setDecision(e.target.value)}
            >
              <option value="uncertain">Uncertain</option>
              <option value="same">Same animal</option>
              <option value="different">Different animal</option>
            </select>
          </label>
          <label>
            Judgement reason{" "}
            <input value={reason} onChange={(e) => setReason(e.target.value)} />
          </label>
          <button
            type="button"
            disabled={
              !roleKey ||
              !reason.trim() ||
              save.isPending ||
              (decision !== "uncertain" && !candidate)
            }
            onClick={() => save.mutate()}
          >
            Record independent judgement
          </button>
          {detail.decisions.map((d) => (
            <p key={d.id}>
              {d.reviewer.name} · {d.outcome} · {d.reason}
            </p>
          ))}
          <button
            type="button"
            disabled={busy}
            onClick={() => queue.mutate(true)}
          >
            Replay frozen appearance study
          </button>
          <button
            type="button"
            disabled={graph.isPending}
            onClick={() => graph.mutate(detail)}
          >
            Save replay in Workflow Builder
          </button>
          {graph.data && (
            <p role="status">
              Saved workflow “{graph.data.name}” · revision{" "}
              {graph.data.revision}
            </p>
          )}
          <a
            href={getApiBaseUrl() + base + "/studies/" + detail.id + "/export"}
            download
          >
            Export appearance report
          </a>
        </article>
      )}
      {errors.map((e, i) => (
        <p key={i} role="alert">
          {e instanceof Error ? e.message : "Appearance operation failed"}
        </p>
      ))}
    </section>
  );
}

export function PoseAppearancePanel({
  projectId,
  videoId,
}: {
  projectId: string;
  videoId: string;
}) {
  const [open, setOpen] = useState(false);
  return (
    <details onToggle={(e) => setOpen(e.currentTarget.open)}>
      <summary>Appearance across gaps and recordings</summary>
      {open && (
        <AppearanceWorkspace
          key={projectId + videoId}
          projectId={projectId}
          videoId={videoId}
        />
      )}
    </details>
  );
}
