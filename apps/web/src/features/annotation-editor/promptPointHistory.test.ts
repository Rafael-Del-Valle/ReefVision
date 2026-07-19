import { describe, expect, it } from "vitest";

import {
  initialPromptPointHistoryState,
  promptPointHistoryReducer,
  type PromptPoint,
} from "./promptPointHistory";

const positive: PromptPoint = {
  id: "positive-1",
  x: 10,
  y: 20,
  kind: "positive",
  createdAt: "2026-07-19T12:00:00Z",
};
const negative: PromptPoint = {
  id: "negative-1",
  x: 30,
  y: 40,
  kind: "negative",
  createdAt: "2026-07-19T12:00:01Z",
};

describe("promptPointHistoryReducer", () => {
  it("records point edits and supports undo and redo", () => {
    const withPositive = promptPointHistoryReducer(
      initialPromptPointHistoryState,
      { type: "add", point: positive },
    );
    const withNegative = promptPointHistoryReducer(withPositive, {
      type: "add",
      point: negative,
    });

    expect(withNegative.present.points).toEqual([positive, negative]);
    expect(withNegative.past).toHaveLength(2);

    const undone = promptPointHistoryReducer(withNegative, { type: "undo" });
    expect(undone.present.points).toEqual([positive]);
    expect(undone.future).toHaveLength(1);

    const redone = promptPointHistoryReducer(undone, { type: "redo" });
    expect(redone.present.points).toEqual([positive, negative]);
  });

  it("removes individual prompts and preserves the edit in history", () => {
    const populated = promptPointHistoryReducer(
      promptPointHistoryReducer(initialPromptPointHistoryState, {
        type: "add",
        point: positive,
      }),
      { type: "add", point: negative },
    );
    const removed = promptPointHistoryReducer(populated, {
      type: "remove",
      pointId: positive.id,
    });

    expect(removed.present.points).toEqual([negative]);
    expect(
      promptPointHistoryReducer(removed, { type: "undo" }).present.points,
    ).toEqual([positive, negative]);
  });

  it("clears prompts as an undoable operation", () => {
    const populated = promptPointHistoryReducer(
      initialPromptPointHistoryState,
      { type: "add", point: positive },
    );
    const cleared = promptPointHistoryReducer(populated, { type: "clear" });

    expect(cleared.present.points).toEqual([]);
    expect(
      promptPointHistoryReducer(cleared, { type: "undo" }).present.points,
    ).toEqual([positive]);
  });
});
