import { describe, expect, it } from "vitest";

import {
  boundedDenseObjectRows,
  selectedDenseObjectRowIds,
} from "./denseObjectList";

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

  it("skips retained-selection traversal when a filtered modality has no off-page rows", () => {
    const retainedSelection = new Proxy(["deleted-scientific-object"], {
      get(target, key, receiver) {
        if (key === "0") {
          throw new Error("Unexpected scan of fully visible or empty modality");
        }
        return Reflect.get(target, key, receiver);
      },
    });
    expect(
      boundedDenseObjectRows([], [], 200, retainedSelection, retainedSelection),
    ).toEqual([]);
    expect(
      boundedDenseObjectRows(
        [{ id: "annotation-a" }],
        [{ id: "mask-a" }],
        2,
        retainedSelection,
        retainedSelection,
      ).map((row) => row.item.id),
    ).toEqual(["annotation-a", "mask-a"]);
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

  it("uses bounded selection reads and memory for huge dense-object selections", () => {
    const annotations = Array.from({ length: 50_000 }, (_, index) => ({
      id: `box-${index}`,
    }));
    const selectedIds = annotations.map((item) => item.id);
    let selectedReads = 0;
    const trackedSelection = new Proxy(selectedIds, {
      get(target, property, receiver) {
        if (typeof property === "string" && /^[0-9]+$/.test(property)) {
          selectedReads += 1;
        }
        return Reflect.get(target, property, receiver);
      },
    });

    const rows = boundedDenseObjectRows(
      annotations,
      [],
      200,
      trackedSelection,
      [],
    );
    expect(rows).toHaveLength(400);
    expect(rows[0].position).toBe(0);
    expect(rows[199].position).toBe(199);
    expect(rows[200].position).toBe(49_800);
    expect(rows[399].position).toBe(49_999);
    expect(selectedReads).toBe(200);
    expect(selectedIds).toHaveLength(50_000);
    expect(annotations).toHaveLength(50_000);
  });

  it("recovers distinct matching pins even when recent selections repeat", () => {
    const annotations = Array.from({ length: 300 }, (_, index) => ({
      id: `box-${index}`,
    }));
    const selectedIds = ["box-250", ...Array(200).fill("box-299")];
    const rows = boundedDenseObjectRows(annotations, [], 10, selectedIds, []);
    expect(rows.map((row) => row.position)).toEqual([
      0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 250, 299,
    ]);
    expect(selectedIds).toHaveLength(201);
    expect(annotations).toHaveLength(300);
  });

  it("keeps selected matching boxes and masks reachable after filtered-out selections", () => {
    const allAnnotations = Array.from({ length: 300 }, (_, index) => ({
      id: `box-${index}`,
    }));
    const allMasks = Array.from({ length: 300 }, (_, index) => ({
      id: `mask-${index}`,
    }));
    // Mimic the editor's class-name filtering: half the observations remain.
    const annotations = allAnnotations.filter((_, index) => index % 2 === 0);
    const masks = allMasks.filter((_, index) => index % 2 === 0);
    const annotationSelection = [
      "box-296",
      ...Array.from({ length: 500 }, (_, index) => `filtered-box-${index}`),
    ];
    const maskSelection = [
      "mask-298",
      ...Array.from({ length: 500 }, (_, index) => `deleted-mask-${index}`),
    ];
    const rows = boundedDenseObjectRows(
      annotations,
      masks,
      10,
      annotationSelection,
      maskSelection,
    );
    expect(rows.map((row) => row.position)).toEqual([
      0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 148, 299,
    ]);
    expect(rows[10].item).toBe(allAnnotations[296]);
    expect(rows[11].item).toBe(allMasks[298]);
    expect(annotationSelection).toHaveLength(501);
    expect(maskSelection).toHaveLength(501);
    expect(allAnnotations).toHaveLength(300);
    expect(allMasks).toHaveLength(300);
  });

  it("bounds filtered-record reads when many stale selected IDs precede valid ones", () => {
    const source = Array.from({ length: 5_000 }, (_, index) => ({
      id: `box-${index}`,
    }));
    let indexedReads = 0;
    const annotations = new Proxy(source, {
      get(target, property, receiver) {
        if (typeof property === "string" && /^[0-9]+$/.test(property)) {
          indexedReads += 1;
        }
        return Reflect.get(target, property, receiver);
      },
    });
    const selectedIds = [
      "box-4999",
      ...Array.from({ length: 5_000 }, (_, index) => `stale-${index}`),
    ];
    const rows = boundedDenseObjectRows(
      annotations,
      [],
      200,
      selectedIds,
      [],
    );
    expect(rows).toHaveLength(201);
    expect(rows[200].position).toBe(4_999);
    // Prefix, one candidate scan and one exceptional-path index build.
    // A repeated full scan for each 200 stale IDs exceeds this bound.
    expect(indexedReads).toBeLessThanOrEqual(2 * source.length + 200);
    expect(selectedIds).toHaveLength(5_001);
    expect(source).toHaveLength(5_000);
  });

  it("fills the bounded 200-pin budget with matching rows, not stale IDs", () => {
    const annotations = Array.from({ length: 1_000 }, (_, index) => ({
      id: `box-${index}`,
    }));
    const selection = [
      ...Array.from({ length: 250 }, (_, index) => `box-${750 + index}`),
      ...Array.from({ length: 800 }, (_, index) => `deleted-${index}`),
    ];
    const rows = boundedDenseObjectRows(annotations, [], 10, selection, []);
    expect(rows).toHaveLength(210);
    expect(rows.slice(0, 10).map((row) => row.position)).toEqual([
      0, 1, 2, 3, 4, 5, 6, 7, 8, 9,
    ]);
    expect(rows[10].position).toBe(800);
    expect(rows[209].position).toBe(999);
    expect(selection).toHaveLength(1_050);
    expect(annotations).toHaveLength(1_000);
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
    ).toEqual([1, 2]);
    expect(annotations).toEqual([{ id: "a" }, { id: "b" }]);
    expect(masks).toEqual([{ id: "m" }]);
  });

  it("recovers a full final window when previously mounted objects were deleted", () => {
    const annotations = Array.from({ length: 350 }, (_, index) => ({
      id: `box-${index}`,
    }));
    const masks = Array.from({ length: 50 }, (_, index) => ({
      id: `mask-${index}`,
    }));
    const selectedAnnotationIds = ["box-3"];
    const selectedMaskIds = ["mask-49"];
    // This state was valid when the image contained more than 500 objects.
    // Deleting/filtering objects must not strand the reviewer on one row.
    const rows = boundedDenseObjectRows(
      annotations,
      masks,
      200,
      selectedAnnotationIds,
      selectedMaskIds,
      500,
    );
    expect(rows).toHaveLength(201);
    expect(rows[0].position).toBe(3);
    expect(rows[1].position).toBe(200);
    expect(rows[200].position).toBe(399);
    expect(rows.filter((row) => row.item.id === "mask-49")).toHaveLength(1);
    expect(rows.filter((row) => row.item.id === "box-3")).toHaveLength(1);
    expect(selectedAnnotationIds).toEqual(["box-3"]);
    expect(selectedMaskIds).toEqual(["mask-49"]);
    expect(annotations).toHaveLength(350);
    expect(masks).toHaveLength(50);
  });

  it("keeps valid near-end jump positions anchored instead of shifting full pages", () => {
    const annotations = Array.from({ length: 420 }, (_, index) => ({
      id: `box-${index}`,
    }));
    const rows = boundedDenseObjectRows(annotations, [], 200, [], [], 400);
    expect(rows).toHaveLength(20);
    expect(rows[0].position).toBe(400);
    expect(rows[19].position).toBe(419);
  });

  it("keeps selected and pinned row IDs distinct between annotations and masks", () => {
    const annotations = [{ id: "same" }, { id: "box-1" }, { id: "box-2" }];
    const masks = [{ id: "same" }, { id: "mask-1" }];
    const selectedBoxes = ["box-2", "same", "missing"];
    const selectedMasks = ["same", "missing"];
    const rows = boundedDenseObjectRows(
      annotations,
      masks,
      1,
      selectedBoxes,
      selectedMasks,
    );
    const selected = selectedDenseObjectRowIds(
      rows,
      selectedBoxes,
      selectedMasks,
    );
    expect([...selected.annotationIds].sort()).toEqual(["box-2", "same"]);
    expect([...selected.maskIds]).toEqual(["same"]);
    expect(selected.annotationIds.has("mask-1")).toBe(false);
    expect(selectedBoxes).toEqual(["box-2", "same", "missing"]);
    expect(selectedMasks).toEqual(["same", "missing"]);
  });

  it("reads a 50,000-ID range selection at most once, even for 400 mounted rows", () => {
    const annotations = Array.from({ length: 50_000 }, (_, index) => ({
      id: "box-" + index,
    }));
    const selection = annotations.map((annotation) => annotation.id);
    const rows = boundedDenseObjectRows(annotations, [], 200, selection, []);
    let reads = 0;
    const trackedSelection = new Proxy(selection, {
      get(target, key, receiver) {
        if (typeof key === "string" && /^\d+$/.test(key)) reads += 1;
        return Reflect.get(target, key, receiver);
      },
    });
    const selected = selectedDenseObjectRowIds(rows, trackedSelection, []);
    expect(rows).toHaveLength(400);
    expect(selected.annotationIds.size).toBe(400);
    expect(selected.annotationIds.has("box-0")).toBe(true);
    expect(selected.annotationIds.has("box-49999")).toBe(true);
    expect(reads).toBeLessThanOrEqual(selection.length);
    expect(annotations).toHaveLength(50_000);
  });

  it("does not scan large selections when no rows are mounted", () => {
    const selection = new Proxy(["box-1"], {
      get(target, key, receiver) {
        if (key === "0") throw new Error("Unexpected selection scan");
        return Reflect.get(target, key, receiver);
      },
    });
    const selected = selectedDenseObjectRowIds([], selection, selection);
    expect(selected.annotationIds.size).toBe(0);
    expect(selected.maskIds.size).toBe(0);
  });
});
