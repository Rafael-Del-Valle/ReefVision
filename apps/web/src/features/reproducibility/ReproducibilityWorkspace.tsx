import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { type FormEvent, useState } from "react";

import { request } from "../../api/client";
import { listStudyDesigns } from "../ecology/studyDesignApi";
import { labRequest } from "../reviewer-lab/reviewerLabApi";
import {
  saveWorkflowGraph,
  type WorkflowGraphRecord,
} from "../workflow-graphs/workflowGraphApi";
import {
  ReproducibilityImportPanel,
  ResearchManifestDetails,
} from "./ReproducibilityImportPanel";
import {
  createResearchPackage,
  downloadResearchPackageUrl,
  listResearchPackages,
  type ResearchSelection,
} from "./reproducibilityApi";

type Comparison = {
  id: string;
  task: string;
  created_at: string;
  content_sha256: string;
};
const PAGE_SIZE = 25;
const initialSelection: ResearchSelection = {
  study_design_id: "",
  reviewer_report_id: "",
  comparison_id: "",
  include_media: true,
  include_model_weights: false,
};

export function ReproducibilityWorkspace({
  projectId,
  onOpenProject,
  onOpenWorkflow,
}: {
  projectId: string;
  onOpenProject: (projectId: string) => void;
  onOpenWorkflow: (graph: WorkflowGraphRecord) => void;
}) {
  const cache = useQueryClient();
  const [selection, setSelection] = useState(initialSelection);
  const [selectedId, setSelectedId] = useState("");
  const study = useInfiniteQuery({
    queryKey: ["research-study-options", projectId],
    queryFn: ({ signal, pageParam }) =>
      listStudyDesigns(projectId, pageParam, signal),
    initialPageParam: 1,
    getNextPageParam: (last, all, page) =>
      all.reduce((count, result) => count + result.items.length, 0) < last.total
        ? page + 1
        : undefined,
  });
  const reviewers = useQuery({
    queryKey: ["research-review-options", projectId],
    queryFn: ({ signal }) =>
      labRequest<{ id: string; title: string }[]>(projectId, "/reports", {
        signal,
      }),
  });
  const comparisons = useInfiniteQuery({
    queryKey: ["research-comparison-options", projectId],
    queryFn: ({ signal, pageParam }) =>
      request<Comparison[]>(
        "/projects/" +
          encodeURIComponent(projectId) +
          "/paired-model-comparisons?completed_only=true&limit=" +
          PAGE_SIZE +
          "&offset=" +
          pageParam,
        { signal },
      ),
    initialPageParam: 0,
    getNextPageParam: (last, _, offset) =>
      last.length === PAGE_SIZE ? offset + PAGE_SIZE : undefined,
  });
  const packageKey = ["reproducibility-packages", projectId];
  const history = useQuery({
    queryKey: packageKey,
    queryFn: ({ signal }) => listResearchPackages(projectId, signal),
    refetchInterval: ({ state }) =>
      state.data?.some(
        (row) => row.status === "queued" || row.status === "running",
      )
        ? 1000
        : false,
  });
  const build = useMutation({
    mutationFn: () => createResearchPackage(projectId, selection),
    onSuccess: ({ package: row }) => {
      cache.setQueryData(packageKey, (prior: typeof history.data) => [
        row,
        ...(prior ?? []),
      ]);
      setSelectedId(row.id);
      void history.refetch();
    },
  });
  const save = useMutation({
    mutationFn: (proof: string) =>
      saveWorkflowGraph(projectId, {
        graph_id: "reproducibility-" + proof,
        name: "Reproducibility proof · " + proof.slice(0, 12),
        nodes: [
          {
            node_id: "project",
            node_type: "project_source",
            name: "Project",
            parameters: {},
          },
          {
            node_id: "proof",
            node_type: "research_reproducibility_package",
            name: "Research reproducibility package",
            parameters: { proof_sha256: proof },
          },
        ],
        edges: [
          {
            edge_id: "project-proof",
            source_node_id: "project",
            source_port_id: "project",
            target_node_id: "proof",
            target_port_id: "project",
          },
        ],
      }),
    onSuccess: onOpenWorkflow,
  });
  const rows = history.data ?? [];
  const package_ = rows.find((row) => row.id === selectedId) ?? rows[0];
  const ready = !!(
    selection.study_design_id &&
    selection.reviewer_report_id &&
    selection.comparison_id
  );
  const set = (key: keyof ResearchSelection, value: string | boolean) =>
    setSelection((prior) => ({ ...prior, [key]: value }));
  function submit(event: FormEvent) {
    event.preventDefault();
    if (ready && !build.isPending) build.mutate();
  }

  return (
    <section
      className="feature-workspace"
      aria-label="Research reproducibility package"
    >
      <h3>Export reproducibility package</h3>
      <form className="panel-card" onSubmit={submit}>
        <p>
          Choose frozen evidence to include with an offline copy of this
          project.
        </p>
        <label>
          Study design revision
          <select
            value={selection.study_design_id}
            onChange={(event) => set("study_design_id", event.target.value)}
          >
            <option value="">Choose a frozen study revision</option>
            {study.data?.pages
              .flatMap((page) => page.items)
              .map((item) => (
                <option key={item.id} value={item.id}>
                  {item.snapshot.declaration.title} · revision {item.revision}
                </option>
              ))}
          </select>
        </label>
        {study.hasNextPage && (
          <button type="button" onClick={() => void study.fetchNextPage()}>
            Show older study designs
          </button>
        )}
        <label>
          Sealed agreement report
          <select
            value={selection.reviewer_report_id}
            onChange={(event) => set("reviewer_report_id", event.target.value)}
          >
            <option value="">Choose a sealed agreement report</option>
            {reviewers.data?.map((item) => (
              <option key={item.id} value={item.id}>
                {item.title}
              </option>
            ))}
          </select>
        </label>
        <label>
          Paired model comparison
          <select
            value={selection.comparison_id}
            onChange={(event) => set("comparison_id", event.target.value)}
          >
            <option value="">Choose a completed comparison</option>
            {comparisons.data?.pages.flat().map((item) => (
              <option key={item.id} value={item.id}>
                {item.task} · {item.content_sha256.slice(0, 12)}
              </option>
            ))}
          </select>
        </label>
        {comparisons.hasNextPage && (
          <button
            type="button"
            onClick={() => void comparisons.fetchNextPage()}
          >
            Show older comparisons
          </button>
        )}
        <label>
          <input
            type="checkbox"
            checked={selection.include_media}
            onChange={(event) => set("include_media", event.target.checked)}
          />
          Include source media
        </label>
        <label>
          <input
            type="checkbox"
            checked={selection.include_model_weights}
            onChange={(event) =>
              set("include_model_weights", event.target.checked)
            }
          />
          Include local model weights
        </label>
        <button type="submit" disabled={!ready || build.isPending}>
          {build.isPending ? "Queuing package…" : "Export package"}
        </button>
        {(study.error ||
          reviewers.error ||
          comparisons.error ||
          build.error) && (
          <p role="alert">
            {
              (
                build.error ??
                study.error ??
                reviewers.error ??
                comparisons.error
              )?.message
            }
          </p>
        )}
      </form>
      <section
        className="panel-card"
        aria-label="Saved reproducibility packages"
      >
        <h3>Saved reproducibility packages</h3>
        {history.error && <p role="alert">{history.error.message}</p>}
        {rows.length > 0 && (
          <label>
            Saved package
            <select
              value={package_?.id ?? ""}
              onChange={(event) => setSelectedId(event.target.value)}
            >
              {rows.map((row) => (
                <option key={row.id} value={row.id}>
                  {row.direction === "import" ? "Imported" : "Exported"} ·{" "}
                  {row.proof_sha256?.slice(0, 12) ?? row.id.slice(0, 12)} ·{" "}
                  {row.status}
                </option>
              ))}
            </select>
          </label>
        )}
        {package_ && (
          <>
            <p role="status">Package {package_.status}</p>
            {package_.error_message && (
              <p role="alert">{package_.error_message}</p>
            )}
            {package_.manifest && (
              <ResearchManifestDetails
                manifest={package_.manifest}
                manifestSha={package_.manifest_sha256}
              />
            )}
            {package_.status === "complete" && package_.proof_sha256 && (
              <div className="button-row">
                <a href={downloadResearchPackageUrl(package_.id)} download>
                  Download reproducibility package
                </a>
                <button
                  type="button"
                  disabled={save.isPending}
                  onClick={() => save.mutate(package_.proof_sha256!)}
                >
                  Open in Workflow Builder
                </button>
              </div>
            )}
          </>
        )}
        {save.error && <p role="alert">{save.error.message}</p>}
      </section>
      <ReproducibilityImportPanel onOpenProject={onOpenProject} />
    </section>
  );
}
