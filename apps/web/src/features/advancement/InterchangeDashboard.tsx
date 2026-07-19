import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type ChangeEvent, useEffect, useMemo, useState } from "react";

import type { Project } from "../../api/client";
import {
  applyInterchange,
  type ClassConflictPolicy,
  type ExistingAnnotationPolicy,
  exportInterchange,
  type InterchangeFormat,
  type InterchangeRequest,
  previewInterchange,
} from "./interchangeApi";

const formatLabels: Record<InterchangeFormat, string> = {
  coco_detection: "COCO detection",
  coco_instance: "COCO instance segmentation",
  coco_panoptic: "COCO panoptic",
  cvat: "CVAT XML",
  labelme: "LabelMe JSON",
  roboflow_coco: "Roboflow COCO",
  roboflow_yolo: "Roboflow YOLO",
};

const exampleDocument = JSON.stringify(
  {
    images: [],
    categories: [],
    annotations: [],
  },
  null,
  2,
);

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KiB`;
  if (value < 1024 * 1024 * 1024) {
    return `${(value / (1024 * 1024)).toFixed(1)} MiB`;
  }
  return `${(value / (1024 * 1024 * 1024)).toFixed(2)} GiB`;
}

function parseDocument(
  format: InterchangeFormat,
  text: string,
  filename?: string,
): Record<string, unknown> {
  if (format === "cvat") {
    return { xml: text, source_filename: filename ?? null };
  }
  const parsed = JSON.parse(text) as unknown;
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("The interchange document must be a JSON object");
  }
  return parsed as Record<string, unknown>;
}

export function InterchangeDashboard({ project }: { project: Project }) {
  const queryClient = useQueryClient();
  const [format, setFormat] = useState<InterchangeFormat>("coco_instance");
  const [documentText, setDocumentText] = useState(exampleDocument);
  const [sourceName, setSourceName] = useState("");
  const [classMapping, setClassMapping] = useState<Record<string, string>>({});
  const [createMissingClasses, setCreateMissingClasses] = useState(false);
  const [classConflictPolicy, setClassConflictPolicy] =
    useState<ClassConflictPolicy>("error");
  const [existingAnnotationPolicy, setExistingAnnotationPolicy] =
    useState<ExistingAnnotationPolicy>("append");
  const [parseError, setParseError] = useState<string | null>(null);
  const [includeImages, setIncludeImages] = useState(true);
  const [includeBoxes, setIncludeBoxes] = useState(true);
  const [includeMasks, setIncludeMasks] = useState(true);
  const [includeArchivedClasses, setIncludeArchivedClasses] = useState(false);
  const [exportFormat, setExportFormat] =
    useState<InterchangeFormat>("coco_instance");

  const activeClasses = useMemo(
    () => project.label_classes.filter((labelClass) => labelClass.is_active),
    [project.label_classes],
  );

  function buildRequest(): InterchangeRequest {
    return {
      format,
      document: parseDocument(format, documentText, sourceName || undefined),
      class_mapping: classMapping,
      create_missing_classes: createMissingClasses,
      class_conflict_policy: classConflictPolicy,
      existing_annotation_policy: existingAnnotationPolicy,
      source_name: sourceName || null,
    };
  }

  const preview = useMutation({
    mutationFn: () => {
      try {
        const request = buildRequest();
        setParseError(null);
        return previewInterchange(project.id, request);
      } catch (error) {
        const message =
          error instanceof Error ? error.message : "Interchange document is invalid";
        setParseError(message);
        throw error;
      }
    },
    onSuccess: (result) => {
      setClassMapping((current) => {
        const next = { ...current };
        for (const mapping of result.mappings) {
          if (next[mapping.source_key] || next[mapping.source_name]) continue;
          if (mapping.resolution === "create") {
            next[mapping.source_key] = "__create__";
          } else if (mapping.resolution === "skip") {
            next[mapping.source_key] = "__skip__";
          } else if (mapping.target_class_id) {
            next[mapping.source_key] = mapping.target_class_id;
          }
        }
        return next;
      });
    },
  });

  const apply = useMutation({
    mutationFn: () => {
      if (!preview.data) throw new Error("Generate a current preview before importing");
      return applyInterchange(project.id, {
        ...buildRequest(),
        preview_checksum: preview.data.preview_checksum,
      });
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["project", project.id] }),
        queryClient.invalidateQueries({ queryKey: ["project-images", project.id] }),
        queryClient.invalidateQueries({ queryKey: ["images", project.id] }),
        queryClient.invalidateQueries({ queryKey: ["project_summaries"] }),
      ]);
    },
  });

  const exportMutation = useMutation({
    mutationFn: () =>
      exportInterchange(project.id, {
        format: exportFormat,
        image_ids: [],
        include_images: includeImages,
        include_boxes: includeBoxes,
        include_masks: includeMasks,
        include_archived_classes: includeArchivedClasses,
      }),
  });

  useEffect(() => {
    preview.reset();
    apply.reset();
    setClassMapping({});
    setParseError(null);
    if (format === "cvat") {
      setDocumentText("<annotations></annotations>");
    } else {
      setDocumentText(exampleDocument);
    }
  }, [format]);

  async function loadFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    try {
      const text = await file.text();
      parseDocument(format, text, file.name);
      setDocumentText(text);
      setSourceName(file.name);
      setClassMapping({});
      setParseError(null);
      preview.reset();
      apply.reset();
    } catch (error) {
      setParseError(
        error instanceof Error ? error.message : "The selected file could not be read",
      );
    } finally {
      event.target.value = "";
    }
  }

  return (
    <section className="dashboard-panel" data-testid="interchange-dashboard">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Phase 9 interoperability</p>
          <h3>External format round trips and class mapping</h3>
          <span>
            Preview image and class collisions, resolve mappings, apply an immutable
            dry-run checksum, or export the current project to a portable ecosystem format.
          </span>
        </div>
        <span>{activeClasses.length} active project classes</span>
      </div>

      <div className="dashboard-layout">
        <div className="dashboard-sidebar">
          <article className="dashboard-card">
            <h4>Import source</h4>
            <label>
              Format
              <select
                value={format}
                onChange={(event) =>
                  setFormat(event.target.value as InterchangeFormat)
                }
              >
                {Object.entries(formatLabels).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Load local annotation file
              <input
                type="file"
                accept={format === "cvat" ? ".xml,text/xml" : ".json,application/json"}
                onChange={(event) => void loadFile(event)}
              />
            </label>
            <label>
              Source name
              <input
                value={sourceName}
                placeholder="Optional filename or dataset name"
                onChange={(event) => setSourceName(event.target.value)}
              />
            </label>
            <label>
              {format === "cvat" ? "CVAT XML" : "Annotation JSON"}
              <textarea
                rows={18}
                value={documentText}
                aria-label="Interchange document"
                onChange={(event) => {
                  setDocumentText(event.target.value);
                  preview.reset();
                  apply.reset();
                }}
              />
            </label>
          </article>

          <article className="dashboard-card">
            <h4>Conflict policy</h4>
            <label className="toggle-row">
              <input
                type="checkbox"
                checked={createMissingClasses}
                onChange={(event) => {
                  setCreateMissingClasses(event.target.checked);
                  preview.reset();
                }}
              />
              Create missing ReefVision classes
            </label>
            <label>
              Multiple source classes mapped to one class
              <select
                value={classConflictPolicy}
                onChange={(event) => {
                  setClassConflictPolicy(
                    event.target.value as ClassConflictPolicy,
                  );
                  preview.reset();
                }}
              >
                <option value="error">Block as conflict</option>
                <option value="skip">Skip later collisions</option>
                <option value="merge">Merge source categories</option>
              </select>
            </label>
            <label>
              Images with existing annotations
              <select
                value={existingAnnotationPolicy}
                onChange={(event) => {
                  setExistingAnnotationPolicy(
                    event.target.value as ExistingAnnotationPolicy,
                  );
                  preview.reset();
                }}
              >
                <option value="append">Append imported annotations</option>
                <option value="skip_image">Skip annotated images</option>
                <option value="replace_imported">Replace earlier external imports</option>
                <option value="error">Block import</option>
              </select>
            </label>
            <button
              type="button"
              disabled={preview.isPending}
              onClick={() => preview.mutate()}
            >
              {preview.isPending ? "Inspecting..." : "Preview import"}
            </button>
            {(parseError || preview.error) && (
              <p className="form-error">
                {parseError ?? preview.error?.message}
              </p>
            )}
          </article>

          <article className="dashboard-card">
            <h4>Project export</h4>
            <label>
              Export format
              <select
                value={exportFormat}
                onChange={(event) =>
                  setExportFormat(event.target.value as InterchangeFormat)
                }
              >
                {Object.entries(formatLabels).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label className="toggle-row">
              <input
                type="checkbox"
                checked={includeImages}
                onChange={(event) => setIncludeImages(event.target.checked)}
              />
              Include managed source images
            </label>
            <label className="toggle-row">
              <input
                type="checkbox"
                checked={includeBoxes}
                onChange={(event) => setIncludeBoxes(event.target.checked)}
              />
              Include bounding boxes
            </label>
            <label className="toggle-row">
              <input
                type="checkbox"
                checked={includeMasks}
                onChange={(event) => setIncludeMasks(event.target.checked)}
              />
              Include polygon and raster masks
            </label>
            <label className="toggle-row">
              <input
                type="checkbox"
                checked={includeArchivedClasses}
                onChange={(event) =>
                  setIncludeArchivedClasses(event.target.checked)
                }
              />
              Include archived classes
            </label>
            <button
              type="button"
              disabled={
                exportMutation.isPending || (!includeBoxes && !includeMasks)
              }
              onClick={() => exportMutation.mutate()}
            >
              {exportMutation.isPending ? "Exporting..." : "Create portable export"}
            </button>
            {exportMutation.error && (
              <p className="form-error">{exportMutation.error.message}</p>
            )}
          </article>
        </div>

        <div className="dashboard-main">
          {preview.data ? (
            <>
              <article className="dashboard-card">
                <div className="section-heading">
                  <div>
                    <p className="eyebrow">Dry-run result</p>
                    <h4>
                      {preview.data.valid
                        ? "Ready to import"
                        : "Resolve blocking conflicts"}
                    </h4>
                  </div>
                  <span>{preview.data.preview_checksum.slice(0, 12)}...</span>
                </div>
                <div className="version-preview-metrics">
                  <span>{preview.data.matched_image_count} matched images</span>
                  <span>{preview.data.missing_image_count} missing images</span>
                  <span>{preview.data.importable_box_count} boxes</span>
                  <span>{preview.data.importable_mask_count} masks</span>
                </div>
                {preview.data.blockers.map((blocker) => (
                  <p key={blocker} className="form-error">
                    {blocker}
                  </p>
                ))}
                {preview.data.warnings.map((warning) => (
                  <p key={warning} className="form-warning">
                    {warning}
                  </p>
                ))}
                <button
                  type="button"
                  disabled={!preview.data.valid || apply.isPending}
                  onClick={() => apply.mutate()}
                >
                  {apply.isPending ? "Importing..." : "Apply verified import"}
                </button>
                {apply.error && (
                  <p className="form-error">{apply.error.message}</p>
                )}
                {apply.data && (
                  <p className="form-success">
                    Imported {apply.data.created_annotation_ids.length} boxes and{" "}
                    {apply.data.created_mask_annotation_ids.length} masks across{" "}
                    {apply.data.affected_image_ids.length} images.
                  </p>
                )}
              </article>

              <article className="dashboard-card">
                <div className="section-heading">
                  <div>
                    <p className="eyebrow">Class mapping</p>
                    <h4>Preview and resolve collisions</h4>
                  </div>
                  <span>{preview.data.source_category_count} source categories</span>
                </div>
                <div className="dashboard-list">
                  {preview.data.mappings.map((mapping) => (
                    <div key={mapping.source_key} className="dashboard-row">
                      <div>
                        <strong>{mapping.source_name}</strong>
                        <p>
                          Source key {mapping.source_key} ·{" "}
                          {mapping.resolution.replaceAll("_", " ")}
                        </p>
                        {mapping.message && <small>{mapping.message}</small>}
                      </div>
                      <label>
                        Map to
                        <select
                          value={
                            classMapping[mapping.source_key] ??
                            mapping.target_class_id ??
                            (mapping.resolution === "create"
                              ? "__create__"
                              : mapping.resolution === "skip"
                                ? "__skip__"
                                : "")
                          }
                          onChange={(event) => {
                            setClassMapping((current) => ({
                              ...current,
                              [mapping.source_key]: event.target.value,
                            }));
                            preview.reset();
                            apply.reset();
                          }}
                        >
                          <option value="">Unmapped</option>
                          <option value="__create__">Create new class</option>
                          <option value="__skip__">Skip category</option>
                          {activeClasses.map((labelClass) => (
                            <option key={labelClass.id} value={labelClass.id}>
                              {labelClass.name}
                            </option>
                          ))}
                        </select>
                      </label>
                    </div>
                  ))}
                </div>
                <p className="annotation-helper">
                  Mapping changes invalidate the old checksum. Preview the import again
                  before Apply becomes available.
                </p>
              </article>

              <article className="dashboard-card">
                <div className="section-heading">
                  <div>
                    <p className="eyebrow">Image matching</p>
                    <h4>Source-to-project preview</h4>
                  </div>
                </div>
                <div className="dashboard-list">
                  {preview.data.images.map((image) => (
                    <div key={image.source_key} className="dashboard-row">
                      <div>
                        <strong>{image.source_filename}</strong>
                        <p>
                          {image.status.replaceAll("_", " ")} ·{" "}
                          {image.annotation_count} annotations
                        </p>
                        {image.message && <small>{image.message}</small>}
                      </div>
                      <span>{image.target_filename ?? "No match"}</span>
                    </div>
                  ))}
                </div>
              </article>
            </>
          ) : (
            <div className="empty-state">
              <h4>No import preview yet</h4>
              <p>
                Load an external annotation document and run Preview to inspect class
                mappings, image matches, conflicts, and the exact import count.
              </p>
            </div>
          )}

          {exportMutation.data && (
            <article className="dashboard-card">
              <div className="section-heading">
                <div>
                  <p className="eyebrow">Export ready</p>
                  <h4>{formatLabels[exportMutation.data.format]}</h4>
                </div>
                <span>{formatBytes(exportMutation.data.archive_size_bytes)}</span>
              </div>
              <div className="version-preview-metrics">
                <span>{exportMutation.data.image_count} images</span>
                <span>{exportMutation.data.box_annotation_count} boxes</span>
                <span>{exportMutation.data.mask_annotation_count} masks</span>
              </div>
              <p>
                Managed archive: <code>{exportMutation.data.archive_path}</code>
              </p>
              <small>SHA-256: {exportMutation.data.archive_sha256}</small>
              {exportMutation.data.warnings.map((warning) => (
                <p key={warning} className="form-warning">
                  {warning}
                </p>
              ))}
            </article>
          )}
        </div>
      </div>
    </section>
  );
}
