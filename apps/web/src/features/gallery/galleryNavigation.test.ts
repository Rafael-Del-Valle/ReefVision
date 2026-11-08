import { afterEach, describe, expect, it, vi } from "vitest";

import {
  parseGalleryPageDraft,
  readBrowserGalleryPreference,
  readGalleryPreference,
  resolveGalleryNavigation,
  writeBrowserGalleryPreference,
  writeGalleryPreference,
} from "./galleryNavigation";

function memoryStorage(initial: Record<string, string> = {}): Storage {
  const values = new Map(Object.entries(initial));
  return {
    get length() {
      return values.size;
    },
    clear: () => values.clear(),
    getItem: (key) => values.get(key) ?? null,
    key: (index) => [...values.keys()][index] ?? null,
    removeItem: (key) => values.delete(key),
    setItem: (key, value) => values.set(key, value),
  };
}

describe("browser gallery storage access", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("restores a saved camera selection after transient WebView2 storage denial", () => {
    const savedStorage = memoryStorage();
    writeGalleryPreference(savedStorage, "project-a", {
      imageId: "camera-original-42",
      page: 3,
      wrap: true,
    });

    vi.stubGlobal("window", {
      get localStorage(): Storage {
        throw new DOMException("Access denied", "SecurityError");
      },
    });
    expect(readBrowserGalleryPreference("project-a")).toEqual({
      imageId: null,
      page: 1,
      wrap: false,
    });
    expect(() =>
      writeBrowserGalleryPreference("project-a", {
        imageId: "camera-original-99",
        page: 9,
        wrap: false,
      }),
    ).not.toThrow();

    // Denied access must not erase the persisted image or its original page.
    vi.stubGlobal("window", { localStorage: savedStorage });
    expect(readBrowserGalleryPreference("project-a")).toEqual({
      imageId: "camera-original-42",
      page: 3,
      wrap: true,
    });
    writeBrowserGalleryPreference("project-a", {
      imageId: "camera-original-43",
      page: 4,
      wrap: false,
    });
    expect(readBrowserGalleryPreference("project-a")).toEqual({
      imageId: "camera-original-43",
      page: 4,
      wrap: false,
    });
  });

  it("preserves the last camera selection when WebView2 storage quota is exhausted", () => {
    const storage = memoryStorage();
    writeGalleryPreference(storage, "project-a", {
      imageId: "camera-original-7",
      page: 2,
      wrap: true,
    });
    const saved = storage.getItem("reefvision.gallery.project-a.v1");

    const quotaStorage = {
      getItem: storage.getItem,
      setItem: (_key: string, _value: string): void => {
        throw new DOMException("Quota exceeded", "QuotaExceededError");
      },
    };
    vi.stubGlobal("window", { localStorage: quotaStorage });
    expect(() =>
      writeBrowserGalleryPreference("project-a", {
        imageId: "camera-original-8",
        page: 3,
        wrap: false,
      }),
    ).not.toThrow();

    // An optional preference write must not erase a previously saved image.
    expect(storage.getItem("reefvision.gallery.project-a.v1")).toBe(saved);
    expect(readBrowserGalleryPreference("project-a")).toEqual({
      imageId: "camera-original-7",
      page: 2,
      wrap: true,
    });

    vi.stubGlobal("window", { localStorage: storage });
    writeBrowserGalleryPreference("project-a", {
      imageId: "camera-original-8",
      page: 3,
      wrap: false,
    });
    expect(readBrowserGalleryPreference("project-a")).toEqual({
      imageId: "camera-original-8",
      page: 3,
      wrap: false,
    });
  });

  it("recovers a saved camera image when WebView2 getItem temporarily throws", () => {
    const storage = memoryStorage();
    writeGalleryPreference(storage, "project-a", {
      imageId: "camera-original-15",
      page: 6,
      wrap: true,
    });
    const blockedStorage = {
      getItem: (_key: string): string | null => {
        throw new DOMException("Storage unavailable", "SecurityError");
      },
      setItem: storage.setItem,
    };
    vi.stubGlobal("window", { localStorage: blockedStorage });
    expect(readBrowserGalleryPreference("project-a")).toEqual({
      imageId: null,
      page: 1,
      wrap: false,
    });

    // A transient read failure must not delete the persisted camera selection.
    vi.stubGlobal("window", { localStorage: storage });
    expect(readBrowserGalleryPreference("project-a")).toEqual({
      imageId: "camera-original-15",
      page: 6,
      wrap: true,
    });
  });

  it("keeps first-image browsing available before WebView2 storage is initialized", () => {
    vi.stubGlobal("window", { localStorage: undefined });

    expect(readBrowserGalleryPreference("project-a")).toEqual({
      imageId: null,
      page: 1,
      wrap: false,
    });
    expect(() =>
      writeBrowserGalleryPreference("project-a", {
        imageId: "camera-original-1",
        page: 1,
        wrap: false,
      }),
    ).not.toThrow();

    const storage = memoryStorage();
    vi.stubGlobal("window", { localStorage: storage });
    writeBrowserGalleryPreference("project-a", {
      imageId: "camera-original-1",
      page: 1,
      wrap: false,
    });
    expect(readBrowserGalleryPreference("project-a").imageId).toBe(
      "camera-original-1",
    );
  });

  it("recovers when WebView2 denies access to the localStorage property itself", () => {
    vi.stubGlobal("window", {
      get localStorage(): Storage {
        throw new DOMException("Access denied", "SecurityError");
      },
    });

    expect(readBrowserGalleryPreference("project-a")).toEqual({
      imageId: null,
      page: 1,
      wrap: false,
    });
    expect(() =>
      writeBrowserGalleryPreference("project-a", {
        imageId: "camera-original-1",
        page: 1,
        wrap: false,
      }),
    ).not.toThrow();
  });
});

describe("gallery preferences", () => {
  it("round-trips camera-style JPEG identifiers without changing their case or internal spacing", () => {
    const storage = memoryStorage();
    for (const imageId of [
      "DSC_0042.JPG",
      "IMG_0123.JPEG",
      "Canon EOS RP/IMG 0007.JpG",
      "Sony α7R III/DSC 0008.JPEG",
      "Sony 📷/DSC 0009.JPG",
    ]) {
      writeGalleryPreference(storage, "camera-project", {
        imageId,
        page: 2,
        wrap: false,
      });
      expect(readGalleryPreference(storage, "camera-project").imageId).toBe(
        imageId,
      );
    }
  });

  it("persists the recent image and page per project", () => {
    const storage = memoryStorage();

    writeGalleryPreference(storage, "project-a", {
      imageId: "image-49",
      page: 3,
      wrap: true,
    });

    expect(readGalleryPreference(storage, "project-a")).toEqual({
      imageId: "image-49",
      page: 3,
      wrap: true,
    });
    expect(readGalleryPreference(storage, "project-b")).toEqual({
      imageId: null,
      page: 1,
      wrap: false,
    });
  });

  it("isolates restored camera selections when another project's preference is corrupt", () => {
    const storage = memoryStorage();
    writeGalleryPreference(storage, "project-a", {
      imageId: "camera-original-a",
      page: 3,
      wrap: true,
    });
    writeGalleryPreference(storage, "project-b", {
      imageId: "camera-original-b",
      page: 8,
      wrap: false,
    });
    storage.setItem("reefvision.gallery.project-b.v1", "{corrupt JSON");

    expect(readGalleryPreference(storage, "project-b")).toEqual({
      imageId: null,
      page: 1,
      wrap: false,
    });
    expect(readGalleryPreference(storage, "project-a")).toEqual({
      imageId: "camera-original-a",
      page: 3,
      wrap: true,
    });
    writeGalleryPreference(storage, "project-b", {
      imageId: "camera-original-b2",
      page: 1,
      wrap: false,
    });
    expect(readGalleryPreference(storage, "project-a").imageId).toBe(
      "camera-original-a",
    );
    expect(readGalleryPreference(storage, "project-b").imageId).toBe(
      "camera-original-b2",
    );
  });

  it("normalizes padded camera IDs without losing their selected gallery page", () => {
    const storage = memoryStorage({
      "reefvision.gallery.project-a.v1": JSON.stringify({
        imageId: "  camera-original-1  ",
        page: 4,
        wrap: false,
      }),
    });
    expect(readGalleryPreference(storage, "project-a")).toEqual({
      imageId: "camera-original-1",
      page: 4,
      wrap: false,
    });

    writeGalleryPreference(storage, "project-a", {
      imageId: "  camera-original-2  ",
      page: 5,
      wrap: true,
    });
    expect(
      JSON.parse(storage.getItem("reefvision.gallery.project-a.v1") ?? "null"),
    ).toEqual({
      imageId: "camera-original-2",
      page: 5,
      wrap: true,
    });
  });

  it("does not expose unknown persisted camera metadata when restoring a selection", () => {
    const storage = memoryStorage({
      "reefvision.gallery.project-a.v1": JSON.stringify({
        imageId: "camera-original-1",
        page: 2,
        wrap: true,
        originalImagePath: "C:\\private\\camera\\original.jpg",
        annotationPayload: { scientificData: "must-not-restore" },
      }),
    });

    expect(readGalleryPreference(storage, "project-a")).toEqual({
      imageId: "camera-original-1",
      page: 2,
      wrap: true,
    });
  });

  it("persists only the approved gallery preference fields", () => {
    const storage = memoryStorage();
    const runtimePreference = {
      imageId: "camera-original-1",
      page: 2,
      wrap: true,
      originalImagePath: "C:\\private\\camera\\original.jpg",
      annotationPayload: { scientificData: "must-not-persist" },
    };
    writeGalleryPreference(storage, "project-a", runtimePreference);
    expect(
      JSON.parse(storage.getItem("reefvision.gallery.project-a.v1") ?? "null"),
    ).toEqual({
      imageId: "camera-original-1",
      page: 2,
      wrap: true,
    });
  });

  it("normalizes an unselected image to page one before persisting", () => {
    const storage = memoryStorage();
    writeGalleryPreference(storage, "project-a", {
      imageId: null,
      page: 9,
      wrap: true,
    });
    expect(
      JSON.parse(storage.getItem("reefvision.gallery.project-a.v1") ?? "null"),
    ).toEqual({
      imageId: null,
      page: 1,
      wrap: true,
    });
  });

  it("restores a saved camera image from preferences written before wrap existed", () => {
    const storage = memoryStorage({
      "reefvision.gallery.project-a.v1": JSON.stringify({
        imageId: "camera-original-1",
        page: 4,
      }),
    });
    expect(readGalleryPreference(storage, "project-a")).toEqual({
      imageId: "camera-original-1",
      page: 4,
      wrap: false,
    });
  });

  it("starts on the first page when no camera image was saved", () => {
    const storage = memoryStorage({
      "reefvision.gallery.project-a.v1": JSON.stringify({
        imageId: null,
        page: 9,
        wrap: true,
      }),
    });
    expect(readGalleryPreference(storage, "project-a")).toEqual({
      imageId: null,
      page: 1,
      wrap: true,
    });
  });

  it("rejects malformed legacy image identifiers and wrapping flags", () => {
    for (const preference of [
      { page: 2, wrap: false },
      { imageId: 7, page: 2, wrap: false },
      { imageId: "camera-original-1", page: 2, wrap: "false" },
      { imageId: "camera-original-1", page: 2, wrap: null },
    ]) {
      const storage = memoryStorage({
        "reefvision.gallery.project-a.v1": JSON.stringify(preference),
      });
      expect(readGalleryPreference(storage, "project-a")).toEqual({
        imageId: null,
        page: 1,
        wrap: false,
      });
    }
  });

  it("ignores non-object and malformed camera gallery preferences without hiding the first image", () => {
    const key = "reefvision.gallery.project-a.v1";
    for (const raw of [
      "null",
      "true",
      "42",
      '"camera-original-1"',
      "[]",
      JSON.stringify({ imageId: "camera-original-1", page: 1.5, wrap: true }),
      JSON.stringify({ imageId: "camera-original-1", page: "2", wrap: true }),
      JSON.stringify({ imageId: "camera-original-1", page: null, wrap: true }),
    ]) {
      const storage = memoryStorage({ [key]: raw });
      expect(readGalleryPreference(storage, "project-a")).toEqual({
        imageId: null,
        page: 1,
        wrap: false,
      });
    }
  });

  it("skips oversized persisted preferences without blocking first-image rendering", () => {
    const key = "reefvision.gallery.project-a.v1";
    const storage = memoryStorage({
      [key]: JSON.stringify({
        imageId: "camera-" + "x".repeat(10_000),
        page: 999,
        wrap: true,
      }),
    });
    expect(readGalleryPreference(storage, "project-a")).toEqual({
      imageId: null,
      page: 1,
      wrap: false,
    });

    // A corrupted preference in one project must not affect another.
    writeGalleryPreference(storage, "project-b", {
      imageId: "camera-original-1",
      page: 2,
      wrap: true,
    });
    expect(readGalleryPreference(storage, "project-b")).toEqual({
      imageId: "camera-original-1",
      page: 2,
      wrap: true,
    });
  });

  it("rejects oversized camera identifiers before writing a gallery selection", () => {
    const storage = memoryStorage();
    writeGalleryPreference(storage, "project-a", {
      imageId: "camera-original-1",
      page: 2,
      wrap: false,
    });
    const key = "reefvision.gallery.project-a.v1";
    const saved = storage.getItem(key);

    writeGalleryPreference(storage, "project-a", {
      imageId: "x".repeat(100_000),
      page: 3,
      wrap: true,
    });
    expect(storage.getItem(key)).toBe(saved);
    expect(readGalleryPreference(storage, "project-a").imageId).toBe(
      "camera-original-1",
    );
  });

  it("does not persist camera IDs that exceed the bounded preference reader", () => {
    const storage = memoryStorage();
    writeGalleryPreference(storage, "project-a", {
      imageId: "camera-original-1",
      page: 2,
      wrap: true,
    });
    const key = "reefvision.gallery.project-a.v1";
    const saved = storage.getItem(key);

    writeGalleryPreference(storage, "project-a", {
      imageId: "camera-" + "x".repeat(5000),
      page: 3,
      wrap: false,
    });
    expect(storage.getItem(key)).toBe(saved);
    expect(readGalleryPreference(storage, "project-a")).toEqual({
      imageId: "camera-original-1",
      page: 2,
      wrap: true,
    });
  });

  it("rejects unsafe saved pages before loading the first camera image", () => {
    for (const page of [2 ** 53, 1e100, Number.MAX_VALUE]) {
      const storage = memoryStorage({
        "reefvision.gallery.project-a.v1": JSON.stringify({
          imageId: "image-12",
          page,
          wrap: true,
        }),
      });

      expect(readGalleryPreference(storage, "project-a")).toEqual({
        imageId: null,
        page: 1,
        wrap: false,
      });
    }
  });

  it("does not overwrite the last valid image with invalid asynchronous pagination", () => {
    const storage = memoryStorage();
    writeGalleryPreference(storage, "project-a", {
      imageId: "camera-original-1",
      page: 2,
      wrap: false,
    });
    const key = "reefvision.gallery.project-a.v1";
    const saved = storage.getItem(key);

    for (const page of [
      0,
      -1,
      1.5,
      Number.NaN,
      Number.POSITIVE_INFINITY,
      2 ** 53,
    ]) {
      writeGalleryPreference(storage, "project-a", {
        imageId: "stale-image",
        page,
        wrap: true,
      });
      expect(storage.getItem(key)).toBe(saved);
    }
    expect(readGalleryPreference(storage, "project-a")).toEqual({
      imageId: "camera-original-1",
      page: 2,
      wrap: false,
    });
  });

  it("rejects control-character camera IDs from persisted preferences and UI writes", () => {
    const key = "reefvision.gallery.project-a.v1";
    const storage = memoryStorage();
    writeGalleryPreference(storage, "project-a", {
      imageId: "camera-original-1",
      page: 2,
      wrap: false,
    });
    const saved = storage.getItem(key);
    for (const imageId of [
      "camera\noriginal",
      "camera\u0000original",
      "camera\u007foriginal",
      "camera\u0085original",
      "camera\u2028original",
      "camera\u2029original",
      "camera\u200boriginal",
      "camera\u200doriginal",
      "camera\u2060original",
      "camera\u202eoriginal",
      "camera\u202aoriginal",
      "camera\u2066original",
      "camera\u2069original",
      "camera\ufefforiginal",
      "camera\ud800original",
      "camera\udc00original",
    ]) {
      const corrupted = memoryStorage({
        [key]: JSON.stringify({ imageId, page: 7, wrap: true }),
      });
      expect(readGalleryPreference(corrupted, "project-a")).toEqual({
        imageId: null,
        page: 1,
        wrap: false,
      });
      writeGalleryPreference(storage, "project-a", {
        imageId,
        page: 7,
        wrap: true,
      });
      expect(storage.getItem(key)).toBe(saved);
    }
  });

  it("rejects blank image IDs without hiding the initial viewport", () => {
    for (const imageId of ["", "   "]) {
      const storage = memoryStorage({
        "reefvision.gallery.project-a.v1": JSON.stringify({
          imageId,
          page: 7,
          wrap: true,
        }),
      });
      expect(readGalleryPreference(storage, "project-a")).toEqual({
        imageId: null,
        page: 1,
        wrap: false,
      });
    }

    const storage = memoryStorage();
    writeGalleryPreference(storage, "project-a", {
      imageId: "camera-original-1",
      page: 2,
      wrap: false,
    });
    const saved = storage.getItem("reefvision.gallery.project-a.v1");
    writeGalleryPreference(storage, "project-a", {
      imageId: " ",
      page: 99,
      wrap: true,
    });
    expect(storage.getItem("reefvision.gallery.project-a.v1")).toBe(saved);
  });

  it("keeps gallery navigation usable when WebView2 storage reads are denied", () => {
    const deniedStorage = {
      getItem: (_key: string): string | null => {
        throw new DOMException("Access denied", "SecurityError");
      },
    };
    expect(readGalleryPreference(deniedStorage, "project-a")).toEqual({
      imageId: null,
      page: 1,
      wrap: false,
    });
  });

  it("does not interrupt image selection when WebView2 storage writes are denied", () => {
    const deniedStorage = {
      setItem: (_key: string, _value: string): void => {
        throw new DOMException("Quota exceeded", "QuotaExceededError");
      },
    };
    expect(() =>
      writeGalleryPreference(deniedStorage, "project-a", {
        imageId: "camera-original-1",
        page: 1,
        wrap: false,
      }),
    ).not.toThrow();
  });

  it("falls back safely when stored data is corrupt", () => {
    const storage = memoryStorage({
      "reefvision.gallery.project-a.v1": '{"imageId":7,"page":-3}',
    });

    expect(readGalleryPreference(storage, "project-a")).toEqual({
      imageId: null,
      page: 1,
      wrap: false,
    });
  });
});

describe("parseGalleryPageDraft", () => {
  it("accepts exact decimal page numbers and clamps valid pages to the collection", () => {
    expect(parseGalleryPageDraft("2", 5)).toBe(2);
    expect(parseGalleryPageDraft(" 003 ", 5)).toBe(3);
    expect(parseGalleryPageDraft("999", 5)).toBe(5);
  });

  it("rejects exponent, fractional, partial, and unsafe page input", () => {
    for (const draft of [
      "",
      " ",
      "0",
      "-1",
      "1e3",
      "3.5",
      "3junk",
      "1_000",
      "9007199254740992",
    ]) {
      expect(parseGalleryPageDraft(draft, 5)).toBeNull();
    }
    // Pasted pathological inputs must not trigger unbounded numeric parsing.
    expect(parseGalleryPageDraft("0".repeat(100_000) + "2", 5)).toBeNull();
    expect(parseGalleryPageDraft(" ".repeat(100_000) + "2", 5)).toBeNull();
    expect(parseGalleryPageDraft("0".repeat(63) + "2", 5)).toBe(2);
    expect(parseGalleryPageDraft("2", 0)).toBeNull();
    expect(parseGalleryPageDraft("2", Number.MAX_SAFE_INTEGER + 1)).toBeNull();
  });
});

describe("gallery partial final-page navigation", () => {
  it("crosses a full page into a one-image final page and back without skipping images", () => {
    const base = {
      action: "next" as const,
      index: 3,
      itemCount: 4,
      page: 1,
      pages: 2,
      wrap: false,
    };
    expect(resolveGalleryNavigation(base)).toEqual({ page: 2, edge: "first" });
    expect(
      resolveGalleryNavigation({
        ...base,
        action: "previous",
        index: 0,
        itemCount: 1,
        page: 2,
      }),
    ).toEqual({ page: 1, edge: "last" });
    expect(
      resolveGalleryNavigation({ ...base, index: 0, itemCount: 1, page: 2 }),
    ).toBeNull();
    expect(
      resolveGalleryNavigation({
        ...base,
        index: 0,
        itemCount: 1,
        page: 2,
        wrap: true,
      }),
    ).toEqual({ page: 1, edge: "first" });
  });
});

describe("resolveGalleryNavigation", () => {
  it("does not navigate using stale or malformed pagination state", () => {
    const valid = {
      action: "next" as const,
      index: 2,
      itemCount: 3,
      page: 1,
      pages: 2,
      wrap: true,
    };
    for (const index of [-1, 3, Number.NaN, Number.POSITIVE_INFINITY, 1.5]) {
      expect(resolveGalleryNavigation({ ...valid, index })).toBeNull();
    }
    for (const page of [0, 3, Number.NaN, 1.5]) {
      expect(resolveGalleryNavigation({ ...valid, page })).toBeNull();
    }
    for (const pages of [0, Number.POSITIVE_INFINITY, 1.5]) {
      expect(resolveGalleryNavigation({ ...valid, pages })).toBeNull();
    }
    for (const itemCount of [0, Number.NaN, 1.5]) {
      expect(resolveGalleryNavigation({ ...valid, itemCount })).toBeNull();
    }
  });

  it("rejects stale pages and unsafe integer indexes before requesting camera images", () => {
    const valid = {
      action: "next" as const,
      index: 0,
      itemCount: 24,
      page: 1,
      pages: 5,
      wrap: true,
    };
    for (const page of [6, Number.MAX_SAFE_INTEGER + 1]) {
      expect(resolveGalleryNavigation({ ...valid, page })).toBeNull();
    }
    for (const index of [Number.MAX_SAFE_INTEGER + 1, -2]) {
      expect(resolveGalleryNavigation({ ...valid, index })).toBeNull();
    }
    for (const itemCount of [Number.MAX_SAFE_INTEGER + 1, -1]) {
      expect(resolveGalleryNavigation({ ...valid, itemCount })).toBeNull();
    }
    expect(
      resolveGalleryNavigation({ ...valid, pages: Number.MAX_SAFE_INTEGER + 1 }),
    ).toBeNull();
  });

  it("rejects malformed runtime navigation payloads instead of advancing an image", () => {
    const valid = {
      action: "next" as const,
      index: 0,
      itemCount: 2,
      page: 1,
      pages: 2,
      wrap: false,
    };
    expect(
      resolveGalleryNavigation({ ...valid, wrap: "false" as unknown as boolean }),
    ).toBeNull();
    expect(
      resolveGalleryNavigation({ ...valid, wrap: null as unknown as boolean }),
    ).toBeNull();
    expect(
      resolveGalleryNavigation({
        ...valid,
        action: "delete" as unknown as typeof valid.action,
      }),
    ).toBeNull();
  });

  it("keeps non-wrapping gallery edges stable across paginated camera images", () => {
    expect(
      resolveGalleryNavigation({
        action: "previous",
        index: 0,
        itemCount: 24,
        page: 1,
        pages: 10,
        wrap: false,
      }),
    ).toBeNull();
    expect(
      resolveGalleryNavigation({
        action: "next",
        index: 7,
        itemCount: 8,
        page: 10,
        pages: 10,
        wrap: false,
      }),
    ).toBeNull();
    expect(
      resolveGalleryNavigation({
        action: "first",
        index: 0,
        itemCount: 24,
        page: 1,
        pages: 10,
        wrap: true,
      }),
    ).toBeNull();
    expect(
      resolveGalleryNavigation({
        action: "last",
        index: 7,
        itemCount: 8,
        page: 10,
        pages: 10,
        wrap: true,
      }),
    ).toBeNull();
  });

  it("wraps between a partial last page and the first camera image", () => {
    const lastImage = {
      index: 2,
      itemCount: 3,
      page: 5,
      pages: 5,
      wrap: true,
    };
    expect(resolveGalleryNavigation({ ...lastImage, action: "next" })).toEqual({
      page: 1,
      edge: "first",
    });
    expect(
      resolveGalleryNavigation({ ...lastImage, action: "next", wrap: false }),
    ).toBeNull();
    expect(
      resolveGalleryNavigation({
        action: "previous",
        index: 0,
        itemCount: 24,
        page: 1,
        pages: 5,
        wrap: true,
      }),
    ).toEqual({ page: 5, edge: "last" });
  });

  it("navigates single-image pages without treating the gallery as empty", () => {
    const base = {
      index: 0,
      itemCount: 1,
      pages: 3,
      wrap: false,
    };
    expect(
      resolveGalleryNavigation({ ...base, action: "next", page: 1 }),
    ).toEqual({ page: 2, edge: "first" });
    expect(
      resolveGalleryNavigation({ ...base, action: "previous", page: 2 }),
    ).toEqual({ page: 1, edge: "last" });
    expect(
      resolveGalleryNavigation({ ...base, action: "last", page: 1 }),
    ).toEqual({ page: 3, edge: "last" });
    expect(
      resolveGalleryNavigation({ ...base, action: "next", page: 3 }),
    ).toBeNull();
    expect(
      resolveGalleryNavigation({ ...base, action: "next", page: 3, wrap: true }),
    ).toEqual({ page: 1, edge: "first" });
  });

  it("moves within a page without requesting another page", () => {
    expect(
      resolveGalleryNavigation({
        action: "next",
        index: 3,
        itemCount: 24,
        page: 9,
        pages: 100_000,
        wrap: false,
      }),
    ).toEqual({ page: 9, edge: "index", index: 4 });
  });

  it("wraps a single gallery page with multiple camera images without changing pages", () => {
    const base = {
      itemCount: 3,
      page: 1,
      pages: 1,
      wrap: true,
    };
    expect(
      resolveGalleryNavigation({ ...base, action: "next", index: 2 }),
    ).toEqual({ page: 1, edge: "first" });
    expect(
      resolveGalleryNavigation({ ...base, action: "previous", index: 0 }),
    ).toEqual({ page: 1, edge: "last" });
    expect(
      resolveGalleryNavigation({ ...base, action: "next", index: 2, wrap: false }),
    ).toBeNull();
    expect(
      resolveGalleryNavigation({ ...base, action: "previous", index: 0, wrap: false }),
    ).toBeNull();
  });

  it("jumps to the first or last camera image on the current page without a redundant page fetch", () => {
    const base = {
      itemCount: 7,
      page: 1,
      pages: 1,
      wrap: false,
    };
    expect(
      resolveGalleryNavigation({ ...base, action: "first", index: 4 }),
    ).toEqual({ page: 1, edge: "first" });
    expect(
      resolveGalleryNavigation({ ...base, action: "last", index: 2 }),
    ).toEqual({ page: 1, edge: "last" });
    expect(
      resolveGalleryNavigation({ ...base, action: "first", index: 0 }),
    ).toBeNull();
    expect(
      resolveGalleryNavigation({ ...base, action: "last", index: 6 }),
    ).toBeNull();
  });

  it("crosses page boundaries without loading the full collection", () => {
    expect(
      resolveGalleryNavigation({
        action: "next",
        index: 23,
        itemCount: 24,
        page: 9,
        pages: 100_000,
        wrap: false,
      }),
    ).toEqual({ page: 10, edge: "first" });
    expect(
      resolveGalleryNavigation({
        action: "previous",
        index: 0,
        itemCount: 24,
        page: 9,
        pages: 100_000,
        wrap: false,
      }),
    ).toEqual({ page: 8, edge: "last" });
  });

  it("supports first, last, optional wrapping, and single-image no-ops", () => {
    expect(
      resolveGalleryNavigation({
        action: "first",
        index: 4,
        itemCount: 24,
        page: 9,
        pages: 10,
        wrap: false,
      }),
    ).toEqual({ page: 1, edge: "first" });
    expect(
      resolveGalleryNavigation({
        action: "last",
        index: 4,
        itemCount: 24,
        page: 9,
        pages: 10,
        wrap: false,
      }),
    ).toEqual({ page: 10, edge: "last" });
    expect(
      resolveGalleryNavigation({
        action: "previous",
        index: 0,
        itemCount: 24,
        page: 1,
        pages: 10,
        wrap: true,
      }),
    ).toEqual({ page: 10, edge: "last" });
    expect(
      resolveGalleryNavigation({
        action: "next",
        index: 0,
        itemCount: 1,
        page: 1,
        pages: 1,
        wrap: true,
      }),
    ).toBeNull();
  });
  it("rejects blank and control-character camera IDs without losing a valid saved selection", () => {
    const values = new Map<string, string>();
    const storage = {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => {
        values.set(key, value);
      },
    };
    const project = "camera-id-recovery";
    writeGalleryPreference(storage, project, {
      imageId: "valid-camera-frame",
      page: 4,
      wrap: true,
    });
    const key = "reefvision.gallery.camera-id-recovery.v1";
    const saved = values.get(key);
    expect(saved).toBeDefined();

    // Exercise real control characters, not literal backslash sequences.
    for (const invalid of [
      "",
      "   ",
      "frame\nsecond",
      "frame\u0000second",
      "frame\u007fsecond",
    ]) {
      values.set(key, JSON.stringify({ imageId: invalid, page: 4, wrap: true }));
      expect(readGalleryPreference(storage, project)).toEqual({
        imageId: null,
        page: 1,
        wrap: false,
      });
    }
    values.set(key, saved!);
    expect(readGalleryPreference(storage, project)).toEqual({
      imageId: "valid-camera-frame",
      page: 4,
      wrap: true,
    });
    writeGalleryPreference(storage, project, {
      imageId: "bad\nframe",
      page: 7,
      wrap: false,
    });
    expect(values.get(key)).toBe(saved);
  });

  it("restores supplementary Unicode camera IDs but rejects lone surrogates", () => {
    const values = new Map<string, string>();
    const storage = {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => {
        values.set(key, value);
      },
    };
    const project = "unicode-camera";
    const imageId = "coral-📷-reef.JPG";
    writeGalleryPreference(storage, project, {
      imageId,
      page: 2,
      wrap: true,
    });
    expect(readGalleryPreference(storage, project)).toEqual({
      imageId,
      page: 2,
      wrap: true,
    });
    const key = "reefvision.gallery.unicode-camera.v1";
    const saved = values.get(key);
    // Use actual unpaired UTF-16 code units, not literal backslash-u text.
    for (const malformed of [
      `bad${String.fromCharCode(0xd800)}`,
      `bad${String.fromCharCode(0xdc00)}`,
    ]) {
      values.set(key, JSON.stringify({ imageId: malformed, page: 2, wrap: true }));
      expect(readGalleryPreference(storage, project).imageId).toBeNull();
      values.set(key, saved!);
      writeGalleryPreference(storage, project, {
        imageId: malformed,
        page: 3,
        wrap: false,
      });
      expect(values.get(key)).toBe(saved);
    }
  });
});
