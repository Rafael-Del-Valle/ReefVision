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

const usageCategoryDefinitions = [
  ["annotations_active", true, false],
  ["annotations_deleted", false, true],
  ["annotation_history", false, true],
  ["prediction_proposals", true, false],
  ["quality_control_issues", true, false],
  ["review_queue_items", true, false],
  ["dataset_versions", false, true],
  ["model_registrations", false, true],
] as const;

function zeroUsageCounts() {
  return usageCategoryDefinitions.map(([key, mutable, immutable]) => ({
    key,
    label: key,
    count: 0,
    mutable,
    immutable,
  }));
}

function classUsage(canDelete: boolean, total = canDelete ? 0 : 1) {
  return {
    class_id: "class-1",
    project_id: project.id,
    class_name: "Muricea Closed",
    is_active: true,
    archived_at: null,
    total_references: total,
    mutable_reference_count: total,
    immutable_reference_count: 0,
    can_delete: canDelete,
    delete_blockers: [],
    compatibility_warnings: [],
    counts: zeroUsageCounts(),
  };
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("ClassManagerPanel", () => {
  it("requires a completed usage review before enabling deletion", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    let resolveUsage: ((response: Response) => void) | undefined;
    let requests = 0;
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(async (input, init) => {
        const url = String(input);
        if (url.endsWith(`/projects/${project.id}/classes/class-1/usage`)) {
          requests += 1;
          if (requests === 1) {
            return new Promise<Response>((resolve) => {
              resolveUsage = resolve;
            });
          }
          return jsonResponse(classUsage(true));
        }
        if (url.endsWith("/classes/class-1") && init?.method === "DELETE") {
          return new Response(null, { status: 204 });
        }
        throw new Error(`Unexpected request: ${init?.method ?? "GET"} ${url}`);
      });
    renderPanel();
    const row = sourceClassRow();
    const remove = within(row).getByRole("button", { name: "Delete unused" });
    expect(remove).toBeDisabled();
    expect(
      within(row).getByText(/Open Usage to verify class references/),
    ).toBeInTheDocument();
    await userEvent.click(within(row).getByRole("button", { name: "Usage" }));
    await waitFor(() => expect(resolveUsage).toBeDefined());
    expect(remove).toBeDisabled();
    resolveUsage?.(jsonResponse(classUsage(true)));
    await waitFor(() => expect(remove).toBeEnabled());
    expect(
      within(row).getByText(/has no references and is eligible for deletion/),
    ).toBeInTheDocument();
    await userEvent.click(
      within(row).getByRole("button", { name: "Hide usage" }),
    );
    expect(remove).toBeDisabled();
    await userEvent.click(within(row).getByRole("button", { name: "Usage" }));
    await waitFor(() => expect(remove).toBeEnabled());
    await userEvent.click(remove);
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(
          ([input, init]) =>
            String(input).endsWith("/classes/class-1") &&
            init?.method === "DELETE",
        ),
      ).toBe(true),
    );
  });

  it.each([
    ["referenced", 200],
    ["unavailable", 503],
  ] as const)("fails closed when usage is %s", async (_reason, status) => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(async (input) => {
        const url = String(input);
        if (url.endsWith(`/projects/${project.id}/classes/class-1/usage`)) {
          return status === 200
            ? jsonResponse(classUsage(false))
            : jsonResponse({ detail: "Usage unavailable" }, 503);
        }
        throw new Error(`Unexpected request: GET ${url}`);
      });
    renderPanel();
    const row = sourceClassRow();
    const remove = within(row).getByRole("button", { name: "Delete unused" });
    await userEvent.click(within(row).getByRole("button", { name: "Usage" }));
    if (status === 200) {
      expect(
        await within(row).findByText("1 total references"),
      ).toBeInTheDocument();
      expect(
        within(row).getByText(/No itemized references are available/),
      ).toBeInTheDocument();
    } else {
      expect(
        await within(row).findByText(/Class usage could not be verified/),
      ).toBeInTheDocument();
    }
    expect(remove).toBeDisabled();
    expect(
      fetchMock.mock.calls.some(
        ([input, init]) =>
          String(input).endsWith("/classes/class-1") &&
          init?.method === "DELETE",
      ),
    ).toBe(false);
  });

  it("rejects a cached eligible result while usage is being refetched", async () => {
    let resolveRefresh: ((response: Response) => void) | undefined;
    let reads = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith(`/projects/${project.id}/classes/class-1/usage`)) {
        reads += 1;
        if (reads === 2) {
          return new Promise<Response>((resolve) => {
            resolveRefresh = resolve;
          });
        }
        return jsonResponse(classUsage(true));
      }
      throw new Error(`Unexpected request: GET ${url}`);
    });
    renderPanel();
    const row = sourceClassRow();
    const remove = within(row).getByRole("button", { name: "Delete unused" });
    await userEvent.click(within(row).getByRole("button", { name: "Usage" }));
    await waitFor(() => expect(remove).toBeEnabled());
    await userEvent.click(
      within(row).getByRole("button", { name: "Hide usage" }),
    );
    await userEvent.click(within(row).getByRole("button", { name: "Usage" }));
    await waitFor(() => expect(resolveRefresh).toBeDefined());
    expect(remove).toBeDisabled();
    resolveRefresh?.(jsonResponse(classUsage(false)));
    expect(
      await within(row).findByText("1 total references"),
    ).toBeInTheDocument();
    expect(remove).toBeDisabled();
  });

  it.each([
    ["foreign project", { project_id: "project-from-another-study" }],
    ["foreign class", { class_id: "another-class" }],
    ["contradictory total", { total_references: 1 }],
    ["hidden mutable references", { mutable_reference_count: 1 }],
    ["hidden immutable references", { immutable_reference_count: 1 }],
    [
      "positive itemized count",
      {
        counts: [
          {
            key: "historical_annotations",
            label: "Historical annotations",
            count: 1,
          },
        ],
      },
    ],
    ["nonempty delete blockers", { delete_blockers: ["Protected evidence"] }],
    ["missing blocker list", { delete_blockers: null }],
    ["missing itemization", { counts: null }],
    ["empty itemization", { counts: [] }],
    ["missing category", { counts: zeroUsageCounts().slice(1) }],
    [
      "duplicate category",
      { counts: [...zeroUsageCounts(), zeroUsageCounts()[0]] },
    ],
    [
      "unknown category",
      {
        counts: [
          ...zeroUsageCounts(),
          {
            key: "unreviewed_scientific_records",
            label: "Unreviewed scientific records",
            count: 0,
            mutable: false,
            immutable: true,
          },
        ],
      },
    ],
    [
      "incorrect category mutability",
      {
        counts: zeroUsageCounts().map((item) =>
          item.key === "dataset_versions" ? { ...item, mutable: true } : item,
        ),
      },
    ],
    [
      "incorrect category immutability",
      {
        counts: zeroUsageCounts().map((item) =>
          item.key === "annotations_deleted"
            ? { ...item, immutable: false }
            : item,
        ),
      },
    ],
    [
      "non-numeric category count",
      {
        counts: zeroUsageCounts().map((item) =>
          item.key === "model_registrations" ? { ...item, count: null } : item,
        ),
      },
    ],
  ] as const)(
    "rejects allegedly deletable usage with %s",
    async (_reason, conflictingFields) => {
      vi.spyOn(window, "confirm").mockReturnValue(true);
      const fetchMock = vi
        .spyOn(globalThis, "fetch")
        .mockImplementation(async (input) => {
          const url = String(input);
          if (url.endsWith(`/projects/${project.id}/classes/class-1/usage`)) {
            return jsonResponse({ ...classUsage(true), ...conflictingFields });
          }
          throw new Error(`Unexpected request: GET ${url}`);
        });
      renderPanel();
      const row = sourceClassRow();
      const remove = within(row).getByRole("button", {
        name: "Delete unused",
      });
      await userEvent.click(within(row).getByRole("button", { name: "Usage" }));
      expect(
        await within(row).findByText(/Usage evidence has an inconsistent/),
      ).toBeInTheDocument();
      expect(remove).toBeDisabled();
      await userEvent.click(remove);
      expect(
        fetchMock.mock.calls.some(
          ([input, init]) =>
            String(input).endsWith("/classes/class-1") &&
            init?.method === "DELETE",
        ),
      ).toBe(false);
    },
  );

  it.each([
    ["reassign", "blockers"],
    ["reassign", "blocking_records"],
    ["reassign", "failures"],
    ["reassign_delete", "blockers"],
    ["reassign_delete", "blocking_records"],
    ["reassign_delete", "failures"],
  ] as const)(
    "keeps %s execution disabled when preview contains %s",
    async (operationType, evidenceType) => {
      const endpoint =
        operationType === "reassign" ? "reassign" : "reassign-delete";
      const previewLabel =
        operationType === "reassign"
          ? "Preview reassign"
          : "Preview Reassign and Delete";
      const runLabel =
        operationType === "reassign"
          ? "Run reassign"
          : "Run Reassign and Delete";
      const fetchMock = vi
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
              id: "blocked-preview-1",
              project_id: project.id,
              source_class_id: "class-1",
              target_class_id: "class-2",
              operation_type: operationType,
              status: "previewed",
              preview_checksum: "c".repeat(64),
              plan: {
                mutable_records: [],
                protected_records: [],
                blocking_records:
                  evidenceType === "blocking_records"
                    ? [
                        {
                          key: "archived_annotation",
                          label: "Protected historical annotation",
                          count: 1,
                          record_ids: ["annotation-3"],
                        },
                      ]
                    : [],
                compatibility_impacts: [],
                warnings: [],
                blockers:
                  evidenceType === "blockers"
                    ? ["A protected class reference prevents this operation."]
                    : [],
              },
              failures:
                evidenceType === "failures"
                  ? ["Preview could not validate scientific references."]
                  : [],
            });
          }
          throw new Error(
            `Unexpected class request: ${init?.method ?? "GET"} ${url}`,
          );
        });

      renderPanel();
      const row = sourceClassRow();
      const runButton = within(row).getByRole("button", { name: runLabel });
      expect(runButton).toBeDisabled();
      await userEvent.click(
        within(row).getByRole("button", { name: previewLabel }),
      );
      const summaryTitle =
        operationType === "reassign"
          ? "Reassign preview"
          : "Reassign and Delete preview";
      expect(await within(row).findByText(summaryTitle)).toBeInTheDocument();
      expect(
        within(row).getByText(/Execution disabled: preview contains blockers/),
      ).toBeInTheDocument();
      expect(runButton).toBeDisabled();
      await userEvent.click(runButton);
      expect(
        fetchMock.mock.calls.filter(
          ([input, init]) =>
            String(input).endsWith(`/classes/class-1/${endpoint}`) &&
            init?.method === "POST",
        ),
      ).toHaveLength(0);
    },
  );

  it("previews and executes a reassignment with the reviewed checksum", async () => {
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
              warnings: [],
              blockers: [],
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
            warnings: [],
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

    await userEvent.click(
      within(sourceClassRow()).getByRole("button", { name: "Run reassign" }),
    );

    await waitFor(() =>
      expect(screen.getByText("Latest operation")).toBeInTheDocument(),
    );

    const executeCall = fetchMock.mock.calls.find(
      ([request, requestInit]) =>
        String(request).endsWith(
          `/projects/${project.id}/classes/class-1/reassign`,
        ) && requestInit?.method === "POST",
    );
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
    ["reassign", "reassign", "Preview reassign", "Run reassign"],
    [
      "reassign_delete",
      "reassign-delete",
      "Preview Reassign and Delete",
      "Run Reassign and Delete",
    ],
  ] as const)(
    "invalidates a %s preview after target change, reversion and audit-note edit",
    async (operationType, endpoint, previewLabel, runLabel) => {
      const thirdClass = {
        ...project.label_classes[1],
        id: "class-3",
        class_index: 2,
        name: "Swiftia Open",
      };
      const fetchMock = vi
        .spyOn(globalThis, "fetch")
        .mockImplementation(async (input, init) => {
          const url = String(input);
          if (
            url.endsWith(
              `/projects/${project.id}/classes/class-1/${endpoint}/preview`,
            ) &&
            init?.method === "POST"
          ) {
            const requested = JSON.parse(String(init.body)) as {
              target_class_id: string;
              notes: string | null;
            };
            return jsonResponse({
              id: "preview-" + requested.target_class_id,
              project_id: project.id,
              source_class_id: "class-1",
              target_class_id: requested.target_class_id,
              operation_type: operationType,
              status: "previewed",
              preview_checksum: "c".repeat(64),
              plan: {
                mutable_records: [],
                protected_records: [],
                blocking_records: [],
                compatibility_impacts: [],
                blockers: [],
              },
              failures: [],
            });
          }
          throw new Error(
            `Unexpected request: ${init?.method ?? "GET"} ${url}`,
          );
        });
      const queryClient = new QueryClient({
        defaultOptions: {
          queries: { retry: false },
          mutations: { retry: false },
        },
      });
      render(
        <QueryClientProvider client={queryClient}>
          <ClassManagerPanel
            project={{
              ...project,
              label_classes: [...project.label_classes, thirdClass],
            }}
          />
        </QueryClientProvider>,
      );
      const row = sourceClassRow();
      const runButton = within(row).getByRole("button", { name: runLabel });
      const previewButton = within(row).getByRole("button", {
        name: previewLabel,
      });
      const target = within(row).getByRole("combobox", {
        name: "Reassign into",
      });
      const notes = within(row).getByRole("textbox", {
        name: "Operation notes",
      });
      expect(runButton).toBeDisabled();
      await userEvent.click(previewButton);
      await waitFor(() => expect(runButton).toBeEnabled());
      await userEvent.selectOptions(target, "class-3");
      expect(runButton).toBeDisabled();
      await userEvent.selectOptions(target, "class-2");
      expect(runButton).toBeDisabled();
      await userEvent.click(previewButton);
      await waitFor(() => expect(runButton).toBeEnabled());
      await userEvent.type(notes, "researcher changed rationale");
      expect(runButton).toBeDisabled();
      await userEvent.click(previewButton);
      await waitFor(() => expect(runButton).toBeEnabled());

      const previews = fetchMock.mock.calls.filter(([input]) =>
        String(input).endsWith(`/${endpoint}/preview`),
      );
      expect(previews).toHaveLength(3);
      expect(previews[2]?.[1]?.body).toContain("researcher changed rationale");
      expect(
        fetchMock.mock.calls.some(([input]) =>
          String(input).endsWith(`/classes/class-1/${endpoint}`),
        ),
      ).toBe(false);
    },
  );

  it("cannot execute a delayed preview for the previously selected class", async () => {
    const thirdClass = {
      ...project.label_classes[1],
      id: "class-3",
      class_index: 2,
      name: "Swiftia Open",
    };
    let resolveFirstPreview: ((response: Response) => void) | undefined;
    let delayedResponse: Response | null = null;
    let previewCount = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      if (
        String(input).endsWith(
          `/projects/${project.id}/classes/class-1/reassign/preview`,
        ) &&
        init?.method === "POST"
      ) {
        previewCount += 1;
        const requested = JSON.parse(String(init.body)) as {
          target_class_id: string;
        };
        const response = jsonResponse({
          id: "preview-" + requested.target_class_id,
          project_id: project.id,
          source_class_id: "class-1",
          target_class_id: requested.target_class_id,
          operation_type: "reassign",
          status: "previewed",
          preview_checksum: "d".repeat(64),
          plan: {
            mutable_records: [],
            protected_records: [],
            blocking_records: [],
            compatibility_impacts: [],
            blockers: [],
          },
          failures: [],
        });
        if (previewCount === 1) {
          delayedResponse = response;
          return new Promise<Response>((resolve) => {
            resolveFirstPreview = resolve;
          });
        }
        return response;
      }
      throw new Error("Unexpected class-operation request");
    });
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <ClassManagerPanel
          project={{
            ...project,
            label_classes: [...project.label_classes, thirdClass],
          }}
        />
      </QueryClientProvider>,
    );
    const row = sourceClassRow();
    const runButton = within(row).getByRole("button", {
      name: "Run reassign",
    });
    const previewButton = within(row).getByRole("button", {
      name: "Preview reassign",
    });
    await userEvent.click(previewButton);
    await waitFor(() => expect(resolveFirstPreview).toBeDefined());
    await userEvent.selectOptions(
      within(row).getByRole("combobox", { name: "Reassign into" }),
      "class-3",
    );
    expect(delayedResponse).not.toBeNull();
    resolveFirstPreview?.(delayedResponse!);
    await waitFor(() =>
      expect(
        screen.getByText(/Reassignment preview no longer matches/),
      ).toBeInTheDocument(),
    );
    expect(runButton).toBeDisabled();
    await userEvent.click(previewButton);
    await waitFor(() => expect(runButton).toBeEnabled());
  });
});
