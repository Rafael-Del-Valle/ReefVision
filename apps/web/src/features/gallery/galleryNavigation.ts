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

const DEFAULT_PREFERENCE: GalleryPreference = {
  imageId: null,
  page: 1,
  wrap: false,
};

function preferenceKey(projectId: string): string {
  return `reefvision.gallery.${projectId}.v1`;
}

export function readGalleryPreference(
  storage: Pick<Storage, "getItem">,
  projectId: string,
): GalleryPreference {
  try {
    const value = storage.getItem(preferenceKey(projectId));
    if (!value) return { ...DEFAULT_PREFERENCE };
    const parsed: unknown = JSON.parse(value);
    if (!parsed || typeof parsed !== "object") return { ...DEFAULT_PREFERENCE };
    const candidate = parsed as Record<string, unknown>;
    if (
      candidate.imageId !== null &&
      (typeof candidate.imageId !== "string" || candidate.imageId.trim().length === 0)
    ) {
      return { ...DEFAULT_PREFERENCE };
    }
    // Corrupted persisted pages such as 1e100 are integers in JavaScript but
    // cannot safely be used for a paginated API query. Fall back before the
    // first image is requested so a bad preference never hides the viewport.
    if (
      typeof candidate.page !== "number" ||
      !Number.isSafeInteger(candidate.page) ||
      candidate.page < 1 ||
      (candidate.wrap !== undefined && typeof candidate.wrap !== "boolean")
    ) {
      return { ...DEFAULT_PREFERENCE };
    }
    // A saved page without a selected image is not a meaningful restore target.
    // Start from the first page so the initial camera image remains visible.
    return {
      imageId: candidate.imageId,
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
  if (
    !Number.isSafeInteger(preference.page) ||
    preference.page < 1 ||
    (preference.imageId !== null &&
      (typeof preference.imageId !== "string" || preference.imageId.trim().length === 0)) ||
    typeof preference.wrap !== "boolean"
  ) {
    return;
  }
  try {
    storage.setItem(preferenceKey(projectId), JSON.stringify(preference));
  } catch {
    // A blocked or full preference store must not prevent annotation work.
  }
}

/** Parse an explicit gallery page without accepting exponent or partial-number input. */
export function parseGalleryPageDraft(draft: string, totalPages: number): number | null {
  if (!Number.isSafeInteger(totalPages) || totalPages < 1) return null;
  const value = draft.trim();
  if (!/^\d+$/.test(value)) return null;
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
