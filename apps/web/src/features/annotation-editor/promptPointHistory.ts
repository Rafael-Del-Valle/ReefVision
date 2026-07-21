export type PromptPointKind = "positive" | "negative";

export interface PromptPoint {
  id: string;
  x: number;
  y: number;
  kind: PromptPointKind;
  createdAt: string;
}

export interface PromptPointSnapshot {
  points: PromptPoint[];
}

export interface PromptPointHistoryState {
  present: PromptPointSnapshot;
  past: PromptPointSnapshot[];
  future: PromptPointSnapshot[];
}

export type PromptPointHistoryAction =
  | { type: "add"; point: PromptPoint }
  | { type: "remove"; pointId: string }
  | { type: "clear" }
  | { type: "replace"; points: PromptPoint[] }
  | { type: "reset" }
  | { type: "undo" }
  | { type: "redo" };

export const initialPromptPointHistoryState: PromptPointHistoryState = {
  present: { points: [] },
  past: [],
  future: [],
};

function commit(
  state: PromptPointHistoryState,
  next: PromptPointSnapshot,
): PromptPointHistoryState {
  return {
    present: next,
    past: [...state.past, state.present],
    future: [],
  };
}

export function promptPointHistoryReducer(
  state: PromptPointHistoryState,
  action: PromptPointHistoryAction,
): PromptPointHistoryState {
  switch (action.type) {
    case "add":
      return commit(state, {
        points: [...state.present.points, action.point],
      });
    case "remove": {
      const points = state.present.points.filter(
        (point) => point.id !== action.pointId,
      );
      return points.length === state.present.points.length
        ? state
        : commit(state, { points });
    }
    case "clear":
      return state.present.points.length === 0
        ? state
        : commit(state, { points: [] });
    case "replace":
      return commit(state, { points: action.points });
    case "reset":
      return initialPromptPointHistoryState;
    case "undo": {
      const previous = state.past.at(-1);
      if (!previous) return state;
      return {
        present: previous,
        past: state.past.slice(0, -1),
        future: [state.present, ...state.future],
      };
    }
    case "redo": {
      const next = state.future[0];
      if (!next) return state;
      return {
        present: next,
        past: [...state.past, state.present],
        future: state.future.slice(1),
      };
    }
  }
}
