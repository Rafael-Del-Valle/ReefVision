import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { ReefPoseGroupingFields } from "./ReefPoseGroupingFields";
import {
  getTemporalDatasets,
  getTemporalInputs,
  getTemporalRuns,
  type TemporalDatasetRequest,
  type TemporalAnatomicalEvents,
  type TemporalRunRequest,
  type TemporalSource,
  type TemporalSplit,
} from "./temporalReefPoseApi";

type Parameters = Record<string, unknown>;
type Props = {
  projectId: string;
  kind: "dataset" | TemporalRunRequest["kind"];
  values: Parameters;
  onChange: (values: Parameters) => void;
  videoId?: string;
  connectedDataset?: boolean;
  connectedModel?: boolean;
};
export const temporalTypes = {
  temporal_reefpose_dataset: "dataset",
  temporal_reefpose_training: "training",
  temporal_reefpose_inference: "inference",
  temporal_reefpose_evaluation: "evaluation",
} as const;

export function temporalKind(nodeType: string) {
  return temporalTypes[nodeType as keyof typeof temporalTypes];
}

const asText = (value: unknown) => (typeof value === "string" ? value : "");
const asSource = (value: unknown) =>
  (value && typeof value === "object" && !Array.isArray(value)
    ? value
    : {}) as TemporalSource;

function Picker({
  label,
  value,
  options,
  onChange,
  placeholder = "Choose…",
}: {
  label: string;
  value: string;
  options: { id: string; name: string }[];
  onChange: (id: string) => void;
  placeholder?: string;
}) {
  return (
    <label>
      {label}
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        <option value="">{placeholder}</option>
        {!!value && !options.some((row) => row.id === value) && (
          <option value={value}>Saved selection unavailable</option>
        )}
        {options.map((row) => (
          <option key={row.id} value={row.id}>
            {row.name}
          </option>
        ))}
      </select>
    </label>
  );
}

function AnatomicalEventFields({
  value,
  onChange,
  landmarks,
}: {
  value: unknown;
  onChange: (value: TemporalAnatomicalEvents | undefined) => void;
  landmarks: { id: string; name: string }[];
}) {
  const config = value as TemporalAnatomicalEvents | undefined;
  const options = landmarks.map((row) => ({
    ...row,
    name: `${row.name} · ${row.id}`,
  }));
  return (
    <fieldset>
      <legend>Anatomical event evaluation</legend>
      <p>
        Apply the same distance and hysteresis thresholds to reviewed targets,
        frame predictions and temporal predictions.
      </p>
      <label className="toggle-row">
        <input
          type="checkbox"
          checked={!!config}
          onChange={(event) =>
            onChange(
              event.target.checked
                ? {
                    landmark_a_id: "",
                    landmark_b_id: "",
                    open_threshold_px: 10,
                    close_threshold_px: 5,
                  }
                : undefined,
            )
          }
        />
        Compare anatomical cycles
      </label>
      {config && (
        <>
          <Picker
            label="Event landmark A"
            value={config.landmark_a_id}
            options={options}
            onChange={(landmark_a_id) => onChange({ ...config, landmark_a_id })}
          />
          <Picker
            label="Event landmark B"
            value={config.landmark_b_id}
            options={options.filter((row) => row.id !== config.landmark_a_id)}
            onChange={(landmark_b_id) => onChange({ ...config, landmark_b_id })}
          />
          <div className="field-grid compact-grid">
            {(
              [
                ["open_threshold_px", "Event opening threshold (px)", 10],
                ["close_threshold_px", "Event closing threshold (px)", 5],
                ["minimum_amplitude_px", "Minimum cycle amplitude (px)", 0],
                ["minimum_duration_seconds", "Minimum cycle duration (s)", 0],
                ["maximum_gap_seconds", "Maximum event gap (s)", 0.25],
                ["onset_tolerance_seconds", "Onset tolerance (s)", 0.25],
                ["offset_tolerance_seconds", "Offset tolerance (s)", 0.25],
              ] as const
            ).map(([key, label, fallback]) => (
              <label key={key}>
                {label}
                <input
                  type="number"
                  step="any"
                  min={0}
                  value={config[key] ?? fallback}
                  onChange={(event) =>
                    onChange({ ...config, [key]: event.target.valueAsNumber })
                  }
                />
              </label>
            ))}
          </div>
        </>
      )}
    </fieldset>
  );
}

export function temporalFieldsIssue(
  kind: Props["kind"],
  values: Parameters,
  dependencies?: {
    dataset?: boolean;
    model?: boolean;
  },
): string | undefined {
  if (asText(values.saved_dataset_id) || asText(values.saved_run_id)) return;
  if (kind === "dataset") {
    const sources = Array.isArray(values.sources)
      ? (values.sources as TemporalDatasetRequest["sources"])
      : [];
    if (
      !asText(values.name).trim() ||
      !sources.length ||
      sources.some(
        (row) =>
          !row.frame_track_id ||
          (!row.reviewed_track_id && !row.animal_identity_id),
      )
    )
      return "Name the dataset and choose at least one frame track paired with reviewed supervision.";
    if (!sources.some((row) => row.split === "train"))
      return "Assign at least one recording to training.";
    if (
      sources.some(
        (row) => row.reviewed_track_id && row.confirm_same_animal !== true,
      )
    )
      return "Confirm the human-reviewed track and frame-model track belong to the same animal.";
  } else if (kind === "training") {
    if (
      (!asText(values.dataset_id) && !dependencies?.dataset) ||
      !asText(values.name).trim()
    )
      return "Choose a frozen temporal dataset and name the checkpoint.";
  } else if (kind === "inference") {
    if (
      (!asText(values.temporal_model_id) && !dependencies?.model) ||
      !asSource(values.source).frame_track_id
    )
      return "Choose a compatible checkpoint and frozen frame-model observations.";
  } else if (
    (!asText(values.dataset_id) && !dependencies?.dataset) ||
    (!asText(values.temporal_model_id) && !dependencies?.model)
  )
    return "Choose a frozen test dataset and a compatible temporal checkpoint.";
  for (const key of [
    "window_length",
    "epochs",
    "batch_size",
    "learning_rate",
    "channels",
    "max_gap_seconds",
    "chunk_size",
  ]) {
    const value = values[key];
    if (
      value !== undefined &&
      value !== null &&
      (!Number.isFinite(value) || Number(value) <= 0)
    )
      return "Enter positive numeric settings.";
  }
  if (
    kind === "training" &&
    (values.context_mode ?? "centered") === "centered" &&
    Number(values.window_length ?? 9) % 2 === 0
  )
    return "Centered context requires an odd window length.";
  if (values.anatomical_events) {
    const event = values.anatomical_events as TemporalAnatomicalEvents;
    if (
      !event.landmark_a_id ||
      !event.landmark_b_id ||
      event.landmark_a_id === event.landmark_b_id
    )
      return "Choose two different landmarks for anatomical cycles.";
    if (
      !Number.isFinite(event.open_threshold_px) ||
      !Number.isFinite(event.close_threshold_px) ||
      event.open_threshold_px <= event.close_threshold_px ||
      event.close_threshold_px < 0
    )
      return "The opening threshold must be greater than the nonnegative closing threshold.";
  }
}

export function TemporalReefPoseFields({
  projectId,
  kind,
  values,
  onChange,
  videoId,
  connectedDataset,
  connectedModel,
}: Props) {
  const input = useInfiniteQuery({
    queryKey: ["temporal-reefpose", projectId, "inputs"],
    initialPageParam: 0,
    queryFn: ({ signal, pageParam }) =>
      getTemporalInputs(projectId, signal, pageParam),
    getNextPageParam: (page, pages) =>
      page.next_offset !== undefined
        ? (page.next_offset ?? undefined)
        : Math.max(
              page.frame_tracks.length + page.reviewed_tracks.length,
              page.frame_models.length + page.temporal_models.length,
              page.identities.length,
            ) >= 100
          ? pages.length * 100
          : undefined,
    refetchOnMount: "always",
  });
  const datasets = useInfiniteQuery({
    queryKey: ["temporal-reefpose", projectId, "dataset-options"],
    initialPageParam: 0,
    queryFn: ({ signal, pageParam }) =>
      getTemporalDatasets(projectId, signal, pageParam),
    getNextPageParam: (page, pages) =>
      page.length >= 100 ? pages.length * 100 : undefined,
    enabled: kind === "training" || kind === "evaluation",
  });
  const pages = input.data?.pages ?? [];
  const datasetOptions = datasets.data?.pages.flat() ?? [];
  const change = (delta: Parameters) => onChange({ ...values, ...delta });
  const sources = Array.isArray(values.sources)
    ? (values.sources as TemporalDatasetRequest["sources"])
    : [];
  const selectedDataset = datasetOptions.find(
    (row) => row.id === values.dataset_id,
  );
  const selectedModel = pages
    .flatMap((page) => page.temporal_models)
    .find((row) => row.id === values.temporal_model_id);
  const selectedSource = asSource(values.source);
  const trackLabel = (row: {
    video_name: string;
    track_number: number;
    revision: number;
  }) =>
    `${row.video_name} · track ${row.track_number} · revision ${row.revision}`;
  function sourceFields(
    source: TemporalSource,
    update: (next: TemporalSource) => void,
    training: boolean,
  ) {
    const frameTracks = pages
      .flatMap((page) => page.frame_tracks)
      .filter((row) => {
        if (videoId && videoId !== row.video_id && !training) return false;
        if (!selectedModel || training) return true;
        const checkpoint = pages
          .flatMap((page) => page.frame_models)
          .find((model) => model.id === row.model_id);
        return (
          row.schema_hash === selectedModel.schema_hash &&
          checkpoint?.sha256 === selectedModel.frame_model_sha256
        );
      });
    const frame = frameTracks.find((row) => row.id === source.frame_track_id);
    const eligible = pages
      .flatMap((page) => page.reviewed_tracks)
      .filter(
        (row) =>
          !!frame &&
          row.video_id === frame.video_id &&
          row.schema_hash === frame.schema_hash,
      );
    const identities = pages
      .flatMap((page) => page.identities)
      .filter((row) => row.video_id === frame?.video_id);
    return (
      <>
        <Picker
          label="Frame-model track"
          value={source.frame_track_id ?? ""}
          options={frameTracks.map((row) => ({
            ...row,
            name: trackLabel(row),
          }))}
          onChange={(frame_track_id) =>
            update({
              frame_track_id,
              group_key: source.group_key,
              discontinuity_frames: source.discontinuity_frames,
            })
          }
        />
        {training && (
          <Picker
            label="Human-reviewed supervision track"
            value={source.reviewed_track_id ?? ""}
            options={eligible.map((row) => ({ ...row, name: trackLabel(row) }))}
            onChange={(reviewed_track_id) =>
              update({
                ...source,
                reviewed_track_id: reviewed_track_id || undefined,
                confirm_same_animal: undefined,
              })
            }
          />
        )}
        {training && source.reviewed_track_id && (
          <label className="toggle-row">
            <input
              type="checkbox"
              checked={source.confirm_same_animal === true}
              onChange={(event) =>
                update({ ...source, confirm_same_animal: event.target.checked })
              }
            />
            I confirmed these two tracks represent the same animal
          </label>
        )}
        <Picker
          label="Reviewed animal identity"
          value={source.animal_identity_id ?? ""}
          options={identities.map((row) => ({
            ...row,
            name: `${row.name} · revision ${row.revision}`,
          }))}
          placeholder="Use selected track alone"
          onChange={(animal_identity_id) =>
            update({
              ...source,
              animal_identity_id: animal_identity_id || undefined,
              identity_observation_run_id: identities.find(
                (row) => row.id === animal_identity_id,
              )?.run_id,
              confirm_same_animal: undefined,
            })
          }
        />
        {training && (
          <ReefPoseGroupingFields
            grouping={source.grouping}
            onChange={(grouping) => update({ ...source, grouping })}
          />
        )}
        {training && (
          <label>
            Recording group
            <input
              value={source.group_key ?? ""}
              onChange={(event) =>
                update({
                  ...source,
                  group_key: event.target.value || undefined,
                })
              }
            />
          </label>
        )}
        <label>
          Discontinuity frames
          <input
            placeholder="Example: 120, 430"
            defaultValue={(source.discontinuity_frames ?? []).join(", ")}
            pattern="[0-9 ,]*"
            onBlur={(event) =>
              update({
                ...source,
                discontinuity_frames: event.target.value
                  .split(",")
                  .map((part) => part.trim())
                  .filter(Boolean)
                  .map(Number),
              })
            }
          />
        </label>
      </>
    );
  }
  const numeric = (
    key: string,
    label: string,
    fallback: number,
    min: number,
    step: number | "any",
    max?: number,
  ) => (
    <label>
      {label}
      <input
        type="number"
        min={min}
        max={max}
        step={step}
        value={values[key] === null ? "" : Number(values[key] ?? fallback)}
        onChange={(event) =>
          change({
            [key]: Number.isNaN(event.target.valueAsNumber)
              ? null
              : event.target.valueAsNumber,
          })
        }
      />
    </label>
  );
  return (
    <>
      {[input.error, datasets.error].filter(Boolean).map((error, index) => (
        <p role="alert" key={index}>
          {error?.message}
        </p>
      ))}
      {input.hasNextPage && (
        <button
          type="button"
          disabled={input.isFetchingNextPage}
          onClick={() => void input.fetchNextPage()}
        >
          More pose tracks and checkpoints
        </button>
      )}
      {datasets.hasNextPage && (
        <button
          type="button"
          disabled={datasets.isFetchingNextPage}
          onClick={() => void datasets.fetchNextPage()}
        >
          More frozen datasets
        </button>
      )}
      {input.isPending && (
        <p role="status">Loading compatible pose evidence…</p>
      )}
      {kind === "dataset" ? (
        <>
          <p>
            Group related recordings before splitting. Only human-reviewed
            landmarks contribute supervision.
          </p>
          <label>
            Dataset name
            <input
              value={asText(values.name)}
              onChange={(event) => change({ name: event.target.value })}
            />
          </label>
          {sources.map((source, index) => (
            <fieldset key={index}>
              <legend>Sequence {index + 1}</legend>
              {sourceFields(
                source,
                (next) =>
                  change({
                    sources: sources.map((row, i) =>
                      i === index ? { ...next, split: source.split } : row,
                    ),
                  }),
                true,
              )}
              <label>
                Sequence partition
                <select
                  value={source.split}
                  onChange={(event) =>
                    change({
                      sources: sources.map((row, i) =>
                        i === index
                          ? {
                              ...row,
                              split: event.target.value as TemporalSplit,
                            }
                          : row,
                      ),
                    })
                  }
                >
                  <option value="train">Train</option>
                  <option value="validation">Validation</option>
                  <option value="test">Test</option>
                </select>
              </label>
              <button
                type="button"
                onClick={() =>
                  change({ sources: sources.filter((_, i) => i !== index) })
                }
              >
                Remove sequence {index + 1}
              </button>
            </fieldset>
          ))}
          <button
            type="button"
            onClick={() =>
              change({
                sources: [...sources, { frame_track_id: "", split: "train" }],
              })
            }
          >
            Add sequence
          </button>
        </>
      ) : (
        <>
          {kind !== "inference" &&
            (connectedDataset ? (
              <p>The connected node supplies the temporal dataset.</p>
            ) : (
              <Picker
                label="Frozen temporal dataset"
                value={asText(values.dataset_id)}
                options={datasetOptions}
                onChange={(dataset_id) =>
                  change({ dataset_id, temporal_model_id: undefined })
                }
              />
            ))}
          {kind !== "training" &&
            (connectedModel ? (
              <p>The connected training node supplies the checkpoint.</p>
            ) : (
              <Picker
                label="Temporal checkpoint"
                value={asText(values.temporal_model_id)}
                options={pages
                  .flatMap((page) => page.temporal_models)
                  .filter(
                    (row) =>
                      (!selectedDataset?.schema_hash ||
                        selectedDataset.schema_hash === row.schema_hash) &&
                      (!selectedDataset?.frame_model_sha256 ||
                        selectedDataset.frame_model_sha256 ===
                          row.frame_model_sha256),
                  )}
                onChange={(temporal_model_id) =>
                  change({
                    temporal_model_id,
                    source: kind === "inference" ? {} : undefined,
                  })
                }
              />
            ))}
          {selectedModel && (
            <p>
              {selectedModel.context_mode === "causal"
                ? "Past observations only"
                : "Uses previous and future observations"}{" "}
              · {selectedModel.window_length} frames · checkpoint{" "}
              <code>{selectedModel.sha256.slice(0, 12)}</code>
            </p>
          )}
          <label>
            Device
            <select
              value={asText(values.device) || "auto"}
              onChange={(event) => change({ device: event.target.value })}
            >
              <option value="auto">Automatic</option>
              <option value="cpu">CPU</option>
              <option value="cuda">CUDA</option>
            </select>
          </label>
          {kind === "training" && (
            <>
              <label>
                Checkpoint name
                <input
                  value={asText(values.name)}
                  onChange={(event) => change({ name: event.target.value })}
                />
              </label>
              <label>
                Temporal context
                <select
                  value={asText(values.context_mode) || "centered"}
                  onChange={(event) =>
                    change({ context_mode: event.target.value })
                  }
                >
                  <option value="causal">
                    Causal · current and past frames
                  </option>
                  <option value="centered">
                    Centered · includes future frames
                  </option>
                </select>
              </label>
              <p>
                Centered inference requires future observations. The result
                records its realized look-ahead in frames and seconds.
              </p>
              {numeric("window_length", "Window length (frames)", 9, 2, 1, 129)}
              {numeric("epochs", "Epochs", 20, 1, 1, 1000)}
              {numeric("batch_size", "Batch size (windows)", 32, 1, 1, 512)}
              <details>
                <summary>Advanced training settings</summary>
                {numeric(
                  "learning_rate",
                  "Learning rate",
                  0.001,
                  0.000001,
                  "any",
                  1,
                )}
                {numeric("channels", "Temporal channels", 32, 4, 1, 256)}
                <label>
                  Maximum context gap (s)
                  <input
                    type="number"
                    min="0.001"
                    step="any"
                    placeholder="Automatic"
                    value={
                      typeof values.max_gap_seconds === "number"
                        ? values.max_gap_seconds
                        : ""
                    }
                    onChange={(event) =>
                      change({
                        max_gap_seconds: Number.isNaN(
                          event.target.valueAsNumber,
                        )
                          ? null
                          : event.target.valueAsNumber,
                      })
                    }
                  />
                </label>
                {numeric("seed", "Training seed", 1337, 0, 1)}
                <label>
                  Coordinate loss
                  <select
                    value={asText(values.loss) || "smooth_l1"}
                    onChange={(event) => change({ loss: event.target.value })}
                  >
                    <option value="smooth_l1">Smooth L1</option>
                    <option value="mse">Mean squared error</option>
                  </select>
                </label>
              </details>
            </>
          )}
          {kind === "inference" &&
            sourceFields(selectedSource, (source) => change({ source }), false)}
          {kind !== "training" &&
            numeric("chunk_size", "Output chunk (frames)", 128, 1, 1, 1024)}
          {kind === "evaluation" && (
            <details>
              <summary>Evaluation settings</summary>
              {numeric(
                "movement_threshold_px_per_second",
                "Rapid movement threshold (px/s)",
                20,
                0.001,
                "any",
              )}
              {numeric(
                "bootstrap_samples",
                "Group bootstrap samples",
                1000,
                0,
                1,
                10000,
              )}
              <AnatomicalEventFields
                value={values.anatomical_events}
                onChange={(anatomical_events) => change({ anatomical_events })}
                landmarks={selectedDataset?.landmarks ?? []}
              />
            </details>
          )}
        </>
      )}
    </>
  );
}

export function TemporalWorkflowControls({
  nodeType,
  projectId,
  parameters,
  onChange,
  connectedDataset,
  connectedModel,
}: {
  nodeType: string;
  projectId: string;
  parameters: Parameters;
  onChange: (parameters: Parameters) => void;
  connectedDataset?: boolean;
  connectedModel?: boolean;
}) {
  const kind = temporalKind(nodeType);
  const savedKey = kind === "dataset" ? "saved_dataset_id" : "saved_run_id";
  const [mode, setMode] = useState(
    Object.hasOwn(parameters, savedKey) ? "replay" : "calculate",
  );
  const savedDatasets = useQuery({
    queryKey: ["temporal-reefpose", projectId, "datasets"],
    queryFn: ({ signal }) => getTemporalDatasets(projectId, signal),
    enabled: mode === "replay" && kind === "dataset",
  });
  const savedRuns = useQuery({
    queryKey: ["temporal-reefpose", projectId, "runs"],
    queryFn: ({ signal }) => getTemporalRuns(projectId, signal),
    enabled: mode === "replay" && kind !== "dataset",
  });
  return (
    <fieldset>
      <legend>Temporal ReefPose configuration</legend>
      <label>
        Operation
        <select
          value={mode}
          onChange={(event) => {
            const next = event.target.value;
            setMode(next);
            const retained = Object.fromEntries(
              Object.entries(parameters).filter(([key]) =>
                key.startsWith("__"),
              ),
            );
            onChange(
              next === "replay" ? { ...retained, [savedKey]: "" } : retained,
            );
          }}
        >
          <option value="calculate">Calculate a new result</option>
          <option value="replay">Replay a saved result</option>
        </select>
      </label>
      {mode === "replay" ? (
        <>
          {(savedDatasets.error || savedRuns.error) && (
            <p role="alert">
              {(savedDatasets.error || savedRuns.error)?.message}
            </p>
          )}
          <Picker
            label={
              kind === "dataset"
                ? "Saved temporal dataset"
                : "Saved temporal run"
            }
            value={asText(parameters[savedKey])}
            options={
              kind === "dataset"
                ? (savedDatasets.data ?? [])
                : (savedRuns.data ?? [])
                    .filter(
                      (row) => row.kind === kind && row.status === "succeeded",
                    )
                    .map((row) => ({
                      id: row.id,
                      name: `${row.kind} · ${row.id.slice(0, 8)}`,
                    }))
            }
            onChange={(id) => onChange({ ...parameters, [savedKey]: id })}
          />
        </>
      ) : (
        <TemporalReefPoseFields
          projectId={projectId}
          kind={kind}
          values={parameters}
          onChange={onChange}
          connectedDataset={connectedDataset}
          connectedModel={connectedModel}
        />
      )}
    </fieldset>
  );
}
