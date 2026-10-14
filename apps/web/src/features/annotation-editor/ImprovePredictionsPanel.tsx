import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  cancelTrainingRun,
  getModels,
  getTrainingRun,
  registerModelFromRun,
  type TrainingRun,
} from "../../api/client";
import { intelligenceRequest } from "./annotationIntelligenceApi";

interface LearningStatus {
  ready: boolean;
  blockers: string[];
  warnings: string[];
  reviewed_image_count: number;
  eligible_object_count: number;
  per_class_counts: Array<{
    label_class_id: string;
    class_name: string;
    count: number;
    train_count: number;
    validation_count: number;
  }>;
  split_counts: Record<string, number>;
  latest_run: TrainingRun | null;
  promotion_policy: string;
}
interface LearningResult {
  readiness: LearningStatus;
  run: TrainingRun | null;
  dataset_version: { id: string; name: string } | null;
  preflight: { blockers?: string[]; warnings?: string[] } | null;
}
interface Metrics {
  map50: number;
  precision: number;
  recall: number;
  mean_absolute_count_error: number;
}
interface Evaluation {
  id: string;
  status: string;
  candidate_metrics: Metrics | null;
  incumbent_metrics: Metrics | null;
  promotion_eligible: boolean;
  blockers: string[];
}
interface Deployment {
  id: string;
  active_model_id: string | null;
  previous_model_id: string | null;
  evaluation_id: string | null;
}

export function ImprovePredictionsPanel({
  projectId,
  onClose,
}: {
  projectId: string;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [task, setTask] = useState("detect");
  const [device, setDevice] = useState("cpu");
  const [epochs, setEpochs] = useState(20);
  const [minimumImages, setMinimumImages] = useState(10);
  const [minimumObjects, setMinimumObjects] = useState(20);
  const [candidateModelId, setCandidateModelId] = useState("");
  const [evaluationId, setEvaluationId] = useState<string | null>(null);
  const [deployment, setDeployment] = useState<Deployment | null>(null);
  const config = {
    task,
    device,
    epochs,
    minimum_images: minimumImages,
    minimum_objects_per_class: minimumObjects,
  };
  const status = useQuery({
    queryKey: ["project-learning", projectId, config],
    queryFn: () =>
      intelligenceRequest<LearningStatus>(
        `/projects/${encodeURIComponent(projectId)}/learning/status`,
        config,
      ),
  });
  const models = useQuery({
    queryKey: ["models", projectId, "detector"],
    queryFn: () => getModels(projectId, "detector"),
  });
  const activeModel = models.data?.find(
    (model) => model.metadata_json.active_for_predictions === true,
  );
  const candidateModels = (models.data ?? []).filter(
    (model) => typeof model.metadata_json.source_training_run_id === "string",
  );
  const improve = useMutation({
    mutationFn: () =>
      intelligenceRequest<LearningResult>(
        `/projects/${encodeURIComponent(projectId)}/learning/improve`,
        config,
      ),
    onSuccess: () => void status.refetch(),
  });
  const runId = improve.data?.run?.id ?? status.data?.latest_run?.id;
  const run = useQuery({
    queryKey: ["training-run", runId],
    queryFn: () => getTrainingRun(runId!),
    enabled: Boolean(runId),
    refetchInterval: (query) => {
      const current = query.state.data?.status;
      return !current || !["completed", "failed", "cancelled"].includes(current)
        ? 1500
        : false;
    },
  });
  const cancel = useMutation({
    mutationFn: () => cancelTrainingRun(runId!),
    onSuccess: () => void run.refetch(),
  });
  const registerCandidate = useMutation({
    mutationFn: () =>
      registerModelFromRun(projectId, { training_run_id: runId! }),
    onSuccess: (model) => {
      setCandidateModelId(model.id);
      void queryClient.invalidateQueries({
        queryKey: ["models", projectId, "detector"],
      });
    },
  });
  const evaluation = useQuery({
    queryKey: ["learning-evaluation", projectId, evaluationId],
    queryFn: () =>
      intelligenceRequest<Evaluation>(
        `/projects/${encodeURIComponent(projectId)}/learning/evaluations/${encodeURIComponent(evaluationId!)}`,
        undefined,
        "GET",
      ),
    enabled: Boolean(evaluationId),
    refetchInterval: (query) =>
      query.state.data?.status === "waiting" ? 1500 : false,
  });
  const startEvaluation = useMutation({
    mutationFn: () => {
      const candidate = candidateModels.find(
        (model) => model.id === candidateModelId,
      );
      const datasetVersionId =
        candidate?.metadata_json.source_dataset_version_id;
      if (!candidate || typeof datasetVersionId !== "string") {
        throw new Error(
          "Register a completed local training checkpoint before evaluation.",
        );
      }
      return intelligenceRequest<Evaluation>(
        `/projects/${encodeURIComponent(projectId)}/learning/evaluations`,
        {
          dataset_version_id: datasetVersionId,
          candidate_model_id: candidate.id,
          incumbent_model_id: activeModel?.id ?? null,
        },
      );
    },
    onSuccess: (value) => setEvaluationId(value.id),
  });
  const promote = useMutation({
    mutationFn: () =>
      intelligenceRequest<Deployment>(
        `/projects/${encodeURIComponent(projectId)}/learning/evaluations/${encodeURIComponent(evaluationId!)}/promote`,
      ),
    onSuccess: (value) => {
      setDeployment(value);
      void queryClient.invalidateQueries({
        queryKey: ["models", projectId, "detector"],
      });
    },
  });
  const rollback = useMutation({
    mutationFn: () =>
      intelligenceRequest<Deployment>(
        `/projects/${encodeURIComponent(projectId)}/learning/deployments/${encodeURIComponent(deployment!.id)}/rollback`,
      ),
    onSuccess: (value) => {
      setDeployment(value);
      void queryClient.invalidateQueries({
        queryKey: ["models", projectId, "detector"],
      });
    },
  });
  const report = improve.data?.readiness ?? status.data;
  const busy = Boolean(
    run.data && !["completed", "failed", "cancelled"].includes(run.data.status),
  );
  const error =
    status.error ||
    models.error ||
    improve.error ||
    cancel.error ||
    registerCandidate.error ||
    startEvaluation.error ||
    evaluation.error ||
    promote.error ||
    rollback.error;
  return (
    <section
      className="sam-review-banner"
      aria-label="Improve project predictions"
    >
      <strong>Improve Predictions from verified annotations</strong>
      <p>
        Mark fully annotated images as Reviewed. Training uses a frozen
        snapshot, keeps related image groups together, and holds out validation
        images. More examples do not guarantee better accuracy.
      </p>
      <label>
        Training task{" "}
        <select value={task} onChange={(event) => setTask(event.target.value)}>
          <option value="detect">Detection</option>
          <option value="segment">Instance segmentation</option>
        </select>
      </label>
      <label>
        Device{" "}
        <select
          value={device}
          onChange={(event) => setDevice(event.target.value)}
        >
          <option value="cpu">CPU</option>
          <option value="auto">Automatic GPU / CPU</option>
        </select>
      </label>
      <label>
        Epochs{" "}
        <input
          type="number"
          min="1"
          max="500"
          value={epochs}
          onChange={(event) =>
            setEpochs(
              Math.max(1, Math.min(500, Number(event.target.value) || 1)),
            )
          }
        />
      </label>
      <label>
        Minimum reviewed images{" "}
        <input
          type="number"
          min="2"
          value={minimumImages}
          onChange={(event) =>
            setMinimumImages(Math.max(2, Number(event.target.value) || 2))
          }
        />
      </label>
      <label>
        Minimum objects per class{" "}
        <input
          type="number"
          min="2"
          value={minimumObjects}
          onChange={(event) =>
            setMinimumObjects(Math.max(2, Number(event.target.value) || 2))
          }
        />
      </label>
      {status.isPending && <p role="status">Checking verified examples…</p>}
      {report && (
        <>
          <p>
            {report.reviewed_image_count} reviewed images ·{" "}
            {report.eligible_object_count} eligible objects
          </p>
          <ul>
            {[...report.blockers, ...report.warnings].map((message, index) => (
              <li key={index}>{message}</li>
            ))}
          </ul>
          {report.per_class_counts.length > 0 && (
            <table>
              <thead>
                <tr>
                  <th>Class</th>
                  <th>Training objects</th>
                  <th>Validation objects</th>
                </tr>
              </thead>
              <tbody>
                {report.per_class_counts.map((item) => (
                  <tr key={item.label_class_id}>
                    <td>{item.class_name}</td>
                    <td>{item.train_count}</td>
                    <td>{item.validation_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <p>{report.promotion_policy}</p>
        </>
      )}
      <button
        type="button"
        disabled={!status.data?.ready || improve.isPending || busy}
        onClick={() => improve.mutate()}
      >
        {improve.isPending
          ? "Preparing immutable training snapshot…"
          : "Train candidate from verified annotations"}
      </button>
      <button
        type="button"
        onClick={() => {
          improve.reset();
          void status.refetch();
        }}
      >
        Refresh readiness
      </button>
      {run.data && <p role="status">Training candidate: {run.data.status}.</p>}
      {busy && (
        <button
          type="button"
          disabled={cancel.isPending}
          onClick={() => cancel.mutate()}
        >
          Cancel candidate training
        </button>
      )}
      {run.data?.status === "completed" && run.data.result_checkpoint_path && (
        <button
          type="button"
          disabled={registerCandidate.isPending}
          onClick={() => registerCandidate.mutate()}
        >
          {registerCandidate.isPending
            ? "Registering candidate checkpoint…"
            : "Register completed candidate checkpoint"}
        </button>
      )}
      <hr />
      <strong>Evaluate and select a trained detector</strong>
      <p>
        Active detector:{" "}
        {activeModel?.display_name ?? "None. Shift+1 uses class-agnostic SAM."}
      </p>
      <label>
        Registered training candidate{" "}
        <select
          aria-label="Registered training candidate"
          value={candidateModelId}
          onChange={(event) => {
            setCandidateModelId(event.target.value);
            setEvaluationId(null);
            setDeployment(null);
          }}
        >
          <option value="">Choose a candidate</option>
          {candidateModels.map((model) => (
            <option key={model.id} value={model.id}>
              {model.display_name}
            </option>
          ))}
        </select>
      </label>
      <button
        type="button"
        disabled={
          !candidateModelId ||
          startEvaluation.isPending ||
          evaluation.data?.status === "waiting"
        }
        onClick={() => startEvaluation.mutate()}
      >
        Evaluate on frozen holdout
      </button>
      {evaluation.data?.status === "waiting" && (
        <p role="status">
          Evaluation inference is running on frozen held-out images…
        </p>
      )}
      {evaluation.data?.candidate_metrics && (
        <dl>
          <dt>Candidate AP50</dt>
          <dd>{evaluation.data.candidate_metrics.map50.toFixed(3)}</dd>
          <dt>Precision / recall</dt>
          <dd>
            {evaluation.data.candidate_metrics.precision.toFixed(3)} /{" "}
            {evaluation.data.candidate_metrics.recall.toFixed(3)}
          </dd>
          <dt>Mean absolute count error</dt>
          <dd>
            {evaluation.data.candidate_metrics.mean_absolute_count_error.toFixed(
              3,
            )}
          </dd>
        </dl>
      )}
      {evaluation.data?.blockers.map((blocker, index) => (
        <p role="alert" key={index}>
          {blocker}
        </p>
      ))}
      <button
        type="button"
        disabled={!evaluation.data?.promotion_eligible || promote.isPending}
        onClick={() => promote.mutate()}
      >
        Promote evaluated candidate
      </button>
      {deployment?.active_model_id && (
        <button
          type="button"
          disabled={rollback.isPending}
          onClick={() => rollback.mutate()}
        >
          Rollback model selection
        </button>
      )}
      <button type="button" onClick={onClose}>
        Close learning panel
      </button>
      {improve.data?.preflight?.blockers?.map((message, index) => (
        <p key={index} role="alert">
          {message}
        </p>
      ))}
      {error && <p role="alert">{error.message}</p>}
    </section>
  );
}
