import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { getImages, imageContentUrl } from "../../api/client";
import { getVideos, videoContentUrl } from "../video/videoApi";
import {
  type TaxonomySource,
  type VisitOutcome,
  taxonomyPage,
} from "./taxonomyApi";

export const outcomes: Record<VisitOutcome, string> = {
  detected: "Detected",
  not_detected: "Observed non-detection",
  unknown: "Unknown",
  unobserved: "Unobserved",
};
export const decisions = {
  confirmed: "Confirmed",
  dismissed: "Dismissed",
  unresolved: "Unresolved",
} as const;
export const ranks = [
  "species",
  "genus",
  "family",
  "order",
  "class",
  "phylum",
  "unranked",
];
export const formValue = (form: FormData, name: string) =>
  String(form.get(name) ?? "").trim();

export function submitFields(fn: (data: FormData) => void) {
  return (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    fn(new FormData(event.currentTarget));
  };
}

export function useTaxonomyPage<T>(projectId: string, resource: string) {
  return useInfiniteQuery({
    queryKey: ["taxonomy", projectId, resource],
    initialPageParam: 0,
    queryFn: ({ pageParam, signal }) =>
      taxonomyPage<T>(projectId, resource, pageParam, signal),
    getNextPageParam: (page) => {
      const start = page.offset + page.items.length;
      return page.items.length && start < page.total ? start : undefined;
    },
  });
}

export function MoreTaxonomyRows({
  hasNextPage,
  isFetchingNextPage,
  fetchNextPage,
  label,
}: {
  hasNextPage: boolean;
  isFetchingNextPage: boolean;
  fetchNextPage: () => Promise<unknown>;
  label: string;
}) {
  return hasNextPage ? (
    <button
      type="button"
      className="secondary"
      disabled={isFetchingNextPage}
      onClick={() => void fetchNextPage()}
    >
      Load more {label}
    </button>
  ) : null;
}

export function TaxonomyErrors({ errors }: { errors: Array<Error | null> }) {
  return errors.map(
    (error, index) =>
      error && (
        <p role="alert" className="form-error" key={index}>
          {error.message}
        </p>
      ),
  );
}

export function SourcePicker({
  projectId,
  label,
  required = true,
}: {
  projectId: string;
  label: string;
  required?: boolean;
}) {
  const [kind, setKind] = useState<"image" | "video">("image");
  const [filter, setFilter] = useState("");
  const [page, setPage] = useState(1);
  const images = useQuery({
    queryKey: ["taxonomy-source-images", projectId, filter, page],
    queryFn: ({ signal }) =>
      getImages(
        projectId,
        { page, pageSize: 30, filename: filter || undefined },
        signal,
      ),
    enabled: kind === "image",
  });
  const videos = useQuery({
    queryKey: ["taxonomy-source-videos", projectId],
    queryFn: ({ signal }) => getVideos(projectId, signal),
    enabled: kind === "video",
  });
  const assets =
    kind === "image"
      ? (images.data?.items ?? [])
      : (videos.data ?? []).filter((row) =>
          row.original_filename.toLowerCase().includes(filter.toLowerCase()),
        );
  const [selected, setSelected] = useState("");
  function resetSelection() {
    setSelected("");
  }
  return (
    <fieldset>
      <legend>{label}</legend>
      <label>
        {label} type
        <select
          value={kind}
          onChange={(event) => {
            setKind(event.currentTarget.value === "video" ? "video" : "image");
            setPage(1);
            resetSelection();
          }}
        >
          <option value="image">Image</option>
          <option value="video">Video</option>
        </select>
      </label>
      <label>
        Filter {label.toLowerCase()} filenames
        <input
          value={filter}
          onChange={(event) => {
            setFilter(event.currentTarget.value);
            setPage(1);
            resetSelection();
          }}
        />
      </label>
      <label>
        {label} file
        <select
          name="source"
          value={selected}
          required={required}
          onChange={(event) => setSelected(event.currentTarget.value)}
        >
          <option value="">Choose original project media</option>
          {assets.map((asset) => (
            <option key={asset.id} value={`${kind}:${asset.id}`}>
              {asset.original_filename}
            </option>
          ))}
        </select>
      </label>
      {kind === "image" &&
        (page > 1 || (images.data?.total ?? 0) > page * 30) && (
          <div className="annotation-editor-inline-actions">
            <button
              type="button"
              className="secondary"
              disabled={page <= 1}
              onClick={() => {
                setPage(page - 1);
                resetSelection();
              }}
            >
              Previous sources
            </button>
            <button
              type="button"
              className="secondary"
              disabled={(images.data?.total ?? 0) <= page * 30}
              onClick={() => {
                setPage(page + 1);
                resetSelection();
              }}
            >
              Next sources
            </button>
          </div>
        )}
      {selected && (
        <a
          href={
            kind === "image"
              ? imageContentUrl(selected.split(":")[1])
              : videoContentUrl(selected.split(":")[1])
          }
          target="_blank"
          rel="noreferrer"
        >
          View selected original
        </a>
      )}
      <TaxonomyErrors
        errors={[kind === "image" ? images.error : videos.error]}
      />
    </fieldset>
  );
}

export function SourceEvidence({
  source,
  label,
}: {
  source?: TaxonomySource | null;
  label: string;
}) {
  if (!source) return null;
  const url =
    source.kind === "image"
      ? imageContentUrl(source.id)
      : videoContentUrl(source.id);
  return (
    <p>
      {label}{" "}
      <a href={url} target="_blank" rel="noreferrer">
        {source.kind} {source.id}
      </a>{" "}
      <code>{source.sha256}</code>
    </p>
  );
}
