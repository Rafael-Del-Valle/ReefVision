import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { useActionConfirmation } from "./ActionConfirmation";

afterEach(cleanup);

function ConfirmationExample({
  result,
}: {
  result: (accepted: boolean) => void;
}) {
  const { confirm, confirmationDialog } = useActionConfirmation();
  function request() {
    void confirm({
      title: "Remove working copy",
      message: "The original archive remains available.",
      confirmLabel: "Remove copy",
      destructive: true,
    }).then(result);
  }
  return (
    <>
      <button onClick={request}>Request removal</button>
      {confirmationDialog}
    </>
  );
}

it("keeps keyboard focus in the confirmation and rejects a duplicate request", async () => {
  const result = vi.fn();
  render(<ConfirmationExample result={result} />);
  const trigger = screen.getByRole("button", { name: "Request removal" });
  await userEvent.click(trigger);
  const dialog = screen.getByRole("alertdialog", {
    name: "Remove working copy",
  });
  const cancel = within(dialog).getByRole("button", { name: "Cancel" });
  const approval = within(dialog).getByRole("button", { name: "Remove copy" });
  expect(cancel).toHaveFocus();
  await userEvent.tab({ shift: true });
  expect(approval).toHaveFocus();
  await userEvent.tab();
  expect(cancel).toHaveFocus();
  fireEvent.click(trigger);
  await waitFor(() => expect(result.mock.calls).toEqual([[false]]));
  expect(dialog).toBeVisible();
  await userEvent.keyboard("{Escape}");
  expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  expect(trigger).toHaveFocus();
  expect(result.mock.calls).toEqual([[false], [false]]);
});

it("rejects a pending confirmation when its owning workspace unmounts", async () => {
  const result = vi.fn();
  const { unmount } = render(<ConfirmationExample result={result} />);
  await userEvent.click(
    screen.getByRole("button", { name: "Request removal" }),
  );
  expect(screen.getByRole("alertdialog")).toBeVisible();
  expect(result).not.toHaveBeenCalled();
  unmount();
  await waitFor(() => expect(result).toHaveBeenCalledExactlyOnceWith(false));
});
