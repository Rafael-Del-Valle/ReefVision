import {
  GeographicMovementAnalyticsApiError,
  getVideoTrackGeographicAnalytics,
  type GeographicTrackAnalytics,
} from "./videoGeographicMovementAnalyticsApi";

export type GeographicMovementAnalyticsState =
  | {
      status: "idle";
      trackId: null;
      data: null;
      error: null;
      errorStatus: null;
    }
  | {
      status: "loading";
      trackId: string;
      data: null;
      error: null;
      errorStatus: null;
    }
  | {
      status: "success";
      trackId: string;
      data: GeographicTrackAnalytics;
      error: null;
      errorStatus: null;
    }
  | {
      status: "error";
      trackId: string;
      data: null;
      error: string;
      errorStatus: number | null;
    };

export type GeographicMovementAnalyticsLoader = (
  trackId: string,
  signal?: AbortSignal,
) => Promise<GeographicTrackAnalytics>;

export type GeographicMovementAnalyticsListener = (
  state: GeographicMovementAnalyticsState,
) => void;

export interface GeographicMovementAnalyticsController {
  getState(): GeographicMovementAnalyticsState;
  selectTrack(trackId: string | null): void;
  reload(): void;
  subscribe(listener: GeographicMovementAnalyticsListener): () => void;
  dispose(): void;
}

function idleState(): GeographicMovementAnalyticsState {
  return {
    status: "idle",
    trackId: null,
    data: null,
    error: null,
    errorStatus: null,
  };
}

function isAbortError(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "name" in error &&
    error.name === "AbortError"
  );
}

function errorMessage(error: unknown): string {
  if (error instanceof Error && error.message.length > 0) {
    return error.message;
  }

  return "Could not load geographic movement analytics.";
}

/**
 * Owns one selected track's geographic analytics request.
 *
 * Backend results are authoritative. This controller performs no
 * geographic or movement calculations.
 */
export function createGeographicMovementAnalyticsController(
  load: GeographicMovementAnalyticsLoader = getVideoTrackGeographicAnalytics,
): GeographicMovementAnalyticsController {
  let state: GeographicMovementAnalyticsState = idleState();

  let selectedTrackId: string | null = null;
  let activeController: AbortController | null = null;
  let requestGeneration = 0;
  let disposed = false;

  const listeners = new Set<GeographicMovementAnalyticsListener>();

  function publish(next: GeographicMovementAnalyticsState): void {
    if (disposed) {
      return;
    }

    state = next;

    for (const listener of listeners) {
      listener(state);
    }
  }

  function startRequest(trackId: string): void {
    requestGeneration += 1;
    const generation = requestGeneration;

    activeController?.abort();

    const controller = new AbortController();
    activeController = controller;

    publish({
      status: "loading",
      trackId,
      data: null,
      error: null,
      errorStatus: null,
    });

    void (async () => {
      try {
        const data = await load(trackId, controller.signal);

        if (
          disposed ||
          generation !== requestGeneration ||
          controller.signal.aborted
        ) {
          return;
        }

        if (data.track_id !== trackId) {
          throw new Error(
            "Geographic analytics response belongs to a different track.",
          );
        }

        activeController = null;

        publish({
          status: "success",
          trackId,
          data,
          error: null,
          errorStatus: null,
        });
      } catch (error: unknown) {
        if (
          disposed ||
          generation !== requestGeneration ||
          controller.signal.aborted ||
          isAbortError(error)
        ) {
          return;
        }

        activeController = null;

        publish({
          status: "error",
          trackId,
          data: null,
          error: errorMessage(error),
          errorStatus:
            error instanceof GeographicMovementAnalyticsApiError
              ? error.status
              : null,
        });
      }
    })();
  }

  return {
    getState(): GeographicMovementAnalyticsState {
      return state;
    },

    selectTrack(trackId: string | null): void {
      if (disposed) {
        return;
      }

      const nextTrackId =
        trackId !== null && trackId.trim().length > 0 ? trackId : null;

      // Repeated selection of the same track, including playback
      // updates, must not trigger another analytics request.
      if (nextTrackId === selectedTrackId) {
        return;
      }

      selectedTrackId = nextTrackId;

      if (nextTrackId === null) {
        requestGeneration += 1;
        activeController?.abort();
        activeController = null;
        publish(idleState());
        return;
      }

      startRequest(nextTrackId);
    },

    reload(): void {
      if (disposed || selectedTrackId === null) {
        return;
      }

      startRequest(selectedTrackId);
    },

    subscribe(listener: GeographicMovementAnalyticsListener): () => void {
      if (disposed) {
        return () => undefined;
      }

      listeners.add(listener);

      return () => {
        listeners.delete(listener);
      };
    },

    dispose(): void {
      if (disposed) {
        return;
      }

      disposed = true;
      requestGeneration += 1;
      activeController?.abort();
      activeController = null;
      listeners.clear();
    },
  };
}
