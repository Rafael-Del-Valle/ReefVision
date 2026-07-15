import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import {
  datasetExportDownloadUrl,
  datasetExportManifestUrl,
  getDatasetVersions,
  getJob,
  getProjectSummaries,
  type DatasetVersionRecord,
} from "../../api/client";
import {
  createFormattedDatasetExport,
  type DatasetExportFormat,
} from "./segmentationExportApi";

type MaskAwareDatasetVersion = DatasetVersionRecord & {
  mask_annotation_count?: number;
};

const exportOptions: Array<{
  value: DatasetExportFormat;
  label: string;
  description: string;
}> = [
  {
    value: "yolo_detection",
    label: "YOLO detection",
    description: "Frozen bounding boxes for Ultralytics detection training.",
  },
  {
    value: "yolo_segmentation",
    label: "YOLO polygon segmentation",
    description:
      "Normalized polygon labels. Raster masks are reported but skipped.",
  },
  {
    value: "semantic_masks",
    label: "Indexed semantic PNG masks",
    description:
      "One class-index PNG per image using both polygon and raster masks.",
  },
];

export function SegmentationExportLauncher() {
  const [open, setOpen] = useState(false);
  const [projectId, setProjectId] = useState("");
  const [versionId, setVersionId] = useState("");
  const [format, setFormat] =
    useState<DatasetExportFormat>("yolo_segmentation");
  const [jobId, setJobId] = useState<string | null>(null);
  const [exportId, setExportId] = useState<string | null>(null);

  const projects = useQuery({
    queryKey: ["project_summaries", "export_launcher"],
    queryFn: ({ signal }) => getProjectSummaries(signal),
    enabled: open,
  });
  const versions = useQuery({
    queryKey: ["dataset_versions", projectId, "export_launcher"],
    queryFn: ({ signal }) => getDatasetVersions(projectId, signal),
    enabled: open && projectId.length > 0,
  });
  const job = useQuery({
    queryKey: ["job", jobId, "export_launcher"],
    queryFn: ({ signal }) => getJob(jobId as string, signal),
    enabled: jobId !== null,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status && ["succeeded", "failed", "cancelled"].includes(status)
        ? false
        : 1000;
    },
  });

  useEffect(() => {
    if (!projectId && projects.data?.length) {
      setProjectId(projects.data[0].id);
    }
  }, [projectId, projects.data]);

  useEffect(() => {
    const available = versions.data ?? [];
    if (!available.some((version) => version.id === versionId)) {
      setVersionId(available[0]?.id ?? "");
    }
  }, [versionId, versions.data]);

  const selectedVersion = useMemo(
    () =>
      (versions.data?.find((version) => version.id === versionId) as
        MaskAwareDatasetVersion | undefined) ?? null,
    [versionId, versions.data],
  );
  const selectedOption =
    exportOptions.find((option) => option.value === format) ?? exportOptions[0];
  const needsMasks = format !== "yolo_detection";
  const hasMasks = (selectedVersion?.mask_annotation_count ?? 0) > 0;

  const queueExport = useMutation({
    mutationFn: () => createFormattedDatasetExport(versionId, format),
    onSuccess: ({ export: exportRecord, job: queuedJob }) => {
      setExportId(exportRecord.id);
      setJobId(queuedJob.id);
    },
  });

  return (
    <>
      <button
        type="button"
        className="secondary"
        data-testid="open-dataset-export-launcher"
        onClick={() => setOpen(true)}
        style={{
          position: "fixed",
          left: "1rem",
          bottom: "1rem",
          zIndex: 9000,
          boxShadow: "0 0.5rem 1.5rem rgba(0, 0, 0, 0.22)",
        }}
      >
        Dataset exports
      </button>

      {open && (
        <div
          className="modal-backdrop"
          role="presentation"
          style={{ zIndex: 12000 }}
        >
          <section
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="dataset-export-launcher-title"
          >
            <div className="section-heading">
              <div>
                <p className="eyebrow">Immutable dataset delivery</p>
                <h2 id="dataset-export-launcher-title">Dataset export</h2>
              </div>
              <button
                type="button"
                className="icon-button"
                onClick={() => setOpen(false)}
              >
                Close
              </button>
            </div>

            <label>
              Project
              <select
                value={projectId}
                onChange={(event) => {
                  setProjectId(event.target.value);
                  setVersionId("");
                  setJobId(null);
                  setExportId(null);
                }}
              >
                <option value="">Choose a project</option>
                {projects.data?.map((project) => (
                  <option key={project.id} value={project.id}>
                    {project.name}
                  </option>
                ))}
              </select>
            </label>

            <label>
              Immutable version
              <select
                value={versionId}
                onChange={(event) => {
                  setVersionId(event.target.value);
                  setJobId(null);
                  setExportId(null);
                }}
              >
                <option value="">Choose a version</option>
                {versions.data?.map((version) => (
                  <option key={version.id} value={version.id}>
                    v{version.version_number} - {version.name}
                  </option>
                ))}
              </select>
            </label>

            <label>
              Export format
              <select
                value={format}
                onChange={(event) => {
                  setFormat(event.target.value as DatasetExportFormat);
                  setJobId(null);
                  setExportId(null);
                }}
              >
                {exportOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
            <p className="annotation-helper">{selectedOption.description}</p>

            {selectedVersion && (
              <div className="version-preview-metrics">
                <span>{selectedVersion.image_count} images</span>
                <span>{selectedVersion.annotation_count} boxes</span>
                <span>{selectedVersion.mask_annotation_count ?? 0} masks</span>
                <span>Schema {selectedVersion.schema_version}</span>
              </div>
            )}

            {needsMasks && selectedVersion && !hasMasks && (
              <p className="form-error">
                This immutable version has no mask annotations. Create a new
                dataset version after saving masks.
              </p>
            )}
            {(projects.error || versions.error || queueExport.error) && (
              <p className="form-error">
                {
                  (projects.error ?? versions.error ?? queueExport.error)
                    ?.message
                }
              </p>
            )}

            <div className="modal-actions">
              <button
                type="button"
                className="secondary"
                onClick={() => setOpen(false)}
              >
                Close
              </button>
              <button
                type="button"
                disabled={
                  !versionId ||
                  queueExport.isPending ||
                  selectedVersion?.status !== "complete" ||
                  (needsMasks && !hasMasks)
                }
                onClick={() => queueExport.mutate()}
              >
                {queueExport.isPending
                  ? "Queueing..."
                  : `Export ${selectedOption.label}`}
              </button>
            </div>

            {job.data && (
              <div className="version-detail-card">
                <strong>Export job: {job.data.status}</strong>
                <p className="annotation-helper">
                  {job.data.error_message ??
                    `${job.data.progress_current} of ${job.data.progress_total} items processed.`}
                </p>
                {job.data.status === "succeeded" && exportId && (
                  <div className="annotation-editor-inline-actions">
                    <a href={datasetExportDownloadUrl(exportId)}>
                      Download ZIP
                    </a>
                    <a href={datasetExportManifestUrl(exportId)}>
                      Download manifest
                    </a>
                  </div>
                )}
              </div>
            )}
          </section>
        </div>
      )}
    </>
  );
}
