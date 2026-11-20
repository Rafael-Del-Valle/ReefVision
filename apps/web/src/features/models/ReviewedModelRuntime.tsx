import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import {
  getImages,
  getJob,
  request,
  type JobRecord,
  type ModelRegistration,
} from "../../api/client";

interface RuntimeSnapshot {
  display_name: string;
  checkpoint_sha256: string;
  task: string;
  provider_id: string;
  provider_version: string;
  runtime_id: string;
  runtime_version: string;
  settings: {
    device: string;
    confidence_threshold: number;
    iou_threshold: number;
  };
  prompt: string;
  applied_image_settings: string[];
}

interface Preview {
  content_sha256: string;
  snapshot: RuntimeSnapshot;
}

interface Selection extends Preview {
  id: string;
  model_id: string;
}

function useSelections(projectId: string) {
  return useQuery({
    queryKey: ["reviewed-model-selections", projectId],
    queryFn: ({ signal }) =>
      request<Selection[]>(
        "/projects/" + projectId + "/model-runtime-selections",
        { signal },
      ),
  });
}

export function ModelSelectionField({
  projectId,
  value,
  onChange,
}: {
  projectId: string;
  value: string;
  onChange: (selection: Selection | undefined) => void;
}) {
  const records = useSelections(projectId);
  return (
    <>
      <label>
        Reviewed model configuration
        <select
          value={value}
          onChange={(event) =>
            onChange(records.data?.find((row) => row.id === event.target.value))
          }
        >
          <option value="">Choose a saved configuration</option>
          {records.data?.map((row) => (
            <option key={row.id} value={row.id}>
              {row.snapshot.display_name} · {row.snapshot.settings.device} ·{" "}
              {row.content_sha256.slice(0, 12)}
            </option>
          ))}
        </select>
      </label>
      {records.error && <p role="alert">{records.error.message}</p>}
    </>
  );
}

function Receipt({ snapshot }: { snapshot: RuntimeSnapshot }) {
  const options = snapshot.settings;
  return (
    <dl>
      <dt>Registered model</dt>
      <dd>
        {snapshot.display_name} · {snapshot.task}
      </dd>
      <dt>Checkpoint SHA-256</dt>
      <dd>
        <code>{snapshot.checkpoint_sha256}</code>
      </dd>
      <dt>Provider</dt>
      <dd>
        {snapshot.provider_id} {snapshot.provider_version}
      </dd>
      <dt>Execution runtime</dt>
      <dd>
        {snapshot.runtime_id} {snapshot.runtime_version} · {options.device}
      </dd>
      <dt>Confidence threshold</dt>
      <dd>
        {snapshot.applied_image_settings.includes("confidence_threshold")
          ? options.confidence_threshold
          : "Unused by this model"}
      </dd>
      <dt>IoU threshold</dt>
      <dd>
        {snapshot.applied_image_settings.includes("iou_threshold")
          ? options.iou_threshold
          : "Unused by this model"}
      </dd>
      {snapshot.prompt && (
        <>
          <dt>Configuration request</dt>
          <dd>{snapshot.prompt}</dd>
        </>
      )}
    </dl>
  );
}

export function ReviewedModelRuntime({
  projectId,
  models,
  openImage,
}: {
  projectId: string;
  models: ModelRegistration[];
  openImage?: (id: string) => void;
}) {
  const queryClient = useQueryClient();
  const base = "/projects/" + projectId;
  const choices = base + "/model-runtime-selections";
  const [modelId, setModelId] = useState("");
  const [runtime, setRuntime] = useState("pytorch");
  const [device, setDevice] = useState("cpu");
  const [prompt, setPrompt] = useState("");
  const [selected, setSelected] = useState("");
  const [imageId, setImageId] = useState("");
  const [page, setPage] = useState(1);
  const [jobId, setJobId] = useState("");
  const [jobImage, setJobImage] = useState("");
  const records = useSelections(projectId);
  const active = records.data?.find((row) => row.id === selected);
  const draft = { model_id: modelId, runtime_id: runtime, device, prompt };
  const draftKey = JSON.stringify(draft);
  const preview = useMutation({
    mutationFn: async (key: string) => ({
      key,
      receipt: await request<Preview>(choices + "/preview", {
        method: "POST",
        body: key,
      }),
    }),
  });
  const review =
    preview.data?.key === draftKey ? preview.data.receipt : undefined;
  const confirm = useMutation({
    mutationFn: (digest: string) =>
      request<Selection>(choices, {
        method: "POST",
        body: JSON.stringify({ draft, reviewed_sha256: digest }),
      }),
    onSuccess: async (row) => {
      await queryClient.invalidateQueries({
        queryKey: ["reviewed-model-selections", projectId],
      });
      setSelected(row.id);
      preview.reset();
    },
  });
  const images = useQuery({
    queryKey: ["reviewed-inference-images", projectId, page],
    queryFn: ({ signal }) =>
      getImages(projectId, { page, pageSize: 40 }, signal),
    enabled: !!active,
  });
  const run = useMutation({
    mutationFn: ({ pin, image }: { pin: Selection; image: string }) =>
      request<JobRecord>(base + "/inference-jobs", {
        method: "POST",
        body: JSON.stringify({
          model_id: pin.model_id,
          runtime_selection_id: pin.id,
          image_ids: [image],
        }),
      }),
    onSuccess: (job, variables) => {
      setJobId(job.id);
      setJobImage(variables.image);
    },
  });
  const job = useQuery({
    queryKey: ["job", jobId],
    queryFn: ({ signal }) => getJob(jobId, signal),
    enabled: !!jobId,
    refetchInterval: (query) =>
      ["succeeded", "failed", "cancelled"].includes(
        query.state.data?.status ?? "",
      )
        ? false
        : 1000,
  });
  return (
    <section
      id="model-ai-runtime-selection"
      className="gallery-panel"
      aria-label="Local model runtime"
    >
      <h3>Local model runtime</h3>
      <label>
        Registered checkpoint
        <select
          value={modelId}
          onChange={(event) => {
            const id = event.target.value;
            setModelId(id);
            setRuntime(
              models.find((item) => item.id === id)?.provider_name === "nnunet"
                ? "nnunetv2"
                : "pytorch",
            );
          }}
        >
          <option value="">Choose a project model</option>
          {models.map((model) => (
            <option value={model.id} key={model.id}>
              {model.display_name} · {model.provider_name} · {model.task}
            </option>
          ))}
        </select>
      </label>
      <label>
        Local runtime
        <select
          value={runtime}
          onChange={(event) => setRuntime(event.target.value)}
        >
          <option value="pytorch">PyTorch</option>
          <option value="nnunetv2">nnU-Net v2 predictor</option>
        </select>
      </label>
      <label>
        Inference device
        <select
          value={device}
          onChange={(event) => setDevice(event.target.value)}
        >
          <option value="cpu">CPU</option>
          <option value="cuda">CUDA</option>
        </select>
      </label>
      <label>
        Configuration request (optional)
        <input
          value={prompt}
          maxLength={500}
          onChange={(event) => setPrompt(event.target.value)}
          placeholder="confidence 0.4, iou 0.5"
        />
      </label>
      <button
        type="button"
        disabled={!modelId || preview.isPending}
        onClick={() => preview.mutate(draftKey)}
      >
        Preview local configuration
      </button>
      {preview.error && <p role="alert">{preview.error.message}</p>}
      {review && (
        <div>
          <h4>Review configuration</h4>
          <Receipt snapshot={review.snapshot} />
          <button
            type="button"
            disabled={confirm.isPending}
            onClick={() => confirm.mutate(review.content_sha256)}
          >
            Confirm reviewed configuration
          </button>
        </div>
      )}
      {confirm.error && <p role="alert">{confirm.error.message}</p>}
      <ModelSelectionField
        projectId={projectId}
        value={selected}
        onChange={(row) => {
          setSelected(row?.id ?? "");
          setJobId("");
          setImageId("");
        }}
      />
      {active && (
        <div>
          <Receipt snapshot={active.snapshot} />
          <label>
            Inference image
            <select
              value={imageId}
              onChange={(event) => setImageId(event.target.value)}
            >
              <option value="">Choose an image</option>
              {images.data?.items.map((image) => (
                <option key={image.id} value={image.id}>
                  {image.original_filename}
                </option>
              ))}
            </select>
          </label>
          {(images.data?.pages ?? 0) > 1 && (
            <div>
              <button
                type="button"
                disabled={page <= 1}
                onClick={() => {
                  setPage(page - 1);
                  setImageId("");
                }}
              >
                Previous images
              </button>
              <span>
                Page {page} of {images.data?.pages}
              </span>
              <button
                type="button"
                disabled={page >= (images.data?.pages ?? 1)}
                onClick={() => {
                  setPage(page + 1);
                  setImageId("");
                }}
              >
                Next images
              </button>
            </div>
          )}
          {images.error && <p role="alert">{images.error.message}</p>}
          <button
            type="button"
            disabled={!imageId || run.isPending}
            onClick={() => run.mutate({ pin: active, image: imageId })}
          >
            Run reviewed inference
          </button>
          {run.error && <p role="alert">{run.error.message}</p>}
          {job.data && (
            <p role="status">
              Inference {job.data.status} · {job.data.id}{" "}
              {job.data.error_message}
            </p>
          )}
          {job.error && <p role="alert">{job.error.message}</p>}
          {job.data?.status === "succeeded" && openImage && (
            <button type="button" onClick={() => openImage(jobImage)}>
              Review image predictions
            </button>
          )}
        </div>
      )}
    </section>
  );
}
