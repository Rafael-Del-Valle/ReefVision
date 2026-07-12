import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FormEvent, useEffect, useState } from "react";

import {
  createDatasetExport,
  createDatasetVersion,
  datasetExportDownloadUrl,
  datasetExportManifestUrl,
  getDatasetVersionComparison,
  getDatasetVersionManifest,
  getDatasetVersions,
  getExports,
  getJob,
  previewDatasetVersion,
  type AnnotationStatus,
  type DatasetSplit,
  type DatasetSplitMethod,
  type DatasetVersionCreatePayload,
  type Project,
} from "../../api/client";

const statusOptions: Array<{ value: AnnotationStatus; label: string }> = [
  { value: "unannotated", label: "Unannotated" },
  { value: "in_progress", label: "In progress" },
  { value: "annotated", label: "Annotated" },
  { value: "reviewed", label: "Reviewed" },
  { value: "excluded", label: "Excluded" },
];

const splitOptions: Array<{ value: DatasetSplit; label: string }> = [
  { value: "train", label: "Train" },
  { value: "validation", label: "Validation" },
  { value: "test", label: "Test" },
  { value: "unassigned", label: "Unassigned" },
];

const splitMethodOptions: Array<{ value: DatasetSplitMethod; label: string }> =
  [
    { value: "group_random", label: "Seeded group-aware split" },
    { value: "random", label: "Seeded image-level split" },
    { value: "manual", label: "Manual split assignment" },
    { value: "none", label: "No split assignment" },
  ];

export function DatasetVersionsPanel({ project }: { project: Project }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [notes, setNotes] = useState("");
  const [parentVersionId, setParentVersionId] = useState("");
  const [splitMethod, setSplitMethod] =
    useState<DatasetSplitMethod>("group_random");
  const [trainRatio, setTrainRatio] = useState("0.7");
  const [validationRatio, setValidationRatio] = useState("0.2");
  const [testRatio, setTestRatio] = useState("0.1");
  const [seed, setSeed] = useState("11");
  const [reuseParentAssignments, setReuseParentAssignments] = useState(false);
  const [enabledStatuses, setEnabledStatuses] = useState<
    Record<AnnotationStatus, boolean>
  >({
    unannotated: false,
    in_progress: false,
    annotated: false,
    reviewed: true,
    excluded: false,
  });
  const [manualAssignments, setManualAssignments] = useState<
    Record<string, DatasetSplit>
  >({});
  const [selectedVersionId, setSelectedVersionId] = useState<string>("");
  const [compareVersionId, setCompareVersionId] = useState<string>("");
  const [activeJobId, setActiveJobId] = useState<string | null>(null);

  const versions = useQuery({
    queryKey: ["dataset_versions", project.id],
    queryFn: ({ signal }) => getDatasetVersions(project.id, signal),
  });
  const exports = useQuery({
    queryKey: ["dataset_exports", project.id],
    queryFn: ({ signal }) => getExports(project.id, undefined, signal),
  });
  const selectedVersion =
    versions.data?.find((version) => version.id === selectedVersionId) ?? null;
  const comparison = useQuery({
    queryKey: ["dataset_version_compare", selectedVersionId, compareVersionId],
    queryFn: () =>
      getDatasetVersionComparison(selectedVersionId, compareVersionId),
    enabled:
      selectedVersionId.length > 0 &&
      compareVersionId.length > 0 &&
      selectedVersionId !== compareVersionId,
  });
  const manifest = useQuery({
    queryKey: ["dataset_version_manifest", selectedVersionId],
    queryFn: ({ signal }) =>
      getDatasetVersionManifest(selectedVersionId, signal),
    enabled: selectedVersionId.length > 0,
  });
  const activeJob = useQuery({
    queryKey: ["job", activeJobId],
    queryFn: ({ signal }) => getJob(activeJobId as string, signal),
    enabled: activeJobId !== null,
    refetchInterval: (query) => {
      const state = query.state.data;
      return state &&
        ["succeeded", "failed", "cancelled"].includes(state.status)
        ? false
        : 1000;
    },
  });

  const preview = useMutation({
    mutationFn: (payload: DatasetVersionCreatePayload) =>
      previewDatasetVersion(project.id, payload),
    onSuccess: (result) => {
      if (splitMethod !== "manual") {
        return;
      }
      setManualAssignments((current) => {
        const next = { ...current };
        result.images.forEach((image) => {
          next[image.image_id] =
            current[image.image_id] ?? image.proposed_split;
        });
        return next;
      });
    },
  });
  const create = useMutation({
    mutationFn: (payload: DatasetVersionCreatePayload) =>
      createDatasetVersion(project.id, payload),
    onSuccess: async (createdVersion) => {
      setName("");
      setNotes("");
      setParentVersionId(createdVersion.id);
      setSelectedVersionId(createdVersion.id);
      setCompareVersionId(createdVersion.parent_version_id ?? "");
      await queryClient.invalidateQueries({
        queryKey: ["dataset_versions", project.id],
      });
    },
  });
  const queueExport = useMutation({
    mutationFn: (versionId: string) => createDatasetExport(versionId),
    onSuccess: async ({ export: exportRecord, job }) => {
      setActiveJobId(job.id);
      setSelectedVersionId(exportRecord.dataset_version_id);
      await queryClient.invalidateQueries({
        queryKey: ["dataset_exports", project.id],
      });
    },
  });

  useEffect(() => {
    if (!versions.data?.length) {
      setSelectedVersionId("");
      setCompareVersionId("");
      return;
    }
    if (!selectedVersionId) {
      setSelectedVersionId(versions.data[0].id);
      setCompareVersionId(versions.data[1]?.id ?? "");
    }
  }, [selectedVersionId, versions.data]);

  useEffect(() => {
    if (
      activeJob.data &&
      ["succeeded", "failed", "cancelled"].includes(activeJob.data.status)
    ) {
      void queryClient.invalidateQueries({
        queryKey: ["dataset_exports", project.id],
      });
    }
  }, [activeJob.data, project.id, queryClient]);

  function selectedStatuses(): AnnotationStatus[] {
    return statusOptions
      .filter((item) => enabledStatuses[item.value])
      .map((item) => item.value);
  }

  function buildPayload(): DatasetVersionCreatePayload {
    return {
      name,
      notes: notes.trim() || undefined,
      parent_version_id: parentVersionId || undefined,
      eligible_annotation_statuses: selectedStatuses(),
      split_method: splitMethod,
      requested_ratios:
        splitMethod === "none" || splitMethod === "manual"
          ? undefined
          : {
              train: Number(trainRatio),
              validation: Number(validationRatio),
              test: Number(testRatio),
            },
      split_seed:
        splitMethod === "none" || splitMethod === "manual"
          ? undefined
          : Number(seed),
      reuse_parent_assignments: reuseParentAssignments,
      manual_assignments:
        splitMethod === "manual"
          ? Object.entries(manualAssignments).map(([image_id, split]) => ({
              image_id,
              split,
            }))
          : undefined,
    };
  }

  function submitPreview(event: FormEvent) {
    event.preventDefault();
    preview.mutate(buildPayload());
  }

  return (
    <section className="versions-panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Immutable snapshots</p>
          <h3>Dataset versions</h3>
        </div>
        <span>{versions.data?.length ?? 0} versions</span>
      </div>

      <div className="versions-layout">
        <div className="versions-creator">
          <form className="version-form" onSubmit={submitPreview}>
            <label>
              Version name
              <input
                value={name}
                placeholder="e.g. Release candidate 1"
                onChange={(event) => setName(event.target.value)}
              />
            </label>
            <label>
              Notes
              <textarea
                value={notes}
                placeholder="What changed in this snapshot?"
                onChange={(event) => setNotes(event.target.value)}
              />
            </label>
            <label>
              Parent version
              <select
                value={parentVersionId}
                onChange={(event) => setParentVersionId(event.target.value)}
              >
                <option value="">None</option>
                {versions.data?.map((version) => (
                  <option key={version.id} value={version.id}>
                    v{version.version_number} - {version.name}
                  </option>
                ))}
              </select>
            </label>

            <div className="version-form-row">
              <label>
                Split method
                <select
                  value={splitMethod}
                  onChange={(event) =>
                    setSplitMethod(event.target.value as DatasetSplitMethod)
                  }
                >
                  {splitMethodOptions.map((item) => (
                    <option key={item.value} value={item.value}>
                      {item.label}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Seed
                <input
                  type="number"
                  value={seed}
                  disabled={splitMethod === "none" || splitMethod === "manual"}
                  onChange={(event) => setSeed(event.target.value)}
                />
              </label>
            </div>

            <div className="version-form-row">
              <label>
                Train ratio
                <input
                  type="number"
                  min="0"
                  max="1"
                  step="0.05"
                  value={trainRatio}
                  disabled={splitMethod === "none" || splitMethod === "manual"}
                  onChange={(event) => setTrainRatio(event.target.value)}
                />
              </label>
              <label>
                Validation ratio
                <input
                  type="number"
                  min="0"
                  max="1"
                  step="0.05"
                  value={validationRatio}
                  disabled={splitMethod === "none" || splitMethod === "manual"}
                  onChange={(event) => setValidationRatio(event.target.value)}
                />
              </label>
              <label>
                Test ratio
                <input
                  type="number"
                  min="0"
                  max="1"
                  step="0.05"
                  value={testRatio}
                  disabled={splitMethod === "none" || splitMethod === "manual"}
                  onChange={(event) => setTestRatio(event.target.value)}
                />
              </label>
            </div>

            <label className="toggle-row">
              <input
                type="checkbox"
                checked={reuseParentAssignments}
                onChange={(event) =>
                  setReuseParentAssignments(event.target.checked)
                }
              />
              Reuse compatible split assignments from the selected parent
              version
            </label>

            <div className="version-status-grid">
              {statusOptions.map((item) => (
                <label key={item.value} className="toggle-row">
                  <input
                    type="checkbox"
                    checked={enabledStatuses[item.value]}
                    onChange={(event) =>
                      setEnabledStatuses((current) => ({
                        ...current,
                        [item.value]: event.target.checked,
                      }))
                    }
                  />
                  {item.label}
                </label>
              ))}
            </div>

            <div className="version-actions">
              <button type="submit" disabled={preview.isPending}>
                {preview.isPending ? "Previewing..." : "Preview snapshot"}
              </button>
              <button
                type="button"
                className="secondary"
                disabled={create.isPending || !name.trim()}
                onClick={() => create.mutate(buildPayload())}
              >
                {create.isPending ? "Creating..." : "Create immutable version"}
              </button>
            </div>
            {(preview.error || create.error) && (
              <p className="form-error">
                {(preview.error ?? create.error)?.message}
              </p>
            )}
          </form>

          {preview.data && (
            <div className="version-preview-card">
              <div className="section-heading">
                <div>
                  <p className="eyebrow">Preview</p>
                  <h4>Snapshot summary</h4>
                </div>
                <span>{preview.data.resolved_split_method}</span>
              </div>
              <div className="version-preview-metrics">
                <span>{preview.data.eligible_image_count} images</span>
                <span>
                  {preview.data.eligible_annotation_count} annotations
                </span>
                <span>
                  {preview.data.missing_group_key_count} missing group keys
                </span>
              </div>
              <div className="version-split-grid">
                {preview.data.split_summary.map((summary) => (
                  <div key={summary.split} className="version-split-card">
                    <strong>{summary.split}</strong>
                    <span>{summary.image_count} images</span>
                    <span>{summary.annotation_count} annotations</span>
                  </div>
                ))}
              </div>
              {preview.data.warnings.length > 0 && (
                <div className="editor-message error">
                  {preview.data.warnings.map((warning) => (
                    <p key={warning}>{warning}</p>
                  ))}
                </div>
              )}
              <div className="version-class-counts">
                {preview.data.per_class_counts.map((item) => (
                  <span key={item.label_class_id} className="count-chip">
                    {item.class_name}: {item.count}
                  </span>
                ))}
              </div>
              {splitMethod === "manual" && (
                <div className="manual-split-table">
                  {preview.data.images.map((image) => (
                    <div key={image.image_id} className="manual-split-row">
                      <div>
                        <strong>{image.original_filename}</strong>
                        <p>
                          {image.annotation_count} annotations
                          {image.group_key
                            ? ` | ${image.group_key}`
                            : " | no group key"}
                        </p>
                      </div>
                      <select
                        value={
                          manualAssignments[image.image_id] ??
                          image.proposed_split
                        }
                        onChange={(event) =>
                          setManualAssignments((current) => ({
                            ...current,
                            [image.image_id]: event.target
                              .value as DatasetSplit,
                          }))
                        }
                      >
                        {splitOptions.map((option) => (
                          <option key={option.value} value={option.value}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        <div className="versions-browser">
          {versions.isPending && <p>Loading dataset versions...</p>}
          {versions.error && (
            <p className="form-error">{versions.error.message}</p>
          )}
          {versions.data?.length === 0 && (
            <div className="empty-state gallery-empty">
              <h4>No dataset versions yet</h4>
              <p>Preview a snapshot and create the first immutable version.</p>
            </div>
          )}
          <div className="version-list">
            {versions.data?.map((version) => (
              <button
                type="button"
                key={version.id}
                className={`version-card ${
                  selectedVersionId === version.id ? "selected" : ""
                }`}
                onClick={() => setSelectedVersionId(version.id)}
              >
                <strong>
                  v{version.version_number} - {version.name}
                </strong>
                <span>{version.image_count} images</span>
                <span>{version.annotation_count} annotations</span>
                <small>{version.manifest_sha256.slice(0, 12)}...</small>
              </button>
            ))}
          </div>

          {selectedVersion && (
            <div className="version-detail-card">
              <div className="section-heading">
                <div>
                  <p className="eyebrow">Selected version</p>
                  <h4>
                    v{selectedVersion.version_number} - {selectedVersion.name}
                  </h4>
                </div>
                <button
                  type="button"
                  disabled={
                    queueExport.isPending ||
                    selectedVersion.status !== "complete"
                  }
                  onClick={() => queueExport.mutate(selectedVersion.id)}
                >
                  {queueExport.isPending
                    ? "Queueing export..."
                    : "Export YOLO dataset"}
                </button>
              </div>
              <p className="annotation-helper">
                {selectedVersion.notes || "No version notes."}
              </p>
              <div className="version-preview-metrics">
                <span>Status: {selectedVersion.status}</span>
                <span>Schema: {selectedVersion.schema_version}</span>
                <span>App: {selectedVersion.reefvision_version}</span>
              </div>
              {selectedVersion.warnings_json.length > 0 && (
                <div className="editor-message error">
                  {selectedVersion.warnings_json.map((warning) => (
                    <p key={warning}>{warning}</p>
                  ))}
                </div>
              )}
              <div className="version-actions">
                <label>
                  Compare against
                  <select
                    value={compareVersionId}
                    onChange={(event) =>
                      setCompareVersionId(event.target.value)
                    }
                  >
                    <option value="">Choose another version</option>
                    {versions.data
                      ?.filter((version) => version.id !== selectedVersion.id)
                      .map((version) => (
                        <option key={version.id} value={version.id}>
                          v{version.version_number} - {version.name}
                        </option>
                      ))}
                  </select>
                </label>
                <div className="version-manifest-links">
                  <span>
                    Manifest checksum: {selectedVersion.manifest_sha256}
                  </span>
                  {manifest.data && (
                    <span>
                      {Object.keys(manifest.data.manifest_json).length}{" "}
                      top-level sections
                    </span>
                  )}
                </div>
              </div>
              {comparison.data && (
                <div className="version-compare-grid">
                  <div className="version-split-card">
                    <strong>Added images</strong>
                    <span>{comparison.data.added_images.length}</span>
                  </div>
                  <div className="version-split-card">
                    <strong>Removed images</strong>
                    <span>{comparison.data.removed_images.length}</span>
                  </div>
                  <div className="version-split-card">
                    <strong>Changed images</strong>
                    <span>{comparison.data.changed_images.length}</span>
                  </div>
                  <div className="version-split-card">
                    <strong>Annotation delta</strong>
                    <span>{comparison.data.annotation_delta}</span>
                  </div>
                </div>
              )}
              {comparison.error && (
                <p className="form-error">{comparison.error.message}</p>
              )}
            </div>
          )}

          <div className="export-list-card">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Recent exports</p>
                <h4>Derived datasets</h4>
              </div>
              <span>{exports.data?.length ?? 0} exports</span>
            </div>
            {activeJob.data && (
              <p>
                Export job {activeJob.data.status}:{" "}
                {activeJob.data.progress_current}/
                {activeJob.data.progress_total}
              </p>
            )}
            {activeJob.data?.error_message && (
              <p className="form-error">{activeJob.data.error_message}</p>
            )}
            <div className="export-list">
              {exports.data?.map((item) => (
                <div key={item.id} className="export-row">
                  <div>
                    <strong>{item.format}</strong>
                    <p>
                      {item.status} | {item.output_path}
                    </p>
                  </div>
                  <div className="export-links">
                    {item.status === "succeeded" && (
                      <>
                        <a
                          className="button-link"
                          href={datasetExportDownloadUrl(item.id)}
                        >
                          Download zip
                        </a>
                        <a
                          className="button-link secondary-link"
                          href={datasetExportManifestUrl(item.id)}
                        >
                          Manifest
                        </a>
                      </>
                    )}
                  </div>
                </div>
              ))}
            </div>
            {exports.error && (
              <p className="form-error">{exports.error.message}</p>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
