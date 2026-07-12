import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FormEvent, useEffect, useMemo, useState } from "react";

import {
  archiveLabelClass,
  createLabelClass,
  deleteLabelClass,
  executeLabelClassReassign,
  executeLabelClassReassignDelete,
  getProjectLabelClassUsage,
  mergeLabelClass,
  previewLabelClassReassign,
  previewLabelClassReassignDelete,
  restoreLabelClass,
  updateLabelClass,
  type ClassOperationRecord,
  type LabelClass,
  type Project,
} from "../../api/client";

function OperationSummary({
  operation,
  title,
}: {
  operation: ClassOperationRecord;
  title: string;
}) {
  return (
    <div className="class-usage-card">
      <strong>{title}</strong>
      <p className="annotation-helper">
        {operation.status} | {operation.operation_type.replaceAll("_", " ")}
      </p>
      {operation.plan.mutable_records.length > 0 && (
        <div className="class-usage-list">
          {operation.plan.mutable_records.map((item) => (
            <div key={item.key} className="class-usage-row">
              <span>{item.label}</span>
              <strong>{item.count}</strong>
            </div>
          ))}
        </div>
      )}
      {operation.plan.protected_records.length > 0 && (
        <div className="class-warning-list">
          {operation.plan.protected_records.map((item) => (
            <p key={item.key} className="annotation-helper">
              {item.label}: {item.count}
            </p>
          ))}
        </div>
      )}
      {operation.plan.compatibility_impacts.map((item) => (
        <p key={item.key} className="annotation-helper">
          {item.label}: {item.status}. {item.message}
        </p>
      ))}
      {operation.plan.blockers.map((blocker) => (
        <p key={blocker} className="form-error">
          {blocker}
        </p>
      ))}
      {operation.failures.map((failure) => (
        <p key={failure} className="form-error">
          {failure}
        </p>
      ))}
    </div>
  );
}

function ClassRow({
  project,
  labelClass,
  allClasses,
}: {
  project: Project;
  labelClass: LabelClass;
  allClasses: LabelClass[];
}) {
  const queryClient = useQueryClient();
  const [name, setName] = useState(labelClass.name);
  const [displayOrder, setDisplayOrder] = useState(labelClass.display_order);
  const [color, setColor] = useState(labelClass.display_color);
  const [description, setDescription] = useState(labelClass.description ?? "");
  const [showUsage, setShowUsage] = useState(false);
  const [reassignNotes, setReassignNotes] = useState("");
  const mergeTargets = useMemo(
    () =>
      allClasses.filter(
        (candidate) =>
          candidate.id !== labelClass.id &&
          candidate.is_active &&
          candidate.archived_at === null,
      ),
    [allClasses, labelClass.id],
  );
  const [mergeTargetId, setMergeTargetId] = useState(mergeTargets[0]?.id ?? "");
  const [reassignTargetId, setReassignTargetId] = useState(
    mergeTargets[0]?.id ?? "",
  );
  const [reassignPreview, setReassignPreview] =
    useState<ClassOperationRecord | null>(null);
  const [reassignDeletePreview, setReassignDeletePreview] =
    useState<ClassOperationRecord | null>(null);
  const [latestOperation, setLatestOperation] =
    useState<ClassOperationRecord | null>(null);

  useEffect(() => {
    setName(labelClass.name);
    setDisplayOrder(labelClass.display_order);
    setColor(labelClass.display_color);
    setDescription(labelClass.description ?? "");
  }, [labelClass]);

  useEffect(() => {
    if (
      mergeTargetId &&
      mergeTargets.some((candidate) => candidate.id === mergeTargetId)
    ) {
      return;
    }
    setMergeTargetId(mergeTargets[0]?.id ?? "");
  }, [mergeTargetId, mergeTargets]);

  useEffect(() => {
    if (
      reassignTargetId &&
      mergeTargets.some((candidate) => candidate.id === reassignTargetId)
    ) {
      return;
    }
    setReassignTargetId(mergeTargets[0]?.id ?? "");
  }, [mergeTargets, reassignTargetId]);

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ["project", project.id] });
    await queryClient.invalidateQueries({ queryKey: ["project_summaries"] });
    await queryClient.invalidateQueries({
      queryKey: ["label_class_usage", labelClass.id],
    });
  };

  const usage = useQuery({
    queryKey: ["label_class_usage", labelClass.id],
    queryFn: ({ signal }) =>
      getProjectLabelClassUsage(project.id, labelClass.id, signal),
    enabled: showUsage,
  });
  const update = useMutation({
    mutationFn: () =>
      updateLabelClass(labelClass.id, {
        name,
        display_order: displayOrder,
        display_color: color,
        description: description.trim() || null,
      }),
    onSuccess: refresh,
  });
  const archive = useMutation({
    mutationFn: () =>
      labelClass.is_active
        ? archiveLabelClass(labelClass.id)
        : restoreLabelClass(labelClass.id),
    onSuccess: refresh,
  });
  const deleteUnused = useMutation({
    mutationFn: () => deleteLabelClass(labelClass.id),
    onSuccess: refresh,
  });
  const merge = useMutation({
    mutationFn: () =>
      mergeLabelClass(labelClass.id, { target_class_id: mergeTargetId }),
    onSuccess: refresh,
  });
  const previewReassign = useMutation({
    mutationFn: () =>
      previewLabelClassReassign(project.id, labelClass.id, {
        target_class_id: reassignTargetId,
        notes: reassignNotes.trim() || null,
      }),
    onSuccess: (operation) => {
      setReassignPreview(operation);
      setLatestOperation(operation);
    },
  });
  const runReassign = useMutation({
    mutationFn: () => {
      if (!reassignPreview) {
        throw new Error("Preview the reassignment before executing it.");
      }
      return executeLabelClassReassign(project.id, labelClass.id, {
        operation_id: reassignPreview.id,
        preview_checksum: reassignPreview.preview_checksum,
        notes: reassignNotes.trim() || null,
      });
    },
    onSuccess: async (operation) => {
      setLatestOperation(operation);
      setReassignPreview(operation);
      await refresh();
    },
  });
  const previewReassignDelete = useMutation({
    mutationFn: () =>
      previewLabelClassReassignDelete(project.id, labelClass.id, {
        target_class_id: reassignTargetId,
        notes: reassignNotes.trim() || null,
      }),
    onSuccess: (operation) => {
      setReassignDeletePreview(operation);
      setLatestOperation(operation);
    },
  });
  const runReassignDelete = useMutation({
    mutationFn: () => {
      if (!reassignDeletePreview) {
        throw new Error("Preview reassign-and-delete before executing it.");
      }
      return executeLabelClassReassignDelete(project.id, labelClass.id, {
        operation_id: reassignDeletePreview.id,
        preview_checksum: reassignDeletePreview.preview_checksum,
        notes: reassignNotes.trim() || null,
      });
    },
    onSuccess: async (operation) => {
      setLatestOperation(operation);
      setReassignDeletePreview(operation);
      await refresh();
    },
  });

  const actionError =
    update.error ??
    archive.error ??
    deleteUnused.error ??
    merge.error ??
    previewReassign.error ??
    runReassign.error ??
    previewReassignDelete.error ??
    runReassignDelete.error ??
    usage.error;

  const usageRows =
    usage.data?.counts.filter((item) => item.count > 0) ?? [];
  const canDelete = usage.data?.can_delete ?? true;

  return (
    <li className={`class-row ${labelClass.is_active ? "" : "inactive"}`}>
      <div className="class-row-header">
        <span className="class-index">{labelClass.class_index}</span>
        <div className="class-row-title">
          <strong>{labelClass.name}</strong>
          <span className="class-meta">
            {labelClass.scientific_name ?? "No scientific name"}
            {labelClass.state_name ? ` | ${labelClass.state_name}` : ""}
          </span>
        </div>
        <span className="status-chip">
          {labelClass.archived_at ? "Archived" : "Active"}
        </span>
      </div>

      <div className="class-row-grid">
        <label>
          Name
          <input
            aria-label={`Name for class ${labelClass.class_index}`}
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
        </label>
        <label>
          Color
          <input
            aria-label={`Color for ${labelClass.name}`}
            type="color"
            value={color}
            onChange={(event) => setColor(event.target.value)}
          />
        </label>
        <label>
          Order
          <input
            aria-label={`Order for ${labelClass.name}`}
            className="order-input"
            type="number"
            min="0"
            value={displayOrder}
            onChange={(event) => setDisplayOrder(Number(event.target.value))}
          />
        </label>
      </div>

      <label>
        Description
        <textarea
          aria-label={`Description for ${labelClass.name}`}
          value={description}
          onChange={(event) => setDescription(event.target.value)}
          placeholder="Optional class description"
        />
      </label>

      <div className="class-row-actions">
        <button type="button" className="secondary" onClick={() => update.mutate()}>
          Save
        </button>
        <button
          type="button"
          className="secondary"
          onClick={() => setShowUsage((current) => !current)}
        >
          {showUsage ? "Hide usage" : "Usage"}
        </button>
        <button type="button" className="secondary" onClick={() => archive.mutate()}>
          {labelClass.is_active ? "Archive" : "Restore"}
        </button>
        <button
          type="button"
          className="danger-ghost"
          disabled={!canDelete || deleteUnused.isPending}
          onClick={() => {
            if (
              window.confirm(
                `Delete unused class "${labelClass.name}"? This cannot be undone.`,
              )
            ) {
              deleteUnused.mutate();
            }
          }}
        >
          Delete unused
        </button>
      </div>

      <div className="class-merge-panel">
        <label>
          Merge into
          <select
            value={mergeTargetId}
            onChange={(event) => setMergeTargetId(event.target.value)}
            disabled={mergeTargets.length === 0}
          >
            {mergeTargets.length === 0 ? (
              <option value="">No active target classes</option>
            ) : (
              mergeTargets.map((candidate) => (
                <option key={candidate.id} value={candidate.id}>
                  {candidate.name}
                </option>
              ))
            )}
          </select>
        </label>
        <button
          type="button"
          className="secondary"
          disabled={!mergeTargetId || merge.isPending}
          onClick={() => {
            if (
              window.confirm(
                `Merge "${labelClass.name}" into the selected class? Mutable references will be reassigned and this class will be archived.`,
              )
            ) {
              merge.mutate();
            }
          }}
        >
          Merge class
        </button>
      </div>

      <div className="class-merge-panel">
        <label>
          Reassign into
          <select
            value={reassignTargetId}
            onChange={(event) => setReassignTargetId(event.target.value)}
            disabled={mergeTargets.length === 0}
          >
            {mergeTargets.length === 0 ? (
              <option value="">No active target classes</option>
            ) : (
              mergeTargets.map((candidate) => (
                <option key={candidate.id} value={candidate.id}>
                  {candidate.name}
                </option>
              ))
            )}
          </select>
        </label>
        <label className="new-class-description">
          Operation notes
          <textarea
            value={reassignNotes}
            onChange={(event) => setReassignNotes(event.target.value)}
            placeholder="Optional audit notes for the reassignment plan"
          />
        </label>
        <div className="class-row-actions">
          <button
            type="button"
            className="secondary"
            disabled={!reassignTargetId || previewReassign.isPending}
            onClick={() => previewReassign.mutate()}
          >
            {previewReassign.isPending ? "Previewing..." : "Preview reassign"}
          </button>
          <button
            type="button"
            className="secondary"
            disabled={!reassignPreview || runReassign.isPending}
            onClick={() => {
              if (
                window.confirm(
                  `Run a class reassignment from "${labelClass.name}" into the selected target class?`,
                )
              ) {
                runReassign.mutate();
              }
            }}
          >
            {runReassign.isPending ? "Reassigning..." : "Run reassign"}
          </button>
          <button
            type="button"
            className="danger-ghost"
            disabled={!reassignTargetId || previewReassignDelete.isPending}
            onClick={() => previewReassignDelete.mutate()}
          >
            {previewReassignDelete.isPending
              ? "Previewing..."
              : "Preview Reassign and Delete"}
          </button>
          <button
            type="button"
            className="danger-ghost"
            disabled={!reassignDeletePreview || runReassignDelete.isPending}
            onClick={() => {
              if (
                window.confirm(
                  `Run Reassign and Delete for "${labelClass.name}"? ReefVision will only delete the class after all safe mutable reassignment work completes.`,
                )
              ) {
                runReassignDelete.mutate();
              }
            }}
          >
            {runReassignDelete.isPending
              ? "Deleting..."
              : "Run Reassign and Delete"}
          </button>
        </div>
      </div>

      {showUsage && usage.data && (
        <div className="class-usage-card">
          <div className="class-usage-summary">
            <strong>{usage.data.total_references} total references</strong>
            <span>
              {usage.data.mutable_reference_count} mutable |{" "}
              {usage.data.immutable_reference_count} immutable
            </span>
          </div>
          {usageRows.length === 0 ? (
            <p className="annotation-helper">
              This class is unused and can be deleted safely.
            </p>
          ) : (
            <div className="class-usage-list">
              {usageRows.map((item) => (
                <div key={item.key} className="class-usage-row">
                  <span>{item.label}</span>
                  <strong>{item.count}</strong>
                </div>
              ))}
            </div>
          )}
          {usage.data.delete_blockers.length > 0 && (
            <div className="class-warning-list">
              {usage.data.delete_blockers.map((warning) => (
                <p key={warning} className="annotation-helper">
                  {warning}
                </p>
              ))}
            </div>
          )}
          {usage.data.compatibility_warnings.length > 0 && (
            <div className="class-warning-list">
              {usage.data.compatibility_warnings.map((warning) => (
                <p key={warning} className="annotation-helper">
                  {warning}
                </p>
              ))}
            </div>
          )}
        </div>
      )}

      {reassignPreview && (
        <OperationSummary operation={reassignPreview} title="Reassign preview" />
      )}

      {reassignDeletePreview && (
        <OperationSummary
          operation={reassignDeletePreview}
          title="Reassign and Delete preview"
        />
      )}

      {latestOperation &&
        latestOperation.status !== "previewed" && (
          <OperationSummary operation={latestOperation} title="Latest operation" />
        )}

      {merge.data && (
        <div className="class-usage-card">
          <strong>Latest merge</strong>
          <div className="class-usage-list">
            {merge.data.affected_counts.map((item) => (
              <div key={item.key} className="class-usage-row">
                <span>{item.label}</span>
                <strong>{item.count}</strong>
              </div>
            ))}
          </div>
          {merge.data.warnings.map((warning) => (
            <p key={warning} className="annotation-helper">
              {warning}
            </p>
          ))}
        </div>
      )}

      {actionError && <p className="form-error">{actionError.message}</p>}
    </li>
  );
}

function NewClassForm({ project }: { project: Project }) {
  const queryClient = useQueryClient();
  const nextIndex =
    Math.max(-1, ...project.label_classes.map((item) => item.class_index)) + 1;
  const [name, setName] = useState("");
  const [classIndex, setClassIndex] = useState(nextIndex);
  const [color, setColor] = useState("#2A9D8F");
  const [description, setDescription] = useState("");
  const mutation = useMutation({
    mutationFn: () =>
      createLabelClass(project.id, {
        class_index: classIndex,
        name,
        display_color: color,
        description: description.trim() || undefined,
      }),
    onSuccess: async () => {
      setName("");
      setClassIndex((current) => current + 1);
      setDescription("");
      await queryClient.invalidateQueries({ queryKey: ["project", project.id] });
      await queryClient.invalidateQueries({ queryKey: ["project_summaries"] });
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    mutation.mutate();
  }

  return (
    <form className="new-class-form" onSubmit={submit}>
      <h3>Add annotation class</h3>
      <label>
        Class index
        <input
          type="number"
          min="0"
          value={classIndex}
          onChange={(event) => setClassIndex(Number(event.target.value))}
        />
      </label>
      <label>
        Name
        <input
          required
          value={name}
          onChange={(event) => setName(event.target.value)}
        />
      </label>
      <label>
        Color
        <input
          type="color"
          value={color}
          onChange={(event) => setColor(event.target.value)}
        />
      </label>
      <label className="new-class-description">
        Description
        <textarea
          value={description}
          onChange={(event) => setDescription(event.target.value)}
          placeholder="Optional class description"
        />
      </label>
      <button type="submit" disabled={mutation.isPending}>
        {mutation.isPending ? "Adding..." : "Add class"}
      </button>
      {mutation.error && <p className="form-error">{mutation.error.message}</p>}
    </form>
  );
}

export function ClassManagerPanel({ project }: { project: Project }) {
  return (
    <div className="class-panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Stable class indices</p>
          <h3>Annotation classes</h3>
        </div>
        <span>
          {project.label_classes.filter((item) => item.is_active).length} active
        </span>
      </div>
      <p className="annotation-helper">
        Archive classes to preserve history, inspect usage before deletion, and
        use distinct Merge, Reassign, or Reassign and Delete workflows without
        changing immutable dataset versions or registered model class maps.
      </p>
      <ul className="class-list">
        {project.label_classes.map((labelClass) => (
          <ClassRow
            key={labelClass.id}
            project={project}
            labelClass={labelClass}
            allClasses={project.label_classes}
          />
        ))}
      </ul>
      <NewClassForm project={project} />
    </div>
  );
}
