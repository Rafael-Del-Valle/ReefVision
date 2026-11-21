import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { OnboardingModal } from "./OnboardingModal";

const projectId = "88168a02-443d-4452-9168-4c881b253bbf";
const revisionId = "ba4578cb-b42b-44b7-9dcc-6f6172c3b8bc";
const hash = "a".repeat(64);
const api = "http://127.0.0.1:49152/api/v1";
const revision = {
  id: revisionId,
  project_id: projectId,
  name: "Reviewed count",
  revision: 3,
  graph_sha256: hash,
};

function renderHelp(apiBaseUrl = api) {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <OnboardingModal
        version="2.0.0"
        hasProject
        automationProject={{ id: projectId, name: "Generated study" }}
        preferredWorkflowRevisionId={revisionId}
        automationApiBaseUrl={apiBaseUrl}
        onStartProject={vi.fn()}
        onOpenWorkspace={vi.fn()}
        onClose={vi.fn()}
        onDismissPermanently={vi.fn()}
      />
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("Help automation commands", () => {
  it("uses an open project and the selected saved revision to copy an inert pinned command", async () => {
    const user = userEvent.setup();
    const fetch = vi.fn(
      async () => new Response(JSON.stringify([revision]), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetch);
    const copy = vi.spyOn(navigator.clipboard, "writeText").mockResolvedValue();
    renderHelp();

    await user.click(screen.getByRole("button", { name: "Automation API" }));
    const dialog = screen.getByRole("dialog", { name: "Automation API" });
    expect(
      within(dialog).getByRole("textbox", { name: "Open project command" }),
    ).toHaveValue(
      `.\\automation\\reefvision.exe --api-url ${api} project open ${projectId}`,
    );
    const revisions = within(dialog).getByRole("combobox", {
      name: "Saved workflow revision",
    });
    const command = within(dialog).getByRole("textbox", {
      name: "Pinned workflow command",
    });
    await waitFor(() => expect(revisions).toHaveValue(revisionId));
    expect(command).toHaveValue(
      `.\\automation\\reefvision.exe --api-url ${api} workflow plan ${projectId} ${revisionId} --sha256 ${hash}`,
    );
    await user.selectOptions(
      within(dialog).getByRole("combobox", { name: "Workflow action" }),
      "run",
    );
    await user.click(
      within(dialog).getByRole("button", { name: "Copy workflow command" }),
    );
    expect(copy).toHaveBeenCalledWith(
      `.\\automation\\reefvision.exe --api-url ${api} workflow run ${projectId} ${revisionId} --sha256 ${hash}`,
    );
    expect(await within(dialog).findByText("Copied command.")).toBeVisible();
    expect(within(dialog).getByText(/exit code 3/i)).toBeVisible();
    expect(fetch.mock.calls).toHaveLength(1);
    await user.click(
      within(dialog).getByRole("button", { name: "Back to Help" }),
    );
    expect(
      screen.getByRole("button", { name: "Automation API" }),
    ).toHaveFocus();
  });

  it("withholds an attached command when the runtime URL embeds credentials", async () => {
    vi.stubGlobal("fetch", vi.fn());
    renderHelp("http://example-user:example-secret@127.0.0.1:49152/api/v1");
    await userEvent.click(
      screen.getByRole("button", { name: "Automation API" }),
    );
    expect(
      screen.getByText(
        "Connect to a local ReefVision API to create attached commands.",
      ),
    ).toBeVisible();
    expect(
      screen.queryByRole("textbox", { name: "Open project command" }),
    ).toBeNull();
    expect(screen.getByRole("dialog")).not.toHaveTextContent("example-secret");
  });
});
