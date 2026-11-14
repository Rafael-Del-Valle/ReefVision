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
      boundedDenseObjectRows(annotations, masks, 4, [], []).map((row) => [
        row.kind,
        row.item.id,
        row.position,
      ]),
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

  it("reads only mounted rows for an in-window selection", () => {
    const source = Array.from({ length: 20_000 }, (_, index) => ({
      id: `box-${index}`,
    }));
    let reads = 0;
    const annotations = new Proxy(source, {
      get(target, property, receiver) {
        if (typeof property === "string" && /^[0-9]+$/.test(property)) {
          reads += 1;
        }
        return Reflect.get(target, property, receiver);
      },
    });

    const rows = boundedDenseObjectRows(annotations, [], 200, ["box-10"], []);
    expect(rows).toHaveLength(200);
    expect(reads).toBe(200);
    expect(source).toHaveLength(20_000);
  });

  it("stops after a distant box without scanning masks", () => {
    const source = Array.from({ length: 20_000 }, (_, index) => ({
      id: `box-${index}`,
    }));
    const maskSource = Array.from({ length: 20_000 }, (_, index) => ({
      id: `mask-${index}`,
    }));
    let annotationReads = 0;
    let maskReads = 0;
    const annotations = new Proxy(source, {
      get(target, property, receiver) {
        if (typeof property === "string" && /^[0-9]+$/.test(property)) {
          annotationReads += 1;
        }
        return Reflect.get(target, property, receiver);
      },
    });
    const masks = new Proxy(maskSource, {
      get(target, property, receiver) {
        if (typeof property === "string" && /^[0-9]+$/.test(property)) {
          maskReads += 1;
        }
        return Reflect.get(target, property, receiver);
      },
    });
    const rows = boundedDenseObjectRows(
      annotations,
      masks,
      100,
      ["box-103", "box-2"],
      [],
    );
    const positions = Array.from({ length: 100 }, (_, index) => index);
    expect(rows.map((row) => row.position)).toEqual([...positions, 103]);
    expect(annotationReads).toBe(104);
    expect(maskReads).toBe(0);
  });

  it("bounds a 20,000-item range selection without losing scientific selection state", () => {
    const annotations = Array.from({ length: 20_000 }, (_, index) => ({
      id: `box-${index}`,
    }));
    const selectedIds = annotations.map((item) => item.id);
    const originalSelection = [...selectedIds];
    const rows = boundedDenseObjectRows(annotations, [], 200, selectedIds, []);

    // 200 ordinary rows plus at most 200 pinned off-window selections.
    expect(rows).toHaveLength(400);
    expect(rows[0].position).toBe(0);
    expect(rows[199].position).toBe(199);
    expect(rows[200].position).toBe(19_800);
    expect(rows[399].position).toBe(19_999);
    expect(selectedIds).toEqual(originalSelection);
    expect(annotations).toHaveLength(20_000);
  });

  it("bounds both selected types independently and preserves source ordering", () => {
    const annotations = Array.from({ length: 2_000 }, (_, index) => ({
      id: `box-${index}`,
    }));
    const masks = Array.from({ length: 3_000 }, (_, index) => ({
      id: `mask-${index}`,
    }));
    const rows = boundedDenseObjectRows(
      annotations,
      masks,
      200,
      annotations.map((item) => item.id),
      masks.map((item) => item.id),
    );

    expect(rows).toHaveLength(600);
    expect(rows[200].position).toBe(1_800);
    expect(rows[399].position).toBe(1_999);
    expect(rows[400].position).toBe(4_800);
    expect(rows[599].position).toBe(4_999);
    expect(rows.map((row) => row.position)).toEqual(
      [...rows.map((row) => row.position)].sort((left, right) => left - right),
    );
    expect(annotations).toHaveLength(2_000);
    expect(masks).toHaveLength(3_000);
  });

  it("retains every sparse off-window selection when fewer than 200 are pinned", () => {
    const annotations = Array.from({ length: 8_000 }, (_, index) => ({
      id: `box-${index}`,
    }));
    const rows = boundedDenseObjectRows(
      annotations,
      [],
      10,
      ["box-7900", "box-12", "box-7999"],
      [],
    );
    expect(rows.slice(10).map((row) => row.position)).toEqual([12, 7900, 7999]);
  });
  it("jumps directly to a distant bounded window without mounting earlier objects", () => {
    const source = Array.from({ length: 20_000 }, (_, index) => ({
      id: `box-${index}`,
    }));
    let reads = 0;
    const annotations = new Proxy(source, {
      get(target, property, receiver) {
        if (typeof property === "string" && /^[0-9]+$/.test(property)) {
          reads += 1;
        }
        return Reflect.get(target, property, receiver);
      },
    });
    const rows = boundedDenseObjectRows(annotations, [], 200, [], [], 18_800);
    expect(rows).toHaveLength(200);
    expect(rows[0].position).toBe(18_800);
    expect(rows[199].position).toBe(18_999);
    expect(reads).toBe(200);
    expect(source).toHaveLength(20_000);
  });

  it("keeps selected objects on both sides of a jump in scientific source order", () => {
    const annotations = Array.from({ length: 1_500 }, (_, index) => ({
      id: `box-${index}`,
    }));
    const rows = boundedDenseObjectRows(
      annotations,
      [],
      200,
      ["box-600", "box-1499"],
      [],
      1_000,
    );
    expect(rows).toHaveLength(202);
    expect(rows[0].position).toBe(600);
    expect(rows[1].position).toBe(1_000);
    expect(rows[200].position).toBe(1_199);
    expect(rows[201].position).toBe(1_499);
    expect(annotations[600].id).toBe("box-600");
  });

  it("jumps across the annotation-mask boundary with original accessible positions", () => {
    const annotations = Array.from({ length: 8 }, (_, index) => ({
      id: `box-${index}`,
    }));
    const masks = Array.from({ length: 8 }, (_, index) => ({
      id: `mask-${index}`,
    }));
    const rows = boundedDenseObjectRows(
      annotations,
      masks,
      5,
      ["box-0"],
      ["mask-7"],
      6,
    );
    expect(rows.map((row) => [row.kind, row.position])).toEqual([
      ["annotation", 0],
      ["annotation", 6],
      ["annotation", 7],
      ["mask", 8],
      ["mask", 9],
      ["mask", 10],
      ["mask", 15],
    ]);
  });

  it("normalizes nonfinite and out-of-bounds jump offsets without changing inputs", () => {
    const annotations = [{ id: "a" }, { id: "b" }];
    const masks = [{ id: "m" }];
    expect(
      boundedDenseObjectRows(annotations, masks, 2, [], [], NaN).map(
        (row) => row.position,
      ),
    ).toEqual([0, 1]);
    expect(
      boundedDenseObjectRows(annotations, masks, 2, [], [], -50).map(
        (row) => row.position,
      ),
    ).toEqual([0, 1]);
    expect(
      boundedDenseObjectRows(annotations, masks, 2, [], [], 999).map(
        (row) => row.position,
      ),
    ).toEqual([2]);
    expect(annotations).toEqual([{ id: "a" }, { id: "b" }]);
    expect(masks).toEqual([{ id: "m" }]);
  });
});
