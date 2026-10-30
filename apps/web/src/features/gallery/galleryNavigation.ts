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
    if (candidate.imageId !== null && typeof candidate.imageId !== "string") {
      return { ...DEFAULT_PREFERENCE };
    }
    if (
      typeof candidate.page !== "number" ||
      !Number.isInteger(candidate.page) ||
      candidate.page < 1 ||
      typeof candidate.wrap !== "boolean"
    ) {
      return { ...DEFAULT_PREFERENCE };
    }
    return {
      imageId: candidate.imageId,
      page: candidate.page,
      wrap: candidate.wrap,
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
  try {
    storage.setItem(preferenceKey(projectId), JSON.stringify(preference));
  } catch {
    // A blocked or full preference store must not prevent annotation work.
  }
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
  if (itemCount < 1 || pages < 1 || (pages === 1 && itemCount === 1)) {
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

export function shouldIgnoreGalleryShortcut(
  target: EventTarget | null,
): boolean {
  return shouldIgnoreShortcutTarget(target);
}
