import { describe, expect, it } from "vitest";

import { resolveRasterMaskSelection } from "./rasterMaskSelection";

describe("resolveRasterMaskSelection", () => {
  const masks = [{ id: "mask-1" }, { id: "mask-2" }];

  it("selects the first existing mask when the workspace opens", () => {
    expect(resolveRasterMaskSelection(null, masks, false)).toBe("mask-1");
  });

  it("keeps editing the currently selected mask", () => {
    expect(resolveRasterMaskSelection("mask-2", masks, false)).toBe("mask-2");
  });

  it("returns no selection only after another mask is explicitly requested", () => {
    expect(resolveRasterMaskSelection("mask-1", masks, true)).toBeNull();
  });
});
