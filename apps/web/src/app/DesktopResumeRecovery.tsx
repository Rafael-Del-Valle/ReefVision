import { useCallback, useEffect, useRef } from "react";
import { type QueryClient, useQueryClient } from "@tanstack/react-query";

import { getRuntimeContext } from "../runtime";

const RESUME_GAP_MS = 8_000;
const LONG_BACKGROUND_MS = 5_000;
const HEARTBEAT_INTERVAL_MS = 2_000;
const DEFAULT_HEALTH_ATTEMPTS = 8;
const DEFAULT_HEALTH_TIMEOUT_MS = 1_500;
const DEFAULT_RETRY_DELAY_MS = 500;

interface ResumeRecoveryOptions {
  attempts?: number;
  healthTimeoutMs?: number;
  retryDelayMs?: number;
  fetchImpl?: typeof fetch;
}

function sleep(milliseconds: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}

function forceWebViewRepaint(): void {
  const body = document.body;
  if (!body) return;

  const previousOpacity = body.style.opacity;
  body.style.opacity = "0.99999";

  // Force WebView2 to recalculate layout immediately. This is intentionally
  // lightweight and preserves all React/editor state.
  void body.offsetHeight;

  const finish = () => {
    body.style.opacity = previousOpacity;
  };

  if (typeof window.requestAnimationFrame === "function") {
    window.requestAnimationFrame(finish);
  } else {
    window.setTimeout(finish, 0);
  }
}

async function fetchHealth(
  apiBaseUrl: string,
  fetchImpl: typeof fetch,
  timeoutMs: number,
): Promise<boolean> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetchImpl(`${apiBaseUrl}/health`, {
      cache: "no-store",
      signal: controller.signal,
    });
    return response.ok;
  } catch {
    return false;
  } finally {
    window.clearTimeout(timeout);
  }
}

export async function performDesktopResumeRecovery(
  queryClient: QueryClient,
  options: ResumeRecoveryOptions = {},
): Promise<boolean> {
  const context = getRuntimeContext();
  if (!context.desktopMode) return false;

  forceWebViewRepaint();

  const attempts = options.attempts ?? DEFAULT_HEALTH_ATTEMPTS;
  const healthTimeoutMs = options.healthTimeoutMs ?? DEFAULT_HEALTH_TIMEOUT_MS;
  const retryDelayMs = options.retryDelayMs ?? DEFAULT_RETRY_DELAY_MS;
  const fetchImpl = options.fetchImpl ?? window.fetch.bind(window);

  for (let attempt = 0; attempt < attempts; attempt += 1) {
    const healthy = await fetchHealth(
      context.apiBaseUrl,
      fetchImpl,
      healthTimeoutMs,
    );

    if (healthy) {
      await Promise.allSettled([
        queryClient.resumePausedMutations(),
        queryClient.refetchQueries({ type: "active" }),
      ]);

      forceWebViewRepaint();
      return true;
    }

    if (attempt + 1 < attempts) {
      await sleep(retryDelayMs);
    }
  }

  // Make the health badge update to "Service unavailable" rather than
  // leaving stale pre-sleep state on screen. Other workspace state remains
  // untouched so unsaved edits are not discarded.
  await Promise.allSettled([
    queryClient.refetchQueries({
      queryKey: ["health"],
      type: "active",
    }),
  ]);

  forceWebViewRepaint();
  return false;
}

export function DesktopResumeRecovery() {
  const queryClient = useQueryClient();
  const recoveryInFlight = useRef<Promise<boolean> | null>(null);

  const triggerRecovery = useCallback(() => {
    if (!getRuntimeContext().desktopMode) return;
    if (recoveryInFlight.current) return;

    const recovery = performDesktopResumeRecovery(queryClient);
    recoveryInFlight.current = recovery;

    void recovery.finally(() => {
      if (recoveryInFlight.current === recovery) {
        recoveryInFlight.current = null;
      }
    });
  }, [queryClient]);

  useEffect(() => {
    if (!getRuntimeContext().desktopMode) return;

    let lastHeartbeatAt = Date.now();
    let hiddenAt: number | null = null;
    let blurredAt: number | null = null;

    const heartbeat = window.setInterval(() => {
      const now = Date.now();
      const elapsed = now - lastHeartbeatAt;
      lastHeartbeatAt = now;

      // JavaScript timers stop while Windows is asleep. A large interval gap
      // therefore gives us a reliable wake signal even when visibility did
      // not change before the machine suspended.
      if (elapsed >= RESUME_GAP_MS) {
        triggerRecovery();
      }
    }, HEARTBEAT_INTERVAL_MS);

    const handleVisibilityChange = () => {
      if (document.visibilityState === "hidden") {
        hiddenAt = Date.now();
        return;
      }

      const now = Date.now();
      if (hiddenAt !== null && now - hiddenAt >= LONG_BACKGROUND_MS) {
        triggerRecovery();
      }
      hiddenAt = null;
    };

    const handleBlur = () => {
      blurredAt = Date.now();
    };

    const handleFocus = () => {
      const now = Date.now();
      if (blurredAt !== null && now - blurredAt >= LONG_BACKGROUND_MS) {
        triggerRecovery();
      }
      blurredAt = null;
    };

    const handlePageShow = (event: PageTransitionEvent) => {
      if (event.persisted) {
        triggerRecovery();
      }
    };

    document.addEventListener("visibilitychange", handleVisibilityChange);
    window.addEventListener("blur", handleBlur);
    window.addEventListener("focus", handleFocus);
    window.addEventListener("pageshow", handlePageShow);

    return () => {
      window.clearInterval(heartbeat);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      window.removeEventListener("blur", handleBlur);
      window.removeEventListener("focus", handleFocus);
      window.removeEventListener("pageshow", handlePageShow);
    };
  }, [triggerRecovery]);

  return null;
}
