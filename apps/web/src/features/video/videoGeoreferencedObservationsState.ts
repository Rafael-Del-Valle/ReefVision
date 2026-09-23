import type {
  GeoReferencedObservationDetail,
  GeoReferencedObservationSummary,
} from "./videoGeoreferencedObservationsApi";

export type GeoMapLoadStatus = "idle" | "loading" | "success" | "error";

export interface GeoMapPoint {
  observationId: string;
  trackId: string | null;
  frameIndex: number;
  frameTimeSeconds: number;
  latitude: number;
  longitude: number;
  uncertaintyAvailable: boolean;
}

export interface GeoObservationTrackGroups {
  tracked: Map<string, GeoReferencedObservationSummary[]>;
  untracked: GeoReferencedObservationSummary[];
}

export interface GeoMapState {
  observations: GeoReferencedObservationSummary[];

  collectionStatus: GeoMapLoadStatus;
  collectionError: string | null;

  selectedObservationId: string | null;
  selectedObservation: GeoReferencedObservationDetail | null;

  detailStatus: GeoMapLoadStatus;
  detailError: string | null;

  activeDetailRequestId: number | null;

  detailCache: Map<string, GeoReferencedObservationDetail>;
}

export type GeoMapAction =
  | {
      type: "collection-loading";
    }
  | {
      type: "collection-success";
      observations: GeoReferencedObservationSummary[];
    }
  | {
      type: "collection-error";
      error: string;
    }
  | {
      type: "select-observation";
      observationId: string;
      requestId: number;
    }
  | {
      type: "detail-success";
      observationId: string;
      requestId: number;
      observation: GeoReferencedObservationDetail;
    }
  | {
      type: "detail-error";
      observationId: string;
      requestId: number;
      error: string;
    }
  | {
      type: "clear-selection";
    };

export function createGeoMapState(): GeoMapState {
  return {
    observations: [],
    collectionStatus: "idle",
    collectionError: null,

    selectedObservationId: null,
    selectedObservation: null,

    detailStatus: "idle",
    detailError: null,

    activeDetailRequestId: null,

    detailCache: new Map(),
  };
}

export function toGeoMapPoint(
  observation: GeoReferencedObservationSummary,
): GeoMapPoint {
  return {
    observationId: observation.id,
    trackId: observation.track_id,
    frameIndex: observation.frame_index,
    frameTimeSeconds: observation.frame_time_s,
    latitude: observation.location.latitude_deg,
    longitude: observation.location.longitude_deg,
    uncertaintyAvailable: observation.uncertainty_available,
  };
}

export function groupGeoObservationsByTrack(
  observations: GeoReferencedObservationSummary[],
): GeoObservationTrackGroups {
  const tracked = new Map<string, GeoReferencedObservationSummary[]>();

  const untracked: GeoReferencedObservationSummary[] = [];

  for (const observation of observations) {
    if (observation.track_id === null) {
      untracked.push(observation);
      continue;
    }

    const existing = tracked.get(observation.track_id) ?? [];

    existing.push(observation);

    tracked.set(observation.track_id, existing);
  }

  for (const items of tracked.values()) {
    items.sort((first, second) => first.frame_index - second.frame_index);
  }

  untracked.sort((first, second) => first.frame_index - second.frame_index);

  return {
    tracked,
    untracked,
  };
}

export function geoMapReducer(
  state: GeoMapState,
  action: GeoMapAction,
): GeoMapState {
  switch (action.type) {
    case "collection-loading":
      return {
        ...state,
        collectionStatus: "loading",
        collectionError: null,
      };

    case "collection-success":
      return {
        ...state,
        observations: action.observations,
        collectionStatus: "success",
        collectionError: null,
      };

    case "collection-error":
      return {
        ...state,
        collectionStatus: "error",
        collectionError: action.error,
      };

    case "select-observation": {
      const cached = state.detailCache.get(action.observationId) ?? null;

      return {
        ...state,
        selectedObservationId: action.observationId,
        selectedObservation: cached,
        detailStatus: cached ? "success" : "loading",
        detailError: null,
        activeDetailRequestId: cached ? null : action.requestId,
      };
    }

    case "detail-success": {
      if (
        state.selectedObservationId !== action.observationId ||
        state.activeDetailRequestId !== action.requestId
      ) {
        return state;
      }

      const detailCache = new Map(state.detailCache);

      detailCache.set(action.observationId, action.observation);

      return {
        ...state,
        selectedObservation: action.observation,
        detailStatus: "success",
        detailError: null,
        activeDetailRequestId: null,
        detailCache,
      };
    }

    case "detail-error":
      if (
        state.selectedObservationId !== action.observationId ||
        state.activeDetailRequestId !== action.requestId
      ) {
        return state;
      }

      return {
        ...state,
        selectedObservation: null,
        detailStatus: "error",
        detailError: action.error,
        activeDetailRequestId: null,
      };

    case "clear-selection":
      return {
        ...state,
        selectedObservationId: null,
        selectedObservation: null,
        detailStatus: "idle",
        detailError: null,
        activeDetailRequestId: null,
      };
  }
}
