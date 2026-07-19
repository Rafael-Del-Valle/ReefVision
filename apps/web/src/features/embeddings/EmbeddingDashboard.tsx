import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import { getApiBaseUrl } from "../../runtime";
import type { Project } from "../../api/client";
import { getJob } from "../phase456/api";

interface EmbeddingRecord {
  id: string;
  image_id: string;
  embedding_model_id: string;
  embedding_model_checksum: string | null;
  dimension: number;
  vector_sha256: string;
  source_json: Record<string, unknown>;
}

interface EmbeddingGenerationResult {
  embedding_model_id: string;
  requested_image_count: number;
  job: { id: string; status: string };
}

interface DiversitySelectionResult {
  candidate_count: number;
  selected_count: number;
  skipped_missing_embedding_count: number;
  vector_dimension: number | null;
  warnings: string[];
  selections: Array<{
    image_id: string;
    group_key: string | null;
    rank: number;
    base_score: number;
    novelty_score: number;
    selection_score: number;
    nearest_selected_image_id: string | null;
  }>;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${getApiBaseUrl()}${path}`, init);
  if (!response.ok) {
    let message = `Request failed with HTTP ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body.detail) message = body.detail;
    } catch {
      // Keep fallback.
    }
    throw new Error(message);
  }
  return (await response.json()) as T;
}

export function EmbeddingDashboard({ project }: { project: Project }) {
  const queryClient = useQueryClient();
  const [provider, setProvider] = useState("color_texture_v1");
  const [modelId, setModelId] = useState("reefvision-color-texture-v1");
  const [device, setDevice] = useState("auto");
  const [localOnly, setLocalOnly] = useState(true);
  const [replaceExisting, setReplaceExisting] = useState(false);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [maximumItems, setMaximumItems] = useState(25);
  const [diversityWeight, setDiversityWeight] = useState(0.7);
  const [maximumPerGroup, setMaximumPerGroup] = useState(3);
  const [selection, setSelection] = useState<DiversitySelectionResult | null>(
    null,
  );

  const embeddings = useQuery({
    queryKey: ["project_embeddings", project.id, modelId],
    queryFn: ({ signal }) => {
      const params = new URLSearchParams({ embedding_model_id: modelId });
      return request<EmbeddingRecord[]>(
        `/projects/${project.id}/embeddings?${params}`,
        { signal },
      );
    },
    enabled: modelId.length > 0,
  });
  const activeJob = useQuery({
    queryKey: ["job", activeJobId],
    queryFn: ({ signal }) => getJob(activeJobId as string, signal),
    enabled: activeJobId !== null,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status && ["succeeded", "failed", "cancelled"].includes(status)
        ? false
        : 1000;
    },
  });

  useEffect(() => {
    if (activeJob.data?.status === "succeeded") {
      void queryClient.invalidateQueries({
        queryKey: ["project_embeddings", project.id],
      });
    }
  }, [activeJob.data?.status, project.id, queryClient]);

  const providerCounts = useMemo(() => {
    const counts = new Map<string, number>();
    (embeddings.data ?? []).forEach((embedding) => {
      const source = String(embedding.source_json.provider_id ?? "unknown");
      counts.set(source, (counts.get(source) ?? 0) + 1);
    });
    return counts;
  }, [embeddings.data]);

  const generation = useMutation({
    mutationFn: () =>
      request<EmbeddingGenerationResult>(
        `/projects/${project.id}/embedding-jobs`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            provider_id: provider,
            model_id: modelId,
            device,
            local_files_only: localOnly,
            image_ids: [],
            replace_existing: replaceExisting,
          }),
        },
      ),
    onSuccess: (result) => setActiveJobId(result.job.id),
  });

  const diversity = useMutation({
    mutationFn: () =>
      request<DiversitySelectionResult>(
        `/projects/${project.id}/embedding-diversity-selection`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            embedding_model_id: modelId,
            candidate_image_ids: [],
            maximum_items: maximumItems,
            diversity_weight: diversityWeight,
            base_scores: {},
            maximum_items_per_group:
              maximumPerGroup > 0 ? maximumPerGroup : null,
          }),
        },
      ),
    onSuccess: setSelection,
  });

  return (
    <section className="dashboard-panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Phase 7</p>
          <h3>Embedding active learning</h3>
          <span>
            Generate local visual embeddings, rank novelty, and build a balanced
            review batch without exporting vectors to a cloud service.
          </span>
        </div>
        <span>{embeddings.data?.length ?? 0} matching embeddings</span>
      </div>

      <div className="dashboard-layout">
        <div className="dashboard-sidebar">
          <article className="dashboard-card">
            <h4>Embedding provider</h4>
            <label>
              Provider
              <select
                value={provider}
                onChange={(event) => {
                  const next = event.target.value;
                  setProvider(next);
                  setModelId(
                    next === "color_texture_v1"
                      ? "reefvision-color-texture-v1"
                      : "facebook/dinov2-small",
                  );
                }}
              >
                <option value="color_texture_v1">
                  Local color and texture · immediate
                </option>
                <option value="transformers_vision">
                  Local Transformers vision model
                </option>
              </select>
            </label>
            <label>
              Model ID or local path
              <input
                value={modelId}
                onChange={(event) => setModelId(event.target.value)}
              />
            </label>
            <label>
              Device
              <select
                value={device}
                onChange={(event) => setDevice(event.target.value)}
              >
                <option value="auto">Auto</option>
                <option value="cpu">CPU</option>
                <option value="cuda">CUDA</option>
              </select>
            </label>
            <label className="toggle-row">
              <input
                type="checkbox"
                checked={localOnly}
                disabled={provider === "color_texture_v1"}
                onChange={(event) => setLocalOnly(event.target.checked)}
              />
              Use installed/local models only
            </label>
            <label className="toggle-row">
              <input
                type="checkbox"
                checked={replaceExisting}
                onChange={(event) => setReplaceExisting(event.target.checked)}
              />
              Replace matching existing embeddings
            </label>
            <button
              type="button"
              disabled={generation.isPending || !modelId.trim()}
              onClick={() => generation.mutate()}
            >
              {generation.isPending
                ? "Queueing..."
                : "Generate project embeddings"}
            </button>
            {generation.error && (
              <p className="form-error">{generation.error.message}</p>
            )}
            {activeJob.data && (
              <p>
                {activeJob.data.status} · {activeJob.data.progress_current}/
                {activeJob.data.progress_total}
              </p>
            )}
          </article>

          <article className="dashboard-card">
            <h4>Diversity batch</h4>
            <label>
              Maximum images
              <input
                type="number"
                min="1"
                max="5000"
                value={maximumItems}
                onChange={(event) =>
                  setMaximumItems(Number(event.target.value))
                }
              />
            </label>
            <label>
              Diversity weight: {diversityWeight.toFixed(2)}
              <input
                type="range"
                min="0"
                max="1"
                step="0.05"
                value={diversityWeight}
                onChange={(event) =>
                  setDiversityWeight(Number(event.target.value))
                }
              />
            </label>
            <label>
              Maximum per group
              <input
                type="number"
                min="0"
                max="5000"
                value={maximumPerGroup}
                onChange={(event) =>
                  setMaximumPerGroup(Number(event.target.value))
                }
              />
            </label>
            <button
              type="button"
              disabled={diversity.isPending || !modelId.trim()}
              onClick={() => diversity.mutate()}
            >
              {diversity.isPending ? "Selecting..." : "Select diverse batch"}
            </button>
            {diversity.error && (
              <p className="form-error">{diversity.error.message}</p>
            )}
          </article>
        </div>

        <div className="dashboard-main">
          <article className="dashboard-card">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Coverage</p>
                <h4>Stored embeddings</h4>
              </div>
            </div>
            {embeddings.isPending ? (
              <p>Loading...</p>
            ) : (
              <div className="version-preview-metrics">
                <span>Total: {embeddings.data?.length ?? 0}</span>
                <span>
                  Dimension: {embeddings.data?.[0]?.dimension ?? "Unavailable"}
                </span>
                {[...providerCounts.entries()].map(([name, count]) => (
                  <span key={name}>
                    {name}: {count}
                  </span>
                ))}
              </div>
            )}
          </article>

          <article className="dashboard-card">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Selected batch</p>
                <h4>Novelty and group balance</h4>
              </div>
              <span>{selection?.selected_count ?? 0} selected</span>
            </div>
            {selection === null ? (
              <p>Generate embeddings, then select a batch.</p>
            ) : (
              <>
                <div className="version-preview-metrics">
                  <span>Candidates: {selection.candidate_count}</span>
                  <span>
                    Missing: {selection.skipped_missing_embedding_count}
                  </span>
                  <span>
                    Dimension: {selection.vector_dimension ?? "Unavailable"}
                  </span>
                </div>
                {selection.warnings.map((warning) => (
                  <p key={warning} className="annotation-helper">
                    {warning}
                  </p>
                ))}
                <div className="dashboard-list">
                  {selection.selections.map((item) => (
                    <div key={item.image_id} className="dashboard-row">
                      <div>
                        <strong>
                          #{item.rank} · {item.image_id}
                        </strong>
                        <p>{item.group_key ?? "Ungrouped"}</p>
                        <small>
                          Nearest selected:{" "}
                          {item.nearest_selected_image_id ?? "seed"}
                        </small>
                      </div>
                      <span>
                        novelty {item.novelty_score.toFixed(3)} · score{" "}
                        {item.selection_score.toFixed(3)}
                      </span>
                    </div>
                  ))}
                </div>
              </>
            )}
          </article>
        </div>
      </div>
    </section>
  );
}
