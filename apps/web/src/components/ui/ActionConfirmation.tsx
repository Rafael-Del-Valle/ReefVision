import { useCallback, useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";

interface ActionConfirmationOptions {
  title: string;
  message: string;
  confirmLabel?: string;
  destructive?: boolean;
}

function ConfirmationDialog({
  title,
  message,
  confirmLabel = "Confirm",
  destructive,
  settle,
}: ActionConfirmationOptions & { settle: (accepted: boolean) => void }) {
  const titleId = useId();
  const descriptionId = useId();
  const dialog = useRef<HTMLElement>(null);
  const cancel = useRef<HTMLButtonElement>(null);
  const approve = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const trigger = document.activeElement;
    cancel.current?.focus();
    function keepFocus(event: FocusEvent) {
      if (
        dialog.current &&
        event.target instanceof Node &&
        !dialog.current.contains(event.target)
      ) {
        cancel.current?.focus();
      }
    }
    document.addEventListener("focusin", keepFocus);
    return () => {
      document.removeEventListener("focusin", keepFocus);
      if (trigger instanceof HTMLElement && trigger.isConnected) {
        trigger.focus();
      }
    };
  }, []);

  return createPortal(
    <div
      className="modal-backdrop"
      role="presentation"
      style={{ zIndex: 13000 }}
    >
      <section
        ref={dialog}
        className="modal"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
        onKeyDown={(event) => {
          event.stopPropagation();
          if (event.key === "Escape") {
            event.preventDefault();
            settle(false);
          } else if (event.key === "Tab") {
            if (event.shiftKey && document.activeElement === cancel.current) {
              event.preventDefault();
              approve.current?.focus();
            } else if (
              !event.shiftKey &&
              document.activeElement === approve.current
            ) {
              event.preventDefault();
              cancel.current?.focus();
            }
          }
        }}
      >
        <h2 id={titleId}>{title}</h2>
        <p id={descriptionId}>{message}</p>
        <div className="modal-actions">
          <button
            ref={cancel}
            type="button"
            className="secondary"
            onClick={() => settle(false)}
          >
            Cancel
          </button>
          <button
            ref={approve}
            type="button"
            className={destructive ? "danger-ghost" : undefined}
            onClick={() => settle(true)}
          >
            {confirmLabel}
          </button>
        </div>
      </section>
    </div>,
    document.body,
  );
}

/** Await an explicit decision. Render confirmationDialog in the component that owns the action. */
export function useActionConfirmation() {
  const [options, setOptions] = useState<ActionConfirmationOptions | null>(
    null,
  );
  const pending = useRef<((accepted: boolean) => void) | null>(null);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      const resolve = pending.current;
      pending.current = null;
      resolve?.(false);
    };
  }, []);

  const confirm = useCallback((next: ActionConfirmationOptions) => {
    if (!mounted.current || pending.current) return Promise.resolve(false);
    return new Promise<boolean>((resolve) => {
      pending.current = resolve;
      setOptions(next);
    });
  }, []);

  function settle(accepted: boolean) {
    const resolve = pending.current;
    if (!resolve) return;
    pending.current = null;
    setOptions(null);
    resolve(accepted);
  }

  return {
    confirm,
    confirmationDialog: options ? (
      <ConfirmationDialog {...options} settle={settle} />
    ) : null,
  };
}
