import { expect, it } from "vitest";
import { currentComponentUncertaintyText, currentVectors } from "./currentVectors";
import type { ScientificRecord } from "./environmentalContextApi";
function component(
  variable: string,
  value: number,
  patch: Partial<ScientificRecord> = {},
): ScientificRecord {
  return {
    id: variable,
    project_id: "project",
    variable,
    value,
    unit: "m/s",
    normalized_value: value,
    normalized_unit: "m/s",
    normalized_uncertainty: null,
    observed_at: "2026-04-03T00:00:00Z",
    source_kind: "modeled",
    location: { latitude: 32.5, longitude: -79.5, crs: "EPSG:4326" },
    depth_m: 5,
    depth_reference: "sea_surface",
    qc: "unassessed",
    environmental_cache_key: "cache",
    provenance: {
      source: "Copernicus Marine",
      dataset_id: "synthetic",
      model_version: "202601",
      acquired_at: "2026-04-04T00:00:00Z",
    },
    content_sha256: "hash",
    ...patch,
  };
}
it("computes speed and direction toward true north from east/north components", () => {
  const vectors = currentVectors([
    component("current_eastward_velocity", 3),
    component("current_northward_velocity", 4),
  ]);
  expect(vectors).toHaveLength(1);
  expect(vectors[0].speed).toBe(5);
  expect(vectors[0].bearing).toBeCloseTo(36.86989765);
});
it("preserves supplied component uncertainty without estimating vector uncertainty", () => {
  const vectors = currentVectors([
    component("current_eastward_velocity", 3, {
      normalized_uncertainty: 0.25,
      uncertainty: { value: 0.25, kind: "standard_deviation" },
    }),
    component("current_northward_velocity", 4, {
      normalized_uncertainty: 0.1,
      uncertainty: { value: 0.1, kind: "bound" },
    }),
  ]);
  expect(vectors).toHaveLength(1);
  expect(vectors[0]).toMatchObject({
    eastUncertainty: { value: 0.25, kind: "standard_deviation" },
    northUncertainty: { value: 0.1, kind: "bound" },
  });
  expect(
    currentComponentUncertaintyText("East", vectors[0].eastUncertainty),
  ).toBe("East component uncertainty: 0.250 m/s (standard deviation)");
  expect(
    currentComponentUncertaintyText("North", vectors[0].northUncertainty),
  ).toBe("North component uncertainty: 0.100 m/s (bound)");
});
it("keeps missing, zero and invalid component uncertainties distinct", () => {
  const unknown = currentVectors([
    component("current_eastward_velocity", 3),
    component("current_northward_velocity", 4, {
      normalized_uncertainty: 0,
      uncertainty: { value: 0, kind: "standard_error" },
    }),
  ])[0];
  expect(unknown.eastUncertainty).toBeNull();
  expect(unknown.northUncertainty).toEqual({
    value: 0,
    kind: "standard_error",
  });
  expect(
    currentComponentUncertaintyText("East", unknown.eastUncertainty),
  ).toBe("East component uncertainty: unknown");
  const invalid = currentVectors([
    component("current_eastward_velocity", 3, {
      normalized_uncertainty: -1,
      uncertainty: { value: 1, kind: "bound" },
    }),
    component("current_northward_velocity", 4, {
      normalized_uncertainty: Number.NaN,
      uncertainty: { value: 1, kind: "bound" },
    }),
  ])[0];
  expect(invalid.eastUncertainty).toBeNull();
  expect(invalid.northUncertainty).toBeNull();
});
it("omits a derived current whose magnitude overflows despite finite components", () => {
  expect(
    currentVectors([
      component("current_eastward_velocity", Number.MAX_VALUE),
      component("current_northward_velocity", Number.MAX_VALUE),
    ]),
  ).toEqual([]);
});
it.each([
  [0, 1, 0],
  [1, 0, 90],
  [0, -1, 180],
  [-1, 0, 270],
  [0, 0, null],
])("handles cardinal and stationary vectors %s/%s", (east, north, bearing) => {
  expect(
    currentVectors([
      component("current_eastward_velocity", east!),
      component("current_northward_velocity", north!),
    ])[0].bearing,
  ).toBe(bearing);
});
it("never combines mismatched depth, observation time, acquisition, model or source", () => {
  for (const patch of [
    { depth_m: 10 },
    { observed_at: "2026-04-03T01:00:00Z" },
    { source_kind: "observed" as const },
    { provenance: { ...component("x", 0).provenance, model_version: "other" } },
    {
      provenance: {
        ...component("x", 0).provenance,
        acquired_at: "2026-04-04T01:00:00Z",
      },
    },
  ]) {
    expect(
      currentVectors([
        component("current_eastward_velocity", 3),
        component("current_northward_velocity", 4, patch),
      ]),
    ).toEqual([]);
  }
});
it("excludes rejected, superseded, duplicate and incompatible coordinates", () => {
  const east = component("current_eastward_velocity", 3);
  const north = component("current_northward_velocity", 4);
  expect(currentVectors([east, { ...east, id: "duplicate" }, north])).toEqual(
    [],
  );
  expect(currentVectors([east, { ...north, qc: "rejected" }])).toEqual([]);
  expect(
    currentVectors([east, { ...north, environmental_snapshot_current: false }]),
  ).toEqual([]);
  expect(currentVectors([east, { ...north, location: null }])).toEqual([]);
});
