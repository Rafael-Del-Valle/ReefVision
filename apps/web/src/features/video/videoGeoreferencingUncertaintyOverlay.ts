interface Coordinate {
  latitude_deg: number;
  longitude_deg: number;
}

interface Viewport {
  width: number;
  height: number;
  padding: number;
}

interface Center {
  x: number;
  y: number;
}

export interface ProjectedHorizontal95Radius {
  cx: number;
  cy: number;
  rx: number;
  ry: number;
  radiusMeters: number;
}

/**
 * Converts an authoritative radius in meters into the existing map's
 * independent longitude/latitude SVG scales.
 *
 * This is display geometry only. It does not calculate uncertainty.
 */
export function projectHorizontal95Radius(
  coordinates: readonly Coordinate[],
  centerLatitudeDeg: number,
  radiusMeters: number | null | undefined,
  center: Center,
  viewport: Viewport,
): ProjectedHorizontal95Radius | null {
  if (
    coordinates.length < 2 ||
    typeof radiusMeters !== "number" ||
    !Number.isFinite(radiusMeters) ||
    radiusMeters <= 0 ||
    !Number.isFinite(centerLatitudeDeg) ||
    Math.abs(centerLatitudeDeg) >= 85 ||
    !Number.isFinite(center.x) ||
    !Number.isFinite(center.y) ||
    viewport.width <= viewport.padding * 2 ||
    viewport.height <= viewport.padding * 2
  ) {
    return null;
  }

  if (
    coordinates.some(
      ({ latitude_deg, longitude_deg }) =>
        !Number.isFinite(latitude_deg) ||
        !Number.isFinite(longitude_deg) ||
        Math.abs(latitude_deg) > 90 ||
        Math.abs(longitude_deg) > 180,
    )
  ) {
    return null;
  }

  const latitudes = coordinates.map((item) => item.latitude_deg);
  const longitudes = coordinates.map((item) => item.longitude_deg);

  const rawLongitudeSpan = Math.max(...longitudes) - Math.min(...longitudes);

  // The existing map does not unwrap antimeridian-crossing tracks.
  if (rawLongitudeSpan > 180) return null;

  // Match the existing map's minimum geographic spans exactly.
  const latitudeSpan = Math.max(
    Math.max(...latitudes) - Math.min(...latitudes),
    0.000001,
  );
  const longitudeSpan = Math.max(rawLongitudeSpan, 0.000001);

  const latitudeRadians = (centerLatitudeDeg * Math.PI) / 180;

  // WGS84 local meridional and prime-vertical radii of curvature.
  const a = 6378137;
  const f = 1 / 298.257223563;
  const e2 = f * (2 - f);
  const sinLatitude = Math.sin(latitudeRadians);
  const denominator = 1 - e2 * sinLatitude * sinLatitude;

  const meridionalRadius = (a * (1 - e2)) / Math.pow(denominator, 1.5);

  const primeVerticalRadius = a / Math.sqrt(denominator);

  const metersPerDegreeLatitude = (Math.PI / 180) * meridionalRadius;

  const metersPerDegreeLongitude =
    (Math.PI / 180) * primeVerticalRadius * Math.cos(latitudeRadians);

  const plotWidth = viewport.width - viewport.padding * 2;
  const plotHeight = viewport.height - viewport.padding * 2;

  const rx =
    (radiusMeters / metersPerDegreeLongitude / longitudeSpan) * plotWidth;

  const ry =
    (radiusMeters / metersPerDegreeLatitude / latitudeSpan) * plotHeight;

  if (!Number.isFinite(rx) || !Number.isFinite(ry) || rx <= 0 || ry <= 0) {
    return null;
  }

  return {
    cx: center.x,
    cy: center.y,
    rx,
    ry,
    radiusMeters,
  };
}
