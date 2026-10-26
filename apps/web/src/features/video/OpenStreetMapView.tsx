import {
  currentComponentUncertaintyText,
  vectorColor,
  type CurrentVector,
} from "../environmental-context/currentVectors";
import L from "leaflet";
import { useEffect, useMemo, useRef } from "react";

import "leaflet/dist/leaflet.css";

import type { GeoReferencedObservationSummary } from "./videoGeoreferencedObservationsApi";

interface OpenStreetMapViewProps {
  observations: GeoReferencedObservationSummary[];
  currentVectors?: CurrentVector[];
  showBasemap?: boolean;
  mapExtent?: [[number, number], [number, number]];
  activeObservationId?: string | null;
  selectedObservationId?: string | null;
  showTrackLines?: boolean;
  selectedUncertaintyRadiusM?: number | null;
  onObservationSelect?: (observation: GeoReferencedObservationSummary) => void;
  onTileFailure?: () => void;
}

const NO_CURRENTS: CurrentVector[] = [];
const DEFAULT_CENTER: L.LatLngExpression = [0, 0];
const DEFAULT_ZOOM = 2;

function observationPosition(
  observation: GeoReferencedObservationSummary,
): L.LatLngTuple {
  return [
    observation.location.latitude_deg,
    observation.location.longitude_deg,
  ];
}

export function OpenStreetMapView({
  observations,
  currentVectors = NO_CURRENTS,
  showBasemap = true,
  mapExtent,
  activeObservationId = null,
  selectedObservationId = null,
  showTrackLines = true,
  selectedUncertaintyRadiusM = null,
  onObservationSelect,
  onTileFailure,
}: OpenStreetMapViewProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<L.Map | null>(null);
  const overlayRef = useRef<L.LayerGroup | null>(null);

  const selectRef = useRef(onObservationSelect);
  const tileFailureRef = useRef(onTileFailure);

  useEffect(() => {
    selectRef.current = onObservationSelect;
  }, [onObservationSelect]);

  useEffect(() => {
    tileFailureRef.current = onTileFailure;
  }, [onTileFailure]);

  const tracks = useMemo(() => {
    const grouped = new Map<string, GeoReferencedObservationSummary[]>();

    for (const observation of observations) {
      if (!observation.track_id) {
        continue;
      }

      const existing = grouped.get(observation.track_id) ?? [];
      existing.push(observation);
      grouped.set(observation.track_id, existing);
    }

    for (const group of grouped.values()) {
      group.sort(
        (left, right) =>
          left.frame_index - right.frame_index ||
          left.id.localeCompare(right.id),
      );
    }

    return grouped;
  }, [observations]);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) {
      return;
    }

    const map = L.map(containerRef.current, {
      zoomControl: true,
      attributionControl: true,
    }).setView(DEFAULT_CENTER, DEFAULT_ZOOM);

    const tiles = L.tileLayer(
      "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
      {
        maxZoom: 19,
        attribution:
          '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
      },
    );

    let consecutiveTileErrors = 0;
    let fallbackReported = false;

    tiles.on("tileload", () => {
      consecutiveTileErrors = 0;
    });

    tiles.on("tileerror", () => {
      consecutiveTileErrors += 1;

      if (consecutiveTileErrors >= 3 && !fallbackReported) {
        fallbackReported = true;
        tileFailureRef.current?.();
      }
    });

    if (showBasemap) tiles.addTo(map);

    const scaleControl = L.control
      .scale({
        position: "bottomleft",
        metric: true,
        imperial: false,
        maxWidth: 120,
      })
      .addTo(map);

    const scaleElement = scaleControl.getContainer();

    if (scaleElement) {
      scaleElement.setAttribute("data-testid", "openstreetmap-scale-control");

      scaleElement.setAttribute("aria-label", "Map scale");

      scaleElement.setAttribute("title", "Map distance scale");
    }

    const overlays = L.layerGroup().addTo(map);

    mapRef.current = map;
    overlayRef.current = overlays;

    requestAnimationFrame(() => {
      map.invalidateSize();
    });

    return () => {
      overlayRef.current = null;
      mapRef.current = null;
      map.remove();
    };
  }, [showBasemap]);

  useEffect(() => {
    const map = mapRef.current;
    const overlays = overlayRef.current;

    if (!map || !overlays) {
      return;
    }

    overlays.clearLayers();

    const drawableCurrents = currentVectors.filter(
      (vector) => Math.abs(vector.latitude) <= 85,
    );
    const positions: L.LatLngTuple[] = [
      ...observations.map(observationPosition),
      ...drawableCurrents.map(
        (vector) => [vector.latitude, vector.longitude] as L.LatLngTuple,
      ),
    ];
    for (const vector of drawableCurrents) {
      const arrow = document.createElement("div");
      arrow.textContent = vector.bearing === null ? "•" : "↑";
      arrow.style.cssText = `font-size:28px;line-height:32px;text-align:center;color:${vectorColor(vector.speed)};transform:rotate(${vector.bearing ?? 0}deg);`;
      const tooltip = document.createElement("span");
      tooltip.textContent = [
        `${vector.speed.toFixed(3)} m/s`,
        vector.bearing === null
          ? "stationary"
          : `${vector.bearing.toFixed(1)}° toward true north`,
        vector.sourceKind,
        vector.dataset,
        vector.observedAt,
        `${vector.depthM} m`,
        "vector speed/direction and position uncertainty not estimated",
        currentComponentUncertaintyText("East", vector.eastUncertainty),
        currentComponentUncertaintyText("North", vector.northUncertainty),
      ].join("; ");
      L.marker([vector.latitude, vector.longitude], {
        icon: L.divIcon({
          html: arrow,
          className: "current-vector-marker",
          iconSize: [32, 32],
          iconAnchor: [16, 16],
        }),
      })
        .bindTooltip(tooltip)
        .addTo(overlays);
    }

    if (showTrackLines) {
      for (const [trackId, trackObservations] of tracks) {
        if (trackObservations.length < 2) {
          continue;
        }

        const activeTrack = trackObservations.some(
          (observation) => observation.id === activeObservationId,
        );

        L.polyline(trackObservations.map(observationPosition), {
          weight: activeTrack ? 5 : 3,
          opacity: activeTrack ? 1 : 0.7,
        })
          .bindTooltip(`Track ${trackId}`)
          .addTo(overlays);
      }
    }

    for (const observation of observations) {
      const active = observation.id === activeObservationId;
      const selected = observation.id === selectedObservationId;

      const marker = L.circleMarker(observationPosition(observation), {
        radius: active ? 8 : selected ? 7 : 5,
        weight: active || selected ? 3 : 1.5,
        fillOpacity: active ? 1 : 0.75,
      });

      marker.bindTooltip(
        [
          `Frame ${observation.frame_index}`,
          `${observation.location.latitude_deg.toFixed(6)}, ${observation.location.longitude_deg.toFixed(6)}`,
        ].join("<br />"),
      );

      marker.on("click", () => {
        selectRef.current?.(observation);
      });

      marker.addTo(overlays);
    }

    const selectedObservation = observations.find(
      (observation) => observation.id === selectedObservationId,
    );

    if (
      selectedObservation &&
      selectedUncertaintyRadiusM !== null &&
      Number.isFinite(selectedUncertaintyRadiusM) &&
      selectedUncertaintyRadiusM > 0
    ) {
      L.circle(observationPosition(selectedObservation), {
        radius: selectedUncertaintyRadiusM,
        weight: 2,
        opacity: 0.8,
        fillOpacity: 0.1,
        dashArray: "5 4",
      })
        .bindTooltip(
          `95% horizontal uncertainty: ${selectedUncertaintyRadiusM.toFixed(2)} m`,
        )
        .addTo(overlays);
    }

    if (mapExtent) {
      map.fitBounds(mapExtent);
    } else if (positions.length === 1) {
      map.setView(positions[0], 18);
    } else if (positions.length > 1) {
      map.fitBounds(L.latLngBounds(positions), {
        padding: [28, 28],
        maxZoom: 18,
      });
    }
  }, [
    activeObservationId,
    currentVectors,
    showBasemap,
    mapExtent,
    observations,
    selectedObservationId,
    selectedUncertaintyRadiusM,
    showTrackLines,
    tracks,
  ]);

  return (
    <div
      data-testid="openstreetmap-georeferenced-view"
      aria-label="OpenStreetMap georeferenced observations"
      ref={containerRef}
      style={{
        width: "100%",
        height: 420,
        minHeight: 320,
        borderRadius: 8,
        overflow: "hidden",
        border: "1px solid var(--border-color, #cbd5e1)",
      }}
    />
  );
}
