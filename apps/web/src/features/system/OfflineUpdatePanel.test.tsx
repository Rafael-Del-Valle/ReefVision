import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { OfflineUpdatePanel } from "./OfflineUpdatePanel";

afterEach(() => vi.restoreAllMocks());
it("requires the review digest and clears a previous verification when the media changes", async () => {
  const client = new QueryClient({
    defaultOptions: { mutations: { retry: false } },
  });
  const verify = vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(
      JSON.stringify({
        status: "verified",
        version: "2.0.0",
        source_commit: "a".repeat(40),
        manifest_sha256: "b".repeat(64),
        installer: "ReefVision_2.0.0_x64_en-US.msi",
        total_verified_bytes: 12,
        files: [{ name: "rv1.cab", status: "matched" }],
      }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    ),
  );
  render(
    <QueryClientProvider client={client}>
      <OfflineUpdatePanel />
    </QueryClientProvider>,
  );
  const folder = screen.getByLabelText("Installer folder");
  const pin = screen.getByLabelText("Expected manifest SHA-256");
  const button = screen.getByRole("button", { name: "Verify offline media" });
  fireEvent.change(folder, { target: { value: "C:/Example media" } });
  fireEvent.change(pin, { target: { value: "incomplete" } });
  expect(button).toBeDisabled();
  fireEvent.change(pin, { target: { value: "b".repeat(64) } });
  fireEvent.click(button);
  expect(
    await screen.findByRole("heading", { name: "Media checksums verified" }),
  ).toBeInTheDocument();
  expect(verify).toHaveBeenCalledOnce();
  expect(JSON.parse(String(verify.mock.calls[0][1]?.body))).toEqual({
    directory: "C:/Example media",
    manifest_sha256: "b".repeat(64),
  });
  fireEvent.change(folder, { target: { value: "C:/Different media" } });
  expect(
    screen.queryByRole("heading", { name: "Media checksums verified" }),
  ).not.toBeInTheDocument();
  expect(verify).toHaveBeenCalledOnce();
});
