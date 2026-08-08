import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FormEvent, useEffect, useRef, useState } from "react";

import {
  cancelJob,
  createInferenceJob,
  getJob,
  getImages,
  getModels,
  imageThumbnailUrl,
  importImages,
  updateImage,
  type AnnotationStatus,
  type JobRecord,
  type ModelRegistration,
  type ImageImportReport,
  type Project,
  type ProjectImageListItem,
} from "../../api/client";
import { AnnotationImportControls } from "./AnnotationImportControls";

const statuses: { value: AnnotationStatus | ""; label: string }[] = [
  { value: "", label: "All statuses" },
  { value: "unannotated", label: "Unannotated" },
  { value: "in_progress", label: "In progress" },
  { value: "annotated", label: "Annotated" },
  { value: "reviewed", label: "Reviewed" },
  { value: "excluded", label: "Excluded" },
];

function ImageCard({
  image,
  selected,
  onToggleSelected,
  onOpenAnnotation,
}: {
  image: ProjectImageListItem;
  selected: boolean;
  onToggleSelected: (imageId: string) => void;
  onOpenAnnotation?: (imageId: string) => void;
}) {
  const queryClient = useQueryClient();
  const [groupKey, setGroupKey] = useState(image.group_key ?? "");
  const [status, setStatus] = useState<AnnotationStatus>(
    image.annotation_status,
  );
  const [thumbnailFailed, setThumbnailFailed] = useState(false);

  useEffect(() => {
    setGroupKey(image.group_key ?? "");
    setStatus(image.annotation_status);
  }, [image]);

  const update = useMutation({
    mutationFn: () =>
      updateImage(image.id, {
        group_key: groupKey || null,
        annotation_status: status,
      }),
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: ["images", image.project_id],
      }),
  });

  return (
    <article className="image-card">
      <div className="thumbnail-frame">
        {image.thumbnail_path && !thumbnailFailed ? (
          <img
            src={imageThumbnailUrl(image.id)}
            alt={`Thumbnail of ${image.original_filename}`}
            loading="lazy"
            decoding="async"
            onError={() => setThumbnailFailed(true)}
          />
        ) : (
          <div className="thumbnail-placeholder" aria-label="Thumbnail pending">
            <span>Thumbnail pending</span>
          </div>
        )}
      </div>
      <div className="image-card-body">
        <div>
          <h4 title={image.original_filename}>{image.original_filename}</h4>
          <p>
            {image.width_px.toLocaleString()} x{" "}
            {image.height_px.toLocaleString()} px
          </p>
        </div>
        <label className="annotation-class-visibility">
          <input
            type="checkbox"
            checked={selected}
            onChange={() => onToggleSelected(image.id)}
          />
          Selected for inference
        </label>
        <div className="image-card-topline">
          <span className="count-chip">
            {image.annotation_count} annotations
          </span>
          <span className="count-chip secondary-chip">
            Revision {image.annotation_revision}
          </span>
        </div>
        <label>
          Image status
          <select
            value={status}
            onChange={(event) =>
              setStatus(event.target.value as AnnotationStatus)
            }
          >
            {statuses
              .filter((item) => item.value)
              .map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
          </select>
        </label>
        <label>
          Group key
          <input
            value={groupKey}
            placeholder="e.g. source-image-001"
            onChange={(event) => setGroupKey(event.target.value)}
          />
        </label>
        <div className="image-card-actions">
          <button
            type="button"
            onClick={() => onOpenAnnotation?.(image.id)}
            disabled={!onOpenAnnotation}
          >
            Annotate
          </button>
          <button
            type="button"
            className="secondary"
            onClick={() => update.mutate()}
            disabled={update.isPending}
          >
            {update.isPending ? "Saving..." : "Save metadata"}
          </button>
        </div>
        {update.error && <p className="form-error">{update.error.message}</p>}
      </div>
    </article>
  );
}

function ImportSummary({ report }: { report: ImageImportReport }) {
  const total =
    report.successful.length +
    report.duplicates.length +
    report.unsupported.length +
    report.failed.length;
  return (
    <div className="import-summary" role="status">
      <strong>{total} files processed</strong>
      <span>{report.successful.length} imported</span>
      <span>{report.duplicates.length} duplicates</span>
      <span>{report.unsupported.length} unsupported</span>
      <span>{report.failed.length} failed</span>
      {[...report.unsupported, ...report.failed].map((item) => (
        <small key={`${item.status}-${item.relative_path ?? item.filename}`}>
          {item.filename}: {item.detail}
        </small>
      ))}
    </div>
  );
}

export function Gallery({
  project,
  onOpenAnnotation,
}: {
  project: Project;
  onOpenAnnotation?: (imageId: string) => void;
}) {
  const queryClient = useQueryClient();
  const folderInput = useRef<HTMLInputElement | null>(null);
  const [page, setPage] = useState(1);
  const [filenameDraft, setFilenameDraft] = useState("");
  const [statusDraft, setStatusDraft] = useState("");
  const [groupDraft, setGroupDraft] = useState("");
  const [filters, setFilters] = useState({
    filename: "",
    annotationStatus: "",
    groupKey: "",
  });
  const [report, setReport] = useState<ImageImportReport | null>(null);
  const [selectedImageIds, setSelectedImageIds] = useState<string[]>([]);
  const [selectedModelId, setSelectedModelId] = useState("");
  const [confidenceThreshold, setConfidenceThreshold] = useState("0.25");
  const [device, setDevice] = useState("cpu");
  const [activeJobId, setActiveJobId] = useState<string | null>(null);

  useEffect(() => {
    if (folderInput.current) {
      folderInput.current.setAttribute("webkitdirectory", "");
      folderInput.current.setAttribute("directory", "");
    }
  }, []);

  const images = useQuery({
    queryKey: ["images", project.id, page, filters],
    queryFn: ({ signal }) =>
      getImages(
        project.id,
        {
          page,
          pageSize: 24,
          filename: filters.filename,
          annotationStatus: filters.annotationStatus,
          groupKey: filters.groupKey,
        },
        signal,
      ),
  });
  const detectorModels = useQuery({
    queryKey: ["models", project.id, "detector"],
    queryFn: () => getModels(project.id, "detector"),
  });
  const activeJob = useQuery({
    queryKey: ["job", activeJobId],
    queryFn: ({ signal }) => getJob(activeJobId as string, signal),
    enabled: activeJobId !== null,
    refetchInterval: (query) => {
      const state = query.state.data as JobRecord | undefined;
      return state &&
        ["succeeded", "failed", "cancelled"].includes(state.status)
        ? false
        : 1000;
    },
  });
  const importer = useMutation({
    mutationFn: (files: File[]) => importImages(project.id, files),
    onSuccess: async (result) => {
      setReport(result);
      setPage(1);
      await queryClient.invalidateQueries({ queryKey: ["images", project.id] });
    },
  });
  const inference = useMutation({
    mutationFn: () =>
      createInferenceJob(project.id, {
        model_id: selectedModelId,
        image_ids: selectedImageIds,
        confidence_threshold: Number(confidenceThreshold),
        device,
      }),
    onSuccess: (job) => {
      setActiveJobId(job.id);
    },
  });
  const cancelInference = useMutation({
    mutationFn: (jobId: string) => cancelJob(jobId),
    onSuccess: (job) => setActiveJobId(job.id),
  });

  useEffect(() => {
    if (!selectedModelId && detectorModels.data?.[0]) {
      setSelectedModelId(detectorModels.data[0].id);
    }
  }, [detectorModels.data, selectedModelId]);

  useEffect(() => {
    setSelectedImageIds([]);
  }, [
    page,
    filters.filename,
    filters.annotationStatus,
    filters.groupKey,
    project.id,
  ]);

  function applyFilters(event: FormEvent) {
    event.preventDefault();
    setPage(1);
    setFilters({
      filename: filenameDraft.trim(),
      annotationStatus: statusDraft,
      groupKey: groupDraft.trim(),
    });
  }

  function acceptFiles(fileList: FileList | null) {
    const selected = Array.from(fileList ?? []);
    if (selected.length) {
      importer.mutate(selected);
    }
  }

  function toggleSelected(imageId: string) {
    setSelectedImageIds((current) =>
      current.includes(imageId)
        ? current.filter((item) => item !== imageId)
        : [...current, imageId],
    );
  }

  const selectedModel =
    detectorModels.data?.find((model) => model.id === selectedModelId) ?? null;

  return (
    <section className="gallery-panel">
      <div className="section-heading gallery-heading">
        <div>
          <p className="eyebrow">Managed image library</p>
          <h3>Project gallery</h3>
          <span>
            {images.data?.total ?? 0} indexed images | {selectedImageIds.length}{" "}
            selected
          </span>
        </div>
        <div className="import-actions">
          <label className="button-label">
            Import files
            <input
              className="visually-hidden"
              type="file"
              accept=".jpg,.jpeg,.png,.tif,.tiff,.webp"
              multiple
              onChange={(event) => acceptFiles(event.target.files)}
            />
          </label>
          <label className="button-label secondary-label">
            Import folder
            <input
              ref={folderInput}
              className="visually-hidden"
              type="file"
              accept=".jpg,.jpeg,.png,.tif,.tiff,.webp"
              multiple
              onChange={(event) => acceptFiles(event.target.files)}
            />
          </label>
        </div>
      </div>

      {importer.isPending && <p>Importing and validating images...</p>}
      {importer.error && <p className="form-error">{importer.error.message}</p>}
      {report && <ImportSummary report={report} />}

      <AnnotationImportControls projectId={project.id} />

      <section className="annotation-sidebar-section">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Detector workflow</p>
            <h3>Run local inference</h3>
          </div>
          <span>{detectorModels.data?.length ?? 0} detector models</span>
        </div>
        <label>
          Detector model
          <select
            value={selectedModelId}
            onChange={(event) => setSelectedModelId(event.target.value)}
          >
            {detectorModels.data?.length ? (
              detectorModels.data.map((model: ModelRegistration) => (
                <option key={model.id} value={model.id}>
                  {model.display_name}
                </option>
              ))
            ) : (
              <option value="">No detector models registered</option>
            )}
          </select>
        </label>
        <label>
          Confidence threshold
          <input
            type="number"
            min="0"
            max="1"
            step="0.05"
            value={confidenceThreshold}
            onChange={(event) => setConfidenceThreshold(event.target.value)}
          />
        </label>
        <label>
          Device
          <select
            value={device}
            onChange={(event) => setDevice(event.target.value)}
          >
            <option value="cpu">CPU</option>
            <option value="auto">Auto</option>
            <option value="cuda">CUDA</option>
          </select>
        </label>
        <div className="annotation-editor-inline-actions">
          <button
            type="button"
            disabled={
              !selectedModel ||
              selectedImageIds.length === 0 ||
              inference.isPending ||
              activeJob.data?.status === "running"
            }
            onClick={() => inference.mutate()}
          >
            {inference.isPending ? "Queueing..." : "Run detector"}
          </button>
          {activeJob.data &&
            !["succeeded", "failed", "cancelled"].includes(
              activeJob.data.status,
            ) && (
              <button
                type="button"
                className="secondary"
                onClick={() => cancelInference.mutate(activeJob.data.id)}
              >
                Cancel job
              </button>
            )}
        </div>
        {inference.error && (
          <p className="form-error">{inference.error.message}</p>
        )}
        {cancelInference.error && (
          <p className="form-error">{cancelInference.error.message}</p>
        )}
        {activeJob.data && (
          <p>
            Job {activeJob.data.status}: {activeJob.data.progress_current}/
            {activeJob.data.progress_total} images
          </p>
        )}
        {activeJob.data?.error_message && (
          <p className="form-error">{activeJob.data.error_message}</p>
        )}
      </section>

      <form className="gallery-filters" onSubmit={applyFilters}>
        <label>
          Filename
          <input
            value={filenameDraft}
            placeholder="Search filenames"
            onChange={(event) => setFilenameDraft(event.target.value)}
          />
        </label>
        <label>
          Filter status
          <select
            value={statusDraft}
            onChange={(event) => setStatusDraft(event.target.value)}
          >
            {statuses.map((item) => (
              <option key={item.value || "all"} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Group key
          <input
            value={groupDraft}
            placeholder="Filter related images"
            onChange={(event) => setGroupDraft(event.target.value)}
          />
        </label>
        <button type="submit">Apply filters</button>
      </form>

      {images.isPending && <p>Loading gallery...</p>}
      {images.error && <p className="form-error">{images.error.message}</p>}
      {images.data?.total === 0 && (
        <div className="empty-state gallery-empty">
          <h4>No matching images</h4>
          <p>Import images or adjust the gallery filters.</p>
        </div>
      )}
      <div className="image-grid">
        {images.data?.items.map((image) => (
          <ImageCard
            key={image.id}
            image={image}
            selected={selectedImageIds.includes(image.id)}
            onToggleSelected={toggleSelected}
            onOpenAnnotation={onOpenAnnotation}
          />
        ))}
      </div>

      {images.data && images.data.pages > 1 && (
        <nav className="pagination" aria-label="Gallery pages">
          <button
            type="button"
            className="secondary"
            disabled={page === 1}
            onClick={() => setPage((current) => current - 1)}
          >
            Previous
          </button>
          <span>
            Page {images.data.page} of {images.data.pages}
          </span>
          <button
            type="button"
            className="secondary"
            disabled={page === images.data.pages}
            onClick={() => setPage((current) => current + 1)}
          >
            Next
          </button>
        </nav>
      )}
    </section>
  );
}
