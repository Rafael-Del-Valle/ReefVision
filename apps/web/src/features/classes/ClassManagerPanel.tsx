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

type ClassPreviewSelection = {
  targetClassId: string;
  notes: string;
  selectionKey: string;
};

type BoundClassPreview = {
  operation: ClassOperationRecord;
  selectionKey: string;
};

type MergeTargetIdentity = {
  name: string;
  class_index: number;
  scientific_name: string | null;
  state_name: string | null;
};

type MergeClassApproval = {
  targetClassId: string;
  expectedUsageCounts: Record<string, number>;
  expectedUsageFingerprint: string;
  expectedTargetIdentity: MergeTargetIdentity;
  expectedSourceIdentity: MergeTargetIdentity;
};

// A preview is not permission to execute while any safety evidence is blocked
// or absent. The backend also validates the immutable preview checksum.
function previewHasNoBlockingEvidence(
  operation: ClassOperationRecord,
): boolean {
  const plan = operation.plan;
  return (
    Array.isArray(plan?.blockers) &&
    plan.blockers.length === 0 &&
    Array.isArray(plan.blocking_records) &&
    plan.blocking_records.length === 0 &&
    Array.isArray(operation.failures) &&
    operation.failures.length === 0
  );
}

// Keep the deletion review synchronized with the thirteen scientific reference
// categories returned by ProjectService._usage_response. A partial or
// unfamiliar breakdown must never authorize irreversible class deletion.
const REQUIRED_USAGE_CATEGORIES: Readonly<
  Record<string, { mutable: boolean; immutable: boolean }>
> = {
  annotations_active: { mutable: true, immutable: false },
  annotations_deleted: { mutable: false, immutable: true },
  annotation_history: { mutable: false, immutable: true },
  mask_annotations_active: { mutable: true, immutable: false },
  mask_annotations_deleted: { mutable: false, immutable: true },
  mask_annotation_history: { mutable: false, immutable: true },
  image_labels_active: { mutable: true, immutable: false },
  image_labels_deleted: { mutable: false, immutable: true },
  prediction_proposals: { mutable: true, immutable: false },
  quality_control_issues: { mutable: true, immutable: false },
  review_queue_items: { mutable: true, immutable: false },
  dataset_versions: { mutable: false, immutable: true },
  model_registrations: { mutable: false, immutable: true },
};

// The backend cannot yet reassign these source-class modalities during Merge.
// Do not offer a misleading operation that would archive the class but strand them.
const UNSUPPORTED_MERGE_CATEGORIES = [
  "mask_annotations_active",
  "mask_annotations_deleted",
  "mask_annotation_history",
  "image_labels_active",
  "image_labels_deleted",
] as const;

function usageHasCompleteEmptyBreakdown(
  counts: Awaited<ReturnType<typeof getProjectLabelClassUsage>>["counts"],
): boolean {
  if (
    !Array.isArray(counts) ||
    counts.length !== Object.keys(REQUIRED_USAGE_CATEGORIES).length
  ) {
    return false;
  }
  const seen = new Set<string>();
  return counts.every((item) => {
    if (!item || typeof item.key !== "string" || seen.has(item.key)) {
      return false;
    }
    const expected = REQUIRED_USAGE_CATEGORIES[item.key];
    if (
      !expected ||
      item.count !== 0 ||
      item.mutable !== expected.mutable ||
      item.immutable !== expected.immutable
    ) {
      return false;
    }
    seen.add(item.key);
    return true;
  });
}

// A can_delete flag alone is not sufficient evidence to destroy a class.
// Reject cross-project results, contradictory totals and incomplete categories.
function usageConfirmsEmptyClass(
  usage: Awaited<ReturnType<typeof getProjectLabelClassUsage>> | undefined,
  projectId: string,
  classId: string,
): boolean {
  return (
    usage !== undefined &&
    usage.project_id === projectId &&
    usage.class_id === classId &&
    usage.can_delete === true &&
    usage.total_references === 0 &&
    usage.mutable_reference_count === 0 &&
    usage.immutable_reference_count === 0 &&
    usageHasCompleteEmptyBreakdown(usage.counts) &&
    Array.isArray(usage.delete_blockers) &&
    usage.delete_blockers.length === 0
  );
}

/** Fail closed if a merge approval is not bound to a complete, coherent
 * project-scoped usage count vector. Mutable and immutable totals must
 * reconcile with the thirteen backend scientific reference categories.
 */
function reviewedMergeCounts(
  usage: Awaited<ReturnType<typeof getProjectLabelClassUsage>> | undefined,
  projectId: string,
  classId: string,
): Record<string, number> | null {
  if (
    !usage ||
    usage.project_id !== projectId ||
    usage.class_id !== classId ||
    !Array.isArray(usage.counts) ||
    !Array.isArray(usage.delete_blockers) ||
    !Array.isArray(usage.compatibility_warnings) ||
    usage.counts.length !== Object.keys(REQUIRED_USAGE_CATEGORIES).length
  ) {
    return null;
  }

  const counts: Record<string, number> = {};
  let mutable = 0;
  let immutable = 0;
  for (const item of usage.counts) {
    const expected = item && REQUIRED_USAGE_CATEGORIES[item.key];
    if (
      !expected ||
      counts[item.key] !== undefined ||
      !Number.isSafeInteger(item.count) ||
      item.count < 0 ||
      item.mutable !== expected.mutable ||
      item.immutable !== expected.immutable
    ) {
      return null;
    }
    counts[item.key] = item.count;
    if (item.mutable) mutable += item.count;
    if (item.immutable) immutable += item.count;
  }
  if (
    mutable !== usage.mutable_reference_count ||
    immutable !== usage.immutable_reference_count ||
    mutable + immutable !== usage.total_references ||
    usage.can_delete !== (mutable + immutable === 0)
  ) {
    return null;
  }
  return counts;
}

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
      {(operation.plan.blocking_records ?? []).map((item) => (
        <p key={item.key} className="form-error">
          {item.label}: {item.count}
        </p>
      ))}
      {(operation.plan.blockers ?? []).map((blocker) => (
        <p key={blocker} className="form-error">
          {blocker}
        </p>
      ))}
      {(operation.failures ?? []).map((failure) => (
        <p key={failure} className="form-error">
          {failure}
        </p>
      ))}
      {operation.status === "previewed" &&
        !previewHasNoBlockingEvidence(operation) && (
          <p className="form-error" role="status">
            Execution disabled: preview contains blockers or incomplete safety
            evidence. Resolve the issues and preview again.
          </p>
        )}
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
  // An edit invalidates prior researcher approval, even after value reversion.
  const [previewEpoch, setPreviewEpoch] = useState(0);
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
  const selectedMergeTarget = mergeTargets.find(
    (candidate) => candidate.id === mergeTargetId,
  );
  const [reassignTargetId, setReassignTargetId] = useState(
    mergeTargets[0]?.id ?? "",
  );
  const [reassignPreview, setReassignPreview] =
    useState<BoundClassPreview | null>(null);
  const [reassignDeletePreview, setReassignDeletePreview] =
    useState<BoundClassPreview | null>(null);
  const [latestOperation, setLatestOperation] =
    useState<ClassOperationRecord | null>(null);
  const previewSelectionKey = JSON.stringify([
    project.id,
    labelClass.id,
    reassignTargetId,
    reassignNotes.trim(),
    previewEpoch,
  ]);
  const matchesPreview = (
    candidate: BoundClassPreview | null,
    operationType: "reassign" | "reassign_delete",
  ) =>
    candidate !== null &&
    candidate.selectionKey === previewSelectionKey &&
    candidate.operation.status === "previewed" &&
    candidate.operation.project_id === project.id &&
    candidate.operation.source_class_id === labelClass.id &&
    candidate.operation.target_class_id === reassignTargetId &&
    candidate.operation.operation_type === operationType;
  const matchesReassignPreview = matchesPreview(reassignPreview, "reassign");
  const matchesReassignDeletePreview = matchesPreview(
    reassignDeletePreview,
    "reassign_delete",
  );
  const canRunReassign =
    matchesReassignPreview &&
    reassignPreview !== null &&
    previewHasNoBlockingEvidence(reassignPreview.operation);
  const canRunReassignDelete =
    matchesReassignDeletePreview &&
    reassignDeletePreview !== null &&
    previewHasNoBlockingEvidence(reassignDeletePreview.operation);

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
    mutationFn: (approved: MergeClassApproval) =>
      mergeLabelClass(labelClass.id, {
        target_class_id: approved.targetClassId,
        expected_usage_counts: approved.expectedUsageCounts,
        expected_usage_fingerprint: approved.expectedUsageFingerprint,
        expected_target_identity: approved.expectedTargetIdentity,
        expected_source_identity: approved.expectedSourceIdentity,
      }),
    onSuccess: refresh,
  });
  const previewReassign = useMutation({
    mutationFn: (selection: ClassPreviewSelection) =>
      previewLabelClassReassign(project.id, labelClass.id, {
        target_class_id: selection.targetClassId,
        notes: selection.notes || null,
      }),
    onSuccess: (operation, selection) => {
      // Delayed HTTP responses remain non-executable if inputs have changed.
      setReassignPreview({ operation, selectionKey: selection.selectionKey });
      setLatestOperation(operation);
    },
  });
  const runReassign = useMutation({
    mutationFn: () => {
      if (!canRunReassign || !reassignPreview) {
        throw new Error(
          "Preview the current reassignment target and notes first.",
        );
      }
      return executeLabelClassReassign(project.id, labelClass.id, {
        operation_id: reassignPreview.operation.id,
        preview_checksum: reassignPreview.operation.preview_checksum,
        notes: reassignNotes.trim() || null,
      });
    },
    onSuccess: async (operation) => {
      setLatestOperation(operation);
      setReassignPreview(null);
      await refresh();
    },
  });
  const previewReassignDelete = useMutation({
    mutationFn: (selection: ClassPreviewSelection) =>
      previewLabelClassReassignDelete(project.id, labelClass.id, {
        target_class_id: selection.targetClassId,
        notes: selection.notes || null,
      }),
    onSuccess: (operation, selection) => {
      setReassignDeletePreview({
        operation,
        selectionKey: selection.selectionKey,
      });
      setLatestOperation(operation);
    },
  });
  const runReassignDelete = useMutation({
    mutationFn: () => {
      if (!canRunReassignDelete || !reassignDeletePreview) {
        throw new Error(
          "Preview the current reassign-and-delete target and notes first.",
        );
      }
      return executeLabelClassReassignDelete(project.id, labelClass.id, {
        operation_id: reassignDeletePreview.operation.id,
        preview_checksum: reassignDeletePreview.operation.preview_checksum,
        notes: reassignNotes.trim() || null,
      });
    },
    onSuccess: async (operation) => {
      setLatestOperation(operation);
      setReassignDeletePreview(null);
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

  const usageRows = Array.isArray(usage.data?.counts)
    ? usage.data.counts.filter((item) => item.count > 0)
    : [];
  const deleteBlockers = Array.isArray(usage.data?.delete_blockers)
    ? usage.data.delete_blockers
    : [];
  const compatibilityWarnings = Array.isArray(
    usage.data?.compatibility_warnings,
  )
    ? usage.data.compatibility_warnings
    : [];
  // Missing, failed, or refetching reference evidence cannot authorize deletion.
  const usageIsVerifiedEmpty = usageConfirmsEmptyClass(
    usage.data,
    project.id,
    labelClass.id,
  );
  const canDelete =
    showUsage && usage.isSuccess && !usage.isFetching && usageIsVerifiedEmpty;
  const mergeUsageCounts = reviewedMergeCounts(
    usage.data,
    project.id,
    labelClass.id,
  );
  const mergeUsageFingerprint = usage.data?.reference_fingerprint;
  const hasUnsupportedMergeReferences =
    mergeUsageCounts !== null &&
    UNSUPPORTED_MERGE_CATEGORIES.some(
      (key) => (mergeUsageCounts[key] ?? 0) > 0,
    );
  const canMerge =
    typeof mergeUsageFingerprint === "string" &&
    /^[0-9a-f]{64}$/.test(mergeUsageFingerprint) &&
    showUsage &&
    usage.isSuccess &&
    !usage.isFetching &&
    mergeUsageCounts !== null &&
    !hasUnsupportedMergeReferences &&
    selectedMergeTarget !== undefined &&
    !merge.isPending;

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
        <button
          type="button"
          className="secondary"
          onClick={() => update.mutate()}
        >
          Save
        </button>
        <button
          type="button"
          className="secondary"
          onClick={() => setShowUsage((current) => !current)}
        >
          {showUsage ? "Hide usage" : "Usage"}
        </button>
        <button
          type="button"
          className="secondary"
          onClick={() => archive.mutate()}
        >
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
      {!showUsage && (
        <p className="annotation-helper">
          Open Usage to verify class references before deleting.
        </p>
      )}
      {showUsage && usage.isFetching && (
        <p className="annotation-helper" role="status">
          Checking current class references before deletion...
        </p>
      )}
      {showUsage && usage.isError && (
        <p className="form-error" role="alert">
          Class usage could not be verified. Deletion remains disabled.
        </p>
      )}

      {showUsage &&
        usage.isSuccess &&
        !usage.isFetching &&
        usage.data &&
        !usageIsVerifiedEmpty &&
        usage.data.can_delete === true && (
          <p className="form-error" role="alert">
            Usage evidence has an inconsistent scope, reference total or
            incomplete category breakdown. Deletion remains disabled.
          </p>
        )}

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
          disabled={!canMerge}
          onClick={() => {
            if (
              selectedMergeTarget !== undefined &&
              mergeUsageCounts !== null &&
              typeof mergeUsageFingerprint === "string" &&
              /^[0-9a-f]{64}$/.test(mergeUsageFingerprint) &&
              window.confirm(
                `Merge source "${labelClass.name}" (class ${labelClass.class_index}; scientific name ${labelClass.scientific_name ?? "unspecified"}; state ${labelClass.state_name ?? "unspecified"}) into target "${selectedMergeTarget.name}" (class ${selectedMergeTarget.class_index}; scientific name ${selectedMergeTarget.scientific_name ?? "unspecified"}; state ${selectedMergeTarget.state_name ?? "unspecified"})? ${usage.data?.total_references ?? 0} reviewed class references include ${usage.data?.immutable_reference_count ?? 0} immutable references. Mutable references will be reassigned, historical records kept, and the source archived. Confirm only after inspecting Usage and the target identity.`,
              )
            ) {
              merge.mutate({
                targetClassId: selectedMergeTarget.id,
                expectedUsageCounts: { ...mergeUsageCounts },
                expectedUsageFingerprint: mergeUsageFingerprint,
                expectedTargetIdentity: {
                  name: selectedMergeTarget.name,
                  class_index: selectedMergeTarget.class_index,
                  scientific_name: selectedMergeTarget.scientific_name,
                  state_name: selectedMergeTarget.state_name,
                },
                expectedSourceIdentity: {
                  name: labelClass.name,
                  class_index: labelClass.class_index,
                  scientific_name: labelClass.scientific_name,
                  state_name: labelClass.state_name,
                },
              });
            }
          }}
        >
          {merge.isPending ? "Merging..." : "Merge class"}
        </button>
        {!showUsage && (
          <p className="annotation-helper">
            Open Usage and review scientific references before merging classes.
          </p>
        )}
        {showUsage && usage.isSuccess && !usage.isFetching && !canMerge && (
          <p className="form-error" role="status">
            {hasUnsupportedMergeReferences
              ? "Class merge is blocked while mask or image-level classification records reference this class. Review these records before merging."
              : "A complete, internally consistent class usage report is required before merging. Refresh Usage and review again."}
          </p>
        )}
      </div>

      <div className="class-merge-panel">
        <label>
          Reassign into
          <select
            value={reassignTargetId}
            onChange={(event) => {
              setReassignTargetId(event.target.value);
              setPreviewEpoch((current) => current + 1);
            }}
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
            onChange={(event) => {
              setReassignNotes(event.target.value);
              setPreviewEpoch((current) => current + 1);
            }}
            placeholder="Optional audit notes for the reassignment plan"
          />
        </label>
        <div className="class-row-actions">
          <button
            type="button"
            className="secondary"
            disabled={
              !reassignTargetId ||
              previewReassign.isPending ||
              runReassign.isPending ||
              runReassignDelete.isPending
            }
            onClick={() =>
              previewReassign.mutate({
                targetClassId: reassignTargetId,
                notes: reassignNotes.trim(),
                selectionKey: previewSelectionKey,
              })
            }
          >
            {previewReassign.isPending ? "Previewing..." : "Preview reassign"}
          </button>
          <button
            type="button"
            className="secondary"
            disabled={
              !canRunReassign ||
              previewReassign.isPending ||
              runReassign.isPending ||
              runReassignDelete.isPending
            }
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
            disabled={
              !reassignTargetId ||
              previewReassignDelete.isPending ||
              runReassign.isPending ||
              runReassignDelete.isPending
            }
            onClick={() =>
              previewReassignDelete.mutate({
                targetClassId: reassignTargetId,
                notes: reassignNotes.trim(),
                selectionKey: previewSelectionKey,
              })
            }
          >
            {previewReassignDelete.isPending
              ? "Previewing..."
              : "Preview Reassign and Delete"}
          </button>
          <button
            type="button"
            className="danger-ghost"
            disabled={
              !canRunReassignDelete ||
              previewReassignDelete.isPending ||
              runReassign.isPending ||
              runReassignDelete.isPending
            }
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

      {showUsage &&
        usage.isSuccess &&
        !usage.isFetching &&
        usage.data &&
        usage.data.project_id === project.id &&
        usage.data.class_id === labelClass.id && (
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
                {usageIsVerifiedEmpty
                  ? "This class has no references and is eligible for deletion."
                  : "No itemized references are available; check the reference total and blockers."}
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
            {deleteBlockers.length > 0 && (
              <div className="class-warning-list">
                {deleteBlockers.map((warning) => (
                  <p key={warning} className="annotation-helper">
                    {warning}
                  </p>
                ))}
              </div>
            )}
            {compatibilityWarnings.length > 0 && (
              <div className="class-warning-list">
                {compatibilityWarnings.map((warning) => (
                  <p key={warning} className="annotation-helper">
                    {warning}
                  </p>
                ))}
              </div>
            )}
          </div>
        )}

      {reassignPreview && matchesReassignPreview && (
        <OperationSummary
          operation={reassignPreview.operation}
          title="Reassign preview"
        />
      )}
      {reassignPreview && !matchesReassignPreview && (
        <p className="annotation-helper" role="status">
          Reassignment preview no longer matches this target or its notes.
          Preview again before executing.
        </p>
      )}

      {reassignDeletePreview && matchesReassignDeletePreview && (
        <OperationSummary
          operation={reassignDeletePreview.operation}
          title="Reassign and Delete preview"
        />
      )}
      {reassignDeletePreview && !matchesReassignDeletePreview && (
        <p className="annotation-helper" role="status">
          Reassign-and-delete preview no longer matches this target or its
          notes. Preview again before executing.
        </p>
      )}

      {latestOperation && latestOperation.status !== "previewed" && (
        <OperationSummary
          operation={latestOperation}
          title="Latest operation"
        />
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
      await queryClient.invalidateQueries({
        queryKey: ["project", project.id],
      });
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
