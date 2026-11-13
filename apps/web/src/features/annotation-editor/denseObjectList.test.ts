import { describe, expect, it } from "vitest";

import { boundedDenseObjectRows } from "./denseObjectList";

describe("dense object-browser window", () => {
  it("bounds DOM candidates without changing or dropping saved scientific records", () => {
    const annotations = Array.from({ length: 10_000 }, (_, index) => ({
      id: `annotation-${index}`,
    }));
    const masks = Array.from({ length: 10_000 }, (_, index) => ({
      id: `mask-${index}`,
    }));
    const rows = boundedDenseObjectRows(annotations, masks, 200, [], []);
    expect(rows).toHaveLength(200);
    expect(rows[0]).toEqual({
      kind: "annotation",
      item: annotations[0],
      position: 0,
    });
    expect(rows[199].item).toBe(annotations[199]);
    expect(annotations).toHaveLength(10_000);
    expect(masks).toHaveLength(10_000);
    expect(annotations[9_999].id).toBe("annotation-9999");
  });

  it("keeps selected annotations and masks outside the window reachable exactly once", () => {
    const annotations = Array.from({ length: 300 }, (_, index) => ({
      id: `box-${index}`,
    }));
    const masks = Array.from({ length: 300 }, (_, index) => ({
      id: `mask-${index}`,
    }));
    const rows = boundedDenseObjectRows(
      annotations,
      masks,
      200,
      ["box-1", "box-299"],
      ["mask-299"],
    );
    expect(rows).toHaveLength(202);
    expect(rows.filter((row) => row.item.id === "box-1")).toHaveLength(1);
    expect(rows[200]).toEqual({
      kind: "annotation",
      item: annotations[299],
      position: 299,
    });
    expect(rows[201]).toEqual({
      kind: "mask",
      item: masks[299],
      position: 599,
    });
  });

  it("pages through masks after annotations while preserving filtered positions", () => {
    const annotations = [{ id: "a" }, { id: "b" }];
    const masks = [{ id: "m1" }, { id: "m2" }, { id: "m3" }];
    expect(
      boundedDenseObjectRows(annotations, masks, 4, [], []).map(
        (row) => [row.kind, row.item.id, row.position],
      ),
    ).toEqual([
      ["annotation", "a", 0],
      ["annotation", "b", 1],
      ["mask", "m1", 2],
      ["mask", "m2", 3],
    ]);
    expect(boundedDenseObjectRows(annotations, masks, 5, [], [])).toHaveLength(
      5,
    );
  });

  it("treats malformed limits conservatively without mutating input arrays", () => {
    const annotations = [{ id: "a" }];
    const masks = [{ id: "m" }];
    expect(
      boundedDenseObjectRows(annotations, masks, NaN, [], []).map(
        (row) => row.item.id,
      ),
    ).toEqual([]);
    expect(
      boundedDenseObjectRows(annotations, masks, -20, ["a"], ["m"]).map(
        (row) => row.item.id,
      ),
    ).toEqual(["a", "m"]);
    expect(annotations).toEqual([{ id: "a" }]);
    expect(masks).toEqual([{ id: "m" }]);
  });
});
