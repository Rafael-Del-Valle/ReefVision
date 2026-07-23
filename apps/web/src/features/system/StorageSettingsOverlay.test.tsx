import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { StorageSettingsOverlay } from "./StorageSettingsOverlay";

vi.mock("../../runtime", () => ({
  getApiBaseUrl: () => "/api/v1",
}));

const response = {
  settings_file: "C:/Users/test/AppData/Local/ReefVision/config/storage.json",
  restart_required: false,
  paths: [
    {
      key: "data_dir",
      label: "Application data root",
      description: "Projects and database",
      active_path: "C:/ReefVision/data",
      pending_path: "C:/ReefVision/data",
      exists: true,
      writable: true,
      free_bytes: 80 * 1024 ** 3,
      restart_required: false,
      environment_variable: "REEFVISION_DATA_DIR",
      environment_locked: false,
    },
    {
      key: "model_cache_dir",
      label: "Model and download cache",
      description: "Downloadable model files",
      active_path: "C:/ReefVision/model-cache",
      pending_path: "C:/ReefVision/model-cache",
      exists: true,
      writable: true,
      free_bytes: 60 * 1024 ** 3,
      restart_required: false,
      environment_variable: "REEFVISION_MODEL_CACHE_DIR",
      environment_locked: false,
    },
    {
      key: "temp_dir",
      label: "Temporary workspace",
      description: "Temporary work files",
      active_path: "C:/ReefVision/tmp",
      pending_path: "C:/ReefVision/tmp",
      exists: true,
      writable: true,
      free_bytes: 40 * 1024 ** 3,
      restart_required: false,
      environment_variable: "REEFVISION_TEMP_DIR",
      environment_locked: false,
    },
  ],
  notes: ["Saved changes take effect after restart."],
};

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("StorageSettingsOverlay", () => {
  it("loads, edits, and saves an external model cache", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify(response), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            ...response,
            restart_required: true,
            paths: response.paths.map((path) =>
              path.key === "model_cache_dir"
                ? {
                    ...path,
                    pending_path: "E:/ReefVision/model-cache",
                    restart_required: true,
                  }
                : path,
            ),
          }),
          {
            status: 200,
            headers: { "Content-Type": "application/json" },
          },
        ),
      );
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(<StorageSettingsOverlay />);
    await user.click(screen.getByRole("button", { name: "Storage settings" }));

    const cacheInput = await screen.findByDisplayValue(
      "C:/ReefVision/model-cache",
    );
    await user.clear(cacheInput);
    await user.type(cacheInput, "E:/ReefVision/model-cache");
    await user.click(
      screen.getByRole("checkbox", {
        name: /I understand ReefVision must restart/i,
      }),
    );
    await user.click(screen.getByRole("button", { name: "Save directories" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    const request = fetchMock.mock.calls[1][1] as RequestInit;
    expect(request.method).toBe("PUT");
    expect(JSON.parse(String(request.body))).toMatchObject({
      data_dir: "C:/ReefVision/data",
      model_cache_dir: "E:/ReefVision/model-cache",
      temp_dir: "C:/ReefVision/tmp",
      acknowledge_restart: true,
    });
    expect(
      await screen.findByText(/Storage settings saved/i),
    ).toBeInTheDocument();
  });

  it("disables a path controlled by an environment variable", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            ...response,
            paths: response.paths.map((path) =>
              path.key === "data_dir"
                ? { ...path, environment_locked: true }
                : path,
            ),
          }),
          {
            status: 200,
            headers: { "Content-Type": "application/json" },
          },
        ),
      ),
    );
    const user = userEvent.setup();

    render(<StorageSettingsOverlay />);
    await user.click(screen.getByRole("button", { name: "Storage settings" }));

    expect(
      await screen.findByDisplayValue("C:/ReefVision/data"),
    ).toBeDisabled();
    expect(await screen.findByText(/REEFVISION_DATA_DIR/)).toBeInTheDocument();
  });
});
