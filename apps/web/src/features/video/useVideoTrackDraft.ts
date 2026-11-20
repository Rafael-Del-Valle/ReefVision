import { useLayoutEffect, useMemo, useState } from "react";

import type { VideoTrackKeyframe, VideoTrackRecord } from "./videoApi";

export function sortedKeyframes(
  items: VideoTrackKeyframe[],
): VideoTrackKeyframe[] {
  return [...items].sort((first, second) => first.frame - second.frame);
}

interface TrackFields {
  labelClassId: string;
  interpolation: "linear" | "hold";
  status: string;
  keyframes: VideoTrackKeyframe[];
}

interface TrackDraft {
  context: string;
  revision: number | null;
  baseline: TrackFields;
  fields: TrackFields;
  before: TrackFields[];
  after: TrackFields[];
}

export function useVideoTrackDraft(
  context: string,
  saved: VideoTrackRecord | undefined,
  defaultClassId: string,
) {
  const [draft, setDraft] = useState<TrackDraft | null>(null);
  useLayoutEffect(() => setDraft(null), [context]);
  const fields = useMemo<TrackFields>(
    () => ({
      labelClassId: saved?.label_class_id ?? defaultClassId,
      interpolation: saved?.interpolation === "hold" ? "hold" : "linear",
      status: saved?.status ?? "verified",
      keyframes: saved ? sortedKeyframes(saved.keyframes_json) : [],
    }),
    [defaultClassId, saved],
  );
  const latest: TrackDraft = {
    context,
    revision: saved?.revision ?? null,
    baseline: fields,
    fields,
    before: [],
    after: [],
  };
  const resolve = (candidate: TrackDraft | null) =>
    candidate?.context === context ? candidate : latest;
  const active = resolve(draft);

  return {
    fields: active.fields,
    revision: active.revision,
    dirty: active.fields !== active.baseline,
    canUndo: active.before.length > 0,
    canRedo: active.after.length > 0,
    change: (edit: (fields: TrackFields) => TrackFields) =>
      setDraft((candidate) => {
        const current = resolve(candidate);
        const changed = edit(current.fields);
        if (changed === current.fields) return candidate;
        return {
          ...current,
          fields: changed,
          before: [...current.before.slice(-49), current.fields],
          after: [],
        };
      }),
    undo: () =>
      setDraft((candidate) => {
        const current = resolve(candidate);
        const previous = current.before.at(-1);
        if (!previous) return candidate;
        return {
          ...current,
          fields: previous,
          before: current.before.slice(0, -1),
          after: [current.fields, ...current.after],
        };
      }),
    redo: () =>
      setDraft((candidate) => {
        const current = resolve(candidate);
        const next = current.after[0];
        if (!next) return candidate;
        return {
          ...current,
          fields: next,
          before: [...current.before, current.fields],
          after: current.after.slice(1),
        };
      }),
    reset: () => setDraft(null),
  };
}
