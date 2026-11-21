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

// A reviewed plan must be complete through its nested records and warnings.
// Invalid records cannot be rendered or treated as researcher authorization.
function validReviewText(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function validReviewTextList(value: unknown): value is string[] {
  return Array.isArray(value) && value.every(validReviewText);
}

function validReviewGroup(value: unknown): boolean {
  if (!value || typeof value !== "object") return false;
  const item = value as Record<string, unknown>;
  // Backend group counts equal the complete listed IDs, not a sample.
  // Never allow a partial review response to authorize class operations.
  return (
    validReviewText(item.key) &&
    validReviewText(item.label) &&
    typeof item.count === "number" &&
    Number.isSafeInteger(item.count) &&
    item.count >= 0 &&
    validReviewTextList(item.record_ids) &&
    item.count === item.record_ids.length &&
    new Set(item.record_ids).size === item.record_ids.length
  );
}

// Reassignment preview groups are a typed inventory, not arbitrary display
// rows. An unfamiliar or repeated category could conceal scientific references
// while still passing checks on individual record counts and identifiers.
const UNSUPPORTED_MERGE_CATEGORIES = [
  "mask_annotations_active",
  "mask_annotations_deleted",
  "mask_annotation_history",
  "image_labels_active",
  "image_labels_deleted",
] as const;

const MUTABLE_PREVIEW_KEYS = new Set([
  "annotations_active",
  "prediction_proposals_pending",
  "quality_control_issues_open",
  "review_queue_items_open",
]);
const PROTECTED_PREVIEW_KEYS = new Set([
  "annotations_deleted",
  "annotation_history",
  "prediction_proposals_historical",
  "quality_control_issues_closed",
  "review_queue_items_closed",
  "dataset_versions",
  "model_registrations",
  ...UNSUPPORTED_MERGE_CATEGORIES,
]);
const BLOCKING_PREVIEW_KEYS = new Set([
  "review_queue_items_workflow",
  "annotations_deleted",
  "prediction_proposals_historical",
  ...UNSUPPORTED_MERGE_CATEGORIES,
]);
const DELETION_BLOCKER_KEYS = new Set([
  "annotations_deleted",
  "prediction_proposals_historical",
  ...UNSUPPORTED_MERGE_CATEGORIES,
]);

function validReviewInventory(
  value: unknown,
  allowedKeys: ReadonlySet<string>,
): boolean {
  if (!Array.isArray(value)) return false;
  const keys = new Set<string>();
  return value.every((item: unknown) => {
    if (!validReviewGroup(item)) return false;
    const key = (item as { key: string }).key;
    if (!allowedKeys.has(key) || keys.has(key)) return false;
    keys.add(key);
    return true;
  });
}

// In reassign-and-delete, every protected historical annotation, proposal
// and unsupported modality must also be explicitly disclosed as a deletion
// blocker. Omission or substitution cannot stand in for researcher review.
function deletionBlockersMatchProtectedInventory(
  operation: ClassOperationRecord,
): boolean {
  if (operation.operation_type !== "reassign_delete") return true;
  const blocked = new Map(
    operation.plan.blocking_records.map((group) => [
      group.key,
      group.record_ids,
    ]),
  );
  return operation.plan.protected_records.every((group) => {
    if (!DELETION_BLOCKER_KEYS.has(group.key)) return true;
    const disclosed = blocked.get(group.key);
    return (
      disclosed !== undefined &&
      disclosed.length === group.record_ids.length &&
      group.record_ids.every((id, index) => id === disclosed[index])
    );
  });
}

function validReviewImpact(value: unknown): boolean {
  if (!value || typeof value !== "object") return false;
  const item = value as Record<string, unknown>;
  return (
    validReviewText(item.key) &&
    validReviewText(item.label) &&
    validReviewText(item.status) &&
    validReviewText(item.message) &&
    validReviewTextList(item.record_ids) &&
    new Set(item.record_ids).size === item.record_ids.length
  );
}

// An immutable class-map warning must name precisely the frozen datasets and
// registered models in the protected reference inventory. A missing or
// mismatched impact cannot count as complete researcher-review evidence.
function compatibilityImpactsMatchProtectedInventory(
  plan: ClassOperationRecord["plan"],
): boolean {
  const compatibilityKeys = ["dataset_versions", "model_registrations"];
  const protectedByKey = new Map<string, string[]>();
  for (const group of plan.protected_records) {
    if (protectedByKey.has(group.key)) return false;
    protectedByKey.set(group.key, group.record_ids);
  }
  const impactsByKey = new Map<string, string[]>();
  for (const impact of plan.compatibility_impacts) {
    if (!compatibilityKeys.includes(impact.key) || impactsByKey.has(impact.key)) {
      return false;
    }
    impactsByKey.set(impact.key, impact.record_ids);
  }
  return compatibilityKeys.every((key) => {
    const expected = protectedByKey.get(key);
    const actual = impactsByKey.get(key);
    return expected === undefined
      ? actual === undefined
      : actual !== undefined &&
          actual.length === expected.length &&
          expected.every((id, index) => id === actual[index]);
  });
}

function operationHasDisplayEvidence(operation: ClassOperationRecord): boolean {
  const plan = operation.plan;
  return (
    (operation.operation_type === "reassign" ||
      operation.operation_type === "reassign_delete") &&
    validReviewInventory(plan?.mutable_records, MUTABLE_PREVIEW_KEYS) &&
    validReviewInventory(plan.protected_records, PROTECTED_PREVIEW_KEYS) &&
    Array.isArray(plan.compatibility_impacts) &&
    plan.compatibility_impacts.every(validReviewImpact) &&
    compatibilityImpactsMatchProtectedInventory(plan) &&
    validReviewInventory(plan.blocking_records, BLOCKING_PREVIEW_KEYS) &&
    deletionBlockersMatchProtectedInventory(operation) &&
    validReviewTextList(plan.warnings) &&
    validReviewTextList(plan.blockers) &&
    validReviewTextList(operation.warnings) &&
    validReviewTextList(operation.failures)
  );
}

// A preview is not permission to execute without an opaque, nonempty operation
// identity, its full SHA-256 review checksum and complete unblocked evidence.
// Backend checksum, scope and concurrency validation remain authoritative.
function previewHasNoBlockingEvidence(
  operation: ClassOperationRecord,
): boolean {
  return (
    operationHasDisplayEvidence(operation) &&
    typeof operation.id === "string" &&
    operation.id.trim().length > 0 &&
    typeof operation.preview_checksum === "string" &&
    /^[0-9a-fA-F]{64}$/.test(operation.preview_checksum) &&
    operation.plan.blockers.length === 0 &&
    operation.plan.blocking_records.length === 0 &&
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
  if (!operationHasDisplayEvidence(operation)) {
    return (
      <div className="class-usage-card">
        <strong>{title}</strong>
        <p className="form-error" role="alert">
          Operation evidence is incomplete. Execution is disabled; preview again
          before reviewing or proceeding.
        </p>
      </div>
    );
  }

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
      <div className="class-warning-list">
        {[...new Set([...operation.plan.warnings, ...operation.warnings])].map(
          (warning) => (
            <p key={warning} className="annotation-helper">
              {warning}
            </p>
          ),
        )}
      </div>
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

// A preview is approval of *these* source/target class revisions, not just IDs.
function classPreviewIdentity(value: LabelClass | undefined) {
  if (!value) return null;
  return [
    value.id,
    value.updated_at,
    value.name,
    value.class_index,
    value.scientific_name,
    value.state_name,
    value.description,
    value.display_order,
    value.display_color,
    value.is_active,
    value.archived_at,
  ];
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
  const selectedReassignTarget = mergeTargets.find(
    (candidate) => candidate.id === reassignTargetId,
  );
  const [reassignPreview, setReassignPreview] =
    useState<BoundClassPreview | null>(null);
  const [reassignDeletePreview, setReassignDeletePreview] =
    useState<BoundClassPreview | null>(null);
  const [latestOperation, setLatestOperation] =
    useState<ClassOperationRecord | null>(null);
  const previewSelectionKey = JSON.stringify([
    project.id,
    classPreviewIdentity(labelClass),
    classPreviewIdentity(selectedReassignTarget),
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
    selectedReassignTarget !== undefined &&
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
      // A late preview must never overwrite a completed operation receipt.
      setReassignPreview({ operation, selectionKey: selection.selectionKey });
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
      // Executing either operation changes its scientific reference inventory.
      // Revoke both prior approvals, including an opposite in-flight preview.
      setReassignPreview(null);
      setReassignDeletePreview(null);
      setPreviewEpoch((current) => current + 1);
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
      // Keep completed scientific operation feedback even if this HTTP preview
      // finishes after the researcher ran a different approved operation.
      setReassignDeletePreview({
        operation,
        selectionKey: selection.selectionKey,
      });
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
      // A completed reassign-and-delete consumes approvals for both actions.
      setReassignPreview(null);
      setReassignDeletePreview(null);
      setPreviewEpoch((current) => current + 1);
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
              !selectedReassignTarget ||
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
              !selectedReassignTarget ||
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
          Reassignment preview no longer matches the class identities, target,
          or notes. Preview again before executing.
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
          Reassign-and-delete preview no longer matches the class identities,
          target, or notes. Preview again before executing.
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
