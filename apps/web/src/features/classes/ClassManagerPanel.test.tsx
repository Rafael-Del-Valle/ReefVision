import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Project } from "../../api/client";
import { ClassManagerPanel } from "./ClassManagerPanel";

const project: Project = {
  id: "project-1",
  name: "CPT Coral Study",
  slug: "cpt-coral-study",
  description: "Octocoral polyp annotations",
  storage_root: "projects/project-1",
  default_annotation_type: "bbox",
  georeference_height_offset_m: 0,
  georeference_height_evidence: null,
  created_at: "2026-07-08T00:00:00Z",
  updated_at: "2026-07-08T00:00:00Z",
  archived_at: null,
  label_classes: [
    {
      id: "class-1",
      project_id: "project-1",
      class_index: 0,
      display_order: 0,
      name: "Muricea Closed",
      scientific_name: null,
      state_name: null,
      description: null,
      display_color: "#E76F51",
      is_active: true,
      archived_at: null,
      created_at: "2026-07-08T00:00:00Z",
      updated_at: "2026-07-08T00:00:00Z",
    },
    {
      id: "class-2",
      project_id: "project-1",
      class_index: 1,
      display_order: 1,
      name: "Muricea Open",
      scientific_name: null,
      state_name: null,
      description: null,
      display_color: "#2A9D8F",
      is_active: true,
      archived_at: null,
      created_at: "2026-07-08T00:00:00Z",
      updated_at: "2026-07-08T00:00:00Z",
    },
  ],
};

function jsonResponse(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function renderPanel() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <ClassManagerPanel project={project} />
    </QueryClientProvider>,
  );
}

function sourceClassRow() {
  const sourceHeading = screen.getAllByText("Muricea Closed", {
    selector: "strong",
  })[0];
  const row = sourceHeading.closest("li");
  expect(row).not.toBeNull();
  return row as HTMLLIElement;
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("ClassManagerPanel", () => {
  describe.each([
    ["reassign", "reassign", "Preview reassign", "Run reassign"],
    [
      "reassign-delete",
      "reassign_delete",
      "Preview Reassign and Delete",
      "Run Reassign and Delete",
    ],
  ] as const)(
    "%s preview",
    (endpoint, operationType, previewLabel, runLabel) => {
      const report = {
        mutable_records: [],
        protected_records: [],
        compatibility_impacts: [],
        blocking_records: [],
        blockers: [],
        warnings: [],
      };
      it.each([
        ["blank operation identity", { id: " " }],
        ["missing checksum", { preview_checksum: null }],
        ["malformed checksum", { preview_checksum: "invalid-sha256" }],
        ["noncanonical checksum", { preview_checksum: "A".repeat(64) }],
        ["missing plan warnings", { plan: { ...report, warnings: null } }],
        ["unreadable operation warning", { warnings: [null] }],
        [
          "missing record groups",
          { plan: { blockers: [], blocking_records: [] } },
        ],
        [
          "missing record identifiers",
          {
            plan: {
              ...report,
              mutable_records: [
                { key: "annotations", label: "Annotations", count: 1 },
              ],
            },
          },
        ],
        [
          "reported record missing its identifier",
          {
            plan: {
              ...report,
              mutable_records: [
                {
                  key: "annotations",
                  label: "Annotations",
                  count: 1,
                  record_ids: [],
                },
              ],
            },
          },
        ],
        ...(
          ["mutable_records", "protected_records", "blocking_records"] as const
        ).map(
          (group) =>
            [
              `duplicate identifiers in ${group}`,
              {
                plan: {
                  ...report,
                  [group]: [
                    {
                      key: "annotations",
                      label: "Annotations",
                      count: 2,
                      record_ids: ["reviewed-id", "reviewed-id"],
                    },
                  ],
                },
              },
            ] as const,
        ),
        [
          "truncated compatibility entry",
          { plan: { ...report, compatibility_impacts: [null] } },
        ],
        ["missing source snapshot", { source_class: null }],
      ] as const)(
        "requires a fresh preview after %s",
        async (_, incomplete) => {
          const complete = {
            id: "reviewed-operation",
            project_id: project.id,
            source_class_id: "class-1",
            target_class_id: "class-2",
            source_class: project.label_classes[0],
            target_class: project.label_classes[1],
            operation_type: operationType,
            status: "previewed",
            preview_checksum: "a".repeat(64),
            plan: report,
            failures: [],
            warnings: [],
          };
          const fetchMock = vi
            .spyOn(globalThis, "fetch")
            .mockResolvedValueOnce(jsonResponse({ ...complete, ...incomplete }))
            .mockResolvedValueOnce(jsonResponse(complete));
          renderPanel();
          const row = within(sourceClassRow());
          const preview = row.getByRole("button", { name: previewLabel });
          const run = row.getByRole("button", { name: runLabel });
          await userEvent.click(preview);
          const evidenceMessage =
            "plan" in incomplete
              ? /Operation evidence is incomplete/
              : /Operation evidence is incomplete|Execution disabled/;
          expect(await row.findByText(evidenceMessage)).toBeVisible();
          expect(run).toBeDisabled();
          await userEvent.click(run);
          expect(screen.queryByRole("alertdialog")).toBeNull();
          expect(fetchMock).toHaveBeenCalledTimes(1);
          expect(String(fetchMock.mock.calls[0][0])).toMatch(
            new RegExp(`/classes/class-1/${endpoint}/preview$`),
          );
          await userEvent.click(preview);
          await waitFor(() => expect(run).toBeEnabled());
          expect(fetchMock).toHaveBeenCalledTimes(2);
        },
      );
    },
  );

  it.each([
    ["Run reassign", "Reassign class", false],
    ["Run Reassign and Delete", "Reassign and delete class", false],
    ["Run reassign", "Reassign class", true],
    ["Run Reassign and Delete", "Reassign and delete class", true],
  ] as const)(
    "consumes both reviewed plans after %s (late opposite preview %s %s)",
    async (runLabel, dialogTitle, latePreview) => {
      const otherPreview =
        runLabel === "Run reassign"
          ? "Preview Reassign and Delete"
          : "Preview reassign";
      const otherEndpoint =
        runLabel === "Run reassign" ? "reassign-delete" : "reassign";
      let releasePreview: (() => void) | undefined;
      let holdPreview = false;
      vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
        const url = String(input);
        if (
          init?.method !== "POST" ||
          !url.includes("/classes/class-1/reassign")
        ) {
          throw new Error(`Unexpected operation ${init?.method} ${url}`);
        }
        const deleteSource = url.includes("reassign-delete");
        const preview = url.endsWith("/preview");
        if (holdPreview && url.endsWith(`/${otherEndpoint}/preview`)) {
          await new Promise<void>((resolve) => {
            releasePreview = resolve;
          });
        }
        return jsonResponse({
          id: deleteSource ? "delete-plan" : "reassign-plan",
          project_id: project.id,
          source_class_id: "class-1",
          target_class_id: "class-2",
          source_class: project.label_classes[0],
          target_class: project.label_classes[1],
          operation_type: deleteSource ? "reassign_delete" : "reassign",
          status: preview ? "previewed" : "completed",
          preview_checksum: (deleteSource ? "d" : "a").repeat(64),
          plan: {
            mutable_records: [],
            protected_records: [],
            blocking_records: [],
            compatibility_impacts: [],
            blockers: [],
            warnings: [],
          },
          failures: [],
          warnings: [],
        });
      });
      renderPanel();
      const row = within(sourceClassRow());
      const button = (name: string) => row.getByRole("button", { name });
      await userEvent.click(button("Preview reassign"));
      await userEvent.click(button("Preview Reassign and Delete"));
      await waitFor(() => {
        expect(button("Run reassign")).toBeEnabled();
        expect(button("Run Reassign and Delete")).toBeEnabled();
      });
      if (latePreview) {
        holdPreview = true;
        await userEvent.click(button(otherPreview));
        await waitFor(() => expect(releasePreview).toBeDefined());
      }
      await userEvent.click(button(runLabel));
      const dialog = await screen.findByRole("alertdialog", {
        name: dialogTitle,
      });
      await userEvent.click(
        within(dialog).getByRole("button", { name: runLabel }),
      );
      expect(await row.findByText("Latest operation")).toBeVisible();
      if (latePreview) {
        holdPreview = false;
        releasePreview?.();
        await waitFor(() => expect(button(otherPreview)).toBeEnabled());
      }
      expect(button("Run reassign")).toBeDisabled();
      expect(button("Run Reassign and Delete")).toBeDisabled();
      await userEvent.click(button("Preview reassign"));
      await waitFor(() => expect(button("Run reassign")).toBeEnabled());
      expect(row.getByText("Latest operation")).toBeVisible();
    },
  );

  it("previews and executes a reassignment with the reviewed checksum", async () => {
    const frozenWarning =
      "Immutable dataset versions keep their original class map for reproducibility.";
    const historyWarning =
      "Historical annotation events remain unchanged for auditability.";
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(async (input, init) => {
        const url = String(input);
        if (
          url.endsWith(
            `/projects/${project.id}/classes/class-1/reassign/preview`,
          ) &&
          init?.method === "POST"
        ) {
          return jsonResponse({
            id: "operation-1",
            project_id: project.id,
            source_class_id: "class-1",
            target_class_id: "class-2",
            operation_type: "reassign",
            status: "previewed",
            preview_checksum: "a".repeat(64),
            requested_by_identity: "local-user:test",
            source_class: {
              id: "class-1",
              name: "Muricea Closed",
              class_index: 0,
              display_order: 0,
              display_color: "#E76F51",
              scientific_name: null,
              state_name: null,
              description: null,
              archived_at: null,
            },
            target_class: {
              id: "class-2",
              name: "Muricea Open",
              class_index: 1,
              display_order: 1,
              display_color: "#2A9D8F",
              scientific_name: null,
              state_name: null,
              description: null,
              archived_at: null,
            },
            plan: {
              mutable_records: [
                {
                  key: "annotations_active",
                  label: "Active annotations",
                  count: 1,
                  record_ids: ["annotation-1"],
                },
              ],
              protected_records: [
                {
                  key: "dataset_versions",
                  label: "Immutable dataset versions",
                  count: 1,
                  record_ids: ["version-1"],
                },
              ],
              blocking_records: [],
              compatibility_impacts: [
                {
                  key: "dataset_versions",
                  label: "Immutable dataset versions",
                  status: "Historical class only",
                  message: "Immutable versions keep the original class map.",
                  record_ids: ["version-1"],
                },
              ],
              warnings: [frozenWarning],
              blockers: [],
            },
            affected_counts: [],
            protected_reference_counts: [],
            warnings: [frozenWarning, historyWarning],
            failures: [],
            rollback_result: {},
            final_state: null,
            notes: null,
            created_at: "2026-07-10T00:00:00Z",
            updated_at: "2026-07-10T00:00:00Z",
            started_at: null,
            completed_at: null,
          });
        }
        if (
          url.endsWith(`/projects/${project.id}/classes/class-1/reassign`) &&
          init?.method === "POST"
        ) {
          return jsonResponse({
            id: "operation-1",
            project_id: project.id,
            source_class_id: "class-1",
            target_class_id: "class-2",
            operation_type: "reassign",
            status: "completed",
            preview_checksum: "a".repeat(64),
            requested_by_identity: "local-user:test",
            source_class: {
              id: "class-1",
              name: "Muricea Closed",
              class_index: 0,
              display_order: 0,
              display_color: "#E76F51",
              scientific_name: null,
              state_name: null,
              description: null,
              archived_at: null,
            },
            target_class: {
              id: "class-2",
              name: "Muricea Open",
              class_index: 1,
              display_order: 1,
              display_color: "#2A9D8F",
              scientific_name: null,
              state_name: null,
              description: null,
              archived_at: null,
            },
            plan: {
              mutable_records: [
                {
                  key: "annotations_active",
                  label: "Active annotations",
                  count: 1,
                  record_ids: ["annotation-1"],
                },
              ],
              protected_records: [],
              blocking_records: [],
              compatibility_impacts: [],
              warnings: [],
              blockers: [],
            },
            affected_counts: [
              {
                key: "annotations_active",
                label: "Active annotations",
                count: 1,
                record_ids: [],
              },
            ],
            protected_reference_counts: [],
            warnings: [historyWarning],
            failures: [],
            rollback_result: { rolled_back: false },
            final_state: "reassigned",
            notes: null,
            created_at: "2026-07-10T00:00:00Z",
            updated_at: "2026-07-10T00:00:01Z",
            started_at: "2026-07-10T00:00:00Z",
            completed_at: "2026-07-10T00:00:01Z",
          });
        }
        if (
          url.endsWith(`/projects/${project.id}/classes/class-1/usage`) &&
          (!init?.method || init.method === "GET")
        ) {
          return jsonResponse({
            class_id: "class-1",
            project_id: project.id,
            class_name: "Muricea Closed",
            is_active: true,
            archived_at: null,
            total_references: 1,
            mutable_reference_count: 1,
            immutable_reference_count: 0,
            can_delete: false,
            delete_blockers: [],
            compatibility_warnings: [],
            counts: [],
          });
        }
        throw new Error(`Unhandled request: ${init?.method ?? "GET"} ${url}`);
      });

    renderPanel();
    await userEvent.click(
      within(sourceClassRow()).getByRole("button", {
        name: "Preview reassign",
      }),
    );

    expect(await screen.findByText("Reassign preview")).toBeInTheDocument();
    expect(screen.getByText(/Historical class only/)).toBeInTheDocument();
    expect(screen.getAllByText(frozenWarning)).toHaveLength(1);
    expect(screen.getByText(historyWarning)).toBeVisible();

    const reassign = within(sourceClassRow()).getByRole("button", {
      name: "Run reassign",
    });
    const executionRequests = () =>
      fetchMock.mock.calls.filter(
        ([url, options]) =>
          String(url).endsWith("/classes/class-1/reassign") &&
          options?.method === "POST",
      );
    await userEvent.click(reassign);
    const confirmation = await screen.findByRole("alertdialog", {
      name: "Reassign class",
    });
    expect(executionRequests()).toHaveLength(0);
    expect(
      within(confirmation).getByRole("button", { name: "Cancel" }),
    ).toHaveFocus();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(executionRequests()).toHaveLength(0);
    expect(reassign).toHaveFocus();
    await userEvent.click(reassign);
    await userEvent.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", {
        name: "Run reassign",
      }),
    );

    await waitFor(() =>
      expect(screen.getByText("Latest operation")).toBeInTheDocument(),
    );
    expect(screen.getByText(historyWarning)).toBeVisible();

    const executeCall = fetchMock.mock.calls.find(
      ([request, requestInit]) =>
        String(request).endsWith(
          `/projects/${project.id}/classes/class-1/reassign`,
        ) && requestInit?.method === "POST",
    );
    expect(executionRequests()).toHaveLength(1);
    expect(executeCall).toBeDefined();
    expect(executeCall?.[1]?.body).toContain("operation-1");
    expect(executeCall?.[1]?.body).toContain("a".repeat(64));
  });

  it("renders blocking records for reassign and delete previews", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (
        url.endsWith(
          `/projects/${project.id}/classes/class-1/reassign-delete/preview`,
        ) &&
        init?.method === "POST"
      ) {
        return jsonResponse({
          id: "operation-2",
          project_id: project.id,
          source_class_id: "class-1",
          target_class_id: "class-2",
          operation_type: "reassign_delete",
          status: "previewed",
          preview_checksum: "b".repeat(64),
          requested_by_identity: "local-user:test",
          source_class: {
            id: "class-1",
            name: "Muricea Closed",
            class_index: 0,
            display_order: 0,
            display_color: "#E76F51",
            scientific_name: null,
            state_name: null,
            description: null,
            archived_at: null,
          },
          target_class: {
            id: "class-2",
            name: "Muricea Open",
            class_index: 1,
            display_order: 1,
            display_color: "#2A9D8F",
            scientific_name: null,
            state_name: null,
            description: null,
            archived_at: null,
          },
          plan: {
            mutable_records: [],
            protected_records: [],
            blocking_records: [
              {
                key: "annotations_deleted",
                label: "Deleted annotations block physical deletion",
                count: 1,
                record_ids: ["annotation-deleted"],
              },
            ],
            compatibility_impacts: [],
            warnings: [],
            blockers: [
              "Deleted annotations still reference this class and would be removed by a hard delete.",
            ],
          },
          affected_counts: [],
          protected_reference_counts: [],
          warnings: [],
          failures: [],
          rollback_result: {},
          final_state: null,
          notes: null,
          created_at: "2026-07-10T00:00:00Z",
          updated_at: "2026-07-10T00:00:00Z",
          started_at: null,
          completed_at: null,
        });
      }
      throw new Error(`Unhandled request: ${init?.method ?? "GET"} ${url}`);
    });

    renderPanel();
    await userEvent.click(
      within(sourceClassRow()).getByRole("button", {
        name: "Preview Reassign and Delete",
      }),
    );

    expect(
      await screen.findByText("Reassign and Delete preview"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Deleted annotations still reference this class and would be removed by a hard delete.",
      ),
    ).toBeInTheDocument();
  });
  it.each([
    ["reassign", "reassign", "Preview reassign", "Run reassign", 0],
    [
      "reassign-delete",
      "reassign_delete",
      "Preview Reassign and Delete",
      "Run Reassign and Delete",
      0,
    ],
    ["reassign", "reassign", "Preview reassign", "Run reassign", 1],
    [
      "reassign-delete",
      "reassign_delete",
      "Preview Reassign and Delete",
      "Run Reassign and Delete",
      1,
    ],
  ] as const)(
    "withdraws %s class-operation preview approval after taxonomy identity drift",
    async (endpoint, operationType, previewLabel, runLabel, changedIndex) => {
      const requests = vi
        .spyOn(globalThis, "fetch")
        .mockImplementation(async (input, init) => {
          const url = String(input);
          if (
            url.endsWith(
              `/projects/${project.id}/classes/class-1/${endpoint}/preview`,
            ) &&
            init?.method === "POST"
          ) {
            return jsonResponse({
              id: "identity-bound-preview",
              project_id: project.id,
              source_class_id: "class-1",
              target_class_id: "class-2",
              source_class: project.label_classes[0],
              target_class: project.label_classes[1],
              operation_type: operationType,
              status: "previewed",
              preview_checksum: "e".repeat(64),
              plan: {
                mutable_records: [],
                protected_records: [],
                blocking_records: [],
                compatibility_impacts: [],
                blockers: [],
                warnings: [],
              },
              failures: [],
              warnings: [],
            });
          }
          throw new Error(
            `Unexpected operation ${init?.method ?? "GET"} ${url}`,
          );
        });
      const queryClient = new QueryClient({
        defaultOptions: {
          queries: { retry: false },
          mutations: { retry: false },
        },
      });
      const panel = (currentProject: Project) => (
        <QueryClientProvider client={queryClient}>
          <ClassManagerPanel project={currentProject} />
        </QueryClientProvider>
      );
      const { rerender } = render(panel(project));
      const row = sourceClassRow();
      const previewButton = within(row).getByRole("button", {
        name: previewLabel,
      });
      const runButton = within(row).getByRole("button", { name: runLabel });
      await userEvent.click(previewButton);
      await waitFor(() => expect(runButton).toBeEnabled());

      // A concurrent taxonomy edit must revoke the prior human preview,
      // even if the selected class ID and typed audit notes have not changed.
      const updated = project.label_classes.map((entry, index) =>
        index === changedIndex
          ? {
              ...entry,
              name: `${entry.name} revised`,
              updated_at: "2026-11-20T23:00:00Z",
            }
          : entry,
      );
      rerender(panel({ ...project, label_classes: updated }));
      expect(runButton).toBeDisabled();
      expect(
        within(row).getByText(/preview no longer matches/i),
      ).toBeInTheDocument();
      await userEvent.click(previewButton);
      await waitFor(() => expect(runButton).toBeEnabled());
      expect(
        requests.mock.calls.filter(([input]) =>
          String(input).endsWith(`/${endpoint}/preview`),
        ),
      ).toHaveLength(2);
      expect(
        requests.mock.calls.some(([input]) =>
          String(input).endsWith(`/class-1/${endpoint}`),
        ),
      ).toBe(false);
    },
  );
});
