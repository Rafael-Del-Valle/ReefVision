import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { TrainingRun } from "../../api/client";
import { ResultsPackageDialog } from "./ResultsPackageDialog";

const run = {
  id: "run-1",
  run_name: "reef experiment",
  task: "detect",
  tuning_config: { mode: "disabled" },
} as unknown as TrainingRun;

describe("ResultsPackageDialog", () => {
  it("provides accessible scientific defaults and checkpoint choices", async () => {
    const close = vi.fn();
    render(<ResultsPackageDialog run={run} onClose={close} />);
    expect(
      screen.getByRole("dialog", { name: "Export Results Package" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Excel workbook")).toBeChecked();
    expect(screen.getByLabelText("Native provider artifacts")).toBeChecked();
    expect(screen.getByLabelText("Model checkpoints")).toHaveValue("best");
    await userEvent.click(
      screen.getByRole("button", { name: "Close export dialog" }),
    );
    expect(close).toHaveBeenCalledOnce();
  });
});
