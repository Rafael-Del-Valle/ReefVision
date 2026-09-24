import { useCallback, useEffect, useRef, useState } from "react";

import { getVideoTrackGeographicAnalytics } from "./videoGeographicMovementAnalyticsApi";

import {
  createGeographicMovementAnalyticsController,
  type GeographicMovementAnalyticsController,
  type GeographicMovementAnalyticsLoader,
  type GeographicMovementAnalyticsState,
} from "./videoGeographicMovementAnalyticsState";

export interface GeographicMovementAnalyticsHookResult {
  state: GeographicMovementAnalyticsState;
  reload: () => void;
}

const IDLE_STATE: GeographicMovementAnalyticsState = {
  status: "idle",
  trackId: null,
  data: null,
  error: null,
  errorStatus: null,
};

export function useGeographicMovementAnalytics(
  trackId: string | null,
  load: GeographicMovementAnalyticsLoader = getVideoTrackGeographicAnalytics,
): GeographicMovementAnalyticsHookResult {
  const normalizedTrackId =
    trackId !== null && trackId.trim().length > 0 ? trackId : null;

  const [state, setState] =
    useState<GeographicMovementAnalyticsState>(IDLE_STATE);

  const controllerRef = useRef<GeographicMovementAnalyticsController | null>(
    null,
  );

  useEffect(() => {
    const controller = createGeographicMovementAnalyticsController(load);

    controllerRef.current = controller;

    const unsubscribe = controller.subscribe(setState);

    controller.selectTrack(normalizedTrackId);
    setState(controller.getState());

    return () => {
      unsubscribe();
      controller.dispose();

      if (controllerRef.current === controller) {
        controllerRef.current = null;
      }
    };
  }, [normalizedTrackId, load]);

  const reload = useCallback(() => {
    controllerRef.current?.reload();
  }, []);

  // Never expose another track's previous analytics while React
  // is transitioning between selected tracks.
  const visibleState: GeographicMovementAnalyticsState =
    state.trackId === normalizedTrackId
      ? state
      : normalizedTrackId === null
        ? IDLE_STATE
        : {
            status: "loading",
            trackId: normalizedTrackId,
            data: null,
            error: null,
            errorStatus: null,
          };

  return {
    state: visibleState,
    reload,
  };
}
