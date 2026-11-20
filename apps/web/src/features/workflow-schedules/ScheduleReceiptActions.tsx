import { useMutation, useQueryClient } from "@tanstack/react-query";

import {
  saveWorkflowGraph,
  type WorkflowGraphRecord,
} from "../workflow-graphs/workflowGraphApi";
import {
  getScheduleOccurrenceReceipt,
  type ScheduleOccurrence,
} from "./workflowScheduleApi";

export function ScheduleReceiptActions({
  item,
  scheduleName,
  onOpenWorkflowGraph,
}: {
  item: ScheduleOccurrence;
  scheduleName: string;
  onOpenWorkflowGraph?: (graph: WorkflowGraphRecord) => void;
}) {
  const queryClient = useQueryClient();
  const download = useMutation({
    mutationFn: () => getScheduleOccurrenceReceipt(item.project_id, item.id),
    onSuccess: (receipt) => {
      const url = URL.createObjectURL(
        new Blob([`${JSON.stringify(receipt, null, 2)}\n`], {
          type: "application/json",
        }),
      );
      const link = document.createElement("a");
      link.href = url;
      link.download = `workflow-schedule-receipt-${receipt.receipt_sha256}.json`;
      link.click();
      URL.revokeObjectURL(url);
    },
  });
  const save = useMutation({
    mutationFn: async () => {
      const { receipt } = await getScheduleOccurrenceReceipt(
        item.project_id,
        item.id,
      );
      return saveWorkflowGraph(item.project_id, {
        graph_id: `schedule-receipt-${item.id}`,
        name: `Schedule receipt · ${scheduleName}`.slice(0, 120),
        nodes: [
          { node_id: "project", node_type: "project_source" },
          {
            node_id: "receipt",
            node_type: "workflow_schedule_receipt",
            parameters: {
              occurrence_id: receipt.occurrence_id,
              scheduled_at: receipt.scheduled_at,
            },
          },
        ],
        edges: [
          {
            edge_id: "project-receipt",
            source_node_id: "project",
            source_port_id: "project",
            target_node_id: "receipt",
            target_port_id: "project",
          },
        ],
      });
    },
    onSuccess: (graph) => {
      void queryClient.invalidateQueries({
        queryKey: ["workflow-graphs", item.project_id],
      });
      void queryClient.invalidateQueries({
        queryKey: ["saved-workflow-graphs", item.project_id],
      });
      onOpenWorkflowGraph?.(graph);
    },
  });
  const error = download.error ?? save.error;
  const pending = download.isPending || save.isPending;

  return (
    <>
      <button
        className="secondary"
        type="button"
        disabled={pending}
        onClick={() => {
          save.reset();
          download.mutate();
        }}
      >
        Download receipt JSON
      </button>
      <button
        className="secondary"
        type="button"
        disabled={pending}
        onClick={() => {
          download.reset();
          save.mutate();
        }}
      >
        Save receipt workflow
      </button>
      {!onOpenWorkflowGraph && save.isSuccess && (
        <p role="status">Saved in Workflow builder.</p>
      )}
      {error && (
        <p className="form-error" role="alert">
          {error.message}
        </p>
      )}
    </>
  );
}
