import { shouldIgnoreShortcutTarget } from "../../components/ui/keyboardShortcuts";

export type GalleryNavigationAction = "previous" | "next" | "first" | "last";

export interface GalleryPreference {
  imageId: string | null;
  page: number;
  wrap: boolean;
}

export type GalleryNavigationDestination =
  | { page: number; edge: "first" | "last" }
  | { page: number; edge: "index"; index: number };

// Bound restored page numbers so corrupted but safe-integer WebView2 state cannot
// request implausibly distant pages and leave the first-image viewport empty.
const MAX_RESTORED_GALLERY_PAGE = 1_000_000;

const DEFAULT_PREFERENCE: GalleryPreference = {
  imageId: null,
  page: 1,
  wrap: false,
};

// Gallery IDs are opaque database identifiers, never control or line-separator text.
// Reject corrupted WebView2 preferences rather than restoring a phantom image.
function validGalleryImageId(value: unknown): value is string {
  return (
    typeof value === "string" &&
    value.length <= 4096 &&
    value.trim().length > 0 &&
    !/[\x00-\x1f\x7f-\x9f\u061c\u200b-\u200f\u2028-\u202e\u2060\u2066-\u206f\ufeff]/.test(value) &&
    // Keep valid supplementary Unicode (e.g. emoji in camera labels), but
    // reject unpaired UTF-16 surrogate halves from corrupted preferences.
    // Unicode-mode matching treats valid surrogate pairs as one code point.
    !/[\ud800-\udfff]/u.test(value)
  );
}

function preferenceKey(projectId: string): string {
  return `reefvision.gallery.${projectId}.v1`;
}

export function readGalleryPreference(
  storage: Pick<Storage, "getItem">,
  projectId: string,
): GalleryPreference {
  try {
    const value = storage.getItem(preferenceKey(projectId));
    if (!value || value.length > 4096) return { ...DEFAULT_PREFERENCE };
    // Corrupted or oversized WebView2 preferences must not block first-image
    // rendering with expensive JSON parsing. Valid preferences contain only
    // a short opaque image ID, page number, and wrap flag.
    const parsed: unknown = JSON.parse(value);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return { ...DEFAULT_PREFERENCE };
    }
    const candidate = parsed as Record<string, unknown>;
    if (candidate.imageId !== null && !validGalleryImageId(candidate.imageId)) {
      return { ...DEFAULT_PREFERENCE };
    }
    // Corrupted persisted pages such as 1e100 are integers in JavaScript but
    // cannot safely be used for a paginated API query. Fall back before the
    // first image is requested so a bad preference never hides the viewport.
    if (
      typeof candidate.page !== "number" ||
      !Number.isSafeInteger(candidate.page) ||
      candidate.page < 1 ||
      candidate.page > MAX_RESTORED_GALLERY_PAGE ||
      (candidate.wrap !== undefined && typeof candidate.wrap !== "boolean")
    ) {
      return { ...DEFAULT_PREFERENCE };
    }
    // A saved page without a selected image is not a meaningful restore target.
    // Start from the first page so the initial camera image remains visible.
    return {
      imageId:
        typeof candidate.imageId === "string" ? candidate.imageId.trim() : null,
      page: candidate.imageId === null ? 1 : candidate.page,
      wrap: candidate.wrap === true,
    };
  } catch {
    return { ...DEFAULT_PREFERENCE };
  }
}

// WebView2 may deny access to the localStorage property itself (SecurityError),
// before getItem/setItem can be called. Keep image browsing usable even then.
export function readBrowserGalleryPreference(projectId: string): GalleryPreference {
  try {
    return readGalleryPreference(window.localStorage, projectId);
  } catch {
    return { ...DEFAULT_PREFERENCE };
  }
}

export function writeBrowserGalleryPreference(
  projectId: string,
  preference: GalleryPreference,
): void {
  try {
    writeGalleryPreference(window.localStorage, projectId, preference);
  } catch {
    // Persisting the last focused image is optional; displaying it is not.
  }
}

export function writeGalleryPreference(
  storage: Pick<Storage, "setItem">,
  projectId: string,
  preference: GalleryPreference,
): void {
  // Never persist invalid pagination state that could hide the initial image
  // on the next project open. Ignore stale UI writes rather than poisoning
  // an otherwise valid preference from an earlier gallery selection.
  try {
    // Runtime callers may supply proxy objects or getters that throw. Keep
    // validation inside the storage boundary so preference persistence can
    // never interrupt image browsing or annotation work.
    if (!preference || typeof preference !== "object") return;
    // Snapshot each field exactly once. Proxy getters can change between
    // validation and serialization; never persist an unvalidated second value.
    const { imageId, page, wrap } = preference;
    if (
      !Number.isSafeInteger(page) ||
      page < 1 ||
      page > MAX_RESTORED_GALLERY_PAGE ||
      (imageId !== null && !validGalleryImageId(imageId)) ||
      typeof wrap !== "boolean"
    ) {
      return;
    }
    const serialized = JSON.stringify({
      // Persist only the versioned preference contract, not arbitrary fields
      // accidentally attached to a runtime object (e.g. image metadata).
      imageId: typeof imageId === "string" ? imageId.trim() : null,
      page: imageId === null ? 1 : page,
      wrap,
    });
    // Keep writes compatible with the bounded reader. An oversized camera ID
    // must not overwrite a previously restorable first-image selection.
    if (serialized.length > 4096) return;
    storage.setItem(preferenceKey(projectId), serialized);
  } catch {
    // A blocked or full preference store must not prevent annotation work.
  }
}

/** Parse an explicit gallery page without accepting exponent or partial-number input. */
export function parseGalleryPageDraft(
  draft: string,
  totalPages: number,
): number | null {
  // WebView2 event payloads and restored UI state can violate TypeScript's
  // compile-time string contract. Never let a malformed page draft interrupt
  // the gallery or its initial-image viewport.
  if (typeof draft !== "string") return null;
  if (
    !Number.isSafeInteger(totalPages) ||
    totalPages < 1 ||
    totalPages > MAX_RESTORED_GALLERY_PAGE
  ) {
    return null;
  }
  // Reject oversized input before trimming so pasted whitespace cannot force
  // an unnecessary full-string normalization on the gallery UI thread.
  if (draft.length > 64) return null;
  const value = draft.trim();
  // Bound parsing work for pasted or corrupted page drafts. A safe integer
  // requires at most 16 decimal digits; leading zeros are harmless but
  // unbounded input must not stall the gallery navigation UI.
  if (value.length > 64 || !/^\d+$/.test(value)) return null;
  const requested = Number(value);
  if (!Number.isSafeInteger(requested) || requested < 1) return null;
  return Math.min(totalPages, requested);
}

export function resolveGalleryNavigation({
  action,
  index,
  itemCount,
  page,
  pages,
  wrap,
}: {
  action: GalleryNavigationAction;
  index: number;
  itemCount: number;
  page: number;
  pages: number;
  wrap: boolean;
}): GalleryNavigationDestination | null {
  // A stale selection can outlive a paginated gallery refresh. Never emit an
  // out-of-range image index or page while the new selection is being resolved.
  if (
    !Number.isSafeInteger(itemCount) ||
    !Number.isSafeInteger(pages) ||
    !Number.isSafeInteger(page) ||
    !Number.isSafeInteger(index) ||
    itemCount < 1 ||
    pages < 1 ||
    pages > MAX_RESTORED_GALLERY_PAGE ||
    page < 1 ||
    page > pages ||
    index < 0 ||
    index >= itemCount ||
    typeof wrap !== "boolean" ||
    !(["previous", "next", "first", "last"] as string[]).includes(action) ||
    (pages === 1 && itemCount === 1)
  ) {
    return null;
  }
  if (action === "first") {
    return page === 1 && index === 0 ? null : { page: 1, edge: "first" };
  }
  if (action === "last") {
    if (page === pages && index === itemCount - 1) return null;
    return { page: pages, edge: "last" };
  }
  if (action === "previous") {
    if (index > 0) return { page, edge: "index", index: index - 1 };
    if (page > 1) return { page: page - 1, edge: "last" };
    return wrap ? { page: pages, edge: "last" } : null;
  }
  if (index < itemCount - 1) {
    return { page, edge: "index", index: index + 1 };
  }
  if (page < pages) return { page: page + 1, edge: "first" };
  return wrap ? { page: 1, edge: "first" } : null;
}

export function shouldIgnoreGalleryShortcut(target: EventTarget | null): boolean {
  return shouldIgnoreShortcutTarget(target);
}
