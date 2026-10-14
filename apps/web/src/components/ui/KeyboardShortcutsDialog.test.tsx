import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { KeyboardShortcutsDialog } from "./KeyboardShortcutsDialog";

it("renders an accessible shortcut reference and closes with Escape", () => {
  const onClose = vi.fn();
  render(<KeyboardShortcutsDialog onClose={onClose} />);

  const dialog = screen.getByRole("dialog", { name: "Keyboard shortcuts" });
  expect(dialog).toHaveAttribute("aria-modal", "true");
  expect(screen.getByText("Full-image SAM proposals")).toBeInTheDocument();
  expect(screen.getByText(/ReefVision internal clipboard/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Close" })).toHaveFocus();

  fireEvent.keyDown(window, { key: "Escape" });
  expect(onClose).toHaveBeenCalledTimes(1);
});
