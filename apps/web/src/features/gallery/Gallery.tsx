import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FormEvent, KeyboardEvent, useEffect, useRef, useState } from "react";

import {
  getImages,
  imageDisplayUrl,
  imageThumbnailUrl,
  importImages,
  updateImage,
  type AnnotationStatus,
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
import {
  readGalleryPreference,
  resolveGalleryNavigation,
  shouldIgnoreGalleryShortcut,
  writeGalleryPreference,
  type GalleryNavigationAction,
} from "./galleryNavigation";

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
  const thumbnailVersion = image.thumbnail_path
    ? encodeURIComponent(image.thumbnail_path)
    : null;
  const thumbnailUrl = thumbnailVersion
    ? `${imageThumbnailUrl(image.id)}&rv_thumb=${thumbnailVersion}`
    : null;

  useEffect(() => {
    setGroupKey(image.group_key ?? "");
    setStatus(image.annotation_status);
  }, [image]);

  // A thumbnail job can finish after an earlier 404. Retry only when its
  // persisted path changes; ordinary query refreshes must not retry a
  // permanently broken thumbnail on every render.
  useEffect(() => {
    setThumbnailFailed(false);
  }, [image.thumbnail_path]);

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
        {thumbnailUrl && !thumbnailFailed ? (
          <img
            src={thumbnailUrl}
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

type PreviewLoadPhase =
  "loading" | "loaded" | "thumbnail-loading" | "thumbnail-loaded" | "error";

function focusedImageUrl(
  imageId: string,
  useThumbnail: boolean,
  retry: number,
  thumbnailPath?: string | null,
): string {
  const original = useThumbnail
    ? imageThumbnailUrl(imageId)
    : imageDisplayUrl(imageId);
  const retried =
    retry === 0
      ? original
      : `${original}${original.includes("?") ? "&" : "?"}rv_retry=${retry}`;
  // A background thumbnail job may replace a failed file at the same API
  // endpoint. Version the request by its persisted path to avoid a cached 404.
  return useThumbnail && thumbnailPath
    ? `${retried}${retried.includes("?") ? "&" : "?"}rv_thumb=${encodeURIComponent(thumbnailPath)}`
    : retried;
}

/**
 * Keep each image's media request lifecycle inside a keyed component.
 * Late events from a previous image cannot affect the newly focused image.
 */
function FocusedImagePreview({ image }: { image: ProjectImageListItem }) {
  const [phase, setPhase] = useState<PreviewLoadPhase>("loading");
  const [retry, setRetry] = useState(0);
  const attemptedThumbnailPath = useRef<string | null>(null);
  const imageElement = useRef<HTMLImageElement | null>(null);
  const canvasElement = useRef<HTMLDivElement | null>(null);
  const thumbnail =
    phase === "thumbnail-loading" || phase === "thumbnail-loaded";
  const waiting = phase === "loading" || phase === "thumbnail-loading";
  // A changed thumbnail path is a new image request. Give it its own DOM
  // element so late events from the previous rendition cannot affect it.
  const requestKind = thumbnail
    ? `thumbnail:${image.thumbnail_path ?? ""}`
    : "original";

  useEffect(() => {
    const canvas = canvasElement.current;
    if (!canvas) return;
    // Gallery media is a fixed preview, not a zoomable annotation canvas.
    // WebView2 otherwise scrolls the document under the cursor and makes the
    // first image appear to shift or partially change while it is loading.
    // Use a non-passive native listener so preventDefault works in WebView2.
    const containPreviewWheel = (event: WheelEvent) => {
      if (event.ctrlKey || event.metaKey) return;
      if (
        (!Number.isFinite(event.deltaX) || event.deltaX === 0) &&
        (!Number.isFinite(event.deltaY) || event.deltaY === 0)
      ) {
        return;
      }
      event.preventDefault();
      event.stopPropagation();
    };
    canvas.addEventListener("wheel", containPreviewWheel, { passive: false });
    return () => canvas.removeEventListener("wheel", containPreviewWheel);
  }, []);

  useEffect(() => {
    if (!waiting) return;
    // A cached WebView2 image can already be decoded before its load handler
    // runs. Reveal those pixels instead of leaving a false loading overlay.
    const element = imageElement.current;
    if (
      element?.complete &&
      element.naturalWidth > 0 &&
      element.naturalHeight > 0
    ) {
      setPhase(thumbnail ? "thumbnail-loaded" : "loaded");
    }
  }, [image.id, retry, thumbnail, waiting]);

  useEffect(() => {
    if (!waiting) return;
    // Some Windows WebView2 media requests stall without either a load or an
    // error event. Never leave the first image obscured indefinitely.
    const timer = window.setTimeout(() => {
      setPhase((current) => {
        // A decoded image may have missed the load event after the first
        // effect. Check again before treating the media request as failed.
        const element = imageElement.current;
        if (
          element?.complete &&
          element.naturalWidth > 0 &&
          element.naturalHeight > 0
        ) {
          return current === "thumbnail-loading"
            ? "thumbnail-loaded"
            : "loaded";
        }
        if (current === "loading") {
          return image.thumbnail_path ? "thumbnail-loading" : "error";
        }
        return current === "thumbnail-loading" ? "error" : current;
      });
    }, 30_000);
    return () => window.clearTimeout(timer);
  }, [image.thumbnail_path, phase, waiting]);

  useEffect(() => {
    if (phase === "thumbnail-loading" && image.thumbnail_path) {
      attemptedThumbnailPath.current = image.thumbnail_path;
    }
    // A background thumbnail can replace a failed or already displayed
    // rendition. Reset its loading state only when the path actually changes:
    // refreshing the same path must never create an endless retry loop.
    if (
      (phase === "error" || phase === "thumbnail-loaded") &&
      image.thumbnail_path &&
      attemptedThumbnailPath.current !== image.thumbnail_path
    ) {
      attemptedThumbnailPath.current = image.thumbnail_path;
      setPhase("thumbnail-loading");
    }
  }, [image.thumbnail_path, phase]);

  function handleLoad(event: { currentTarget: HTMLImageElement }) {
    // The load event is sufficient to reveal the image. In some WebView2
    // versions decode() can remain pending even after a successful load,
    // leaving the first image obscured by a perpetual loading indicator.
    // Keyed previews and the connection check reject stale image events.
    if (event.currentTarget.isConnected) {
      setPhase(thumbnail ? "thumbnail-loaded" : "loaded");
    }
  }

  function handleError(event: { currentTarget: HTMLImageElement }) {
    // A stale request can report an error after Retry replaced its <img>.
    // Never let that event obscure newer, successfully decoded pixels.
    if (!event.currentTarget.isConnected) return;
    setPhase((current) => {
      if (current === "loading") {
        return image.thumbnail_path ? "thumbnail-loading" : "error";
      }
      return current === "thumbnail-loading" ? "error" : current;
    });
  }

  return (
    <div ref={canvasElement} className="rv-media-canvas">
      {phase === "error" ? (
        <div className="rv-media-load-error" role="alert">
          <strong>Image could not be displayed</strong>
          <span>
            The full-resolution file and any available thumbnail could not be
            loaded. Annotation data was not changed.
          </span>
          <button
            type="button"
            className="secondary"
            onClick={() => {
              setRetry((current) => current + 1);
              setPhase("loading");
            }}
          >
            Retry image
          </button>
        </div>
      ) : (
        <>
          {waiting && (
            <p role="status" className="rv-media-load-status">
              {thumbnail
                ? "Loading thumbnail preview..."
                : "Loading full-resolution image..."}
            </p>
          )}
          {waiting && (
            <button
              type="button"
              className="secondary"
              onClick={() => {
                // WebView2 can stall without an error event. Allow the user
                // to bypass the watchdog without mutating image data.
                setRetry((current) => current + 1);
                setPhase("loading");
              }}
            >
              Retry loading image
            </button>
          )}
          {phase === "thumbnail-loaded" && (
            <>
              <p role="status" className="rv-media-load-warning">
                Full-resolution image unavailable. Showing a thumbnail preview;
                source annotations are unchanged.
              </p>
              <button
                type="button"
                className="secondary"
                onClick={() => {
                  // A transient WebView2/source failure should not strand the
                  // gallery on a low-resolution preview. Retry only the media
                  // request; never modify the original or annotations.
                  setRetry((current) => current + 1);
                  setPhase("loading");
                }}
              >
                Retry full-resolution image
              </button>
            </>
          )}
          <img
            ref={imageElement}
            key={`${retry}:${requestKind}`}
            src={focusedImageUrl(
              image.id,
              thumbnail,
              retry,
              image.thumbnail_path,
            )}
            alt={`Focused project image: ${image.original_filename}`}
            decoding="async"
            onLoad={handleLoad}
            onError={handleError}
          />
        </>
      )}
    </div>
  );
}

export function Gallery({
  project,
  onOpenAnnotation,
  onInferenceSelectionChange,
  onFocusedImageChange,
}: {
  project: Project;
  onOpenAnnotation?: (imageId: string) => void;
  onInferenceSelectionChange?: (imageIds: string[]) => void;
  onFocusedImageChange?: (imageId: string | null) => void;
}) {
  const queryClient = useQueryClient();
  const folderInput = useRef<HTMLInputElement | null>(null);
  const initialPreference = useRef(
    readGalleryPreference(window.localStorage, project.id),
  );
  const activeThumbnail = useRef<HTMLButtonElement | null>(null);
  const filmstripRef = useRef<HTMLDivElement | null>(null);
  const [page, setPage] = useState(initialPreference.current.page);
  const [pageDraft, setPageDraft] = useState(
    String(initialPreference.current.page),
  );
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
  const [focusedImageId, setFocusedImageId] = useState<string | null>(
    initialPreference.current.imageId,
  );
  const [wrapNavigation, setWrapNavigation] = useState(
    initialPreference.current.wrap,
  );
  const [pendingNavigationEdge, setPendingNavigationEdge] = useState<
    "first" | "last" | null
  >(null);
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
    onInferenceSelectionChange?.(selectedImageIds);
  }, [onInferenceSelectionChange, selectedImageIds]);

  useEffect(
    () => () => {
      onInferenceSelectionChange?.([]);
    },
    [onInferenceSelectionChange, project.id],
  );

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

  const visibleImages = images.data?.items ?? [];
  const focusedImage =
    visibleImages.find((image) => image.id === focusedImageId) ??
    visibleImages[0] ??
    null;

  useEffect(() => {
    onFocusedImageChange?.(focusedImage?.id ?? null);
  }, [focusedImage?.id, onFocusedImageChange]);

  useEffect(() => {
    if (!focusedImage) return;
    writeGalleryPreference(window.localStorage, project.id, {
      imageId: focusedImage.id,
      page,
      wrap: wrapNavigation,
    });
  }, [focusedImage, page, project.id, wrapNavigation]);

  useEffect(() => {
    const filmstrip = filmstripRef.current;
    const thumbnail = activeThumbnail.current;
    if (!filmstrip || !thumbnail) return;
    // Only move the horizontal strip, not the surrounding image viewport.
    const strip = filmstrip.getBoundingClientRect();
    const active = thumbnail.getBoundingClientRect();
    if (active.left < strip.left) {
      filmstrip.scrollLeft += active.left - strip.left;
    } else if (active.right > strip.right) {
      filmstrip.scrollLeft += active.right - strip.right;
    }
  }, [focusedImage?.id]);

  useEffect(() => {
    const filmstrip = filmstripRef.current;
    if (!filmstrip) return;

    // A vertical mouse wheel should browse the horizontal thumbnail strip,
    // not scroll the page and partially displace the focused image.
    // A non-passive native listener is needed to suppress WebView2's default
    // document scrolling; React wheel listeners can be passive at the root.
    const handleWheel = (event: WheelEvent) => {
      if (event.ctrlKey) return;
      const delta =
        Math.abs(event.deltaX) > Math.abs(event.deltaY)
          ? event.deltaX
          : event.deltaY;
      if (!Number.isFinite(delta) || delta === 0) return;
      // Even when all thumbnails fit, wheel input must not scroll the
      // surrounding document and partially displace the focused image.
      event.preventDefault();
      event.stopPropagation();
      if (filmstrip.scrollWidth <= filmstrip.clientWidth) return;
      const multiplier =
        event.deltaMode === 1
          ? 16
          : event.deltaMode === 2
            ? filmstrip.clientWidth
            : 1;
      filmstrip.scrollLeft = Math.max(
        0,
        Math.min(
          filmstrip.scrollWidth - filmstrip.clientWidth,
          filmstrip.scrollLeft + delta * multiplier,
        ),
      );
    };

    filmstrip.addEventListener("wheel", handleWheel, { passive: false });
    return () => filmstrip.removeEventListener("wheel", handleWheel);
  }, [focusedImage?.id]);

  useEffect(
    () => () => {
      onFocusedImageChange?.(null);
    },
    [onFocusedImageChange, project.id],
  );

  useEffect(() => {
    if (!images.data) return;
    if (images.data.total > 0 && page > Math.max(1, images.data.pages)) {
      setPendingNavigationEdge("first");
      setPage(Math.max(1, images.data.pages));
      return;
    }
    if (visibleImages.length === 0) {
      setFocusedImageId(null);
      return;
    }
    if (pendingNavigationEdge) {
      setFocusedImageId(
        pendingNavigationEdge === "last"
          ? visibleImages[visibleImages.length - 1].id
          : visibleImages[0].id,
      );
      setPendingNavigationEdge(null);
      return;
    }
    if (
      !focusedImageId ||
      !visibleImages.some((image) => image.id === focusedImageId)
    ) {
      setFocusedImageId(visibleImages[0].id);
    }
  }, [focusedImageId, images.data, page, pendingNavigationEdge, visibleImages]);

  function navigate(action: GalleryNavigationAction) {
    if (!focusedImage || !images.data) return;
    const destination = resolveGalleryNavigation({
      action,
      index: visibleImages.findIndex((item) => item.id === focusedImage.id),
      itemCount: visibleImages.length,
      page,
      pages: images.data.pages,
      wrap: wrapNavigation,
    });
    if (!destination) return;
    if (destination.page === page && destination.edge === "index") {
      setFocusedImageId(
        visibleImages[destination.index]?.id ?? focusedImage.id,
      );
      return;
    }
    if (destination.page === page) {
      setFocusedImageId(
        destination.edge === "last"
          ? (visibleImages[visibleImages.length - 1]?.id ?? focusedImage.id)
          : (visibleImages[0]?.id ?? focusedImage.id),
      );
      return;
    }
    setPendingNavigationEdge(destination.edge === "last" ? "last" : "first");
    setPage(destination.page);
  }

  function handleViewerKeyDown(event: KeyboardEvent<HTMLElement>) {
    if (shouldIgnoreGalleryShortcut(event.target)) return;
    const action: GalleryNavigationAction | null =
      event.key === "ArrowLeft"
        ? "previous"
        : event.key === "ArrowRight"
          ? "next"
          : event.key === "Home"
            ? "first"
            : event.key === "End"
              ? "last"
              : null;
    if (!action) return;
    event.preventDefault();
    event.stopPropagation();
    navigate(action);
  }

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
              accept=".jpg,.jpeg,.jpe,.jfif,.jfi,.jif,.png,.tif,.tiff,.webp,.bmp,.dib,.gif"
              multiple
              onChange={(event) => {
                acceptFiles(event.currentTarget.files);
                // Permit retrying the same camera file after a failed import.
                event.currentTarget.value = "";
              }}
            />
          </label>
          <label className="button-label secondary-label">
            Import folder
            <input
              ref={folderInput}
              className="visually-hidden"
              type="file"
              accept=".jpg,.jpeg,.jpe,.jfif,.jfi,.jif,.png,.tif,.tiff,.webp,.bmp,.dib,.gif"
              multiple
              onChange={(event) => {
                acceptFiles(event.currentTarget.files);
                // Permit retrying the same camera file after a failed import.
                event.currentTarget.value = "";
              }}
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
        <section
          className="rv-media-workbench"
          aria-label="Image workbench"
          aria-keyshortcuts="ArrowLeft ArrowRight Home End"
          title="Navigate images with Left/Right Arrow, Home, and End"
          tabIndex={0}
          onKeyDown={handleViewerKeyDown}
        >
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

            <FocusedImagePreview
              key={`${project.id}:${focusedImage.id}`}
              image={focusedImage}
            />

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
              ref={filmstripRef}
              className="rv-media-filmstrip"
              role="list"
              aria-label="Nearby images"
            >
              {visibleImages.map((image) => (
                <button
                  key={image.id}
                  ref={image.id === focusedImage.id ? activeThumbnail : null}
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
          <label className="rv-gallery-wrap-toggle">
            <input
              type="checkbox"
              checked={wrapNavigation}
              onChange={(event) => setWrapNavigation(event.target.checked)}
              title="Persistently wrap from the first image to the last and from the last to the first"
            />
            Wrap image navigation
          </label>
        </section>
      )}

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
