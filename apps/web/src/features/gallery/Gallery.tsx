import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FormEvent, KeyboardEvent, useEffect, useRef, useState } from "react";

import {
  cancelJob,
  createInferenceJob,
  getJob,
  getImages,
  getModels,
  imageDisplayUrl,
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
import {
  EmptyState,
  ErrorState,
  LoadingState,
} from "../../components/ui/AsyncState";
import { StatusBadge } from "../../components/ui/StatusBadge";
import { WorkspaceShell } from "../../components/ui/WorkspaceShell";

const statuses: { value: AnnotationStatus | ""; label: string }[] = [
  { value: "", label: "All statuses" },
  { value: "unannotated", label: "Unannotated" },
  { value: "in_progress", label: "In progress" },
  { value: "annotated", label: "Annotated" },
  { value: "reviewed", label: "Reviewed" },
  { value: "excluded", label: "Excluded" },
];

const IMAGE_IMPORT_BATCH_SIZE = 10;

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
    <article
      className={`image-card ${selected ? "selected" : ""}`}
      tabIndex={0}
      aria-label={`${image.original_filename}, ${image.annotation_count} annotations, ${status}`}
      onDoubleClick={() => onOpenAnnotation?.(image.id)}
      onKeyDown={(event: KeyboardEvent<HTMLElement>) => {
        if (event.key === "Enter") onOpenAnnotation?.(image.id);
        if (event.key === " ") {
          event.preventDefault();
          onToggleSelected(image.id);
        }
      }}
    >
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
        <div className="image-card-identity">
          <h4 title={image.original_filename}>{image.original_filename}</h4>
          <p>
            {image.width_px.toLocaleString()} x{" "}
            {image.height_px.toLocaleString()} px
          </p>
        </div>
        <label className="image-card-select">
          <input
            type="checkbox"
            checked={selected}
            onChange={() => onToggleSelected(image.id)}
          />
          Select image
        </label>
        <div className="image-card-topline">
          <span className="count-chip">
            {image.annotation_count} annotations
          </span>
          <StatusBadge status={status} />
        </div>
        <div className="image-card-actions">
          <button
            type="button"
            onClick={() => onOpenAnnotation?.(image.id)}
            disabled={!onOpenAnnotation}
          >
            Annotate
          </button>
        </div>
        <details className="image-card-details">
          <summary>Image details</summary>
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
          <small>Annotation revision {image.annotation_revision}</small>
          <button
            type="button"
            className="secondary"
            onClick={() => update.mutate()}
            disabled={update.isPending}
          >
            {update.isPending ? "Saving..." : "Save metadata"}
          </button>
        </details>
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
  const [pageDraft, setPageDraft] = useState("1");
  const [filenameDraft, setFilenameDraft] = useState("");
  const [statusDraft, setStatusDraft] = useState("");
  const [groupDraft, setGroupDraft] = useState("");
  const [filters, setFilters] = useState({
    filename: "",
    annotationStatus: "",
    groupKey: "",
  });
  const [report, setReport] = useState<ImageImportReport | null>(null);
  const [importProgress, setImportProgress] = useState<{
    processed: number;
    total: number;
  } | null>(null);
  const [selectedImageIds, setSelectedImageIds] = useState<string[]>([]);
  const [focusedImageId, setFocusedImageId] = useState<string | null>(null);
  const [selectedModelId, setSelectedModelId] = useState("");
  const [confidenceThreshold, setConfidenceThreshold] = useState("0.25");
  const [device, setDevice] = useState("cpu");
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [sortBy, setSortBy] = useState<
    "filename" | "newest" | "oldest" | "annotations"
  >("newest");
  const [showAdvanced, setShowAdvanced] = useState(false);

  useEffect(() => {
    if (folderInput.current) {
      folderInput.current.setAttribute("webkitdirectory", "");
      folderInput.current.setAttribute("directory", "");
    }
  }, []);

  const images = useQuery({
    queryKey: ["images", project.id, page, filters, sortBy],
    queryFn: ({ signal }) =>
      getImages(
        project.id,
        {
          page,
          pageSize: 24,
          filename: filters.filename,
          annotationStatus: filters.annotationStatus,
          groupKey: filters.groupKey,
          sortBy,
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
    mutationFn: async (files: File[]) => {
      const combined: ImageImportReport = {
        project_id: project.id,
        successful: [],
        duplicates: [],
        unsupported: [],
        failed: [],
      };
      setReport(null);
      setImportProgress({ processed: 0, total: files.length });

      for (
        let index = 0;
        index < files.length;
        index += IMAGE_IMPORT_BATCH_SIZE
      ) {
        const batch = files.slice(index, index + IMAGE_IMPORT_BATCH_SIZE);
        const result = await importImages(project.id, batch);
        combined.successful.push(...result.successful);
        combined.duplicates.push(...result.duplicates);
        combined.unsupported.push(...result.unsupported);
        combined.failed.push(...result.failed);

        const processed = Math.min(index + batch.length, files.length);
        setImportProgress({ processed, total: files.length });
        setReport({
          ...combined,
          successful: [...combined.successful],
          duplicates: [...combined.duplicates],
          unsupported: [...combined.unsupported],
          failed: [...combined.failed],
        });
      }

      return combined;
    },
    onSuccess: async (result) => {
      setReport(result);
      setSortBy("newest");
      setPage(1);
      await queryClient.invalidateQueries({ queryKey: ["images", project.id] });
    },
    onSettled: () => setImportProgress(null),
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
    sortBy,
    project.id,
  ]);

  useEffect(() => {
    setPageDraft(String(page));
  }, [page]);

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

  const visibleImages = images.data?.items ?? [];
  const focusedImage =
    visibleImages.find((image) => image.id === focusedImageId) ??
    visibleImages[0] ??
    null;

  useEffect(() => {
    if (visibleImages.length === 0) {
      setFocusedImageId(null);
      return;
    }
    if (
      !focusedImageId ||
      !visibleImages.some((image) => image.id === focusedImageId)
    ) {
      setFocusedImageId(visibleImages[0].id);
    }
  }, [focusedImageId, visibleImages]);

  function jumpToPage(event: FormEvent) {
    event.preventDefault();
    const totalPages = images.data?.pages ?? 1;
    const requested = Number.parseInt(pageDraft, 10);
    if (!Number.isFinite(requested)) {
      setPageDraft(String(page));
      return;
    }
    const destination = Math.max(1, Math.min(totalPages, requested));
    setPage(destination);
    setPageDraft(String(destination));
  }

  function resetFilters() {
    setFilenameDraft("");
    setStatusDraft("");
    setGroupDraft("");
    setFilters({ filename: "", annotationStatus: "", groupKey: "" });
    setPage(1);
  }

  return (
    <WorkspaceShell
      className="gallery-panel"
      eyebrow="Images & annotation"
      title="Project gallery"
      description={`Browse, select, and annotate imagery in ${project.name}.`}
      actions={
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
      }
    >
      {importer.isPending && (
        <LoadingState
          title={
            importProgress
              ? `Importing images (${importProgress.processed}/${importProgress.total})`
              : "Importing images"
          }
          description="ReefVision imports large selections in smaller batches while validating files, checking duplicates, and creating managed copies."
        />
      )}
      {importer.error && (
        <ErrorState
          title="Images could not be imported"
          message="ReefVision could not complete this import."
          error={importer.error}
        />
      )}
      {report && <ImportSummary report={report} />}

      {focusedImage && (
        <section className="rv-media-workbench" aria-label="Image workbench">
          <div className="rv-media-viewer">
            <div className="rv-media-viewer-toolbar">
              <div>
                <p className="eyebrow">Focused image</p>
                <strong title={focusedImage.original_filename}>
                  {focusedImage.original_filename}
                </strong>
              </div>
              <div className="rv-media-viewer-actions">
                <StatusBadge status={focusedImage.annotation_status} />
                <button
                  type="button"
                  className="secondary"
                  onClick={() => toggleSelected(focusedImage.id)}
                >
                  {selectedImageIds.includes(focusedImage.id)
                    ? "Remove from batch"
                    : "Add to batch"}
                </button>
                <button
                  type="button"
                  onClick={() => onOpenAnnotation?.(focusedImage.id)}
                  disabled={!onOpenAnnotation}
                >
                  Open annotation editor
                </button>
              </div>
            </div>

            <div className="rv-media-canvas">
              <img
                src={imageDisplayUrl(focusedImage.id)}
                alt={`Focused project image: ${focusedImage.original_filename}`}
                decoding="async"
              />
            </div>

            <div className="rv-filmstrip-heading">
              <span>
                Image{" "}
                {visibleImages.findIndex(
                  (image) => image.id === focusedImage.id,
                ) + 1}{" "}
                of {visibleImages.length} on this page
              </span>
              <span>Scroll the filmstrip to review nearby images</span>
            </div>

            <div
              className="rv-media-filmstrip"
              role="list"
              aria-label="Nearby images"
            >
              {visibleImages.map((image) => (
                <button
                  key={image.id}
                  type="button"
                  role="listitem"
                  className={
                    image.id === focusedImage.id ? "active" : undefined
                  }
                  aria-label={`Focus ${image.original_filename}`}
                  aria-current={
                    image.id === focusedImage.id ? "true" : undefined
                  }
                  onClick={() => setFocusedImageId(image.id)}
                >
                  <span className="rv-filmstrip-thumbnail">
                    {image.thumbnail_path ? (
                      <img
                        src={imageThumbnailUrl(image.id)}
                        alt=""
                        loading="lazy"
                        decoding="async"
                      />
                    ) : (
                      <span aria-hidden="true">…</span>
                    )}
                  </span>
                  <span className="rv-filmstrip-meta">
                    <strong>{image.original_filename}</strong>
                    <small>
                      {image.annotation_count} annotations ·{" "}
                      {image.annotation_status.replaceAll("_", " ")}
                    </small>
                  </span>
                  <span
                    className={`rv-filmstrip-status status-${image.annotation_status}`}
                    aria-hidden="true"
                  />
                </button>
              ))}
            </div>
          </div>

          <aside
            className="rv-media-context"
            aria-label="Focused image inspector"
          >
            <p className="eyebrow">Image inspector</p>
            <h3>{focusedImage.original_filename}</h3>
            <dl>
              <div>
                <dt>Dimensions</dt>
                <dd>
                  {focusedImage.width_px.toLocaleString()} ×{" "}
                  {focusedImage.height_px.toLocaleString()}
                </dd>
              </div>
              <div>
                <dt>Annotations</dt>
                <dd>{focusedImage.annotation_count}</dd>
              </div>
              <div>
                <dt>Status</dt>
                <dd>{focusedImage.annotation_status.replaceAll("_", " ")}</dd>
              </div>
              <div>
                <dt>Revision</dt>
                <dd>{focusedImage.annotation_revision}</dd>
              </div>
              <div>
                <dt>Group</dt>
                <dd>{focusedImage.group_key || "Unassigned"}</dd>
              </div>
            </dl>
            <p>
              The central viewer is for scientific review and navigation. Open
              the annotation editor for geometry edits, model proposals, scale
              calibration, and verified annotation changes.
            </p>
          </aside>
        </section>
      )}

      <section className="annotation-sidebar-section">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Project models</p>
            <h3>Batch model deployment</h3>
          </div>
          <span>{detectorModels.data?.length ?? 0} project models</span>
        </div>
        <p className="annotation-helper">
          Run a trained or imported project model such as best.pt on the
          selected images. Grounding DINO and other prompted, open-vocabulary
          tools remain separate assist workflows.
        </p>
        <label>
          Trained or imported project model
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
              <option value="">No project models registered</option>
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
            <option value="auto">Auto</option>
            <option value="cuda">CUDA</option>
            <option value="cpu">CPU</option>
          </select>
        </label>
        <div className="annotation-editor-inline-actions">
          <button
            type="button"
            disabled={
              !selectedModel ||
              selectedImageIds.length === 0 ||
              inference.isPending ||
              activeJob.data?.status === "queued" ||
              activeJob.data?.status === "running"
            }
            onClick={() => inference.mutate()}
          >
            {inference.isPending
              ? "Queueing model..."
              : "Run model on selected images"}
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
          <p className="annotation-helper">
            Model job {activeJob.data.status}: {activeJob.data.progress_current}
            /{activeJob.data.progress_total} images
          </p>
        )}
        {activeJob.data?.error_message && (
          <p className="form-error">{activeJob.data.error_message}</p>
        )}
      </section>

      <details
        className="gallery-advanced"
        open={showAdvanced}
        onToggle={(event) => setShowAdvanced(event.currentTarget.open)}
      >
        <summary>Advanced annotation import</summary>
        <AnnotationImportControls projectId={project.id} />
      </details>

      <form className="gallery-filters" onSubmit={applyFilters}>
        <label>
          Filename
          <input
            value={filenameDraft}
            placeholder="Search filenames"
            onChange={(event) => {
              const value = event.target.value;
              setFilenameDraft(value);
              setFilters((current) => ({ ...current, filename: value.trim() }));
              setPage(1);
            }}
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
        <label>
          Sort
          <select
            value={sortBy}
            onChange={(event) => {
              setSortBy(event.target.value as typeof sortBy);
              setPage(1);
            }}
          >
            <option value="newest">Newest first</option>
            <option value="oldest">Oldest first</option>
            <option value="filename">Filename</option>
            <option value="annotations">Annotation count</option>
          </select>
        </label>
        <button type="submit">Apply filters</button>
        <button type="button" className="secondary" onClick={resetFilters}>
          Clear
        </button>
      </form>

      <div className="gallery-selection-toolbar" aria-live="polite">
        <strong>{selectedImageIds.length} selected</strong>
        <button
          type="button"
          className="secondary"
          disabled={visibleImages.length === 0}
          onClick={() =>
            setSelectedImageIds(visibleImages.map((image) => image.id))
          }
        >
          Select all visible
        </button>
        <button
          type="button"
          className="secondary"
          disabled={selectedImageIds.length === 0}
          onClick={() => setSelectedImageIds([])}
        >
          Clear selection
        </button>
      </div>

      {images.isPending && (
        <LoadingState
          title="Loading images"
          description="Preparing thumbnails and annotation status."
        />
      )}
      {images.error && (
        <ErrorState
          title="Images could not be loaded"
          message="ReefVision could not load this project's images."
          error={images.error}
          onRetry={() => void images.refetch()}
        />
      )}
      {images.data?.total === 0 && (
        <EmptyState
          title={
            filters.filename || filters.annotationStatus || filters.groupKey
              ? "No matching images"
              : "No images yet"
          }
          description={
            filters.filename || filters.annotationStatus || filters.groupKey
              ? "Clear or adjust the gallery filters."
              : "Import images to begin annotation."
          }
        />
      )}
      <div className="image-grid">
        {visibleImages.map((image) => (
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
            onClick={() => setPage(1)}
          >
            First
          </button>
          <button
            type="button"
            className="secondary"
            disabled={page === 1}
            onClick={() => setPage((current) => current - 1)}
          >
            Previous
          </button>
          <form onSubmit={jumpToPage}>
            <label>
              Page
              <input
                type="number"
                min={1}
                max={images.data.pages}
                step={1}
                value={pageDraft}
                aria-label="Page number"
                onChange={(event) => setPageDraft(event.target.value)}
                onBlur={(event) => {
                  if (event.currentTarget.form) {
                    event.currentTarget.form.requestSubmit();
                  }
                }}
              />
            </label>
            <span> of {images.data.pages}</span>
            <button type="submit" className="secondary">
              Go
            </button>
          </form>
          <button
            type="button"
            className="secondary"
            disabled={page === images.data.pages}
            onClick={() => setPage((current) => current + 1)}
          >
            Next
          </button>
          <button
            type="button"
            className="secondary"
            disabled={page === images.data.pages}
            onClick={() => setPage(images.data.pages)}
          >
            Last
          </button>
        </nav>
      )}
    </WorkspaceShell>
  );
}
