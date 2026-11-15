import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useState } from "react";

import {
  cancelJob,
  getJob,
  request,
  retryJob,
  type JobRecord,
} from "../../api/client";
import { StaticComparisonResult } from "./StaticComparisonResult";
import {
  listStaticComparisons,
  staticComparisonPath,
  staticLineageLabels,
  type StaticComparisonConfiguration,
  type StaticComparisonRecord,
  type StaticOptions,
} from "./staticComparisonApi";

const pageSize = 25;
const activeStatus = (status?: string) =>
  ["queued", "running", "cancel_requested"].includes(status ?? "");

export function StaticComparisonPanel(props: {
  projectId: string;
  onOpenImage?: (imageId: string) => void;
}) {
  return <StaticComparisonContent key={props.projectId} {...props} />;
}

function StaticComparisonContent({
  projectId,
  onOpenImage,
}: {
  projectId: string;
  onOpenImage?: (imageId: string) => void;
}) {
  const base = staticComparisonPath(projectId);
  const cache = useQueryClient();
  const savedKey = ["static-comparisons", projectId];
  const selectionKey = `reefvision-static-comparison-${projectId}`;
  const [selected, setSelected] = useState(
    () => sessionStorage.getItem(selectionKey) ?? "",
  );
  const [open, setOpen] = useState(Boolean(selected));
  const [offset, setOffset] = useState(0);
  const [datasetId, setDatasetId] = useState("");
  const [firstModel, setFirstModel] = useState("");
  const [secondModel, setSecondModel] = useState("");
  const [split, setSplit] =
    useState<StaticComparisonConfiguration["split"]>("test");
  const [classIds, setClassIds] = useState<string[]>([]);
  const [confidence, setConfidence] = useState("0.25");
  const [iou, setIou] = useState("0.7");
  const [device, setDevice] =
    useState<StaticComparisonConfiguration["inference"]["device"]>("auto");
  const [groups, setGroups] = useState(false);
  const [limits, setLimits] = useState(false);
  const [icc, setIcc] = useState<StaticComparisonConfiguration["icc"]>(null);

  const choices = useInfiniteQuery({
    queryKey: ["static-comparison-options", projectId],
    enabled: open,
    initialPageParam: 0,
    queryFn: ({ signal, pageParam }) =>
      request<StaticOptions>(
        `${base}/options?limit=${pageSize}&offset=${pageParam}`,
        { signal },
      ),
    getNextPageParam: (page, pages) =>
      Math.max(page.datasets.length, page.models.length) === pageSize
        ? pages.length * pageSize
        : undefined,
  });
  const saved = useQuery({
    queryKey: [...savedKey, offset],
    enabled: open,
    queryFn: ({ signal }) =>
      listStaticComparisons(projectId, pageSize, offset, signal),
    refetchInterval: (query) =>
      query.state.data?.some((row) => activeStatus(row.status)) ? 1000 : false,
  });
  const job = useQuery({
    queryKey: ["static-comparison-job", projectId, selected],
    enabled: open && Boolean(selected),
    queryFn: ({ signal }) => getJob(selected, signal),
    refetchInterval: (query) =>
      activeStatus(query.state.data?.status) ? 1000 : false,
  });
  const report = useQuery({
    queryKey: ["static-comparison-result", projectId, selected],
    enabled: open && job.data?.status === "succeeded",
    queryFn: ({ signal }) =>
      request<StaticComparisonRecord>(`${base}/${selected}`, { signal }),
  });
  function selectComparison(id: string) {
    setSelected(id);
    if (id) sessionStorage.setItem(selectionKey, id);
    else sessionStorage.removeItem(selectionKey);
  }
  function refresh() {
    void cache.invalidateQueries({ queryKey: savedKey });
    void job.refetch();
  }
  const submit = useMutation({
    mutationFn: (configuration: StaticComparisonConfiguration) =>
      request<JobRecord>(base, {
        method: "POST",
        body: JSON.stringify(configuration),
      }),
    onSuccess: (pending) => {
      cache.setQueryData(
        ["static-comparison-job", projectId, pending.id],
        pending,
      );
      setOffset(0);
      selectComparison(pending.id);
      void cache.invalidateQueries({ queryKey: savedKey });
    },
  });
  const jobAction = useMutation({
    mutationFn: (action: "cancel" | "retry") =>
      action === "retry" ? retryJob(selected) : cancelJob(selected),
    onSuccess: refresh,
  });
  const datasets = choices.data?.pages.flatMap((page) => page.datasets) ?? [];
  const modelChoices = choices.data?.pages.flatMap((page) => page.models) ?? [];
  const dataset = datasets.find((row) => row.id === datasetId);
  const classScope = classIds.length
    ? classIds
    : (dataset?.classes.map((row) => row.id) ?? []);
  const models = modelChoices.filter((row) =>
    row.mapped_class_ids.some((id) => classScope.includes(id)),
  );
  const ready =
    dataset &&
    (split === "test" ? dataset.test_reviewed_count : dataset.reviewed_count) >
      0 &&
    models.some((row) => row.id === firstModel) &&
    (!secondModel || models.some((row) => row.id === secondModel));
  const selectedIsListed = saved.data?.some((row) => row.id === selected);
  const error =
    submit.error ??
    jobAction.error ??
    job.error ??
    saved.error ??
    choices.error ??
    report.error;

  return (
    <details
      className="management-card"
      open={open}
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary>Static-image human–model comparison</summary>
      <p>
        Count bounding-box detections on reviewed images in an immutable dataset
        version. Training and model-selection evidence determines the evaluation
        label.
      </p>
      {choices.isFetching && !choices.data && (
        <p role="status">Loading datasets and detectors…</p>
      )}
      {choices.data && datasets.length === 0 && (
        <p>
          Mark reference images reviewed and save a dataset version to get
          started.
        </p>
      )}
      {choices.data && datasets.length > 0 && (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (!ready) return;
            submit.mutate({
              dataset_version_id: datasetId,
              model_ids: [firstModel, secondModel].filter(Boolean),
              split,
              class_ids: classIds,
              inference: {
                confidence_threshold: Number(confidence),
                iou_threshold: Number(iou),
                device,
              },
              independent_groups: groups,
              homoscedastic_normal_differences: groups && limits,
              icc: groups ? icc : null,
            });
          }}
        >
          <div className="form-row">
            <label>
              Reviewed reference dataset
              <select
                required
                value={datasetId}
                onChange={(event) => {
                  setDatasetId(event.target.value);
                  setClassIds([]);
                  setFirstModel("");
                  setSecondModel("");
                }}
              >
                <option value="">Choose a dataset</option>
                {datasets.map((row) => (
                  <option key={row.id} value={row.id}>
                    {row.name} · {row.reviewed_count} reviewed
                  </option>
                ))}
              </select>
            </label>
            <label>
              Reference images
              <select
                value={split}
                onChange={(event) =>
                  setSplit(event.target.value as typeof split)
                }
              >
                <option value="test">
                  Reviewed test split
                  {dataset && ` (${dataset.test_reviewed_count})`}
                </option>
                <option value="all">
                  All reviewed images{dataset && ` (${dataset.reviewed_count})`}
                </option>
              </select>
            </label>
            {choices.hasNextPage && (
              <button
                type="button"
                disabled={choices.isFetchingNextPage}
                onClick={() => void choices.fetchNextPage()}
              >
                Load more datasets and detectors
              </button>
            )}
          </div>
          {dataset && split === "test" && dataset.test_reviewed_count === 0 && (
            <p>
              This version has no reviewed test images. Select another version
              or use all reviewed images.
            </p>
          )}
          {dataset && (
            <>
              <label>
                Reference classes
                <select
                  multiple
                  value={classIds}
                  onChange={(event) =>
                    setClassIds(
                      Array.from(
                        event.target.selectedOptions,
                        (item) => item.value,
                      ),
                    )
                  }
                >
                  {dataset.classes.map((row) => (
                    <option key={row.id} value={row.id}>
                      {row.name}
                    </option>
                  ))}
                </select>
              </label>
              <p>Leave the class selection empty to use every frozen class.</p>
            </>
          )}
          {dataset && !models.length && (
            <p>
              Register a bounding-box detector with project class mappings for
              this reference.
            </p>
          )}
          <div className="form-row">
            {[
              {
                label: "Primary detector",
                value: firstModel,
                other: secondModel,
                set: setFirstModel,
                required: true,
              },
              {
                label: "Second detector",
                value: secondModel,
                other: firstModel,
                set: setSecondModel,
                required: false,
              },
            ].map(({ label, value, other, set, required }) => (
              <label key={label}>
                {label}
                <select
                  required={required}
                  value={value}
                  disabled={!models.length}
                  onChange={(event) => set(event.target.value)}
                >
                  <option value="">
                    {required ? "Choose a detector" : "None"}
                  </option>
                  {models
                    .filter((row) => row.id !== other)
                    .map((row) => (
                      <option key={row.id} value={row.id}>
                        {row.name} ·{" "}
                        {
                          row.mapped_class_ids.filter((id) =>
                            classScope.includes(id),
                          ).length
                        }
                        /{classScope.length} classes
                      </option>
                    ))}
                </select>
              </label>
            ))}
          </div>
          <details>
            <summary>Inference and agreement settings</summary>
            <div className="form-row">
              <label>
                Confidence threshold
                <input
                  type="number"
                  min="0"
                  max="1"
                  step="0.01"
                  required
                  value={confidence}
                  onChange={(event) => setConfidence(event.target.value)}
                />
              </label>
              <label>
                Overlap threshold (IoU)
                <input
                  type="number"
                  min="0"
                  max="1"
                  step="0.01"
                  required
                  value={iou}
                  onChange={(event) => setIou(event.target.value)}
                />
              </label>
              <label>
                Device
                <select
                  value={device}
                  onChange={(event) =>
                    setDevice(event.target.value as typeof device)
                  }
                >
                  <option value="auto">Auto</option>
                  <option value="cpu">CPU</option>
                  <option value="cuda">CUDA</option>
                </select>
              </label>
            </div>
            <label>
              <input
                type="checkbox"
                checked={groups}
                onChange={(event) => setGroups(event.target.checked)}
              />
              I confirm the frozen group keys identify independent sampling
              units, including any related organisms, colonies, tanks, or sites.
            </label>
            <label>
              <input
                type="checkbox"
                checked={limits && groups}
                disabled={!groups}
                onChange={(event) => setLimits(event.target.checked)}
              />
              I confirm approximately normal differences with constant variance
              for agreement limits.
            </label>
            <label>
              Intraclass correlation
              <select
                value={groups ? (icc ?? "") : ""}
                disabled={!groups}
                onChange={(event) =>
                  setIcc((event.target.value || null) as typeof icc)
                }
              >
                <option value="">Omit ICC</option>
                <option value="A,1">ICC(A,1) · absolute agreement</option>
                <option value="C,1">ICC(C,1) · consistency</option>
              </select>
            </label>
          </details>
          <button type="submit" disabled={!ready || submit.isPending}>
            Run count comparison
          </button>
        </form>
      )}
      <label>
        Saved count comparison
        <select
          value={selected}
          onChange={(event) => selectComparison(event.target.value)}
        >
          <option value="">Choose a comparison</option>
          {!!selected && !selectedIsListed && (
            <option value={selected}>Selected comparison</option>
          )}
          {saved.data?.map((row) => (
            <option key={row.id} value={row.id}>
              {row.reference_name} · {row.model_names.join(" / ")} ·{" "}
              {row.evaluation_status
                ? staticLineageLabels[row.evaluation_status]
                : row.status}{" "}
              · {row.id.slice(0, 8)}
            </option>
          ))}
        </select>
      </label>
      <div className="form-row">
        <button
          type="button"
          disabled={offset === 0}
          onClick={() => setOffset(offset - pageSize)}
        >
          Newer comparisons
        </button>
        <button
          type="button"
          disabled={saved.data?.length !== pageSize}
          onClick={() => setOffset(offset + pageSize)}
        >
          Older comparisons
        </button>
      </div>
      {job.data && activeStatus(job.data.status) && (
        <p role="status">
          {job.data.status.replaceAll("_", " ")} · {job.data.progress_current} /{" "}
          {job.data.progress_total} image runs{" "}
          <button
            type="button"
            disabled={
              jobAction.isPending || job.data.status === "cancel_requested"
            }
            onClick={() => jobAction.mutate("cancel")}
          >
            Cancel comparison
          </button>
        </p>
      )}
      {job.data?.status === "failed" && (
        <p role="alert">
          {job.data.error_message || "The comparison failed."}{" "}
          <button
            type="button"
            disabled={
              jobAction.isPending || !!job.data.request_json.workflow_run_id
            }
            onClick={() => jobAction.mutate("retry")}
          >
            Retry comparison
          </button>
        </p>
      )}
      {job.data?.status === "cancelled" && (
        <p role="status">Comparison cancelled.</p>
      )}
      {error && <p role="alert">{error.message}</p>}
      {report.data && (
        <StaticComparisonResult
          key={report.data.id}
          projectId={projectId}
          record={report.data}
          onOpenImage={onOpenImage}
        />
      )}
    </details>
  );
}
